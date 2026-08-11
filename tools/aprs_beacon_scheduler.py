#!/usr/bin/env python3
"""Guarded Pluto APRS position beacon scheduler."""

from __future__ import annotations

import json
import os
import time
from urllib.request import Request, urlopen


def main() -> int:
    if os.environ.get("APRS_BEACON_ENABLED") != "1":
        print("APRS beacon scheduler disabled", flush=True)
        return 0
    if os.environ.get("APRS_BEACON_CONFIRM") != "I_UNDERSTAND_RF_TX":
        raise SystemExit("APRS_BEACON_CONFIRM is required")
    interval = max(600, int(os.environ.get("APRS_BEACON_INTERVAL_SECONDS", "600")))
    base_url = os.environ.get("PLUTO_API_URL", "http://192.168.68.104").rstrip("/")
    payload = {
        "profile": "TX_AUDIO_FM",
        "frequency_hz": int(os.environ.get("APRS_BEACON_FREQUENCY_HZ", "144390000")),
        "duration_seconds": int(os.environ.get("APRS_BEACON_DURATION_SECONDS", "5")),
        "tx_audio_source": "file",
        "tx_audio_path": os.environ.get("APRS_BEACON_PCM_PATH", "/mnt/jffs2/aprs-position.pcm"),
        "tx_audio_rate_hz": 48000,
        "tx_fm_deviation_hz": 20000,
        "tx_amplitude": 0.25,
        "tx_gain_db": 0,
        "confirm_live_tx": True,
    }
    body = json.dumps(payload).encode("utf-8")
    while True:
        request = Request(f"{base_url}/radio/tx/start", data=body, method="POST", headers={"Content-Type": "application/json"})
        with urlopen(request, timeout=20) as response:
            result = json.loads(response.read().decode("utf-8"))
        print(json.dumps({"ok": result.get("ok"), "state": result.get("tx", {}).get("state"), "frequency_hz": payload["frequency_hz"]}), flush=True)
        time.sleep(interval)


if __name__ == "__main__":
    main()
