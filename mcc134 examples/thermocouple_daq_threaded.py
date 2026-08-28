#!~/thermocouple-daq/venv/bin python
"""
    Script Purpose:
        Acquire temperature data from MCC 134 thermocouple DAQ device using a software-timed loop.

    Features:
        - Reads temperature data from user-selected channels.
        - Supports user-defined sampling frequency.
        - Saves data to a CSV file in real-time using a separate thread.
        - Handles various thermocouple error states (Open, OverRange, CommonMode).

    MCC 134 Functions Demonstrated:
        mcc134.t_in_read
"""
from __future__ import print_function
from time import sleep
from sys import stdout
from daqhats import mcc134, HatIDs, HatError, TcTypes
from daqhats_utils import select_hat_device, tc_type_to_string
from datetime import datetime as dt
from threading import Thread
from queue import Queue
import math
import os
import csv
import glob
import numpy as np
import pandas as pd
import signal 
import logging

# Constants
CURSOR_BACK_2 = '\x1b[2D'
ERASE_TO_END_OF_LINE = '\x1b[0K'

# Database information
NULL_VALUE = 'NaN'

def csv_writer_thread(output_filename, queue):
    """
    Thread function to write rows to a CSV file.
    """
    with open(output_filename, 'a', newline='') as csvfile:
        writer = csv.writer(csvfile)
        while True:
            row = queue.get()
            if row is None:  # Sentinel value to exit the thread
                break
            writer.writerow(row)
            queue.task_done()

def main():
    """
    This function is executed automatically when the module is run directly.
    """
    logging.basicConfig(
        filename='thermocouple_daq.log',
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    logging.info("Logger initialized.")

    tc_type = TcTypes.TYPE_K   # change this to the desired thermocouple type
    delay_between_reads = 1  # Seconds
    channels = []
    output_filename = 'temp.csv'
    column_names = ['timestamp']

    # Set up signal handler to gracefully exit on SIGTERM or SIGHUP (from SSH being closed).
    def handle_signal(signum, frame):
        signal_name = "SIGTERM" if signum == signal.SIGTERM else "SIGHUP"
        logging.info(f"{signal_name} received. Exiting gracefully...")
        row_queue.put(None)  # Signal the writer thread to exit
        writer_thread.join()
        exit(0)

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGHUP, handle_signal)

    try:
        # Get an instance of the selected hat device object.
        address = select_hat_device(HatIDs.MCC_134)
        hat = mcc134(address)

        logging.info("Thermocouple DAQ started.")
        print('\nTC DAQ modified from MCC 134 single data value read example')
        print('    Function used: mcc134.t_in_read')
        print('    Channels: Selectable by user input')
        print('    Thermocouple type: ' + tc_type_to_string(tc_type))

        try:
            max_channels = int(input("\n Type desired number of channels (1-4): "))
            channels = [i for i in range(0, max_channels)]
            logging.info(f"Selected channels: {channels}")
        except (NameError, SyntaxError):
            pass

        try:
            freq = float(input("\n Enter the frequecny (0.1 - 10 Hz): "))
            delay_between_reads = 1.0/freq
            if freq > 10.0 or freq < 0.1:
                raise ValueError('Frequency must be between 0.1 and 10 Hz.')
        except (NameError, SyntaxError):
            pass

        try:
            output_filename = input('Name of csv (ending with .csv): ')
            if '.csv' not in output_filename:
                raise ValueError('Filename must end with .csv')
        except (NameError, SyntaxError):
            pass
            
        try:
            input("\nPress 'Enter' to continue")
        except (NameError, SyntaxError):
            pass

        # Set up channels for reading
        for channel in channels:
            hat.tc_type_write(channel, tc_type)


        # Print start message
        print('\nAcquiring data ... Press Ctrl-C to abort')

        # Display the header row for the data table.
        print('\n  Sample', end='')
        for channel in channels:
            print('     Channel', channel, end='')
            column_names.append(f'ch{channel:d}')
        print('')
        
        df = pd.DataFrame(columns=column_names)
        data_samples = []
        
        # Initialize the CSV writer thread
        row_queue = Queue()
        writer_thread = Thread(target=csv_writer_thread, args=(output_filename, row_queue), daemon=True)
        writer_thread.start()

        # Write the header row to the CSV file
        row_queue.put(column_names)

        try:
            samples_per_channel = 0
            while True:
                print('\r{:8d}'.format(samples_per_channel), end='')

                prior_read_start = dt.now()
                # Read a single value from each selected channel.
                for channel in channels:
                    value = hat.t_in_read(channel)
                    if value == mcc134.OPEN_TC_VALUE:
                        print('     Open     ', end='')
                        val = 'Open'
                        val = NULL_VALUE
                    elif value == mcc134.OVERRANGE_TC_VALUE:
                        print('     OverRange', end='')
                        val = 'OverRange'
                    elif value == mcc134.COMMON_MODE_TC_VALUE:
                        print('   Common Mode', end='')
                        val = 'CommonMode'
                    else:
                        print('{:12.2f} C'.format(value), end='')
                        val = value
                    data_samples.append(val)

                # Construct row entry into dataframe
                row = [pd.Timestamp.utcnow(), ]

                # Append data samples based on size of data (allows for handling of variable channel numbers)
                for sample in data_samples:
                    row.append(sample)

                # Add the row to the queue for the writer thread
                row_queue.put(row)

                df.loc[samples_per_channel] = row
                data_samples = []
                stdout.flush()

                # Update samples per channel count
                samples_per_channel += 1

                # Wait the specified interval between reads.
                # sleep(delay_between_reads)
                while(dt.now() - prior_read_start).total_seconds() < delay_between_reads:
                    pass
            
        except KeyboardInterrupt:
            # Clear the '^C' from the display.
            logging.info("KeyboardInterrupt received. Exiting gracefully...")
            print(CURSOR_BACK_2, ERASE_TO_END_OF_LINE, '\n')
            row_queue.put(None)
            writer_thread.join()

    except (HatError, ValueError) as error:
        print('\n', error)

if __name__ == '__main__':
    # This will only be run when the module is called directly.
    main()
