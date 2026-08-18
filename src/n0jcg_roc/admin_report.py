from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from html import escape
import json
import os
from pathlib import Path
import re
import subprocess
import time
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from . import __version__
from .applications import collect_application_status
from .config import load_station_config
from .system_status import collect_system_status
from .weather import read_weather_status
from .winlink import STATUS_CACHE_PATH, collect_winlink_status, summarize_sessions


SENDER_ADDRESS = "ROC@n0jcg.com"
SENDER_NAME = "N0JCG Radio Operations Center"
DEFAULT_SETTINGS_PATH = Path(os.environ.get("ROC_ADMIN_REPORT_SETTINGS", "/var/lib/n0jcg-roc/admin-report.json"))
DEFAULT_STATE_PATH = Path(os.environ.get("ROC_ADMIN_REPORT_STATE", "/var/lib/n0jcg-roc/admin-report-state.json"))
DEFAULT_TRIGGER_PATH = Path(os.environ.get("ROC_ADMIN_REPORT_TRIGGER", "/var/lib/n0jcg-roc/admin-report-send-now.json"))
DEFAULT_CREDENTIALS_READY_PATH = Path("/var/lib/n0jcg-roc/admin-report-credentials-ready")
DEFAULT_APPLICATION_SETTINGS_PATH = Path(
    os.environ.get("ROC_APPLICATION_SETTINGS", "/var/lib/n0jcg-roc/applications.json")
)
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "station.toml"
APRS_JOURNAL_UNIT = os.environ.get("APRS_JOURNAL_UNIT", "n0jcg-aprs-rx.service")
EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
CALLSIGN_PATTERN = re.compile(r"^(?:\[[^\]]+\]\s*)?([A-Z0-9][A-Z0-9-]{1,8})>", re.IGNORECASE)


def utc_now(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_json(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _atomic_json(path: Path, payload: dict, mode: int = 0o640) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.chmod(temporary, mode)
    os.replace(temporary, path)


def _recipient(value: object) -> str:
    address = str(value or "").strip()
    if len(address) > 254 or not EMAIL_PATTERN.fullmatch(address):
        raise ValueError("recipient must be a valid email address")
    return address


def _interval_hours(value: object) -> int:
    if isinstance(value, bool):
        raise ValueError("interval_hours must be from 1 through 168")
    try:
        interval = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError("interval_hours must be from 1 through 168") from error
    if not 1 <= interval <= 168:
        raise ValueError("interval_hours must be from 1 through 168")
    return interval


def load_report_settings(path: Path = DEFAULT_SETTINGS_PATH) -> dict:
    payload = _read_json(path)
    enabled = payload.get("enabled", False)
    recipient = payload.get("recipient", "")
    interval = payload.get("interval_hours", 12)
    try:
        recipient = _recipient(recipient) if recipient else ""
    except ValueError:
        recipient = ""
    try:
        interval = _interval_hours(interval)
    except ValueError:
        interval = 12
    return {
        "enabled": enabled if isinstance(enabled, bool) else False,
        "recipient": recipient,
        "interval_hours": interval,
        "updated_utc": payload.get("updated_utc") if isinstance(payload.get("updated_utc"), str) else None,
    }


def save_report_settings(path: Path, payload: object, *, now: datetime | None = None) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("settings must be a JSON object")
    current = load_report_settings(path)
    enabled = payload.get("enabled", current["enabled"])
    if not isinstance(enabled, bool):
        raise ValueError("enabled must be true or false")
    recipient_value = str(payload.get("recipient", current["recipient"]) or "").strip()
    recipient = _recipient(recipient_value) if recipient_value else ""
    interval = _interval_hours(payload.get("interval_hours", current["interval_hours"]))
    if enabled and not recipient:
        raise ValueError("recipient is required when reports are enabled")
    settings = {
        "enabled": enabled,
        "recipient": recipient,
        "interval_hours": interval,
        "updated_utc": utc_now(now),
    }
    _atomic_json(path, settings)
    return settings


def credentials_configured(environ: dict[str, str] | None = None) -> bool:
    values = environ if environ is not None else os.environ
    return bool(values.get("CLOUDFLARE_ACCOUNT_ID", "").strip() and values.get("CLOUDFLARE_API_TOKEN", "").strip())


def safe_report_status(
    settings_path: Path = DEFAULT_SETTINGS_PATH,
    state_path: Path = DEFAULT_STATE_PATH,
    trigger_path: Path = DEFAULT_TRIGGER_PATH,
    *,
    environ: dict[str, str] | None = None,
) -> dict:
    return {
        **load_report_settings(settings_path),
        "sender": SENDER_ADDRESS,
        "credentials_configured": credentials_configured(environ) or DEFAULT_CREDENTIALS_READY_PATH.is_file(),
        "send_now_queued": trigger_path.is_file(),
        "delivery": _read_json(state_path),
    }


def queue_report_now(
    settings_path: Path = DEFAULT_SETTINGS_PATH,
    trigger_path: Path = DEFAULT_TRIGGER_PATH,
    *,
    now: datetime | None = None,
) -> dict:
    settings = load_report_settings(settings_path)
    if not settings["enabled"]:
        raise ValueError("enable and save operator reports before sending now")
    if not settings["recipient"]:
        raise ValueError("report recipient is not configured")
    request = {"requested_utc": utc_now(now)}
    _atomic_json(trigger_path, request)
    return request


def collect_aprs_statistics(window_hours: int, *, runner: Callable = subprocess.run) -> dict:
    try:
        result = runner(
            [
                "journalctl", f"--unit={APRS_JOURNAL_UNIT}", f"--since=-{window_hours}h",
                "--output=cat", "--no-pager", "--quiet",
            ],
            capture_output=True,
            check=False,
            text=True,
            timeout=8,
        )
        lines = result.stdout.splitlines() if result.returncode == 0 else []
    except (OSError, subprocess.SubprocessError):
        lines = []
    frames = []
    callsigns = set()
    for raw in lines:
        frame = raw.strip()
        match = CALLSIGN_PATTERN.match(frame)
        if not match:
            continue
        frames.append(frame)
        callsigns.add(match.group(1).upper())
    internet = sum(1 for frame in frames if frame.startswith("[ig]"))
    return {
        "window_hours": window_hours,
        "decoded_frames": len(frames) - internet,
        "internet_frames": internet,
        "total_frames": len(frames),
        "unique_callsigns": len(callsigns),
    }


def _cached_winlink_sessions(path: Path = STATUS_CACHE_PATH) -> list[dict]:
    sessions = _read_json(path).get("sessions", [])
    return sessions if isinstance(sessions, list) else []


def collect_report(
    window_hours: int,
    *,
    config_path: Path = DEFAULT_CONFIG_PATH,
    application_settings_path: Path = DEFAULT_APPLICATION_SETTINGS_PATH,
    now: datetime | None = None,
) -> dict:
    generated = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    station = load_station_config(config_path).get("station", {})
    winlink = collect_winlink_status()
    return {
        "generated_utc": utc_now(generated),
        "window_hours": window_hours,
        "window_start_utc": utc_now(generated - timedelta(hours=window_hours)),
        "station": {
            "callsign": station.get("callsign"),
            "site_label": station.get("site_label"),
        },
        "aprs": collect_aprs_statistics(window_hours),
        "winlink": {
            "state": winlink.get("state"),
            "sessions": summarize_sessions(_cached_winlink_sessions(), generated, window_hours=window_hours),
            "queues": winlink.get("queues", {}),
            "reliability": winlink.get("reliability", {}),
        },
        "system": collect_system_status(),
        "weather": read_weather_status(),
        "applications": collect_application_status(application_settings_path),
        "privacy": "Message bodies, subjects, recipients, credentials, and environment variables are excluded.",
    }


def _value(value: object, suffix: str = "") -> str:
    return "Unavailable" if value is None else f"{value}{suffix}"


def render_report(report: dict) -> tuple[str, str, str]:
    station = report["station"]
    aprs = report["aprs"]
    winlink = report["winlink"]
    sessions = winlink["sessions"]
    resources = report["system"]["resources"]
    weather = report["weather"]
    applications = report["applications"].get("applications", [])
    title = f"N0JCG ROC {report['window_hours']}-hour operations report"
    lines = [
        title,
        f"Station: {station.get('callsign') or 'Not configured'} - {station.get('site_label') or 'Not configured'}",
        f"Window: {report['window_start_utc']} through {report['generated_utc']}",
        "",
        "APRS",
        f"  RF frames decoded: {aprs['decoded_frames']}",
        f"  Internet-only frames: {aprs['internet_frames']}",
        f"  Unique callsigns: {aprs['unique_callsigns']}",
        "",
        "Winlink RMS",
        f"  State: {winlink.get('state', 'unknown')}",
        f"  Sessions: {sessions['sessions']} ({sessions['successful_sessions']} successful, {sessions['failed_sessions']} failed)",
        f"  Messages sent / received: {sessions['messages_sent']} / {sessions['messages_received']}",
        f"  Bytes sent / received: {sessions['bytes_sent']} / {sessions['bytes_received']}",
        "",
        "Current ROC snapshot",
        f"  CPU: {_value(resources['cpu'].get('utilization_percent'), '%')}",
        f"  Memory: {_value(resources['memory'].get('used_percent'), '%')}",
        f"  Temperature: {_value(resources['temperature'].get('celsius'), ' C')}",
        f"  Weather gateway: {'available' if weather.get('available') else 'unavailable'}",
    ]
    for app in applications:
        lines.append(f"  {app.get('name', app.get('id', 'Application'))}: {app.get('state', 'unknown')}")
    lines.extend(["", report["privacy"], f"Generated by N0JCG ROC {__version__}"])
    text = "\n".join(lines)

    rows = [
        ("APRS RF frames decoded", aprs["decoded_frames"]),
        ("APRS internet-only frames", aprs["internet_frames"]),
        ("Unique APRS callsigns", aprs["unique_callsigns"]),
        ("Winlink sessions", sessions["sessions"]),
        ("Successful Winlink sessions", sessions["successful_sessions"]),
        ("Failed Winlink sessions", sessions["failed_sessions"]),
        ("Winlink messages sent", sessions["messages_sent"]),
        ("Winlink messages received", sessions["messages_received"]),
        ("Current CPU utilization", _value(resources["cpu"].get("utilization_percent"), "%")),
        ("Current memory utilization", _value(resources["memory"].get("used_percent"), "%")),
        ("Current temperature", _value(resources["temperature"].get("celsius"), " C")),
    ]
    table = "".join(
        f"<tr><th style='text-align:left;padding:7px;border-bottom:1px solid #d5deea'>{escape(str(label))}</th>"
        f"<td style='text-align:right;padding:7px;border-bottom:1px solid #d5deea'>{escape(str(value))}</td></tr>"
        for label, value in rows
    )
    html = (
        "<!doctype html><html><body style='font-family:Arial,sans-serif;color:#082653'>"
        f"<h1>{escape(title)}</h1>"
        f"<p><strong>{escape(str(station.get('callsign') or 'Station'))}</strong> &middot; "
        f"{escape(str(station.get('site_label') or 'Location not configured'))}</p>"
        f"<p>{escape(report['window_start_utc'])} through {escape(report['generated_utc'])}</p>"
        f"<table style='border-collapse:collapse;min-width:420px'>{table}</table>"
        f"<p><strong>Winlink RMS:</strong> {escape(str(winlink.get('state', 'unknown')))}</p>"
        f"<p><strong>Weather gateway:</strong> {'available' if weather.get('available') else 'unavailable'}</p>"
        f"<p style='color:#52657f'>{escape(report['privacy'])}</p>"
        f"<p style='color:#52657f'>Generated by N0JCG ROC {escape(__version__)}</p>"
        "</body></html>"
    )
    return title, text, html


def send_cloudflare_email(
    recipient: str,
    subject: str,
    text_body: str,
    html_body: str,
    *,
    environ: dict[str, str] | None = None,
    opener: Callable = urlopen,
) -> dict:
    values = environ if environ is not None else os.environ
    account_id = values.get("CLOUDFLARE_ACCOUNT_ID", "").strip()
    token = values.get("CLOUDFLARE_API_TOKEN", "").strip()
    if not account_id or not token:
        raise ValueError("Cloudflare Email Sending credentials are not configured")
    payload = {
        "to": _recipient(recipient),
        "from": {"address": SENDER_ADDRESS, "name": SENDER_NAME},
        "subject": subject,
        "text": text_body,
        "html": html_body,
    }
    request = Request(
        f"https://api.cloudflare.com/client/v4/accounts/{account_id}/email/sending/send",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with opener(request, timeout=15) as response:
            result = json.load(response)
    except HTTPError as error:
        raise RuntimeError(f"Cloudflare Email Sending returned HTTP {error.code}") from error
    except (URLError, OSError, json.JSONDecodeError) as error:
        raise RuntimeError("Cloudflare Email Sending request failed") from error
    if not result.get("success"):
        errors = result.get("errors") if isinstance(result.get("errors"), list) else []
        message = errors[0].get("message") if errors and isinstance(errors[0], dict) else "request rejected"
        raise RuntimeError(f"Cloudflare Email Sending rejected the report: {message}")
    delivery = result.get("result") if isinstance(result.get("result"), dict) else {}
    return {
        "delivered": len(delivery.get("delivered", [])),
        "queued": len(delivery.get("queued", [])),
        "permanent_bounces": len(delivery.get("permanent_bounces", [])),
        "message_id": delivery.get("message_id"),
    }


def report_due(settings: dict, state: dict, now: datetime | None = None) -> tuple[bool, str]:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if state.get("status") == "failed" and state.get("next_due_utc"):
        try:
            retry_due = datetime.fromisoformat(str(state["next_due_utc"]).replace("Z", "+00:00")).astimezone(timezone.utc)
            return current >= retry_due, utc_now(retry_due)
        except (ValueError, TypeError):
            pass
    baseline_raw = state.get("last_sent_utc") or settings.get("updated_utc")
    try:
        baseline = datetime.fromisoformat(str(baseline_raw).replace("Z", "+00:00")).astimezone(timezone.utc)
    except (ValueError, TypeError):
        baseline = current
    next_due = baseline + timedelta(hours=settings["interval_hours"])
    return current >= next_due, utc_now(next_due)


def run_once(
    *,
    settings_path: Path = DEFAULT_SETTINGS_PATH,
    state_path: Path = DEFAULT_STATE_PATH,
    trigger_path: Path = DEFAULT_TRIGGER_PATH,
    config_path: Path = DEFAULT_CONFIG_PATH,
    application_settings_path: Path = DEFAULT_APPLICATION_SETTINGS_PATH,
    now: datetime | None = None,
) -> dict:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    settings = load_report_settings(settings_path)
    state = _read_json(state_path)
    send_now = trigger_path.is_file()
    due, next_due = report_due(settings, state, current)
    if not settings["enabled"]:
        return {"status": "disabled"}
    if not settings["recipient"]:
        return {"status": "waiting", "error": "recipient is not configured"}
    if not due and not send_now:
        return {"status": "scheduled", "next_due_utc": next_due}
    attempt = utc_now(current)
    try:
        if not credentials_configured():
            raise ValueError("Cloudflare Email Sending credentials are not configured")
        report = collect_report(
            settings["interval_hours"],
            config_path=config_path,
            application_settings_path=application_settings_path,
            now=current,
        )
        subject, text_body, html_body = render_report(report)
        delivery = send_cloudflare_email(settings["recipient"], subject, text_body, html_body)
        new_state = {
            "status": "sent",
            "last_attempt_utc": attempt,
            "last_sent_utc": attempt,
            "next_due_utc": utc_now(current + timedelta(hours=settings["interval_hours"])),
            "delivery": delivery,
        }
    except (OSError, ValueError, RuntimeError) as error:
        new_state = {
            "status": "failed",
            "last_attempt_utc": attempt,
            "last_sent_utc": state.get("last_sent_utc"),
            "next_due_utc": utc_now(current + timedelta(minutes=15)),
            "error": str(error),
        }
    if send_now:
        trigger_path.unlink(missing_ok=True)
    _atomic_json(state_path, new_state)
    return new_state


def main() -> None:
    parser = argparse.ArgumentParser(description="N0JCG ROC periodic operator report service")
    parser.add_argument("--once", action="store_true", help="check the schedule once and exit")
    parser.add_argument("--poll-seconds", type=int, default=10)
    args = parser.parse_args()
    if args.once:
        print(json.dumps(run_once(), indent=2))
        return
    while True:
        result = run_once()
        print(json.dumps({"checked_utc": utc_now(), **result}), flush=True)
        time.sleep(max(5, args.poll_seconds))


if __name__ == "__main__":
    main()
