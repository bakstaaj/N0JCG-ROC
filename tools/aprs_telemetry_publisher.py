#!/usr/bin/env python3
"""Publish low-rate N0JCG-5 ROC health telemetry to APRS-IS (Internet only)."""
from __future__ import annotations

import json
import os
import socket
import time
from pathlib import Path
from urllib.request import Request, urlopen


CALLSIGN = os.environ.get("APRS_TELEMETRY_CALL", "N0JCG-5")
SERVER = os.environ.get("APRS_IGATE_SERVER", "rotate.aprs2.net")
PORT = int(os.environ.get("APRS_IGATE_PORT", "14580"))
LOGIN = os.environ.get("APRS_IGATE_LOGIN", CALLSIGN)
PASSCODE = os.environ.get("APRS_IGATE_PASSCODE", "")
INTERVAL = max(300, int(os.environ.get("APRS_TELEMETRY_INTERVAL_SECONDS", "1800")))
API_BASE = os.environ.get("ROC_API_BASE", "http://127.0.0.1")
STATE_PATH = Path(os.environ.get("APRS_TELEMETRY_STATE", "/var/lib/n0jcg-roc/aprs-telemetry.json"))
DESTINATION = "APDW17"
VERSION = "N0JCG-ROC-Telemetry 1.0"


def fetch(path: str) -> dict:
    request = Request(f"{API_BASE}{path}", headers={"Accept": "application/json"})
    with urlopen(request, timeout=8) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload if isinstance(payload, dict) else {}


def clamp(value: float | int | None, low: float = 0, high: float = 255) -> int:
    try:
        return int(round(max(low, min(high, float(value)))))
    except (TypeError, ValueError):
        return 0


def snapshot(previous_count: int | None) -> tuple[list[int], int, dict]:
    system = fetch("/api/system")
    aprs = fetch("/api/aprs")
    pipeline = aprs.get("pipeline") or {}
    cpu = (system.get("resources") or {}).get("cpu") or {}
    memory = (system.get("resources") or {}).get("memory") or {}
    temperature = (system.get("resources") or {}).get("temperature") or {}
    count = int(aprs.get("packet_count") or 0)
    delta = count - previous_count if previous_count is not None else 0
    state_score = {"healthy": 255, "degraded": 128, "fault": 0}.get(pipeline.get("state"), 0)
    values = [
        clamp(temperature.get("celsius"), 0, 255),
        clamp(cpu.get("utilization_percent")),
        clamp(memory.get("used_percent")),
        clamp(delta),
        state_score,
    ]
    bits = [
        bool(aprs.get("active")),
        pipeline.get("state") == "healthy",
        pipeline.get("state") != "fault",
        bool(pipeline.get("last_rf_packet_timestamp_utc")),
        bool(pipeline.get("last_pipeline_activity_utc")),
        True,  # APRS-IS publisher reached this local API.
        False,
        False,
    ]
    return values, count, {"state": pipeline.get("state"), "packet_count": count, "packet_delta": delta, "bits": bits}


def frame(payload: str) -> str:
    """Build a direct APRS telemetry information-field packet.

    Telemetry data and its PARM/UNIT/EQNS/BITS definitions are not APRS
    messages. Keeping the payload directly after the colon is required for
    APRS-IS telemetry indexers such as aprs.fi to recognize the packets.
    """
    return f"{CALLSIGN}>{DESTINATION}:{payload}"


def telemetry_message(payload: str) -> str:
    """Build an addressed APRS telemetry-definition message."""
    return f"{CALLSIGN}>{DESTINATION}::{CALLSIGN:<9}:{payload}"


def definitions() -> list[str]:
    return [
        # APRS101 limits the five parameter labels to 7, 7, 6, 6, and 5
        # characters respectively. Keep these short so aprs.fi accepts them.
        telemetry_message("PARM.CPU,LOAD,MEM,RF,PIPE"),
        telemetry_message("UNIT.degC,percent,percent,frames,score"),
        telemetry_message("EQNS.0,0.392157,0,0,0.392157,0,0,0.392157,0,0,1,0,0,1,0"),
        # BITS has one project-name field, limited to 23 characters.
        telemetry_message("BITS.11111111,ROC health bits"),
    ]


def telemetry(values: list[int], sequence: int, bits: list[bool]) -> str:
    digital = "".join("1" if bit else "0" for bit in bits)
    return frame(f"T#{sequence % 1000:03d},{','.join(f'{value:03d}' for value in values)},{digital}")


def initial_sequence() -> int:
    """Continue the sequence across service restarts."""
    try:
        saved = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return (int(saved.get("sequence", -1)) + 1) % 1000
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return int(time.time() // INTERVAL) % 1000


def run() -> None:
    if not PASSCODE:
        raise SystemExit("APRS telemetry requires APRS_IGATE_PASSCODE")
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    previous_count = None
    sequence = initial_sequence()
    while True:
        try:
            values, count, metadata = snapshot(previous_count)
            previous_count = count
            with socket.create_connection((SERVER, PORT), timeout=15) as connection:
                connection.sendall(f"user {LOGIN} pass {PASSCODE} vers {VERSION}\r\n".encode())
                connection.settimeout(5)
                response_parts = []
                while True:
                    response_parts.append(connection.recv(512).decode("ascii", "replace"))
                    response = "".join(response_parts)
                    if "logresp" in response.lower() or "verified" in response.lower() or "unverified" in response.lower():
                        break
                response = "".join(response_parts)
                if "unverified" in response.lower() or ("verified" not in response.lower() and "logresp" not in response.lower()):
                    raise RuntimeError(f"APRS-IS login rejected: {response.strip()}")
                for frame in definitions():
                    connection.sendall((frame + "\r\n").encode())
                connection.sendall((telemetry(values, sequence, metadata["bits"]) + "\r\n").encode())
            STATE_PATH.write_text(json.dumps({**metadata, "sequence": sequence, "sent_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, indent=2) + "\n")
            sequence += 1
        except Exception as error:  # noqa: BLE001 - watchdog must keep retrying
            STATE_PATH.write_text(json.dumps({"error": str(error), "sent_utc": None}, indent=2) + "\n")
        time.sleep(INTERVAL)


if __name__ == "__main__":
    run()
