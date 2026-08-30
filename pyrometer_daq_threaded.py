#!~/pyrometer-daq/venv/bin python
"""
    Script Purpose:
        Acquire pyrometer data from an MCC 118 analog-input DAQ HAT using a
        hardware timed continuous scan, and stream it to a CSV file via a separate
        writer thread.

    Sensor:
        CTLaser pyrometer, in 0 - 10 V analog output modeon channel 0, mapping linearly to
        490 C - 2000 C (see pyrometer_utils.volts_to_temperature).

    Features:
        - Reads a single channel (CH0) with the MCC 118's internal hardware clock.
        - Continuous scan: samples are pulled from the on-board buffer as they arrive,
          so no samples are dropped as long as the reader keeps up.
        - User-defined scan rate.
        - Converts each voltage sample to temperature.
        - Writes timestamp / voltage / temperature rows to CSV in a background thread.
        - Reports hardware/buffer overruns.

    MCC 118 functions used:
        mcc118.a_in_scan_start
        mcc118.a_in_scan_read
        mcc118.a_in_scan_actual_rate
        mcc118.a_in_scan_stop
        mcc118.a_in_scan_cleanup

"""
from sys import stdout
from datetime import datetime as dt, timedelta
from threading import Thread
from queue import Queue
import csv
import logging
import signal

from daqhats import mcc118, HatIDs, HatError, OptionFlags
from daqhats_utils import select_hat_device, chan_list_to_mask

from pyrometer_utils import volts_to_temperature

# The pyrometer is wired to a single MCC 118 channel.
PYRO_CHANNEL = 0

# Continuous-scan buffer size, in samples per channel. 0 lets the library pick a
# default sized for the scan rate.
SCAN_BUFFER_SAMPLES = 0

# How often (samples read) to refresh the on-screen status line.
STATUS_EVERY = 1

# Timeout (seconds) for each a_in_scan_read call. Use -1 to wait for all requested
# samples; a finite value returns whatever is available so the loop stays responsive.
READ_TIMEOUT = 5.0


def csv_writer_thread(output_filename, row_queue):
    """
    Thread function to write rows to a CSV file. Drains row_queue until it
    receives the None sentinel.
    """
    with open(output_filename, 'a', newline='') as csvfile:
        writer = csv.writer(csvfile)
        while True:
            row = row_queue.get()
            if row is None:  # Sentinel value to exit the thread
                break
            writer.writerow(row)
            row_queue.task_done()


def main():
    logging.basicConfig(
        filename='pyrometer_daq.log',
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    logging.info("Logger initialized.")

    channels = [PYRO_CHANNEL]
    channel_mask = chan_list_to_mask(channels)
    num_channels = len(channels)

    scan_rate = 100.0            # Hz, default; user can override below
    output_filename = 'pyrometer.csv'
    column_names = ['timestamp', 'voltage_V', 'temperature_C']

    row_queue = Queue()
    writer_thread = None

    # Graceful exit on SIGTERM / SIGHUP (e.g. SSH session closed).
    def handle_signal(signum, frame):
        signal_name = "SIGTERM" if signum == signal.SIGTERM else "SIGHUP"
        logging.info("%s received. Exiting gracefully...", signal_name)
        row_queue.put(None)
        if writer_thread is not None:
            writer_thread.join()
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, handle_signal)
    if hasattr(signal, 'SIGHUP'):  # SIGHUP does not exist on Windows
        signal.signal(signal.SIGHUP, handle_signal)

    try:
        # Get an instance of the selected hat device object.
        address = select_hat_device(HatIDs.MCC_118)
        hat = mcc118(address)

        logging.info("Pyrometer DAQ started.")
        print('\nPyrometer DAQ (MCC 118 continuous hardware-timed scan)')
        print('    Functions used: mcc118.a_in_scan_start / a_in_scan_read')
        print('    Channel: {:d} (fixed)'.format(PYRO_CHANNEL))
        print('    Sensor: 0-10 V -> 490-2000 C')

        try:
            scan_rate = float(input("\n Enter the scan rate (Hz) [default 100]: "))
            if scan_rate <= 0.0:
                raise ValueError('Scan rate must be positive.')
        except (NameError, SyntaxError, ValueError):
            print('   Using default scan rate: {:.1f} Hz'.format(scan_rate))

        try:
            entered = input('Name of csv (ending with .csv) [default pyrometer.csv]: ')
            if entered:
                if '.csv' not in entered:
                    raise ValueError('Filename must end with .csv')
                output_filename = entered
        except (NameError, SyntaxError):
            pass

        # Report the rate the hardware will actually use (may differ from requested).
        actual_rate = hat.a_in_scan_actual_rate(num_channels, scan_rate)
        print('\n    Requested rate: {:.3f} Hz'.format(scan_rate))
        print('    Actual rate:    {:.3f} Hz'.format(actual_rate))
        logging.info("Requested rate %.3f Hz, actual rate %.3f Hz", scan_rate, actual_rate)

        try:
            input("\nPress 'Enter' to start acquiring")
        except (NameError, SyntaxError):
            pass

        # Start the CSV writer thread and write the header.
        writer_thread = Thread(target=csv_writer_thread,
                               args=(output_filename, row_queue), daemon=True)
        writer_thread.start()
        row_queue.put(column_names)

        # Start the continuous hardware-timed scan.
        hat.a_in_scan_start(channel_mask, SCAN_BUFFER_SAMPLES, scan_rate,
                            OptionFlags.CONTINUOUS)

        print('\nAcquiring data ... Press Ctrl-C to abort')
        print('\n  Samples        Latest V      Latest C')

        # Timestamps are reconstructed from a wall-clock anchor plus the sample
        # index divided by the actual scan rate (the hardware clock is uniform).
        start_time = dt.now()
        total_samples = 0
        sample_period = timedelta(seconds=1.0 / actual_rate)

        try:
            while True:
                # Read every sample currently available in the on-board buffer.
                result = hat.a_in_scan_read(-1, READ_TIMEOUT)

                if result.hardware_overrun:
                    logging.warning("Hardware overrun detected.")
                    print('\n*** Hardware overrun ***')
                if result.buffer_overrun:
                    logging.warning("Buffer overrun detected (reader fell behind).")
                    print('\n*** Buffer overrun ***')

                for volts in result.data:
                    temperature_c, out_of_range = volts_to_temperature(volts)
                    timestamp = start_time + total_samples * sample_period
                    row = [timestamp.strftime('%Y-%m-%d %H:%M:%S.%f'),
                           '{:.5f}'.format(volts),
                           '{:.3f}'.format(temperature_c)]
                    row_queue.put(row)
                    total_samples += 1
                    if out_of_range:
                        logging.warning("Voltage out of range: %.5f V", volts)

                # Throttled status line (avoid one print per sample at high rates).
                if result.data:
                    last_v = result.data[-1]
                    last_t, _ = volts_to_temperature(last_v)
                    print('\r{:9d}   {:12.5f}   {:12.2f}'.format(
                        total_samples, last_v, last_t), end='')
                    stdout.flush()

                if not result.running:
                    # Scan stopped on its own (e.g. an error) -- exit the loop.
                    logging.info("Scan reported not running; stopping.")
                    break

        except KeyboardInterrupt:
            logging.info("KeyboardInterrupt received. Exiting gracefully...")
            print('\nStopping...')

        finally:
            hat.a_in_scan_stop()
            hat.a_in_scan_cleanup()
            row_queue.put(None)      # Tell the writer thread to finish.
            writer_thread.join()
            print('Acquired {:d} samples. Data saved to {}.'.format(
                total_samples, output_filename))

    except (HatError, ValueError) as error:
        print('\n', error)


if __name__ == '__main__':
    main()
