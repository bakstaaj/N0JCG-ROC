from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import socket
import subprocess
import time
from typing import Callable
from urllib.parse import parse_qs


RUNTIME_CONFIG_PATH = Path("/var/lib/n0jcg-winlink/bpq32.cfg")
MAIL_STORE_PATH = Path("/var/lib/n0jcg-winlink/Mail")
MESSAGE_INDEX_PATH = Path("/var/lib/n0jcg-winlink/DIRMES.SYS")
STATUS_CACHE_PATH = Path("/var/lib/n0jcg-roc/winlink-status.json")
PTT_DEVICE_PATH = Path(
    "/dev/serial/by-id/usb-Silicon_Labs_CP2102N_USB_to_UART_Bridge_Controller_30217bb31dc6ef11ba3469527a5e3baa-if00-port0"
)
JOURNAL_PATTERN = re.compile(r"^(?P<timestamp>\S+)\s+\S+\s+\S+:\s+(?P<message>.*)$")
BPQ_MESSAGE_RECORD_SIZE = 308
BPQ_MESSAGE_STATUS_OFFSET = 1
BPQ_MESSAGE_FLAGS_OFFSET = 154
BPQ_MESSAGE_SOURCE_FLAGS = 4 | 8 | 16 | 32 | 64


def summarize_mail_index(path: Path = MESSAGE_INDEX_PATH) -> dict:
    """Return privacy-safe BPQMail counts from its fixed-record message index."""
    empty = {
        "available": False,
        "pending": 0,
        "delivered": 0,
        "received": 0,
        "archived": 0,
        "retained_total": 0,
    }
    try:
        data = path.read_bytes()
    except OSError:
        return empty
    if len(data) < BPQ_MESSAGE_RECORD_SIZE or len(data) % BPQ_MESSAGE_RECORD_SIZE:
        return empty

    result = {**empty, "available": True}
    for offset in range(BPQ_MESSAGE_RECORD_SIZE, len(data), BPQ_MESSAGE_RECORD_SIZE):
        record = data[offset:offset + BPQ_MESSAGE_RECORD_SIZE]
        status = chr(record[BPQ_MESSAGE_STATUS_OFFSET])
        if status not in {"N", "Y", "F", "K", "H", "D", "$"}:
            continue
        result["retained_total"] += 1
        if status in {"N", "$", "H"}:
            result["pending"] += 1
        if status in {"F", "D"}:
            result["delivered"] += 1
        if record[BPQ_MESSAGE_FLAGS_OFFSET] & BPQ_MESSAGE_SOURCE_FLAGS:
            result["received"] += 1
        if status == "K":
            result["archived"] += 1
    return result


def _utc_iso(value: str) -> str | None:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_runtime_config(path: Path = RUNTIME_CONFIG_PATH) -> dict:
    """Read only non-secret identity and RF fields from the LinBPQ config."""
    result = {
        "node_call": None,
        "node_alias": None,
        "rms_call": None,
        "post_office_call": None,
        "frequency_hz": None,
        "mode": None,
    }
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return result
    for raw_line in lines:
        line = raw_line.strip()
        if line.startswith("NODECALL="):
            result["node_call"] = line.split("=", 1)[1].strip()
        elif line.startswith("NODEALIAS="):
            result["node_alias"] = line.split("=", 1)[1].strip()
        elif line.startswith("APPLICATION 1,"):
            fields = [field.strip() for field in line.split(",")]
            result["rms_call"] = fields[3] if len(fields) > 3 else None
        elif line.startswith("APPLICATION 2,"):
            fields = [field.strip() for field in line.split(",")]
            result["post_office_call"] = fields[3] if len(fields) > 3 else None
        elif line.startswith("WL2KREPORT "):
            fields = [field.strip() for field in line.split(",")]
            if len(fields) > 6:
                try:
                    result["frequency_hz"] = int(fields[6])
                except ValueError:
                    pass
            if len(fields) > 7:
                result["mode"] = fields[7].replace("PKT", "Packet ")
    return result


def parse_linbpq_journal(lines: list[str]) -> dict:
    sessions: list[dict] = []
    commissioning = {
        "rf_path_verified": False,
        "cms_authentication_verified": False,
        "outbound_message_verified": False,
        "inbound_message_verified": False,
        "public_channel_report_verified": False,
    }
    pending_channel_report = False
    last_channel_report_utc = None
    for line in lines:
        match = JOURNAL_PATTERN.match(line.strip())
        if not match:
            continue
        timestamp_utc = _utc_iso(match.group("timestamp"))
        message = match.group("message")
        if message == "WL2K Database update ok" and pending_channel_report:
            commissioning["public_channel_report_verified"] = True
            pending_channel_report = False
            continue
        if not message.startswith("Sending "):
            continue
        encoded = message[len("Sending "):].strip()
        if not encoded.startswith("{"):
            encoded = "{" + encoded + "}"
        try:
            report = json.loads(encoded)
        except json.JSONDecodeError:
            continue
        if "Callsign" in report:
            if report.get("ServiceCode") == "PUBLIC" and report.get("Frequency"):
                pending_channel_report = True
                last_channel_report_utc = timestamp_utc
            continue
        payload = report
        if payload.get("Application") != "BPQ32" or not str(payload.get("Mode", "")).startswith("Packet"):
            continue
        try:
            frequency_hz = int(payload.get("Frequency", 0) or 0)
        except (TypeError, ValueError):
            frequency_hz = 0
        if frequency_hz <= 0:
            continue
        session = {
            "timestamp_utc": timestamp_utc,
            "caller": payload.get("Client"),
            "gateway": payload.get("Server"),
            "mode": payload.get("Mode"),
            "frequency_hz": frequency_hz,
            "duration_seconds": payload.get("HoldingSeconds"),
            "messages_sent": payload.get("MessagesSent", 0),
            "messages_received": payload.get("MessagesReceived", 0),
            "bytes_sent": payload.get("BytesSent", 0),
            "bytes_received": payload.get("BytesReceived", 0),
            "successful": payload.get("LastCommand") == "FQ",
        }
        sessions.append(session)
        commissioning["rf_path_verified"] = True
        commissioning["cms_authentication_verified"] = True
        commissioning["outbound_message_verified"] |= session["messages_sent"] > 0
        commissioning["inbound_message_verified"] |= session["messages_received"] > 0
    # LinBPQ prints the successful response immediately after the channel
    # report. If the bounded journal ended between the two records, retain the
    # observed report timestamp but do not mark it verified.
    return {
        "last_session": sessions[-1] if sessions else None,
        "sessions": sessions,
        "session_count": len(sessions),
        "commissioning": commissioning,
        "last_channel_report_utc": last_channel_report_utc,
    }


def _run(command: list[str]) -> str:
    try:
        completed = subprocess.run(command, check=False, capture_output=True, text=True, timeout=4)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return completed.stdout if completed.returncode == 0 else ""


def _service_status(service: str, runner: Callable[[list[str]], str]) -> dict:
    output = runner([
        "systemctl", "show", service, "--no-pager",
        "--property=ActiveState,SubState,ActiveEnterTimestampMonotonic,NRestarts",
    ])
    values = {}
    for line in output.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    started_utc = None
    try:
        entered_monotonic = int(values.get("ActiveEnterTimestampMonotonic", "0")) / 1_000_000
        if entered_monotonic:
            elapsed = max(0, time.monotonic() - entered_monotonic)
            started_utc = (datetime.now(timezone.utc) - timedelta(seconds=elapsed)).strftime("%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        pass
    return {
        "active": values.get("ActiveState") == "active",
        "state": values.get("ActiveState", "unknown"),
        "substate": values.get("SubState", "unknown"),
        "started_utc": started_utc,
        "restart_count": int(values.get("NRestarts", "0") or 0) if values.get("NRestarts", "0").isdigit() else 0,
    }


def summarize_gateway_reliability(
    rms_lines: list[str],
    modem_lines: list[str],
    rms_service: dict,
    modem_service: dict,
    now: datetime | None = None,
) -> dict:
    """Summarize operational events without exposing message or credential data."""
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    cutoff = current - timedelta(hours=24)
    cms_connections = 0
    cms_failures = 0
    modem_faults = 0
    last_cms_event = None

    def recent_messages(lines: list[str]):
        for line in lines:
            match = JOURNAL_PATTERN.match(line.strip())
            if not match:
                continue
            timestamp_utc = _utc_iso(match.group("timestamp"))
            if not timestamp_utc:
                continue
            timestamp = datetime.fromisoformat(timestamp_utc.replace("Z", "+00:00"))
            if timestamp >= cutoff:
                yield timestamp_utc, match.group("message")

    for timestamp_utc, message in recent_messages(rms_lines):
        lowered = message.lower()
        if "connected to cms" in lowered:
            cms_connections += 1
            last_cms_event = {"timestamp_utc": timestamp_utc, "successful": True}
        elif "connect to" in lowered and "failed" in lowered:
            cms_failures += 1
            last_cms_event = {"timestamp_utc": timestamp_utc, "successful": False}

    modem_fault_tokens = (
        "audio device error",
        "could not open",
        "device or resource busy",
        "no such device",
        "fatal error",
    )
    for _, message in recent_messages(modem_lines):
        lowered = message.lower()
        if any(token in lowered for token in modem_fault_tokens):
            modem_faults += 1

    if not rms_service.get("active") or not modem_service.get("active"):
        state = "fault"
    elif modem_faults or (last_cms_event and not last_cms_event["successful"]):
        state = "warning"
    else:
        state = "healthy"
    return {
        "state": state,
        "window_hours": 24,
        "cms_connections": cms_connections,
        "cms_connection_failures": cms_failures,
        "modem_faults": modem_faults,
        "last_cms_event": last_cms_event,
        "rms_started_utc": rms_service.get("started_utc"),
        "modem_started_utc": modem_service.get("started_utc"),
        "rms_restart_count": rms_service.get("restart_count", 0),
        "modem_restart_count": modem_service.get("restart_count", 0),
    }


def _port_listening(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.15):
            return True
    except OSError:
        return False


def _load_cache(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _store_cache(path: Path, payload: dict) -> None:
    try:
        if not path.parent.is_dir():
            return
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)
    except OSError:
        pass


def _session_key(session: dict) -> tuple:
    return (
        session.get("timestamp_utc"),
        session.get("caller"),
        session.get("duration_seconds"),
        session.get("bytes_sent"),
        session.get("bytes_received"),
    )


def merge_sessions(cached: list[dict], observed: list[dict], limit: int = 500) -> list[dict]:
    merged = {}
    for session in [*cached, *observed]:
        if not isinstance(session, dict) or not session.get("timestamp_utc"):
            continue
        try:
            if int(session.get("frequency_hz", 0) or 0) <= 0:
                continue
        except (TypeError, ValueError):
            continue
        merged[_session_key(session)] = session
    return sorted(merged.values(), key=lambda item: item["timestamp_utc"])[-limit:]


def summarize_sessions(sessions: list[dict], now: datetime | None = None) -> dict:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    window_start = current - timedelta(hours=24)
    recent = []
    for session in sessions:
        try:
            timestamp = datetime.fromisoformat(str(session.get("timestamp_utc", "")).replace("Z", "+00:00"))
        except ValueError:
            continue
        if timestamp >= window_start:
            recent.append((timestamp.astimezone(timezone.utc), session))
    successful = sum(1 for _, session in recent if session.get("successful"))
    durations = [session.get("duration_seconds") for _, session in recent if isinstance(session.get("duration_seconds"), (int, float))]
    hour_start = current.replace(minute=0, second=0, microsecond=0) - timedelta(hours=23)
    buckets = []
    for offset in range(24):
        bucket_start = hour_start + timedelta(hours=offset)
        bucket_end = bucket_start + timedelta(hours=1)
        buckets.append({
            "hour_utc": bucket_start.strftime("%Y-%m-%dT%H:00:00Z"),
            "sessions": sum(1 for timestamp, _ in recent if bucket_start <= timestamp < bucket_end),
        })
    return {
        "window_hours": 24,
        "window_start_utc": window_start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sessions": len(recent),
        "successful_sessions": successful,
        "failed_sessions": len(recent) - successful,
        "success_percent": round((successful / len(recent)) * 100, 1) if recent else None,
        "unique_callsigns": len({session.get("caller") for _, session in recent if session.get("caller")}),
        "messages_sent": sum(int(session.get("messages_sent", 0) or 0) for _, session in recent),
        "messages_received": sum(int(session.get("messages_received", 0) or 0) for _, session in recent),
        "bytes_sent": sum(int(session.get("bytes_sent", 0) or 0) for _, session in recent),
        "bytes_received": sum(int(session.get("bytes_received", 0) or 0) for _, session in recent),
        "average_duration_seconds": round(sum(durations) / len(durations), 1) if durations else None,
        "hourly": buckets,
    }


def collect_winlink_status(
    config_path: Path = RUNTIME_CONFIG_PATH,
    mail_store_path: Path = MAIL_STORE_PATH,
    message_index_path: Path = MESSAGE_INDEX_PATH,
    cache_path: Path = STATUS_CACHE_PATH,
    runner: Callable[[list[str]], str] = _run,
) -> dict:
    runtime = parse_runtime_config(config_path)
    rms_service = _service_status("n0jcg-winlink-rms.service", runner)
    modem_service = _service_status("n0jcg-winlink-modem.service", runner)
    journal = runner([
        "journalctl", "-u", "n0jcg-winlink-rms.service", "-n", "2500",
        "--no-pager", "--quiet", "-o", "short-iso",
    ])
    modem_journal = runner([
        "journalctl", "-u", "n0jcg-winlink-modem.service", "-n", "1000",
        "--no-pager", "--quiet", "-o", "short-iso",
    ])
    activity = parse_linbpq_journal(journal.splitlines())
    reliability = summarize_gateway_reliability(
        journal.splitlines(), modem_journal.splitlines(), rms_service, modem_service,
    )
    cached = _load_cache(cache_path)
    cached_milestones = cached.get("commissioning", {})
    merged_milestones = {
        key: bool(value or cached_milestones.get(key))
        for key, value in activity["commissioning"].items()
    }
    cached_sessions = cached.get("sessions", []) if isinstance(cached.get("sessions", []), list) else []
    sessions = merge_sessions(cached_sessions, activity["sessions"])
    last_session = sessions[-1] if sessions else activity["last_session"] or cached.get("last_session")
    statistics_24h = summarize_sessions(sessions)
    reliability["cms_connections"] = max(
        reliability["cms_connections"], statistics_24h["successful_sessions"],
    )
    if reliability["last_cms_event"] is None and last_session and last_session.get("successful"):
        reliability["last_cms_event"] = {
            "timestamp_utc": last_session.get("timestamp_utc"),
            "successful": True,
        }
    last_channel_report_utc = activity["last_channel_report_utc"] or cached.get("last_channel_report_utc")
    _store_cache(cache_path, {
        "commissioning": merged_milestones,
        "last_session": last_session,
        "last_channel_report_utc": last_channel_report_utc,
        "sessions": sessions,
    })
    try:
        stored_messages = sum(1 for item in mail_store_path.glob("m_*.mes") if item.is_file())
    except OSError:
        stored_messages = 0
    message_counts = summarize_mail_index(message_index_path)
    post_office_online = _port_listening(8772)
    operational = rms_service["active"] and modem_service["active"] and bool(runtime["rms_call"])
    return {
        "state": "operational" if operational else "fault",
        "identity": runtime,
        "services": {"linbpq": rms_service, "dire_wolf": modem_service},
        "hardware": {
            "ptt_serial_present": PTT_DEVICE_PATH.exists(),
            "usb_audio_present": Path("/proc/asound/cards").exists(),
        },
        "cms": {
            "last_session_successful": bool(last_session and last_session.get("successful")),
            "last_sync_utc": last_session.get("timestamp_utc") if last_session else None,
            "channel_report_utc": last_channel_report_utc,
        },
        "last_rf_session": last_session,
        "session_count_observed": len(sessions),
        "statistics_24h": statistics_24h,
        "reliability": reliability,
        "queues": {
            "local_message_store": stored_messages,
            "pending": message_counts["pending"],
            "delivered": message_counts["delivered"],
            "received": message_counts["received"],
            "archived": message_counts["archived"],
            "retained_total": message_counts["retained_total"],
            "index_available": message_counts["available"],
            "last_session_sent": last_session.get("messages_sent", 0) if last_session else 0,
            "last_session_received": last_session.get("messages_received", 0) if last_session else 0,
            "post_office_online": post_office_online,
            "post_office_port": 8772,
        },
        "commissioning": merged_milestones,
        "privacy": "Message bodies, subjects, recipients, and credentials are not exposed.",
    }


def collect_winlink_session_page(query: str) -> dict:
    status = collect_winlink_status()
    params = parse_qs(query)
    sort = params.get("sort", ["newest"])[0].lower()
    result_filter = params.get("result", ["all"])[0].lower()
    callsign = params.get("callsign", [""])[0].strip().upper()[:12]
    try:
        page = max(1, int(params.get("page", ["1"])[0]))
    except ValueError:
        page = 1
    cached = _load_cache(STATUS_CACHE_PATH)
    sessions = cached.get("sessions", []) if isinstance(cached.get("sessions", []), list) else []
    if result_filter == "successful":
        sessions = [session for session in sessions if session.get("successful")]
    elif result_filter == "failed":
        sessions = [session for session in sessions if not session.get("successful")]
    else:
        result_filter = "all"
    if callsign:
        sessions = [session for session in sessions if callsign in str(session.get("caller", "")).upper()]
    sessions = sorted(sessions, key=lambda item: item.get("timestamp_utc", ""), reverse=sort != "oldest")
    sort = "oldest" if sort == "oldest" else "newest"
    page_size = 25
    total = len(sessions)
    pages = max(1, (total + page_size - 1) // page_size)
    page = min(page, pages)
    start = (page - 1) * page_size
    return {
        "sessions": sessions[start:start + page_size],
        "page": page,
        "page_size": page_size,
        "pages": pages,
        "total": total,
        "sort": sort,
        "result": result_filter,
        "callsign": callsign,
        "statistics_24h": status["statistics_24h"],
        "privacy": status["privacy"],
    }
