from __future__ import annotations

import json
import os
from pathlib import Path
from threading import Lock


_SETTINGS_LOCK = Lock()
_MAX_OVERVIEW_TITLE_LENGTH = 120


def default_overview_title(station: dict) -> str:
    callsign = str(station.get("callsign", "")).strip().upper()
    site_label = str(station.get("site_label", "")).strip()
    return " · ".join(part for part in (callsign, site_label) if part)


def _valid_overview_title(value: object) -> str:
    title = str(value).strip()
    if not title:
        raise ValueError("station overview title is required")
    if len(title) > _MAX_OVERVIEW_TITLE_LENGTH:
        raise ValueError(f"station overview title must be {_MAX_OVERVIEW_TITLE_LENGTH} characters or fewer")
    if any(ord(character) < 32 or ord(character) == 127 for character in title):
        raise ValueError("station overview title cannot contain control characters")
    return title


def load_station_settings(path: Path, station: dict) -> dict:
    title = default_overview_title(station)
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(stored, dict) and "overview_title" in stored:
            title = _valid_overview_title(stored["overview_title"])
    except (OSError, json.JSONDecodeError, ValueError):
        pass
    return {"overview_title": title}


def save_station_settings(path: Path, station: dict, payload: object) -> dict:
    if not isinstance(payload, dict) or "overview_title" not in payload:
        raise ValueError("overview_title is required")
    settings = {"overview_title": _valid_overview_title(payload["overview_title"])}
    with _SETTINGS_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
        os.chmod(temporary, 0o640)
        os.replace(temporary, path)
    return settings
