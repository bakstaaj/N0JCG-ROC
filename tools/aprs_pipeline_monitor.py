#!/usr/bin/env python3
"""Fail-visible APRS pipeline watchdog (receive-only; never transmits)."""
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime" / "aprs"
STATE = RUNTIME / "pipeline-health.json"
STALE = int(os.environ.get("APRS_PIPELINE_STALE_SECONDS", "180"))
RF_QUIET = int(os.environ.get("APRS_RF_QUIET_SECONDS", "21600"))


def active() -> bool:
    for proc in Path("/proc").glob("[0-9]*"):
        try:
            cmd = (proc / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="ignore")
        except OSError:
            continue
        if "rtl_fm" in cmd and os.environ.get("APRS_RTL_SERIAL", "00014439") in cmd:
            return True
    return False


def check() -> dict:
    now = time.time()
    audio = RUNTIME / "audio-ring.wav"
    age = None
    if audio.exists():
        try:
            age = max(0, int(now - audio.stat().st_mtime))
        except OSError:
            pass
    last_rf = None
    try:
        result = subprocess.run(["journalctl", "--unit=n0jcg-aprs-rx.service", "--output=json", "--no-pager", "--lines=500"], capture_output=True, text=True, check=False, timeout=8)
        for line in result.stdout.splitlines():
            item = json.loads(line)
            message = str(item.get("MESSAGE") or "")
            if message.startswith("[ig]") or ">" not in message:
                continue
            stamp = int(item.get("__REALTIME_TIMESTAMP", 0)) / 1_000_000
            if stamp and (last_rf is None or stamp > last_rf):
                last_rf = stamp
    except (OSError, subprocess.SubprocessError, ValueError, json.JSONDecodeError):
        pass
    rf_age = None if last_rf is None else max(0, int(now - last_rf))
    if not active():
        state, summary = "fault", "RTL receiver process is not running"
    elif age is not None and age > STALE:
        state, summary = "fault", f"audio pipeline has not advanced for {age} seconds"
    elif rf_age is None or rf_age > RF_QUIET:
        state, summary = "degraded", "receiver and audio pipeline are active, but no recent RF decode was recorded"
    else:
        state, summary = "healthy", "receiver process and audio pipeline are active"
    return {
        "state": state,
        "summary": summary,
        "checked_at_utc": datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "pipeline_age_seconds": age,
        "rf_age_seconds": rf_age,
    }


def main() -> None:
    RUNTIME.mkdir(parents=True, exist_ok=True)
    previous = None
    while True:
        result = check()
        STATE.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        if result["state"] != previous:
            try:
                subprocess.run(["logger", "-t", "n0jcg-aprs-monitor", f"{result['state']}: {result['summary']}"], check=False)
            except OSError:
                pass
            previous = result["state"]
        time.sleep(60)


if __name__ == "__main__":
    main()
