#!/usr/bin/env python3
"""Poll an Ecowitt GW1100 over its documented local HTTP API."""
from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from n0jcg_roc.weather import normalize_gateway_live_data  # noqa: E402


def get_json(url: str, timeout: float) -> object:
    with urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def post_json(url: str, payload: dict[str, object], timeout: float) -> None:
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urlopen(request, timeout=timeout) as response:
        result = json.loads(response.read().decode("utf-8"))
        if not result.get("ok"):
            raise RuntimeError(f"ROC ingest rejected observation: {result}")


def collect_once(gateway_url: str, ingest_url: str, timeout: float) -> dict[str, object]:
    base = gateway_url.rstrip("/")
    live = get_json(f"{base}/get_livedata_info?", timeout)
    if not isinstance(live, dict):
        raise ValueError("GW1100 live-data response is not a JSON object")
    try:
        # Page 1 contains the integrated outdoor arrays, including the WS90.
        sensors = get_json(f"{base}/get_sensors_info?page=1", timeout)
    except (OSError, ValueError, HTTPError, URLError):
        sensors = []
    inventory = sensors if isinstance(sensors, list) else []
    observation = normalize_gateway_live_data(live, gateway_url=base, sensor_inventory=inventory)
    post_json(ingest_url, observation, timeout)
    return observation


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gateway-url", default=os.environ.get("GW1100_URL", "http://192.168.68.131"))
    parser.add_argument(
        "--ingest-url",
        default=os.environ.get("ROC_WEATHER_INGEST_URL", "http://127.0.0.1:8095/api/weather/ingest"),
    )
    parser.add_argument("--interval", type=int, default=int(os.environ.get("WEATHER_POLL_SECONDS", "30")))
    parser.add_argument("--timeout", type=float, default=float(os.environ.get("WEATHER_HTTP_TIMEOUT", "8")))
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    if args.interval < 10:
        parser.error("--interval must be at least 10 seconds")

    stopping = False

    def stop(_signum: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    while not stopping:
        try:
            observation = collect_once(args.gateway_url, args.ingest_url, args.timeout)
            fields = observation["outdoor_sensor_detected"]
            print(f"weather observation stored; outdoor_sensor_detected={str(fields).lower()}", flush=True)
        except (OSError, ValueError, RuntimeError, HTTPError, URLError) as error:
            print(f"weather collection failed: {error}", file=sys.stderr, flush=True)
        if args.once:
            return 0
        for _ in range(args.interval):
            if stopping:
                break
            time.sleep(1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
