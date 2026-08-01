from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import tomllib


DEFAULT_CONFIG = {
    "station": {
        "name": "N0JCG Radio Operations Center",
        "callsign": "N0JCG",
        "linux_user": "n0jcg",
        "site_label": "Cripple Creek, Colorado",
        "grid_square": "DM78JT",
    },
    "server": {
        "hostname": "n0jcg-roc",
        "lan_address": "192.168.68.145",
        "listen_address": "0.0.0.0",
        "listen_port": 8095,
    },
    "safety": {
        "transmit_enabled": False,
        "gateway_frequency_hz": 0,
        "coordination_confirmed": False,
    },
    "identities": {
        "winlink_rms": "N0JCG-10",
        "aprs_igate": "N0JCG-5",
    },
}


def load_station_config(path: Path | None = None) -> dict:
    """Load local station settings while retaining safe defaults."""
    config = deepcopy(DEFAULT_CONFIG)
    if path is None or not path.exists():
        return config

    with path.open("rb") as config_file:
        supplied = tomllib.load(config_file)

    for section in config:
        values = supplied.get(section, {})
        if isinstance(values, dict):
            config[section].update(values)
    return config


def transmit_interlock(config: dict) -> dict:
    safety = config["safety"]
    reasons: list[str] = []
    if not safety.get("transmit_enabled", False):
        reasons.append("operator transmit enable is off")
    if not safety.get("coordination_confirmed", False):
        reasons.append("local frequency coordination is not confirmed")
    if int(safety.get("gateway_frequency_hz", 0)) <= 0:
        reasons.append("gateway frequency is not configured")
    return {"ready": not reasons, "reasons": reasons}
