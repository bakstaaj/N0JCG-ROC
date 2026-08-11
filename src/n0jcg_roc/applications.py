from __future__ import annotations

from copy import deepcopy
import ipaddress
import json
import os
from pathlib import Path
import re
from threading import Lock
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


DEFAULT_APPLICATIONS = {
    "air_traffic": {
        "name": "N0JCG Air Traffic Center",
        "enabled": True,
        "host": "192.168.68.137",
        "port": 8090,
    },
    "scanner": {
        "name": "N0JCG Scanner",
        "enabled": True,
        "host": "192.168.68.137",
        "port": 8070,
    },
}

_SETTINGS_LOCK = Lock()
_HOSTNAME_PATTERN = re.compile(r"^(?=.{1,253}$)[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?$")


def _valid_host(value: object) -> str:
    host = str(value).strip()
    if not host or "/" in host or "://" in host or any(char.isspace() for char in host):
        raise ValueError("host must be an IP address or hostname without a URL path")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        if not _HOSTNAME_PATTERN.fullmatch(host):
            raise ValueError("host must be a valid IP address or hostname")
    return host


def _valid_port(value: object) -> int:
    if isinstance(value, bool):
        raise ValueError("port must be a number from 1 through 65535")
    try:
        port = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError("port must be a number from 1 through 65535") from error
    if not 1 <= port <= 65535:
        raise ValueError("port must be a number from 1 through 65535")
    return port


def application_url(application: dict) -> str:
    host = application["host"]
    try:
        if ipaddress.ip_address(host).version == 6:
            host = f"[{host}]"
    except ValueError:
        pass
    return f"http://{host}:{application['port']}"


def load_application_settings(path: Path) -> dict:
    applications = deepcopy(DEFAULT_APPLICATIONS)
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        stored = {}
    for application_id, values in stored.get("applications", {}).items():
        if application_id not in applications or not isinstance(values, dict):
            continue
        try:
            if "enabled" in values and isinstance(values["enabled"], bool):
                applications[application_id]["enabled"] = values["enabled"]
            if "host" in values:
                applications[application_id]["host"] = _valid_host(values["host"])
            if "port" in values:
                applications[application_id]["port"] = _valid_port(values["port"])
        except ValueError:
            continue
    return {"applications": applications}


def save_application_settings(path: Path, payload: object) -> dict:
    if not isinstance(payload, dict) or not isinstance(payload.get("applications"), dict):
        raise ValueError("applications must be a JSON object")
    updates = payload["applications"]
    unknown = set(updates) - set(DEFAULT_APPLICATIONS)
    if unknown:
        raise ValueError(f"unknown application: {sorted(unknown)[0]}")

    with _SETTINGS_LOCK:
        settings = load_application_settings(path)
        for application_id, values in updates.items():
            if not isinstance(values, dict):
                raise ValueError(f"{application_id} settings must be a JSON object")
            application = settings["applications"][application_id]
            if "enabled" in values:
                if not isinstance(values["enabled"], bool):
                    raise ValueError(f"{application_id} enabled must be true or false")
                application["enabled"] = values["enabled"]
            if "host" in values:
                application["host"] = _valid_host(values["host"])
            if "port" in values:
                application["port"] = _valid_port(values["port"])

        serializable = {
            "applications": {
                application_id: {
                    "enabled": values["enabled"],
                    "host": values["host"],
                    "port": values["port"],
                }
                for application_id, values in settings["applications"].items()
            }
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_text(json.dumps(serializable, indent=2) + "\n", encoding="utf-8")
        os.chmod(temporary, 0o640)
        os.replace(temporary, path)
        return settings


def _read_json(url: str) -> dict:
    with urlopen(url, timeout=2) as response:
        payload = json.load(response)
    if not isinstance(payload, dict):
        raise ValueError("remote response was not a JSON object")
    return payload


def _air_traffic_metrics(payload: dict) -> dict:
    aircraft = payload.get("aircraft") if isinstance(payload.get("aircraft"), dict) else {}
    return {
        "aircraft_count": payload.get("aircraft_count", aircraft.get("count")),
        "aircraft_with_position": payload.get("aircraft_with_position", aircraft.get("with_position")),
    }


def _scanner_metrics(payload: dict, base_url: str) -> dict:
    activity = payload.get("activity_summary") if isinstance(payload.get("activity_summary"), dict) else {}
    metrics = {
        "voice_calls": activity.get("distinct_voice_calls", activity.get("voice_call_events", 0)),
        "vhf_locks": 0,
        "uhf_locks": 0,
    }
    try:
        analog = _read_json(f"{base_url}/api/analog/status")
        roles = analog.get("roles") if isinstance(analog.get("roles"), dict) else {}
        vhf = roles.get("analog_2m") if isinstance(roles.get("analog_2m"), dict) else {}
        uhf = roles.get("analog_70cm") if isinstance(roles.get("analog_70cm"), dict) else {}
        metrics["vhf_locks"] = vhf.get("lock_count", 0)
        metrics["uhf_locks"] = uhf.get("lock_count", 0)
        metrics["vhf_state"] = vhf.get("state")
        metrics["uhf_state"] = uhf.get("state")
    except (HTTPError, OSError, URLError, ValueError, json.JSONDecodeError):
        metrics["analog_status_unavailable"] = True
    return metrics


def collect_application_status(path: Path) -> dict:
    settings = load_application_settings(path)
    result = []
    for application_id, values in settings["applications"].items():
        entry = {"id": application_id, **values, "url": application_url(values)}
        if not values["enabled"]:
            entry.update({"state": "disabled", "reachable": False, "metrics": {}})
            result.append(entry)
            continue
        try:
            payload = _read_json(f"{entry['url']}/api/status")
            metrics = _air_traffic_metrics(payload) if application_id == "air_traffic" else _scanner_metrics(payload, entry["url"])
            entry.update({"state": "online", "reachable": True, "metrics": metrics})
        except (HTTPError, OSError, URLError, ValueError, json.JSONDecodeError) as error:
            entry.update({"state": "offline", "reachable": False, "metrics": {}, "error": str(error)})
        result.append(entry)
    return {"applications": result}
