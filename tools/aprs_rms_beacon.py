#!/usr/bin/env python3
"""Publish the RMS gateway position to APRS-IS without using RF."""
from __future__ import annotations

import os
import socket
import time

CALL = os.environ.get("APRS_RMS_BEACON_CALL", "N0JCG-10").strip().upper()
SERVER = os.environ.get("APRS_IGATE_SERVER", "rotate.aprs2.net")
PORT = int(os.environ.get("APRS_IGATE_PORT", "14580"))
PASSCODE = os.environ.get("APRS_IGATE_PASSCODE", "")
LATITUDE = float(os.environ.get("APRS_RMS_BEACON_LATITUDE", "38.800788"))
LONGITUDE = float(os.environ.get("APRS_RMS_BEACON_LONGITUDE", "-105.200100"))
INTERVAL = max(300, int(os.environ.get("APRS_RMS_BEACON_INTERVAL_SECONDS", "1800")))
COMMENT = os.environ.get("APRS_RMS_BEACON_COMMENT", "N0JCG RMS Packet Gateway 145.070 MHz")

def coord(value: float, positive: str, negative: str, width: int) -> str:
    hemi = positive if value >= 0 else negative
    absolute = abs(value)
    degrees = int(absolute)
    minutes = (absolute - degrees) * 60
    return f"{degrees:0{width}d}{minutes:05.2f}{hemi}"

def packet() -> str:
    if not CALL or not PASSCODE:
        raise ValueError("APRS RMS beacon call and APRS-IS passcode are required")
    if not -90 <= LATITUDE <= 90 or not -180 <= LONGITUDE <= 180:
        raise ValueError("APRS RMS beacon coordinates are out of range")
    # ``W`` is the overlay and alternate-table ``a`` is the Winlink symbol.
    body = f"!{coord(LATITUDE, 'N', 'S', 2)}W{coord(LONGITUDE, 'E', 'W', 3)}a{COMMENT}"
    return f"{CALL}>APN000,TCPIP*:{body}"

def send() -> str:
    with socket.create_connection((SERVER, PORT), timeout=15) as connection:
        connection.sendall(f"user {CALL} pass {PASSCODE} vers N0JCG-ROC-RMS 1.0\r\n".encode())
        response = ""
        connection.settimeout(5)
        while "logresp" not in response.lower() and len(response) < 4096:
            response += connection.recv(1024).decode("ascii", "replace")
        if "verified" not in response.lower() and "unverified" not in response.lower():
            raise RuntimeError(f"APRS-IS login rejected: {response.strip()}")
        message = packet()
        connection.sendall((message + "\r\n").encode("ascii"))
        return message

def main() -> int:
    while True:
        try:
            print(send(), flush=True)
        except Exception as error:  # noqa: BLE001 - keep the beacon alive
            print(f"RMS APRS-IS beacon failed: {error}", flush=True)
        time.sleep(INTERVAL)

if __name__ == "__main__":
    raise SystemExit(main())
