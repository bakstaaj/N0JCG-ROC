#!/usr/bin/env python3
"""Fail-visible APRS pipeline watchdog (receive-only; never transmits)."""
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from n0jcg_roc.aprs_alerts import load_alert_settings, send_alert_email

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime" / "aprs"
STATE = RUNTIME / "pipeline-health.json"
STALE = int(os.environ.get("APRS_PIPELINE_STALE_SECONDS", "180"))
RF_QUIET = int(os.environ.get("APRS_RF_QUIET_SECONDS", "21600"))
AUTO_RECOVER = os.environ.get("APRS_AUTO_RECOVER", "1") == "1"
RECOVERY_COOLDOWN = int(os.environ.get("APRS_AUTO_RECOVER_COOLDOWN_SECONDS", "300"))
RECOVERY_CONFIRMATIONS = max(1, int(os.environ.get("APRS_AUTO_RECOVER_CONFIRMATIONS", "2")))


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
    rtl_errors = []
    try:
        rtl_text = (RUNTIME / "rtl.log").read_text(encoding="utf-8", errors="replace")
        for marker in ("usb_claim_interface error", "Failed to open rtlsdr device", "No supported devices found"):
            if any(marker in line for line in rtl_text.splitlines()[-20:]):
                rtl_errors.append(marker)
    except OSError:
        pass
    igate_failures = 0
    try:
        journal_text = result.stdout if 'result' in locals() else ""
        igate_failures = len([line for line in journal_text.splitlines() if "Connect to IGate server" in line and "failed" in line.lower()])
    except Exception:
        pass
    if not active():
        state, summary = "fault", "RTL receiver process is not running (possible USB disconnect or Dire Wolf exit)"
    elif age is None:
        state, summary = "fault", "audio pipeline has not produced an audio ring"
    elif age > STALE:
        state, summary = "fault", f"audio pipeline has not advanced for {age} seconds"
    elif rtl_errors:
        state, summary = "fault", f"RTL device error: {rtl_errors[-1]}"
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
        "rtl_errors": rtl_errors,
        "aprs_is_connection_failures": igate_failures,
    }


def send_alert(result: dict) -> None:
    settings = load_alert_settings()
    if not settings["enabled"] or not settings["recipient"]:
        return
    delivery = send_alert_email(settings["recipient"], f"N0JCG APRS pipeline {result['state']}",
                                f"{result['summary']}\nChecked: {result['checked_at_utc']}\n")
    if not delivery["ok"]:
        subprocess.run(["logger", "-t", "n0jcg-aprs-monitor", "email alert failed"], check=False)


def recover_if_needed(result: dict, fault_count: int, last_recovery: float | None) -> tuple[int, float | None]:
    """Restart only after repeated stale/fault checks and a cooldown.

    A single delayed file update must not interrupt a live receiver. Recovery
    is limited to the receive listener and never touches transmit services.
    """
    if result["state"] != "fault":
        return 0, last_recovery
    fault_count += 1
    now = time.time()
    if not AUTO_RECOVER or fault_count < RECOVERY_CONFIRMATIONS:
        return fault_count, last_recovery
    if last_recovery is not None and now - last_recovery < RECOVERY_COOLDOWN:
        return fault_count, last_recovery
    completed = subprocess.run(["systemctl", "restart", "n0jcg-aprs-rx.service"], capture_output=True, text=True, check=False, timeout=30)
    if completed.returncode == 0:
        result["auto_recovery"] = "listener restart requested"
        subprocess.run(["logger", "-t", "n0jcg-aprs-monitor", "fault recovery: restarted n0jcg-aprs-rx.service"], check=False)
    else:
        result["auto_recovery"] = "listener restart failed"
        subprocess.run(["logger", "-t", "n0jcg-aprs-monitor", "fault recovery failed"], check=False)
    return 0, now


def main() -> None:
    RUNTIME.mkdir(parents=True, exist_ok=True)
    previous = None
    fault_count = 0
    last_recovery = None
    while True:
        result = check()
        fault_count, last_recovery = recover_if_needed(result, fault_count, last_recovery)
        STATE.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        if result["state"] != previous:
            try:
                subprocess.run(["logger", "-t", "n0jcg-aprs-monitor", f"{result['state']}: {result['summary']}"], check=False)
            except OSError:
                pass
            send_alert(result)
            previous = result["state"]
        time.sleep(60)


if __name__ == "__main__":
    main()
