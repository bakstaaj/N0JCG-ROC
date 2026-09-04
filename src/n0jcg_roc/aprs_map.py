from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
from threading import Lock
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from . import __version__


APRSFI_API_URL = "https://api.aprs.fi/api/get"
APRSFI_SOURCE_URL = "https://aprs.fi/"
APRSFI_CACHE_SECONDS = 600
APRSFI_MAX_CALLSIGNS = 20
APRS_MAP_WINDOW_HOURS = 24
APRS_JOURNAL_UNIT = os.environ.get("APRS_JOURNAL_UNIT", "n0jcg-aprs-rx.service")
CALLSIGN_PATTERN = re.compile(r"^(?:\[[^\]]+\]\s*)?([A-Z0-9][A-Z0-9-]{1,8})>", re.IGNORECASE)
POSITION_PATTERN = re.compile(r"[!=/@](\d{2})(\d{2}\.\d{2})([NS])[^0-9A-Za-z]?([0-9]{3})(\d{2}\.\d{2})([EW])")
_SETTINGS_LOCK = Lock()


def _symbol_from_frame(frame: str, position: re.Match[str]) -> str | None:
    """Return the APRS table/code pair immediately following an uncompressed position."""
    # The table identifier is the character between latitude and longitude;
    # the symbol code follows the longitude hemisphere.
    span = frame[position.start():position.end()]
    table = re.search(r"[NS]([/\\A-Z0-9])\d{3}", span)
    suffix = frame[position.end():]
    if table and suffix:
        return table.group(1) + suffix[0]
    return None


def heard_callsigns(log_path: Path, limit: int = APRSFI_MAX_CALLSIGNS) -> list[str]:
    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    callsigns: list[str] = []
    seen: set[str] = set()
    for line in reversed(lines):
        match = CALLSIGN_PATTERN.match(line.strip())
        if not match:
            continue
        callsign = match.group(1).upper()
        if callsign in seen:
            continue
        seen.add(callsign)
        callsigns.append(callsign)
        if len(callsigns) >= limit:
            break
    return callsigns


def _heard_activity_from_lines(lines: list[str], limit: int = APRSFI_MAX_CALLSIGNS) -> dict:
    callsigns: list[str] = []
    seen: set[str] = set()
    frame_count = 0
    for line in reversed(lines):
        match = CALLSIGN_PATTERN.match(line.strip())
        if not match:
            continue
        frame_count += 1
        callsign = match.group(1).upper()
        if callsign in seen or len(callsigns) >= limit:
            continue
        seen.add(callsign)
        callsigns.append(callsign)
    return {"callsigns": callsigns, "frame_count": frame_count}


def _heard_activity_from_journal(lines: list[str], limit: int = APRSFI_MAX_CALLSIGNS) -> dict:
    records: list[dict] = []
    for line in lines:
        try:
            entry = json.loads(line)
            frame = str(entry.get("MESSAGE") or "").strip()
            timestamp_epoch = int(entry["__REALTIME_TIMESTAMP"]) / 1_000_000
        except (ValueError, TypeError, KeyError, json.JSONDecodeError, OSError):
            continue
        match = CALLSIGN_PATTERN.match(frame)
        if not match:
            continue
        records.append({
            "callsign": match.group(1).upper(),
            "frame": frame,
            "timestamp_utc": datetime.fromtimestamp(timestamp_epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        })

    callsigns: list[str] = []
    tracks: dict[str, list[dict]] = {}
    for record in records:
        # Internet-only frames describe the ROC beacon, not an RF device heard
        # by the receiver, so they must not create a local track.
        if record["frame"].startswith("[ig]"):
            continue
        position = POSITION_PATTERN.search(record["frame"])
        if not position:
            continue
        lat_deg, lat_min, lat_hemi, lon_deg, lon_min, lon_hemi = position.groups()
        latitude = (int(lat_deg) + float(lat_min) / 60) * (1 if lat_hemi == "N" else -1)
        longitude = (int(lon_deg) + float(lon_min) / 60) * (1 if lon_hemi == "E" else -1)
        points = tracks.setdefault(record["callsign"], [])
        points.append({
            "latitude": latitude,
            "longitude": longitude,
            "timestamp_utc": record["timestamp_utc"],
            "frame": record["frame"],
            "symbol": _symbol_from_frame(record["frame"], position),
        })
    tracks = {callsign: points[-200:] for callsign, points in tracks.items()}
    latest_by_callsign: dict[str, dict] = {}
    for record in reversed(records):
        callsign = record["callsign"]
        if callsign in latest_by_callsign:
            continue
        latest_by_callsign[callsign] = {
            "heard_utc": record["timestamp_utc"],
            "heard_frame": record["frame"],
        }
        if len(callsigns) < limit:
            callsigns.append(callsign)
    latest_by_callsign = {
        callsign: latest_by_callsign[callsign]
        for callsign in callsigns
    }
    return {
        "callsigns": callsigns,
        "frame_count": len(records),
        "latest_by_callsign": latest_by_callsign,
        "tracks": tracks,
    }


def recent_heard_activity(window_hours: int = APRS_MAP_WINDOW_HOURS) -> dict:
    try:
        result = subprocess.run(
            [
                "journalctl",
                f"--unit={APRS_JOURNAL_UNIT}",
                f"--since=-{window_hours}h",
                "--output=json",
                "--no-pager",
            ],
            capture_output=True,
            check=False,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return {"callsigns": [], "frame_count": 0, "latest_by_callsign": {}, "tracks": {}, "source": "systemd-journal-unavailable"}
    if result.returncode != 0:
        return {"callsigns": [], "frame_count": 0, "latest_by_callsign": {}, "tracks": {}, "source": "systemd-journal-unavailable"}
    return {**_heard_activity_from_journal(result.stdout.splitlines()), "source": "systemd-journal"}


def _with_heard_evidence(stations: list[dict], activity: dict) -> list[dict]:
    latest_by_callsign = activity.get("latest_by_callsign") or {}
    return [
        {**station, **latest_by_callsign.get(station.get("callsign"), {})}
        for station in stations
    ]


def load_aprsfi_settings(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = {}
    api_key = payload.get("api_key", "")
    enabled = payload.get("enabled", False)
    return {
        "enabled": enabled if isinstance(enabled, bool) else False,
        "api_key": api_key if isinstance(api_key, str) else "",
    }


def save_aprsfi_settings(path: Path, payload: object) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("settings must be a JSON object")
    current = load_aprsfi_settings(path)
    enabled = payload.get("enabled", current["enabled"])
    if not isinstance(enabled, bool):
        raise ValueError("enabled must be true or false")
    api_key = payload.get("api_key", current["api_key"])
    if not isinstance(api_key, str):
        raise ValueError("api_key must be a string")
    api_key = api_key.strip()
    if api_key and (len(api_key) < 8 or len(api_key) > 256 or any(char.isspace() for char in api_key)):
        raise ValueError("api_key format is invalid")
    with _SETTINGS_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_text(json.dumps({"enabled": enabled, "api_key": api_key}, indent=2) + "\n", encoding="utf-8")
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    return {"enabled": enabled, "configured": bool(api_key)}


def _load_cache(path: Path, callsigns: list[str]) -> dict | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        age = time.time() - float(payload["cached_epoch"])
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None
    if age > APRSFI_CACHE_SECONDS or payload.get("callsigns") != callsigns:
        return None
    payload["cache_age_seconds"] = max(0, round(age))
    payload["cached"] = True
    return payload


def _save_cache(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o640)
    os.replace(temporary, path)


def _station_entry(entry: dict, *, cutoff_epoch: float | None = None) -> dict | None:
    try:
        latitude = float(entry["lat"])
        longitude = float(entry["lng"])
    except (KeyError, TypeError, ValueError):
        return None
    lasttime = entry.get("lasttime") or entry.get("time")
    try:
        last_report_epoch = int(lasttime)
        if cutoff_epoch is not None and last_report_epoch < cutoff_epoch:
            return None
        last_report_utc = datetime.fromtimestamp(last_report_epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError, OSError):
        last_report_utc = None
    callsign = str(entry.get("name") or entry.get("srccall") or "").upper()
    if not callsign:
        return None
    return {
        "callsign": callsign,
        "latitude": latitude,
        "longitude": longitude,
        "last_report_utc": last_report_utc,
        "comment": entry.get("comment"),
        "path": entry.get("path"),
        "symbol": entry.get("symbol"),
        "speed_kmh": entry.get("speed"),
        "course_degrees": entry.get("course"),
        "aprsfi_url": f"https://aprs.fi/{callsign}",
    }


def collect_aprs_map(
    log_path: Path,
    settings_path: Path,
    cache_path: Path,
    *,
    force_refresh: bool = False,
) -> dict:
    now_epoch = time.time()
    cutoff_epoch = now_epoch - (APRS_MAP_WINDOW_HOURS * 60 * 60)
    settings = load_aprsfi_settings(settings_path)
    # Do not touch journalctl (or any external service) when the integration
    # is disabled or has no API key. This endpoint is intentionally fast in
    # its unconfigured state and avoids blocking callers on a slow journal.
    if not settings["enabled"] or not settings["api_key"]:
        return {
            "configured": bool(settings["api_key"]),
            "enabled": settings["enabled"],
            "callsigns_heard": [], "callsign_count": 0, "frame_count": 0,
            "window_hours": APRS_MAP_WINDOW_HOURS,
            "window_start_utc": datetime.fromtimestamp(cutoff_epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "activity_source": "not-queried",
            "stations": [], "tracks": {}, "source": "aprs.fi",
            "source_url": APRSFI_SOURCE_URL, "max_callsigns": APRSFI_MAX_CALLSIGNS,
            "message": "aprs.fi map integration is disabled." if not settings["enabled"] else "Enter an aprs.fi API key to display station positions.",
        }
    activity = recent_heard_activity(APRS_MAP_WINDOW_HOURS)
    callsigns = activity["callsigns"]
    base = {
        "configured": False,
        "callsigns_heard": callsigns,
        "callsign_count": len(callsigns),
        "frame_count": activity["frame_count"],
        "window_hours": APRS_MAP_WINDOW_HOURS,
        "window_start_utc": datetime.fromtimestamp(cutoff_epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "activity_source": activity["source"],
        "stations": [],
        "tracks": activity.get("tracks", {}),
        "source": "aprs.fi",
        "source_url": APRSFI_SOURCE_URL,
        "max_callsigns": APRSFI_MAX_CALLSIGNS,
    }
    api_key = settings["api_key"]
    base["enabled"] = settings["enabled"]
    if not settings["enabled"]:
        return {**base, "configured": bool(api_key), "message": "aprs.fi map integration is disabled."}
    if not api_key:
        return {**base, "message": "Enter an aprs.fi API key to display station positions."}
    base["configured"] = True
    if not callsigns:
        return {**base, "message": "No decoded APRS source callsigns are available yet."}

    if not force_refresh:
        cached = _load_cache(cache_path, callsigns)
        if cached is not None:
            return {**base, **cached, "stations": _with_heard_evidence(cached.get("stations", []), activity)}

    query = urlencode({"name": ",".join(callsigns), "what": "loc", "apikey": api_key, "format": "json"})
    request = Request(
        f"{APRSFI_API_URL}?{query}",
        headers={"User-Agent": f"N0JCG-ROC/{__version__} (+https://n0jcg.com/)"},
    )
    try:
        with urlopen(request, timeout=6) as response:
            payload = json.load(response)
        if payload.get("result") != "ok":
            raise ValueError(payload.get("description") or "aprs.fi request failed")
        stations = [
            station
            for entry in payload.get("entries", [])
            if (station := _station_entry(entry, cutoff_epoch=cutoff_epoch))
        ]
        cache = {
            "callsigns": callsigns,
            "stations": stations,
            "position_count": len(stations),
            "cached_epoch": time.time(),
            "cached_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "cache_age_seconds": 0,
            "cached": False,
        }
        _save_cache(cache_path, cache)
        return {**base, **cache, "stations": _with_heard_evidence(stations, activity)}
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        stale = _load_cache(cache_path, callsigns)
        if stale is not None:
            return {
                **base,
                **stale,
                "stations": _with_heard_evidence(stale.get("stations", []), activity),
                "stale": True,
                "error": str(error),
            }
        return {**base, "error": str(error), "message": "aprs.fi position lookup is currently unavailable."}
