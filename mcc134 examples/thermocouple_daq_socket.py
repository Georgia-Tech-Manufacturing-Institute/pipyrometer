#!~/thermocouple-daq/venv/bin python
"""
    UPDATED BY KATE MAY 2026 because the other script broke for some reason??
    NEEDS CORRESPONDING PC SCRIPT TO RUN PROPERLY

    Script Purpose:
        Acquire temperature data from MCC 134 thermocouple DAQ device using a software-timed loop.

    Features:
        - Reads temperature data from user-selected channels.
        - Supports user-defined sampling frequency.
        - Pushes data to a UDP Server that can be accessed by other devices on the local network.
        - Optional CSV Saving in case UDP Connection drops
        - Handles various thermocouple error states (Open, OverRange, CommonMode).

    MCC 134 Functions Demonstrated:
        mcc134.t_in_read
"""
from __future__ import print_function
from sys import stdout
from daqhats import mcc134, HatIDs, HatError, TcTypes
from daqhats_utils import select_hat_device, tc_type_to_string
from datetime import datetime as dt
import threading
import queue
import math
import os
import csv
import glob
import numpy as np
import pandas as pd
import signal
import logging
import time

#UDP Messaging
import socket
import sys
from struct import pack

# Constants
CURSOR_BACK_2 = '\x1b[2D'
ERASE_TO_END_OF_LINE = '\x1b[0K'

# Database information
NULL_VALUE = 'NaN'

class ThermocoupleApplication:
    # THREAD HANDLING ITEMS
    # ---------------------
    def __init__(s):
        # x = input('Press 1 for UDP or 2 for TCP...')
        x='1'
        if x == '1': 
            s._threads = [
            s._read_thermocouples,
            s._UDP_conn,
            #s._TCP_conn,
        ]
        elif x == '2': 
            s._threads = [
            s._read_thermocouples,
            #s._UDP_conn,
            s._TCP_conn,
        ]
        else: 
            ValueError(f'Pressed key "{x}" invalid. Exiting.')
        s._running = True
        s._connected = False

    def run(s):
        s._thread_objs=[]
        for thread in s._threads:
            t = threading.Thread(target=thread)
            t.start()
            s._thread_objs.append(t)

        s._UDP_queue=queue.Queue(maxsize=0)

    def kill_threads(s):
        print("Entered kill sequence.")
        s._running=False
        for thread in s._thread_objs:
            print('Closing thread...')
            if thread == s._TCP_conn: 
                s._server.close()
            thread.join()
            
        time.sleep(1)
        print("Done! :)")
    # ---------------------

    # UDP Connection
    def _UDP_conn(s):
        # Create a socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # s._server.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
        # Set IP
        host, port = '0.0.0.0', 55555
        server_address = (host, port) 
        sock.bind((host, port))
        
        print('Waiting for Connection...')

        _, client_address = sock.recvfrom(1024)

        print('\n' + f'Connected to {client_address}.')
        s._connected = True
        
        while s._running: 
            row = s._UDP_queue.get()
            if row is None:  # Sentinel value to exit the thread
                pass
            else:
                # Pack three 32-bit floats into message and send
                row = [format(x,'.5f').zfill(10) if not isinstance(x,str) else x for x in row]
                #print(f"\n--\nROW\n{row}\n--\n")
                format_str = ', '.join([f"{len(x)}s" for x in row]).replace(', ','')
                row = [x.encode('utf-8') for x in row]
                #print(f"\n--\nFORMAT STR\n{format_str}\n--\n")
                message = pack(format_str, *row)
                sock.sendto(message, client_address)
            #time.sleep(0.01)
        sock.close()
        print('Stopped sending data.')

    # TCP Connection
    def _TCP_conn(s):
        # Create a socket
        s._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s._server.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
        # Set IP
        host, port = '0.0.0.0', 55555
        server_address = (host, port) 

        s._server.bind((host, port))
        s._server.listen(5)
        
        print('Waiting for Connection...')
        
        while s._running: 
            client, address = s._server.accept()
            #print('connected?')
            client_handler = threading.Thread(target=s._handle_client, args=(client,))
            client_handler.start()
        print('Exited UDP conn.')

    def _handle_client(s, client_socket): 
        print('\n\n')
        print(f'Started connection to {client_socket}.')
        print('\n\n')
        # Send messages
        with client_socket as sock:
            while s._running:
                row = s._UDP_queue.get()
                if row is None:  # Sentinel value to exit the thread
                    pass
                else:
                    # Pack three 32-bit floats into message and send
                    #print(f"\n--\nROW\n{row}\n--\n")
                    row = [format(x,'.5f').zfill(10) if not isinstance(x,str) else x for x in row]
                    format_str = ', '.join([f"{len(x)}s" for x in row]).replace(', ','')
                    row = [x.encode('utf-8') for x in row]
                    #print(f"\n--\nFORMAT STR\n{format_str}\n--\n")
                    message = pack(format_str, *row)
                    sock.send(message)
	            #time.sleep(0.01)
        print('Stopped sending data.')

    # CSV Saving
    def _CSV_backup(s):
        """
        Thread function to write rows to a CSV file.
        """
        with open(s.output_csv_name, 'a', newline='') as csvfile:
            writer = csv.writer(csvfile)
            while s._running:
                row = s._CSV_queue.get()
                if row is None:  # Sentinel value to exit the thread
                    break
                writer.writerow(row)

    # Thermocouple reading
    def _read_thermocouples(s):
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
        s.output_csv_name = 'temp.csv'
        column_names = ['timestamp']
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
                #max_channels = int(input("\n Type desired number of channels (1-4): "))
                max_channels = int(4)
                channels = [i for i in range(0, max_channels)]
                logging.info(f"Selected channels: {channels}")
            except (NameError, SyntaxError):
                pass

            try:
                #freq = float(input("\n Enter the frequecny (0.1 - 10 Hz): "))
                freq=float(10)
                delay_between_reads = 1.0/freq
                if freq > 10.0 or freq < 0.1:
                    raise ValueError('Frequency must be between 0.1 and 10 Hz.')
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
            #csv_tf = input("Type 1 to enable CSV saving backup, or press enter to skip.")
            csv_tf = ''
            while not s._connected: 
                time.sleep(0.1)
            if csv_tf=='1':
                try:
                    s.output_csv_name = input('Name of csv (ending with .csv): ')
                    if '.csv' not in s.output_csv_name:
                        raise ValueError('Filename must end with .csv')
                except (NameError, SyntaxError):
                    pass
                s._thread_objs.append(threading.Thread(target=s._CSV_backup))
                s._thread_objs[len(s._thread_objs)-1].start()

                # Write the header row to the CSV file
                s._CSV_queue=queue.Queue(maxsize=0)
                s._CSV_queue.put(column_names)
                csv_toggle=True
            else: 
                csv_toggle=False
            s._UDP_queue.put(column_names)

            try:
                samples_per_channel = 0
                while s._running:
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
                    row = [pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S'), ]

                    # Append data samples based on size of data (allows for handling of variable channel numbers)
                    for sample in data_samples:
                        row.append(sample)

                    # Add the row to the queue for the writer thread
                    s._UDP_queue.put(row)
                    if csv_toggle: 
                        s._CSV_queue.put(row)

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
                s._UDP_queue.put(None)
                s.kill_threads()

        except (HatError, ValueError, KeyboardInterrupt) as error:
            if error!=KeyboardInterrupt:
                print('\n', error)
        print('Stopped Thermocouple collection.')

# put signal def here
# Set up signal handler to gracefully exit on SIGTERM or SIGHUP (from SSH being closed).
def handle_signal(signum):
    signal_name = "SIGTERM" if signum == signal.SIGTERM else "SIGHUP"
    logging.info(f"{signal_name} received. Exiting gracefully...")
    thermo_app._UDP_queue.put(None)  # Signal the writer thread to exit
    thermo_app.kill_threads()
    exit(0)


if __name__ == "__main__":
    thermo_app = ThermocoupleApplication()
    thermo_app.run()


    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGHUP, handle_signal)


    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt: 
        print("Killing threads...")
        final=thermo_app.kill_threads()
