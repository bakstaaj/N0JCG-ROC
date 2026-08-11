#!/usr/bin/env python3
"""Feed a safe sample WS90 observation into a running ROC."""
from __future__ import annotations

import argparse
import json
from urllib.request import Request, urlopen


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8095")
    parser.add_argument("--temperature-c", type=float, default=18.4)
    parser.add_argument("--humidity", type=float, default=42.0)
    args = parser.parse_args()
    payload = {
        "station_id": "WS90-SIM",
        "location": "N0JCG ROC",
        "temperature_c": args.temperature_c,
        "humidity_percent": args.humidity,
        "pressure_hpa": 823.5,
        "wind_speed_mps": 2.1,
        "wind_direction_deg": 245,
        "wind_gust_mps": 4.8,
        "rain_rate_mm_h": 0,
        "rain_today_mm": 0,
        "uv_index": 1.2,
        "solar_w_m2": 112,
        "battery_ok": True,
    }
    request = Request(
        f"{args.base_url.rstrip('/')}/api/weather/ingest",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urlopen(request, timeout=5) as response:
        print(response.read().decode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
