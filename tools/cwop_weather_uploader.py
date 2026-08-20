#!/usr/bin/env python3
"""Publish the latest ROC weather observation to CWOP via APRS-IS.

The GW1100 remains receive-only from the ROC's perspective.  This service
converts the normalized local observation into an APRS weather report and
uploads it to the CWOP APRS-IS service.  It never keys a radio.
"""
from __future__ import annotations

import json
import math
import os
import socket
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

LATEST = Path(os.environ.get("N0JCG_WEATHER_LATEST", "/tmp/n0jcg-roc/weather/latest.json"))
STATE = Path(os.environ.get("CWOP_STATE_PATH", "/var/lib/n0jcg-roc/cwop-weather.json"))
CALL = os.environ.get("CWOP_STATION_ID", "").strip().upper()
PASSCODE = os.environ.get("CWOP_APRS_PASSCODE", "-1").strip() or "-1"
SERVER = os.environ.get("CWOP_APRS_SERVER", "cwop.aprs.net")
PORT = int(os.environ.get("CWOP_APRS_PORT", "14580"))
INTERVAL = max(300, int(os.environ.get("CWOP_INTERVAL_SECONDS", "300")))
ROC_API_BASE = os.environ.get("ROC_API_BASE", "http://127.0.0.1")
SETTINGS_PATH = Path(os.environ.get("CWOP_SETTINGS_PATH", "/var/lib/n0jcg-roc/cwop.json"))


def _num(value: object) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _coord(value: object, positive: str, negative: str, width: int) -> str:
    number = _num(value)
    if number is None:
        raise ValueError("CWOP latitude/longitude are required")
    hemi = positive if number >= 0 else negative
    absolute = abs(number)
    degrees = int(absolute)
    minutes = (absolute - degrees) * 60
    return f"{degrees:0{width}d}{minutes:05.2f}{hemi}"


def _weather_packet(observation: dict[str, object]) -> str:
    fields = observation.get("fields") or {}
    if not isinstance(fields, dict):
        raise ValueError("weather observation has no fields")
    lat = observation.get("latitude") or os.environ.get("CWOP_LATITUDE")
    lon = observation.get("longitude") or os.environ.get("CWOP_LONGITUDE")
    if lat is None or lon is None:
        raise ValueError("set CWOP_LATITUDE and CWOP_LONGITUDE")
    # Complete APRS weather reports require an explicit UTC timestamp suffix.
    timestamp = datetime.now(timezone.utc).strftime("%d%H%Mz")
    wind_dir = int(round(_num(fields.get("wind_direction_deg")) or 0)) % 360
    wind_mph = int(round((_num(fields.get("wind_speed_mps")) or 0) * 2.236936))
    gust_mph = int(round((_num(fields.get("wind_gust_mps")) or 0) * 2.236936))
    temp_f = int(round((_num(fields.get("temperature_c")) or 0) * 9 / 5 + 32))
    pressure = _num(fields.get("pressure_hpa"))
    pressure_tenths = int(round(pressure * 10)) if pressure is not None else None
    rain = _num(fields.get("rain_today_mm"))
    rain_hundredths = int(round(rain / 25.4 * 100)) if rain is not None else 0
    # APRS timestamped position/weather reports begin with '@' and have no
    # separator between the
    # UTC timestamp and the latitude.  A space here makes APRS-IS accept the
    # line as text but causes consumers such as aprs.fi to reject the weather
    # information field as an unsupported packet format.
    body = f"@{timestamp}{_coord(lat, 'N', 'S', 2)}/{_coord(lon, 'E', 'W', 3)}_"
    body += f"{wind_dir:03d}/{wind_mph:03d}g{gust_mph:03d}t{temp_f:03d}"
    body += f"r{rain_hundredths:03d}"
    if pressure_tenths is not None:
        body += f"b{pressure_tenths:06d}"
    body += f" {CALL} ROC Weather"
    return f"{CALL}>APRS,TCPIP*:{body}"


def upload(packet: str) -> str:
    with socket.create_connection((SERVER, PORT), timeout=15) as connection:
        connection.sendall(f"user {CALL} pass {PASSCODE} vers N0JCG-ROC-CWOP 1.0\r\n".encode())
        response = ""
        connection.settimeout(5)
        while "logresp" not in response.lower() and len(response) < 4096:
            response += connection.recv(1024).decode("ascii", "replace")
        if "verified" not in response.lower() and "unverified" not in response.lower():
            raise RuntimeError(f"CWOP/APRS-IS login rejected: {response.strip()}")
        connection.sendall((packet + "\r\n").encode())
        return response.strip()


def run_once() -> dict[str, object]:
    global CALL, PASSCODE, INTERVAL
    try:
        settings = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        settings = {}
    if not settings.get("enabled"):
        return {"ok": True, "skipped": True, "reason": "CWOP disabled or not configured"}
    CALL = str(settings.get("station_id") or CALL).upper()
    os.environ["CWOP_LATITUDE"] = str(settings.get("latitude") or os.environ.get("CWOP_LATITUDE", ""))
    os.environ["CWOP_LONGITUDE"] = str(settings.get("longitude") or os.environ.get("CWOP_LONGITUDE", ""))
    INTERVAL = max(300, int(settings.get("interval_seconds", INTERVAL)))
    if not CALL:
        raise ValueError("CWOP station ID is not configured")
    try:
        request = Request(f"{ROC_API_BASE.rstrip('/')}/api/weather", headers={"Accept": "application/json"})
        with urlopen(request, timeout=10) as response:
            status = json.loads(response.read().decode("utf-8"))
        observation = status.get("observation") if isinstance(status, dict) else None
    except OSError:
        observation = None
    if not isinstance(observation, dict):
        observation = json.loads(LATEST.read_text(encoding="utf-8"))
    packet = _weather_packet(observation)
    response = upload(packet)
    result = {"ok": True, "station_id": CALL, "packet": packet, "server": SERVER, "response": response,
              "sent_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    while True:
        try:
            print(json.dumps(run_once()), flush=True)
        except Exception as error:  # noqa: BLE001 - keep the uploader alive
            STATE.parent.mkdir(parents=True, exist_ok=True)
            STATE.write_text(json.dumps({"ok": False, "error": str(error)}, indent=2) + "\n", encoding="utf-8")
            print(f"CWOP upload failed: {error}", flush=True)
        time.sleep(INTERVAL)


if __name__ == "__main__":
    raise SystemExit(main())
