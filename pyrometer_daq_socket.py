#!/usr/bin/env python3
"""Acquire pyrometer data from an MCC 118 DAQ HAT and stream it to a PC
over UDP as JSON datagrams.

NEEDS A CORRESPONDING PC SCRIPT TO RUN PROPERLY -- see pc_receiver.py,
or use PyLHW's pyrometer_monitor for the full GUI integration.

Sensor:
    CTLaser pyrometer, 0-10 V analog output on channel 0, mapping
    linearly to 490-2000 C (see pyrometer_utils.volts_to_temperature).

Wire format (JSON over UDP):
    Registration:  Pi receives {"command": "handshake"} from the PC and
                   remembers the sender as the current client.  Re-
                   registration from a new address is accepted at any time.
    Data:          Pi sends one datagram per scan-read batch:
                   {
                     "type": "pyro_data",
                     "v": 1,
                     "seq": <int>,
                     "t0": <float>,          # UTC epoch of first sample
                     "dt": <float>,          # seconds between samples
                     "rate": <float>,        # actual hardware scan rate
                     "voltage": [<float>...],
                     "temperature": [<float>...],
                     "hw_overrun": <bool>,
                     "buf_overrun": <bool>
                   }
    Handshake ack: Pi sends {"type": "handshake_ack", "v": 1, "rate": <float>}
                   immediately on registration so the PC knows it connected.

MCC 118 functions used:
    mcc118.a_in_scan_start / a_in_scan_read / a_in_scan_stop / a_in_scan_cleanup
"""
from sys import stdout
from datetime import datetime, timezone, timedelta
import json
import logging
import select
import signal
import socket
import threading
import time

from daqhats import mcc118, HatIDs, HatError, OptionFlags

from pyrometer_utils import volts_to_temperature, select_hat_device, chan_list_to_mask
from pyro_protocol import encode_batch, encode_handshake_ack

# --- Configuration -----------------------------------------------------------
PYRO_CHANNEL = 0
SCAN_RATE = 100.0
SCAN_BUFFER_SAMPLES = 0
READ_TIMEOUT = 5.0
READ_CHUNK_S = 0.1

HOST = '0.0.0.0'
PORT = 55555

MAX_SAMPLES_PER_DATAGRAM = 25

ENABLE_CSV_BACKUP = False
CSV_FILENAME = 'pyrometer.csv'
# -----------------------------------------------------------------------------

_log = logging.getLogger(__name__)


class PyrometerStreamer:
    def __init__(self):
        self._running = True
        self._client_addr = None
        self._client_lock = threading.Lock()
        self._sock = None
        self._actual_rate = 0

    def run(self):
        logging.basicConfig(
            filename='pyrometer_daq.log',
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
        )
        _log.info("Pyrometer streamer starting.")

        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.bind((HOST, PORT))
        self._sock.setblocking(False)

        listener = threading.Thread(target=self._listen_for_clients, daemon=True)
        listener.start()

        self._acquire_and_stream()

    def stop(self):
        self._running = False
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass

    def _listen_for_clients(self):
        """Accept (re-)registration datagrams while running."""
        while self._running:
            try:
                readable, _, _ = select.select([self._sock], [], [], 0.5)
            except (OSError, ValueError):
                break
            if not readable:
                continue
            try:
                data, addr = self._sock.recvfrom(1024)
            except (OSError, ValueError):
                break
            try:
                msg = json.loads(data.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            if msg.get("command") == "handshake":
                with self._client_lock:
                    old = self._client_addr
                    self._client_addr = addr
                    rate = self._actual_rate or 0
                if old != addr:
                    _log.info("Client registered: %s (was %s)", addr, old)
                    print('\nClient registered: {}'.format(addr))
                try:
                    self._sock.sendto(encode_handshake_ack(rate), addr)
                except OSError:
                    pass

    def _send(self, payload_bytes):
        with self._client_lock:
            addr = self._client_addr
        if addr is None:
            return
        try:
            self._sock.sendto(payload_bytes, addr)
        except OSError as e:
            _log.warning("UDP send failed: %s", e)

    def _acquire_and_stream(self):
        channels = [PYRO_CHANNEL]
        channel_mask = chan_list_to_mask(channels)
        num_channels = len(channels)

        try:
            address = select_hat_device(HatIDs.MCC_118)
            hat = mcc118(address)
        except (HatError, ValueError) as e:
            print('\n', e)
            return

        actual_rate = hat.a_in_scan_actual_rate(num_channels, SCAN_RATE)
        self._actual_rate = actual_rate
        _log.info("Requested %.3f Hz, actual %.3f Hz", SCAN_RATE, actual_rate)
        print('\nPyrometer DAQ (MCC 118 -> UDP JSON)')
        print('    Channel: {:d}   Sensor: 0-10 V -> 490-2000 C'.format(PYRO_CHANNEL))
        print('    Requested rate: {:.3f} Hz   Actual rate: {:.3f} Hz'.format(
            SCAN_RATE, actual_rate))
        print('    Listening on {}:{}'.format(HOST, PORT))
        print('    Waiting for client handshake...')

        sample_period_s = 1.0 / actual_rate
        read_chunk = max(1, int(actual_rate * READ_CHUNK_S))
        hat.a_in_scan_start(channel_mask, SCAN_BUFFER_SAMPLES, SCAN_RATE,
                            OptionFlags.CONTINUOUS)

        print('\nAcquiring & streaming ... Press Ctrl-C to abort\n')

        start_time = datetime.now(timezone.utc)
        total_samples = 0
        seq = 0

        csv_file = None
        csv_writer = None
        if ENABLE_CSV_BACKUP:
            import csv
            csv_file = open(CSV_FILENAME, 'a', newline='')
            csv_writer = csv.writer(csv_file)
            csv_writer.writerow(['timestamp_utc', 'voltage_V', 'temperature_C'])

        try:
            while self._running:
                result = hat.a_in_scan_read(read_chunk, READ_TIMEOUT)

                if result.hardware_overrun:
                    _log.warning("Hardware overrun detected.")
                if result.buffer_overrun:
                    _log.warning("Buffer overrun detected.")

                if not result.data:
                    if not result.running:
                        break
                    continue

                voltages = list(result.data)
                temperatures = []
                for v in voltages:
                    t_c, oor = volts_to_temperature(v)
                    temperatures.append(t_c)
                    if oor:
                        _log.warning("Voltage out of range: %.5f V", v)

                # Split into chunks that fit in a single UDP datagram.
                for i in range(0, len(voltages), MAX_SAMPLES_PER_DATAGRAM):
                    chunk_v = voltages[i:i + MAX_SAMPLES_PER_DATAGRAM]
                    chunk_t = temperatures[i:i + MAX_SAMPLES_PER_DATAGRAM]
                    t0_epoch = (start_time + timedelta(
                        seconds=(total_samples + i) * sample_period_s
                    )).timestamp()

                    payload = encode_batch(
                        seq=seq,
                        t0_epoch=t0_epoch,
                        dt_s=sample_period_s,
                        actual_rate=actual_rate,
                        voltages=chunk_v,
                        temperatures=chunk_t,
                        hw_overrun=result.hardware_overrun,
                        buf_overrun=result.buffer_overrun,
                    )
                    self._send(payload)

                    seq += 1

                if csv_writer is not None:
                    for j, v in enumerate(voltages):
                        ts = start_time + timedelta(
                            seconds=(total_samples + j) * sample_period_s)
                        csv_writer.writerow([
                            ts.strftime('%Y-%m-%d %H:%M:%S.%f'),
                            '{:.5f}'.format(v),
                            '{:.3f}'.format(temperatures[j]),
                        ])

                total_samples += len(voltages)

                if voltages:
                    last_v = voltages[-1]
                    last_t = temperatures[-1]
                    print('\r{:9d} samples   {:10.5f} V   {:9.2f} C'.format(
                        total_samples, last_v, last_t), end='')
                    stdout.flush()

                if not result.running:
                    break

        except KeyboardInterrupt:
            _log.info("KeyboardInterrupt received.")
        finally:
            hat.a_in_scan_stop()
            hat.a_in_scan_cleanup()
            if csv_file is not None:
                csv_file.close()

        print('\nStopped. {:d} samples acquired.'.format(total_samples))


# Graceful exit on SIGTERM / SIGHUP.
_streamer = None

def _handle_signal(signum, frame):
    name = "SIGTERM" if signum == signal.SIGTERM else "SIGHUP"
    _log.info("%s received.", name)
    if _streamer is not None:
        _streamer.stop()
    raise SystemExit(0)


if __name__ == "__main__":
    _streamer = PyrometerStreamer()

    signal.signal(signal.SIGTERM, _handle_signal)
    if hasattr(signal, 'SIGHUP'):
        signal.signal(signal.SIGHUP, _handle_signal)

    try:
        _streamer.run()
    except KeyboardInterrupt:
        print("\nStopping...")
        _streamer.stop()
