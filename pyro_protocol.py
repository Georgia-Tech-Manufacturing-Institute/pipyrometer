"""Pyrometer UDP JSON wire protocol -- encode/decode helpers.

No hardware dependencies (no daqhats, no MCC 118). Safe to import on
Windows for tests, and in PyLHW's pyrometer_monitor.
"""

import json

PROTOCOL_VERSION = 1


def encode_batch(seq, t0_epoch, dt_s, actual_rate, voltages, temperatures,
                 hw_overrun=False, buf_overrun=False):
    """Build a JSON datagram payload from a batch of samples."""
    return json.dumps({
        "type": "pyro_data",
        "v": PROTOCOL_VERSION,
        "seq": seq,
        "t0": round(t0_epoch, 6),
        "dt": round(dt_s, 9),
        "rate": round(actual_rate, 3),
        "voltage": [round(v, 5) for v in voltages],
        "temperature": [round(t, 3) for t in temperatures],
        "hw_overrun": hw_overrun,
        "buf_overrun": buf_overrun,
    }).encode("utf-8")


def decode_batch(data):
    """Parse a raw datagram into a dict. Returns None on bad data."""
    try:
        msg = json.loads(data.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if msg.get("type") != "pyro_data":
        return None
    return msg


def encode_handshake():
    """Build the client registration datagram."""
    return json.dumps({"command": "handshake"}).encode("utf-8")


def encode_handshake_ack(rate):
    """Build the server's handshake acknowledgement."""
    return json.dumps({
        "type": "handshake_ack",
        "v": PROTOCOL_VERSION,
        "rate": round(rate, 3),
    }).encode("utf-8")
