from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess

from .admin_report import send_cloudflare_email

SENDER_ADDRESS = "roc@n0jcg.com"
DEFAULT_PATH = Path(os.environ.get("ROC_APRS_ALERT_SETTINGS", "/var/lib/n0jcg-roc/aprs-alert.json"))
EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def load_alert_settings(path: Path = DEFAULT_PATH) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = {}
    recipient = str(payload.get("recipient") or "").strip()
    if not EMAIL_PATTERN.fullmatch(recipient):
        recipient = ""
    return {"enabled": payload.get("enabled") is True, "recipient": recipient,
            "sender": SENDER_ADDRESS, "updated_utc": payload.get("updated_utc")}


def save_alert_settings(path: Path, payload: object) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("settings must be an object")
    current = load_alert_settings(path)
    enabled = payload.get("enabled", current["enabled"])
    recipient = str(payload.get("recipient", current["recipient"]) or "").strip()
    if not isinstance(enabled, bool):
        raise ValueError("enabled must be true or false")
    if enabled and not EMAIL_PATTERN.fullmatch(recipient):
        raise ValueError("a valid recipient is required when alerts are enabled")
    result = {"enabled": enabled, "recipient": recipient, "sender": SENDER_ADDRESS,
              "updated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o640)
    os.replace(temporary, path)
    return result


def send_alert_email(recipient: str, subject: str, body: str) -> dict:
    if not EMAIL_PATTERN.fullmatch(recipient):
        return {"ok": False, "error": "recipient is not configured"}
    try:
        delivery = send_cloudflare_email(recipient, subject, body, f"<p>{body.replace(chr(10), '<br>')}</p>")
        return {"ok": True, **delivery}
    except (OSError, RuntimeError, ValueError) as error:
        return {"ok": False, "error": str(error)}
