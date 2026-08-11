from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
# Latest observations are transactional runtime data; keep them outside the
# protected application tree so the hardened systemd service can write them.
WEATHER_RUNTIME_DIR = Path(os.environ.get("N0JCG_WEATHER_RUNTIME_DIR", "/tmp/n0jcg-roc/weather"))
LATEST_PATH = WEATHER_RUNTIME_DIR / "latest.json"
STALE_AFTER_SECONDS = int(os.environ.get("N0JCG_WEATHER_STALE_SECONDS", "180"))

NUMBER_PATTERN = re.compile(r"[-+]?\d+(?:\.\d+)?")


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = NUMBER_PATTERN.search(str(value))
    return float(match.group(0)) if match else None


def _temperature_c(value: Any, unit: str = "C") -> float | None:
    number = _number(value)
    if number is None:
        return None
    return (number - 32.0) * 5.0 / 9.0 if unit.upper().startswith("F") else number


def _pressure_hpa(value: Any) -> float | None:
    number = _number(value)
    if number is None:
        return None
    return number * 33.8638866667 if "inhg" in str(value).lower() else number


def _speed_mps(value: Any) -> float | None:
    number = _number(value)
    if number is None:
        return None
    unit = str(value).lower()
    if "mph" in unit:
        return number * 0.44704
    if "km/h" in unit or "kph" in unit:
        return number / 3.6
    if "knot" in unit or "kt" in unit:
        return number * 0.514444
    return number


def _rain_mm(value: Any) -> float | None:
    number = _number(value)
    if number is None:
        return None
    return number * 25.4 if "in" in str(value).lower() else number


def _item_map(items: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(items, list):
        return {}
    return {str(item.get("id", "")).lower(): item for item in items if isinstance(item, dict)}


def normalize_gateway_live_data(
    payload: dict[str, Any], *, gateway_url: str, sensor_inventory: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """Convert the GW1100 HTTP get_livedata_info response to ROC fields."""
    common = _item_map(payload.get("common_list"))
    rain = _item_map(payload.get("piezoRain") or payload.get("rain"))
    indoor = payload.get("wh25") or []
    indoor = indoor[0] if isinstance(indoor, list) and indoor and isinstance(indoor[0], dict) else {}

    def common_value(item_id: str) -> Any:
        item = common.get(item_id)
        return item.get("val") if item else None

    def rain_value(item_id: str) -> Any:
        item = rain.get(item_id)
        return item.get("val") if item else None

    outdoor_temp = common.get("0x02")
    outdoor_temp_value = outdoor_temp.get("val") if outdoor_temp else None
    outdoor_temp_unit = outdoor_temp.get("unit", "C") if outdoor_temp else "C"
    outdoor_available = any(common_value(item_id) is not None for item_id in ("0x02", "0x07", "0x0a", "0x0b"))

    return {
        "source": "gw1100-http",
        "station_id": "GW1100-WS90",
        "location": "N0JCG ROC",
        "gateway_url": gateway_url,
        "outdoor_sensor_detected": outdoor_available,
        "sensor_inventory": sensor_inventory or [],
        "temperature_c": _temperature_c(outdoor_temp_value, str(outdoor_temp_unit)),
        "humidity_percent": _number(common_value("0x07")),
        "pressure_hpa": _pressure_hpa(indoor.get("rel")),
        "pressure_absolute_hpa": _pressure_hpa(indoor.get("abs")),
        "wind_speed_mps": _speed_mps(common_value("0x0b")),
        "wind_direction_deg": _number(common_value("0x0a")),
        "wind_gust_mps": _speed_mps(common_value("0x0c")),
        "rain_rate_mm_h": _rain_mm(rain_value("0x0e")),
        "rain_today_mm": _rain_mm(rain_value("0x10")),
        "uv_index": _number(common_value("0x17")),
        "solar_w_m2": _number(common_value("0x15")),
        "indoor_temperature_c": _temperature_c(indoor.get("intemp"), str(indoor.get("unit", "C"))),
        "indoor_humidity_percent": _number(indoor.get("inhumi")),
    }


def normalize_observation(payload: dict[str, Any], *, source: str = "gw1100") -> dict[str, Any]:
    """Normalize GW1100/WS90 values into the ROC weather contract."""
    fields = {
        "temperature_c": payload.get("temperature_c", payload.get("tempinf")),
        "humidity_percent": payload.get("humidity_percent", payload.get("humidity")),
        "pressure_hpa": payload.get("pressure_hpa", payload.get("baromrelin")),
        "pressure_absolute_hpa": payload.get("pressure_absolute_hpa", payload.get("baromabsin")),
        "wind_speed_mps": payload.get("wind_speed_mps", payload.get("windspeed")),
        "wind_direction_deg": payload.get("wind_direction_deg", payload.get("winddir")),
        "wind_gust_mps": payload.get("wind_gust_mps", payload.get("windgust")),
        "rain_rate_mm_h": payload.get("rain_rate_mm_h", payload.get("rainrate")),
        "rain_today_mm": payload.get("rain_today_mm", payload.get("dailyrain")),
        "uv_index": payload.get("uv_index", payload.get("uv")),
        "solar_w_m2": payload.get("solar_w_m2", payload.get("solarradiation")),
        "battery_ok": payload.get("battery_ok"),
        "indoor_temperature_c": payload.get("indoor_temperature_c"),
        "indoor_humidity_percent": payload.get("indoor_humidity_percent"),
    }
    return {
        "source": payload.get("source", source),
        "received_utc": payload.get("received_utc") or _utc_now(),
        "station_id": payload.get("station_id", "WS90"),
        "location": payload.get("location", "N0JCG ROC"),
        "gateway_url": payload.get("gateway_url"),
        "outdoor_sensor_detected": bool(payload.get("outdoor_sensor_detected")),
        "sensor_inventory": payload.get("sensor_inventory", []),
        "units": {"temperature": "C", "pressure": "hPa", "wind": "m/s", "rain": "mm"},
        "fields": fields,
    }


def read_weather_status() -> dict[str, Any]:
    try:
        observation = json.loads(LATEST_PATH.read_text(encoding="utf-8"))
        received = datetime.strptime(observation["received_utc"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        age_seconds = max(0, int((datetime.now(timezone.utc) - received).total_seconds()))
        return {
            "configured": True,
            "available": True,
            "stale": age_seconds > STALE_AFTER_SECONDS,
            "age_seconds": age_seconds,
            "observation": observation,
        }
    except (OSError, ValueError, TypeError, KeyError):
        return {
            "configured": True,
            "available": False,
            "observation": None,
            "source": "gw1100",
            "message": "Waiting for GW1100/WS90 data",
        }


def store_observation(payload: dict[str, Any], *, source: str = "gw1100") -> dict[str, Any]:
    observation = normalize_observation(payload, source=source)
    WEATHER_RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    temporary = LATEST_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(observation, indent=2) + "\n", encoding="utf-8")
    temporary.replace(LATEST_PATH)
    return observation
