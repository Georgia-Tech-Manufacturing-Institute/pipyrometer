#!~/thermocouple-daq/venv/bin python
"""
    MCC 134 Functions Demonstrated:
        mcc134.t_in_read

    Purpose:
        Read a single data value for each channel in a loop.

    Description:
        This example demonstrates acquiring data using a software timed loop
        to read a single value from each selected channel on each iteration
        of the loop.
"""
from __future__ import print_function
from time import sleep
from sys import stdout
from daqhats import mcc134, HatIDs, HatError, TcTypes
from daqhats_utils import select_hat_device, tc_type_to_string
from datetime import datetime as dt
import math
import os
import csv
import glob
import numpy as np
import pandas as pd

# Constants
CURSOR_BACK_2 = '\x1b[2D'
ERASE_TO_END_OF_LINE = '\x1b[0K'

# Database information
NULL_VALUE = 'NaN'

def init_csv(name='record', header=[]):
    init_date = dt.now().strftime('%Y-%m-%d')
    init_time = dt.now().strftime('%H-%M-%S')
    # Create directory if it doesn't exist
    directory = os.path.join('data', init_date)
    if not os.path.exists(directory):
        os.makedirs(directory)
    filename = os.path.join(directory, f'{name}_{init_time}.csv')

    with open(filename, 'a', newline='') as f:
        csv_writer = csv.writer(f)

        if len(header)>0:
            csv_writer.writerow(header)
    return filename

def toSQLiteDB():
    input_files = glob.glob("*.csv")
    print(input_files)
    output_filename = input('Name of database (ending with .sqlite): ')

    # all the usual options are supported
    options = csv_to_sqlite.CsvOptions(typing_style="full", encoding="windows-1250") 

    csv_to_sqlite.write_csv(input_files, output_filename, options)
    # https://pypi.org/project/csv-to-sqlite/ (source of code)


def main():
    """
    This function is executed automatically when the module is run directly.
    """
    tc_type = TcTypes.TYPE_K   # change this to the desired thermocouple type
    delay_between_reads = 1  # Seconds
    channels = []
    output_filename = 'temp.csv'
    column_names = ['timestamp']

    try:
        # Get an instance of the selected hat device object.
        address = select_hat_device(HatIDs.MCC_134)
        hat = mcc134(address)

        print('\nTC DAQ modified from MCC 134 single data value read example')
        print('    Function used: mcc134.t_in_read')
        print('    Channels: Selectable by user input')
        print('    Thermocouple type: ' + tc_type_to_string(tc_type))

        try:
            max_channels = int(input("\n Type desired number of channels (1-4): "))
            channels = [i for i in range(0, max_channels)]
        except (NameError, SyntaxError):
            pass

        try:
            freq = float(input("\n Enter the frequecny (0.1 - 10 Hz): "))
            delay_between_reads = 1.0/freq
        except (NameError, SyntaxError):
            pass

        try:
            output_filename = input('Name of csv (ending with .csv): ')
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
        
        try:
            samples_per_channel = 0
            while True:
                print('\r{:8d}'.format(samples_per_channel), end='')

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

                df.loc[samples_per_channel] = row
                data_samples = []
                stdout.flush()

                # Update samples per channel count
                samples_per_channel += 1

                # Wait the specified interval between reads.
                sleep(delay_between_reads)
            
        except KeyboardInterrupt:
            # Clear the '^C' from the display.
            print(CURSOR_BACK_2, ERASE_TO_END_OF_LINE, '\n')
            df.to_csv(output_filename)

    except (HatError, ValueError) as error:
        print('\n', error)


if __name__ == '__main__':
    # This will only be run when the module is called directly.
    main()
