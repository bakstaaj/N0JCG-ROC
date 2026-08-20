#!/usr/bin/env python3
"""Record protocol-safe Winlink phase health and bounded recovery evidence.

This observer never generates or edits Winlink frames.  It only samples the
RMS/modem journals, writes a privacy-safe state file, and optionally requests
an RMS-only restart after a stale session when WINLINK_AUTO_RECOVER=1.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import time

from n0jcg_roc.winlink import summarize_rf_diagnostics

STATE = Path(os.environ.get("WINLINK_PROTOCOL_STATE", "/var/lib/n0jcg-roc/winlink-protocol-health.json"))
INTERVAL = max(5, int(os.environ.get("WINLINK_WATCHDOG_INTERVAL", "15")))
STALE_SECONDS = max(60, int(os.environ.get("WINLINK_STALE_SECONDS", "240")))


def journal(service: str) -> list[str]:
    try:
        result = subprocess.run(
            ["journalctl", "-u", service, "-n", "1200", "--no-pager", "--quiet", "-o", "short-iso"],
            check=False, capture_output=True, text=True, timeout=8,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    return result.stdout.splitlines() if result.returncode == 0 else []


def write_state(payload: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATE.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary.replace(STATE)


def main() -> None:
    last_recovery = 0.0
    while True:
        now = datetime.now(timezone.utc)
        diagnostics = summarize_rf_diagnostics(journal("n0jcg-winlink-rms.service"), journal("n0jcg-winlink-modem.service"), now)
        last_event = diagnostics.get("last_event_utc")
        age = None
        if last_event:
            try:
                age = max(0, int((now - datetime.fromisoformat(last_event.replace("Z", "+00:00"))).total_seconds()))
            except ValueError:
                pass
        stale = bool(age is not None and age >= STALE_SECONDS and diagnostics.get("phase") not in {"idle", "disconnected"})
        recovered = False
        if stale and os.environ.get("WINLINK_AUTO_RECOVER", "0") == "1" and time.time() - last_recovery >= STALE_SECONDS:
            try:
                result = subprocess.run(["systemctl", "restart", "n0jcg-winlink-rms.service"], check=False, timeout=30)
                recovered = result.returncode == 0
                if recovered:
                    last_recovery = time.time()
            except (OSError, subprocess.TimeoutExpired):
                recovered = False
        write_state({
            "updated_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "phase": diagnostics.get("phase"),
            "finding": diagnostics.get("finding"),
            "next_action": diagnostics.get("next_action"),
            "last_event_utc": last_event,
            "last_event_age_seconds": age,
            "stale": stale,
            "auto_recover_enabled": os.environ.get("WINLINK_AUTO_RECOVER", "0") == "1",
            "recovered": recovered,
            "evidence_events": diagnostics.get("evidence_events", 0),
            "privacy": diagnostics.get("privacy"),
        })
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
