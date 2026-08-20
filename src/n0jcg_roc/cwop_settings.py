from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

DEFAULT = {
    "enabled": False,
    "station_id": "",
    "latitude": "",
    "longitude": "",
    "interval_seconds": 300,
    "configured": False,
    "updated_utc": None,
}
CALL_RE = re.compile(r"^[A-Z0-9]{3,6}(?:-[A-Z0-9]{1,2})?$")


def load_cwop_settings(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        result = {**DEFAULT, **data}
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        result = dict(DEFAULT)
    result["configured"] = bool(result.get("station_id") and result.get("latitude") and result.get("longitude"))
    return result


def save_cwop_settings(path: Path, payload: object) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("settings must be an object")
    current = load_cwop_settings(path)
    station_id = str(payload.get("station_id", current["station_id"])).strip().upper()
    latitude = str(payload.get("latitude", current["latitude"])).strip()
    longitude = str(payload.get("longitude", current["longitude"])).strip()
    if station_id and not CALL_RE.fullmatch(station_id):
        raise ValueError("station ID must be a valid callsign")
    try:
        if latitude and not -90 <= float(latitude) <= 90: raise ValueError
        if longitude and not -180 <= float(longitude) <= 180: raise ValueError
        interval = max(300, min(3600, int(payload.get("interval_seconds", current["interval_seconds"]))))
    except (TypeError, ValueError):
        raise ValueError("latitude, longitude, and interval are invalid") from None
    result = {**current, "enabled": bool(payload.get("enabled", current["enabled"])), "station_id": station_id,
              "latitude": latitude, "longitude": longitude, "interval_seconds": interval,
              "updated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    result["configured"] = bool(station_id and latitude and longitude)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    return result
