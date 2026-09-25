#!/usr/bin/env python3
"""PC-side companion to pyrometer_daq_socket.py.

Sends a JSON handshake to the Pi, then receives batched pyrometer samples
as JSON datagrams, prints them, and optionally saves to CSV.  This is the
standalone reference receiver; for the full PyLHW GUI integration, use
pyrometer_monitor.PyrometerMonitor instead.

Usage:
    1. Start pyrometer_daq_socket.py on the Pi.
    2. Set PI_HOST below to the Pi's IP address.
    3. Run:  python pc_receiver.py
"""
import csv
import json
import socket
import sys
from datetime import datetime, timezone, timedelta

# --- Configuration -----------------------------------------------------------
PI_HOST = '169.254.200.84'
PI_PORT = 55555

SAVE_CSV = True
CSV_FILENAME = 'pyrometer_received.csv'
# -----------------------------------------------------------------------------

HANDSHAKE_MSG = json.dumps({"command": "handshake"}).encode("utf-8")


def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(5.0)

    server = (PI_HOST, PI_PORT)
    sock.sendto(HANDSHAKE_MSG, server)
    print('Sent handshake to {}:{}. Waiting for data... (Ctrl-C to quit)'.format(
        PI_HOST, PI_PORT))

    csv_file = None
    writer = None
    if SAVE_CSV:
        csv_file = open(CSV_FILENAME, 'a', newline='')
        writer = csv.writer(csv_file)
        writer.writerow(['timestamp_utc', 'voltage_V', 'temperature_C'])

    received = 0
    last_seq = -1
    try:
        while True:
            try:
                data, _ = sock.recvfrom(4096)
            except socket.timeout:
                sock.sendto(HANDSHAKE_MSG, server)
                continue

            try:
                msg = json.loads(data.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                print('\rBad datagram ({:d} bytes)'.format(len(data)), end='')
                continue

            msg_type = msg.get("type")

            if msg_type == "handshake_ack":
                print('Connected. Pi scan rate: {:.3f} Hz'.format(msg.get("rate", 0)))
                continue

            if msg_type != "pyro_data":
                continue

            seq = msg["seq"]
            if last_seq >= 0 and seq != last_seq + 1:
                gap = seq - last_seq - 1
                print('\n*** Dropped {:d} datagram(s) (seq {:d} -> {:d}) ***'.format(
                    gap, last_seq, seq))
            last_seq = seq

            voltages = msg["voltage"]
            temperatures = msg["temperature"]
            t0 = msg["t0"]
            dt = msg["dt"]

            for i, (v, t) in enumerate(zip(voltages, temperatures)):
                ts = datetime.fromtimestamp(t0 + i * dt, tz=timezone.utc)
                received += 1

                if writer is not None:
                    writer.writerow([
                        ts.strftime('%Y-%m-%d %H:%M:%S.%f'),
                        '{:.5f}'.format(v),
                        '{:.3f}'.format(t),
                    ])

            if voltages:
                print('\r{:9d}   {:10.5f} V   {:9.2f} C   seq={:d}'.format(
                    received, voltages[-1], temperatures[-1], seq), end='')
                sys.stdout.flush()

            if msg.get("hw_overrun"):
                print('\n*** Hardware overrun on Pi ***')
            if msg.get("buf_overrun"):
                print('\n*** Buffer overrun on Pi ***')

    except KeyboardInterrupt:
        print('\nStopping. Received {:d} samples.'.format(received))
    finally:
        sock.close()
        if csv_file is not None:
            csv_file.close()
            print('Saved to {}.'.format(CSV_FILENAME))


if __name__ == '__main__':
    main()
