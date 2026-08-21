from __future__ import annotations

import argparse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import mimetypes
import os
from datetime import datetime, timezone
from pathlib import Path
import re
import sqlite3
import subprocess
import threading
import time
from urllib.parse import parse_qs, urlparse

from . import __version__
from .applications import collect_application_status, save_application_settings
from .admin_report import (
    DEFAULT_SETTINGS_PATH as DEFAULT_ADMIN_REPORT_SETTINGS_PATH,
    DEFAULT_STATE_PATH as DEFAULT_ADMIN_REPORT_STATE_PATH,
    DEFAULT_TRIGGER_PATH as DEFAULT_ADMIN_REPORT_TRIGGER_PATH,
    queue_report_now,
    safe_report_status,
    save_report_settings,
)
from .aprs_map import collect_aprs_map, load_aprsfi_settings, save_aprsfi_settings
from .aprs_alerts import DEFAULT_PATH as DEFAULT_APRS_ALERT_SETTINGS_PATH, load_alert_settings, save_alert_settings, send_alert_email
from .aprs_observability import aprs_is_health, packet_quality, update_rf_history
from .config import load_station_config, transmit_interlock
from .cwop_settings import load_cwop_settings, save_cwop_settings
from .inventory import SERVICES
from .licensing import LicenseClient, LicenseError, RocTrialController
from .operator_controls import (
    ALLOWED_ACTIONS,
    OperatorAuth,
    append_audit,
    recent_audit,
    request_helper,
    set_trial_services_enabled,
    session_cookie,
)
from .operator_activity import probe_rf_session
from .system_status import collect_system_status
from .station_settings import load_station_settings, save_station_settings
from .telemetry import DEFAULT_TELEMETRY_PATH, read_telemetry, record_telemetry, reset_telemetry
from .weather import read_weather_status, store_observation
from .winlink import collect_winlink_session_page, collect_winlink_status


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WEB_ROOT = PROJECT_ROOT / "web"
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "station.toml"
APRS_LOG_PATH = PROJECT_ROOT / "runtime" / "aprs" / "packets.log"
APRS_JOURNAL_UNIT = os.environ.get("APRS_JOURNAL_UNIT", "n0jcg-aprs-rx.service")
_APRS_RECORD_CACHE_LOCK = threading.Lock()
_APRS_RECORD_CACHE: dict[int, tuple[float, list[dict]]] = {}
DEFAULT_APPLICATION_SETTINGS_PATH = Path(
    os.environ.get("ROC_APPLICATION_SETTINGS", str(PROJECT_ROOT / "runtime" / "applications.json"))
)
DEFAULT_APRSFI_SETTINGS_PATH = Path(
    os.environ.get("ROC_APRSFI_SETTINGS", str(PROJECT_ROOT / "runtime" / "aprs-fi.json"))
)
DEFAULT_APRSFI_CACHE_PATH = Path(
    os.environ.get("ROC_APRSFI_CACHE", str(PROJECT_ROOT / "runtime" / "aprs-fi-cache.json"))
)
DEFAULT_STATION_SETTINGS_PATH = Path(
    os.environ.get("ROC_STATION_SETTINGS", "/var/lib/n0jcg-roc/station.json")
)
DEFAULT_CWOP_SETTINGS_PATH = Path(os.environ.get("ROC_CWOP_SETTINGS", "/var/lib/n0jcg-roc/cwop.json"))
DEFAULT_OPERATOR_AUDIT_PATH = Path("/var/lib/n0jcg-roc/operator-audit.jsonl")
DEFAULT_OPERATOR_SOCKET_PATH = Path("/run/n0jcg-operator-helper/control.sock")
DEFAULT_MAINTENANCE_PATH = Path("/var/lib/n0jcg-roc/winlink-maintenance")
DEFAULT_LICENSE_STATE_PATH = Path("/var/lib/n0jcg-roc/licensing")
APRS_RTL_SERIAL = os.environ.get("APRS_RTL_SERIAL", "00014439")
APRS_FRAME_PATTERN = re.compile(r"^(?:\[[^\]]+\]\s*)?[A-Z0-9][A-Z0-9-]{1,8}>[^:]+:.+$")
APRS_EXPECTED_FREQUENCY_HZ = int(os.environ.get("APRS_EXPECTED_FREQUENCY_HZ", "144390000"))
APRS_DIGI_SURVEY_HOURS = int(os.environ.get("APRS_DIGI_SURVEY_HOURS", "72"))
APRS_PIPELINE_STALE_SECONDS = int(os.environ.get("APRS_PIPELINE_STALE_SECONDS", "180"))
APRS_RF_QUIET_SECONDS = int(os.environ.get("APRS_RF_QUIET_SECONDS", "21600"))
APRS_PIPELINE_STATE_PATH = PROJECT_ROOT / "runtime" / "aprs" / "pipeline-health.json"
APRS_RF_HISTORY_PATH = PROJECT_ROOT / "runtime" / "aprs" / "rf-history.json"


def collect_telemetry_sample(application_settings_path: Path) -> dict:
    system = collect_system_status()
    aprs = collect_aprs_status()
    applications = collect_application_status(application_settings_path).get("applications", [])
    air_traffic = next((item for item in applications if item.get("id") == "air_traffic"), {})
    scanner = next((item for item in applications if item.get("id") == "scanner"), {})
    air_metrics = air_traffic.get("metrics") or {}
    scanner_metrics = scanner.get("metrics") or {}
    return {
        "timestamp": int(time.time() * 1000),
        "cpu": system.get("resources", {}).get("cpu", {}).get("utilization_percent"),
        "memory": system.get("resources", {}).get("memory", {}).get("used_percent"),
        "temperature": system.get("resources", {}).get("temperature", {}).get("celsius"),
        "aprsFrames": aprs.get("packet_count"),
        "aircraft": air_metrics.get("aircraft_count") if air_traffic.get("reachable") else None,
        "voiceCalls": scanner_metrics.get("voice_calls") if scanner.get("reachable") else None,
        "vhfLocks": scanner_metrics.get("vhf_locks") if scanner.get("reachable") else None,
        "uhfLocks": scanner_metrics.get("uhf_locks") if scanner.get("reachable") else None,
    }


def run_telemetry_collector(server: "RocServer") -> None:
    while not server.telemetry_stop.is_set():
        try:
            record_telemetry(
                collect_telemetry_sample(server.application_settings_path),
                server.telemetry_path,
            )
        except (OSError, ValueError, TypeError, sqlite3.Error) as error:
            print(f"telemetry collection failed: {error}")
        server.telemetry_stop.wait(30)


def parse_aprs_frames(lines: list[str]) -> list[str]:
    return [line.strip() for line in lines if APRS_FRAME_PATTERN.match(line.strip())]


def parse_aprs_journal_records(lines: list[str]) -> list[dict]:
    records = []
    for line in lines:
        try:
            entry = json.loads(line)
            frame = str(entry.get("MESSAGE") or "").strip()
            timestamp_epoch = int(entry["__REALTIME_TIMESTAMP"]) / 1_000_000
        except (ValueError, TypeError, KeyError, json.JSONDecodeError, OSError):
            continue
        if not APRS_FRAME_PATTERN.match(frame):
            continue
        records.append({
            "frame": frame,
            "origin": aprs_frame_origin(frame),
            "timestamp_utc": datetime.fromtimestamp(timestamp_epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        })
    return records


def collect_aprs_frame_records(*, runner=None, max_lines: int = 50000) -> list[dict]:
    use_cache = runner is None
    current_epoch = time.time()
    max_lines = max(100, min(50000, int(max_lines)))
    if use_cache:
        with _APRS_RECORD_CACHE_LOCK:
            cached_epoch, cached_records = _APRS_RECORD_CACHE.get(max_lines, (0.0, []))
            if current_epoch - cached_epoch < 5:
                return list(cached_records)
        runner = subprocess.run
    try:
        result = runner(
            [
                "journalctl",
                f"--unit={APRS_JOURNAL_UNIT}",
                "--output=json",
                "--no-pager",
                f"--lines={max_lines}",
            ],
            capture_output=True,
            check=False,
            text=True,
            timeout=8,
        )
        records = parse_aprs_journal_records(result.stdout.splitlines()) if result.returncode == 0 else []
    except (OSError, subprocess.SubprocessError):
        records = []
    if not records:
        try:
            lines = APRS_LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
            timestamp = datetime.fromtimestamp(APRS_LOG_PATH.stat().st_mtime, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except OSError:
            lines, timestamp = [], None
        records = [
            {"frame": frame, "origin": aprs_frame_origin(frame), "timestamp_utc": timestamp}
            for frame in parse_aprs_frames(lines)
        ]
    if use_cache:
        with _APRS_RECORD_CACHE_LOCK:
            _APRS_RECORD_CACHE[max_lines] = (current_epoch, list(records))
    return records


def aprs_frame_origin(frame: str) -> str:
    """Identify locally generated APRS-IS traffic separately from RF decodes."""
    return "internet" if frame.startswith("[ig]") else "rf"


def _aprs_receiver_process_active() -> bool:
    for proc in Path("/proc").glob("[0-9]*"):
        try:
            command = (proc / "cmdline").read_bytes().replace(b"\x00", b" ").decode("utf-8", "ignore")
        except OSError:
            continue
        if "rtl_fm" in command and APRS_RTL_SERIAL in command:
            return True
    return False


def collect_aprs_pipeline_health(records: list[dict] | None = None) -> dict:
    """Return a fail-visible health assessment for the APRS RF pipeline.

    A running systemd process is not sufficient: audio-ring freshness and RF
    decode freshness are evaluated separately.  Internet-only iGate beacons
    deliberately do not count as RF evidence.
    """
    now = time.time()
    active = _aprs_receiver_process_active()
    audio_path = APRS_LOG_PATH.parent / "audio-ring.wav"
    rtl_log_path = APRS_LOG_PATH.parent / "rtl.log"
    packet_path = APRS_LOG_PATH
    mtimes = {}
    for name, path in (("audio", audio_path), ("rtl", rtl_log_path), ("packets", packet_path)):
        try:
            mtimes[name] = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except OSError:
            mtimes[name] = None
    freshest_path = None
    freshest_mtime = None
    for path in (audio_path, packet_path, rtl_log_path):
        try:
            value = path.stat().st_mtime
        except OSError:
            continue
        if freshest_mtime is None or value > freshest_mtime:
            freshest_mtime, freshest_path = value, path
    pipeline_age_seconds = None if freshest_mtime is None else max(0, int(now - freshest_mtime))
    rf_records = [item for item in (records or collect_aprs_frame_records(max_lines=500)) if item.get("origin") == "rf"]
    last_rf = rf_records[-1] if rf_records else None
    last_rf_epoch = None
    if last_rf and last_rf.get("timestamp_utc"):
        try:
            last_rf_epoch = datetime.fromisoformat(last_rf["timestamp_utc"].replace("Z", "+00:00")).timestamp()
        except (TypeError, ValueError):
            pass
    rf_age_seconds = None if last_rf_epoch is None else max(0, int(now - last_rf_epoch))
    reasons = []
    state = "healthy"
    if not active:
        state, reasons = "fault", ["RTL receiver process is not running"]
    elif audio_path.exists() and (pipeline_age_seconds is None or pipeline_age_seconds > APRS_PIPELINE_STALE_SECONDS):
        state, reasons = "fault", [f"audio pipeline has not advanced for {pipeline_age_seconds or 'an unknown number of'} seconds"]
    elif rf_age_seconds is None or rf_age_seconds > APRS_RF_QUIET_SECONDS:
        state = "degraded"
        reasons = ["RF decode is quiet or stale; receiver process and audio pipeline are still active"]
    else:
        reasons = ["receiver process, audio pipeline, and RF decodes are current"]
    return {
        "state": state,
        "active": active,
        "summary": reasons[0],
        "reasons": reasons,
        "checked_at_utc": datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "last_pipeline_activity_utc": None if freshest_mtime is None else datetime.fromtimestamp(freshest_mtime, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "pipeline_age_seconds": pipeline_age_seconds,
        "last_rf_packet_timestamp_utc": last_rf.get("timestamp_utc") if last_rf else None,
        "rf_age_seconds": rf_age_seconds,
        "expected_frequency_hz": APRS_EXPECTED_FREQUENCY_HZ,
        "pipeline_files": mtimes,
    }


def collect_aprs_status() -> dict:
    try:
        lines = APRS_LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        lines = []
    records = collect_aprs_frame_records(max_lines=500)
    frames = [record["frame"] for record in records]
    all_frames = parse_aprs_frames(lines)
    active = _aprs_receiver_process_active()
    pipeline = collect_aprs_pipeline_health(records)
    quality = packet_quality(records)
    journal_lines = []
    try:
        journal = subprocess.run(
            ["journalctl", f"--unit={APRS_JOURNAL_UNIT}", "--no-pager", "--lines=200"],
            capture_output=True, check=False, text=True, timeout=8,
        )
        journal_lines = journal.stdout.splitlines()
    except (OSError, subprocess.SubprocessError):
        pass
    # Dire Wolf's tee output is the authoritative APRS-IS evidence on the
    # receive service; systemd may not retain the older connection messages.
    try:
        journal_lines.extend(APRS_LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()[-500:])
    except OSError:
        pass
    is_health = aprs_is_health(records, journal_lines=journal_lines)
    try:
        rf_history = update_rf_history(APRS_RF_HISTORY_PATH, records)
    except (OSError, ValueError, TypeError):
        rf_history = {"hours": [], "points": [], "retention_hours": 168}
    return {
        "configured": True,
        "active": active,
        "pipeline": pipeline,
        "packet_count": len(all_frames),
        "last_packet": frames[-1] if frames else None,
        "last_packet_origin": aprs_frame_origin(frames[-1]) if frames else None,
        "last_packet_timestamp_utc": records[-1]["timestamp_utc"] if records else None,
        "packets": frames[-20:],
        "recent": lines[-20:],
        "quality": quality,
        "aprs_is": is_health,
        "rf_history": rf_history,
    }


def collect_aprs_digipeater_survey(station: dict | None = None) -> dict:
    """Summarize actual locally heard digipeater hops without transmitting."""
    cutoff = time.time() - max(1, APRS_DIGI_SURVEY_HOURS) * 3600
    records = collect_aprs_frame_records(max_lines=5000)
    station = station or {}
    origin_lat, origin_lon = station.get("latitude"), station.get("longitude")
    hop_pattern = re.compile(r"^[A-Z0-9][A-Z0-9-]{1,8}$", re.IGNORECASE)
    position_pattern = re.compile(r"[!=/@](\d{2})(\d{2}\.\d{2})([NS])[/\\](\d{3})(\d{2}\.\d{2})([EW])")
    ignored_prefixes = ("WIDE", "TRACE", "RELAY", "NCA", "SS")
    observed: dict[str, dict] = {}
    for record in records:
        if record.get("origin") != "rf":
            continue
        timestamp = record.get("timestamp_utc")
        try:
            epoch = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00")).timestamp()
        except (TypeError, ValueError):
            continue
        if epoch < cutoff:
            continue
        frame = str(record.get("frame") or "")
        match = re.match(r"^(?:\[[^\]]+\]\s*)?([^>]+)>([^:]+):(.*)$", frame)
        if not match:
            continue
        source, header, payload = match.groups()
        position = position_pattern.search(payload)
        lat_lon = None
        if position:
            lat_deg, lat_min, lat_hemi, lon_deg, lon_min, lon_hemi = position.groups()
            lat_lon = ((int(lat_deg) + float(lat_min) / 60) * (1 if lat_hemi == "N" else -1),
                       (int(lon_deg) + float(lon_min) / 60) * (1 if lon_hemi == "E" else -1))
        for raw_hop in header.split(",")[1:]:
            if not raw_hop.strip().endswith("*"):
                continue
            hop = raw_hop.strip()[:-1].upper()
            if not hop_pattern.match(hop) or hop.startswith(ignored_prefixes):
                continue
            item = observed.setdefault(hop, {"callsign": hop, "count": 0, "last_heard_utc": timestamp, "source_callsigns": set(), "position": None})
            item["count"] += 1
            item["last_heard_utc"] = max(item["last_heard_utc"] or timestamp, timestamp or "")
            item["source_callsigns"].add(source.upper())
            if lat_lon and item["position"] is None:
                item["position"] = {"latitude": round(lat_lon[0], 5), "longitude": round(lat_lon[1], 5)}
    entries = []
    for item in observed.values():
        entry = {**item, "source_callsigns": sorted(item["source_callsigns"])}
        if entry["position"] and origin_lat is not None and origin_lon is not None:
            lat1, lon1, lat2, lon2 = map(math.radians, [float(origin_lat), float(origin_lon), entry["position"]["latitude"], entry["position"]["longitude"]])
            a = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
            entry["source_distance_km"] = round(6371.0 * 2 * math.asin(math.sqrt(a)), 1)
        entries.append(entry)
    entries.sort(key=lambda item: (item["count"], item["last_heard_utc"] or ""), reverse=True)
    return {
        "window_hours": APRS_DIGI_SURVEY_HOURS,
        "window_start_utc": datetime.fromtimestamp(cutoff, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "observed_count": len(entries),
        "observed": entries,
        "message": "No digipeater hops have been observed locally in this survey window." if not entries else "Observed hops are based only on RF frames decoded by the ROC.",
    }


def collect_aprs_frame_page(query: str) -> dict:
    records = collect_aprs_frame_records()
    params = parse_qs(query)
    try:
        page = max(1, int(params.get("page", ["1"])[0]))
    except ValueError:
        page = 1
    sort = params.get("sort", ["newest"])[0].lower()
    ordered = list(reversed(records)) if sort != "oldest" else list(records)
    total = len(ordered)
    page_size = 25
    start = (page - 1) * page_size
    return {
        "frames": ordered[start:start + page_size],
        "page": page,
        "page_size": page_size,
        "total": total,
        "pages": max(1, (total + page_size - 1) // page_size),
        "sort": sort if sort in {"newest", "oldest"} else "newest",
    }


def collect_gateway_status(config: dict) -> dict:
    """Expose gateway readiness without providing a transmit operation."""
    aprs = collect_aprs_status()
    interlock = transmit_interlock(config)
    return {
        "receive": {
            "aprs": {
                "active": aprs["active"],
                "packet_count": aprs["packet_count"],
                "kiss_port": 18001,
                "agw_port": 18000,
                "rf_role": "receive-only",
            }
        },
        "winlink": collect_winlink_status(),
        "transmit": interlock,
    }


class RocRequestHandler(BaseHTTPRequestHandler):
    server_version = f"N0JCG-ROC/{__version__}"

    def do_GET(self) -> None:  # noqa: N802 - standard library handler API
        route = urlparse(self.path).path
        if route in {"/api/license/status", "/api/registration/status"}:
            self._json({"ok": True, "registration": self.server.trial_controller.status()})
            return
        if route == "/api/health":
            self._json(
                {
                    "status": "ok",
                    "version": __version__,
                    "mode": "phase-0-foundation",
                    "transmit": transmit_interlock(self.server.station_config),
                }
            )
            return
        if route == "/api/station":
            self._json({
                **self.server.station_config,
                "display": load_station_settings(
                    self.server.station_settings_path,
                    self.server.station_config["station"],
                ),
            })
            return
        if route == "/api/station/settings":
            self._json(load_station_settings(
                self.server.station_settings_path,
                self.server.station_config["station"],
            ))
            return
        if route == "/api/aprs/context":
            station = self.server.station_config["station"]
            self._json({
                "ok": True,
                "latitude": station["latitude"],
                "longitude": station["longitude"],
                "utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "callsign": station["callsign"],
                "source": "N0JCG ROC connected PC",
            })
            return
        if route == "/api/services":
            self._json({"services": SERVICES})
            return
        if route == "/api/system":
            self._json(collect_system_status())
            return
        if route == "/api/telemetry":
            self._json(read_telemetry(self.server.telemetry_path))
            return
        if route == "/api/aprs":
            self._json(collect_aprs_status())
            return
        if route == "/api/aprs/quality":
            self._json(collect_aprs_status().get("quality", {}))
            return
        if route == "/api/aprs/is-health":
            self._json(collect_aprs_status().get("aprs_is", {}))
            return
        if route == "/api/aprs/rf-history":
            self._json(collect_aprs_status().get("rf_history", {}))
            return
        if route == "/api/aprs/alerts/settings":
            settings = load_alert_settings(self.server.aprs_alert_settings_path)
            self._json({"enabled": settings["enabled"], "configured": bool(settings["recipient"]), "sender": settings["sender"], "recipient": settings["recipient"] if self._operator_session() else ""})
            return
        if route == "/api/aprs/frames":
            self._json(collect_aprs_frame_page(urlparse(self.path).query))
            return
        if route == "/api/aprs/digipeaters":
            self._json(collect_aprs_digipeater_survey(self.server.station_config["station"]))
            return
        if route == "/api/aprs-map":
            params = parse_qs(urlparse(self.path).query)
            force_refresh = params.get("refresh", ["0"])[0] == "1"
            payload = collect_aprs_map(
                APRS_LOG_PATH,
                self.server.aprsfi_settings_path,
                self.server.aprsfi_cache_path,
                force_refresh=force_refresh,
            )
            station = self.server.station_config["station"]
            payload["map_center"] = {
                "latitude": station["latitude"],
                "longitude": station["longitude"],
                "label": station["site_label"],
            }
            self._json(payload)
            return
        if route == "/api/aprs-map/settings":
            settings = load_aprsfi_settings(self.server.aprsfi_settings_path)
            self._json({"enabled": settings["enabled"], "configured": bool(settings["api_key"])})
            return
        if route == "/api/gateway":
            self._json(collect_gateway_status(self.server.station_config))
            return
        if route == "/api/winlink/sessions":
            self._json(collect_winlink_session_page(urlparse(self.path).query))
            return
        if route == "/api/operator/status":
            session = self._operator_session()
            rf_activity = probe_rf_session()
            self._json({
                "configured": self.server.operator_auth.configured,
                "authenticated": session is not None,
                "csrf_token": session.get("csrf") if session else None,
                "session_expires_utc": datetime.fromtimestamp(session["exp"], timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if session else None,
                "maintenance_mode": self.server.maintenance_path.exists(),
                "helper_available": self.server.operator_socket_path.exists(),
                "rf_session_active": rf_activity["active"],
                "rf_activity_check_available": rf_activity["available"],
                "controls": sorted(ALLOWED_ACTIONS),
            })
            return
        if route == "/api/operator/diagnostics":
            if self._operator_session() is None:
                self._json({"ok": False, "error": "operator login required"}, HTTPStatus.UNAUTHORIZED)
                return
            gateway = collect_gateway_status(self.server.station_config)
            diagnostics = {
                "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "product": "N0JCG Radio Operations Center",
                "version": __version__,
                "station": {
                    "callsign": self.server.station_config["station"].get("callsign"),
                    "site_label": self.server.station_config["station"].get("site_label"),
                },
                "system": collect_system_status(),
                "gateway": gateway,
                "operator": {
                    "maintenance_mode": self.server.maintenance_path.exists(),
                    "recent_audit": recent_audit(self.server.operator_audit_path),
                },
                "privacy": "Message bodies, subjects, recipients, credentials, and environment variables are excluded.",
            }
            self._download_json(diagnostics, "n0jcg-roc-diagnostics.json")
            return
        if route == "/api/admin-report/settings":
            if self._operator_session() is None:
                self._json({"ok": False, "error": "operator login required"}, HTTPStatus.UNAUTHORIZED)
                return
            self._json(safe_report_status(
                self.server.admin_report_settings_path,
                self.server.admin_report_state_path,
                self.server.admin_report_trigger_path,
            ))
            return
        if route == "/api/weather":
            status = read_weather_status()
            status["cwop"] = load_cwop_settings(self.server.cwop_settings_path)
            self._json(status)
            return
        if route == "/api/weather/cwop/settings":
            if self._operator_session() is None:
                self._json({"ok": False, "error": "operator login required"}, HTTPStatus.UNAUTHORIZED)
                return
            self._json(load_cwop_settings(self.server.cwop_settings_path))
            return
        if route == "/api/applications":
            self._json(collect_application_status(self.server.application_settings_path))
            return
        self._static(route)

    def do_POST(self) -> None:  # noqa: N802 - standard library handler API
        route = urlparse(self.path).path
        if route in {"/api/license/activate", "/api/registration/activate"}:
            try:
                registration = self.server.trial_controller.activate(self._read_json(4096))
                self._json({"ok": True, "registration": registration})
            except ConnectionError as error:
                self._json({"ok": False, "error": str(error)}, HTTPStatus.BAD_GATEWAY)
            except (LicenseError, ValueError, TypeError, json.JSONDecodeError, UnicodeError, OSError) as error:
                self._json({"ok": False, "error": str(error)}, HTTPStatus.BAD_REQUEST)
            return
        if route in {"/api/license/trial/reset", "/api/registration/trial/reset"}:
            try:
                self._json({"ok": True, "registration": self.server.trial_controller.reset_trial()})
            except (LicenseError, ValueError, OSError) as error:
                self._json(
                    {"ok": False, "error": str(error), "registration": self.server.trial_controller.status(start_trial=False)},
                    HTTPStatus.CONFLICT,
                )
            return
        if route == "/api/operator/login":
            if not self.server.operator_auth.configured:
                self._json({"ok": False, "error": "operator controls are not configured"}, HTTPStatus.SERVICE_UNAVAILABLE)
                return
            if not self._login_allowed():
                append_audit(self.server.operator_audit_path, remote=self.client_address[0], event="login", result="rate_limited")
                self._json({"ok": False, "error": "too many login attempts; try again later"}, HTTPStatus.TOO_MANY_REQUESTS)
                return
            try:
                payload = self._read_json(2048)
                password = str(payload.get("password", ""))
            except (ValueError, TypeError, json.JSONDecodeError, UnicodeError) as error:
                self._json({"ok": False, "error": str(error)}, HTTPStatus.BAD_REQUEST)
                return
            if not self.server.operator_auth.verify_password(password):
                self._record_login_failure()
                append_audit(self.server.operator_audit_path, remote=self.client_address[0], event="login", result="denied")
                self._json({"ok": False, "error": "invalid operator password"}, HTTPStatus.UNAUTHORIZED)
                return
            self._clear_login_failures()
            token, csrf_token, max_age = self.server.operator_auth.issue_session()
            append_audit(self.server.operator_audit_path, remote=self.client_address[0], event="login", result="success")
            self._json(
                {"ok": True, "authenticated": True, "csrf_token": csrf_token, "expires_in_seconds": max_age},
                headers={"Set-Cookie": f"n0jcg_operator={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={max_age}"},
            )
            return
        if route == "/api/operator/logout":
            session = self._operator_session(require_csrf=True)
            if session is None:
                self._json({"ok": False, "error": "valid operator session required"}, HTTPStatus.UNAUTHORIZED)
                return
            append_audit(self.server.operator_audit_path, remote=self.client_address[0], event="logout", result="success")
            self._json(
                {"ok": True, "authenticated": False},
                headers={"Set-Cookie": "n0jcg_operator=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0"},
            )
            return
        if route == "/api/operator/action":
            session = self._operator_session(require_csrf=True)
            if session is None:
                self._json({"ok": False, "error": "valid operator session required"}, HTTPStatus.UNAUTHORIZED)
                return
            try:
                payload = self._read_json(2048)
                action = str(payload.get("action", ""))
                if action not in ALLOWED_ACTIONS:
                    raise ValueError("operator action is not allowed")
                if action == "cms_test":
                    rf_activity = probe_rf_session()
                    if not rf_activity["available"]:
                        append_audit(self.server.operator_audit_path, remote=self.client_address[0], event=action, result="blocked", detail="RF activity unavailable")
                        self._json({"ok": False, "error": "CMS test blocked: unable to verify that the RF channel is idle"}, HTTPStatus.CONFLICT)
                        return
                    if rf_activity["active"]:
                        append_audit(self.server.operator_audit_path, remote=self.client_address[0], event=action, result="blocked", detail="active RF session")
                        self._json({"ok": False, "error": "CMS test blocked: an RF session is active"}, HTTPStatus.CONFLICT)
                        return
                parameters = None
                helper_timeout = 35.0
                if action == "wifi_connect":
                    ssid = str(payload.get("ssid", ""))
                    password = str(payload.get("password", ""))
                    if not ssid or len(ssid.encode("utf-8")) > 32 or any(ord(character) < 32 for character in ssid):
                        raise ValueError("SSID is invalid")
                    if len(password.encode("utf-8")) > 64 or any(character in password for character in ("\n", "\r", "\x00")):
                        raise ValueError("Wi-Fi password is invalid")
                    parameters = {"ssid": ssid, "password": password}
                    helper_timeout = 80.0
                elif action == "ethernet_set":
                    interface = str(payload.get("interface", ""))
                    address_cidr = str(payload.get("address_cidr", ""))
                    gateway = str(payload.get("gateway", ""))
                    dns = str(payload.get("dns", ""))
                    if not interface or len(interface) > 32 or not all(character.isalnum() or character in "_.:-" for character in interface):
                        raise ValueError("Ethernet interface is invalid")
                    if any(len(value) > 64 for value in (address_cidr, gateway, dns)):
                        raise ValueError("Ethernet settings are invalid")
                    parameters = {
                        "interface": interface,
                        "address_cidr": address_cidr,
                        "gateway": gateway,
                        "dns": dns,
                    }
                    helper_timeout = 70.0
                elif action == "repair_service":
                    service = str(payload.get("service", ""))
                    if not service or len(service) > 32 or not service.replace("_", "").isalnum():
                        raise ValueError("service repair target is invalid")
                    parameters = {"service": service}
                    helper_timeout = 45.0
                result = request_helper(action, self.server.operator_socket_path, helper_timeout, parameters)
            except (OSError, ValueError, TypeError, json.JSONDecodeError, UnicodeError) as error:
                append_audit(self.server.operator_audit_path, remote=self.client_address[0], event="operator_action", result="failed", detail=str(error))
                self._json({"ok": False, "error": str(error)}, HTTPStatus.BAD_GATEWAY)
                return
            append_audit(
                self.server.operator_audit_path,
                remote=self.client_address[0],
                event=action,
                result="success" if result.get("ok") else "failed",
                detail=(
                    str(payload.get("ssid", "")) if action == "wifi_connect"
                    else str(payload.get("address_cidr", "")) if action == "ethernet_set"
                    else ""
                ),
            )
            self._json(result, HTTPStatus.OK if result.get("ok") else HTTPStatus.BAD_GATEWAY)
            return
        if route == "/api/station/settings":
            length = int(self.headers.get("Content-Length", "0"))
            if length > 4096:
                self._json({"ok": False, "error": "settings payload is too large"}, HTTPStatus.BAD_REQUEST)
                return
            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                settings = save_station_settings(
                    self.server.station_settings_path,
                    self.server.station_config["station"],
                    payload,
                )
                self._json({"ok": True, **settings})
            except (ValueError, TypeError, json.JSONDecodeError, OSError) as error:
                self._json({"ok": False, "error": str(error)}, HTTPStatus.BAD_REQUEST)
            return
        if route == "/api/weather/ingest":
            length = int(self.headers.get("Content-Length", "0"))
            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("JSON object required")
                self._json({"ok": True, "observation": store_observation(payload)})
            except (ValueError, TypeError, json.JSONDecodeError) as error:
                self._json({"ok": False, "error": str(error)}, HTTPStatus.BAD_REQUEST)
            return
        if route == "/api/weather/cwop/settings":
            if self._operator_session(require_csrf=True) is None:
                self._json({"ok": False, "error": "valid operator session required"}, HTTPStatus.UNAUTHORIZED)
                return
            try:
                settings = save_cwop_settings(self.server.cwop_settings_path, self._read_json(4096))
                append_audit(self.server.operator_audit_path, remote=self.client_address[0], event="cwop_settings", result="success", detail=f"enabled={settings['enabled']}")
                self._json({"ok": True, **settings})
            except (ValueError, TypeError, json.JSONDecodeError, OSError) as error:
                self._json({"ok": False, "error": str(error)}, HTTPStatus.BAD_REQUEST)
            return
        if route == "/api/telemetry/reset":
            if self._operator_session(require_csrf=True) is None:
                self._json({"ok": False, "error": "valid operator session required"}, HTTPStatus.UNAUTHORIZED)
                return
            try:
                result = reset_telemetry(self.server.telemetry_path)
                append_audit(
                    self.server.operator_audit_path,
                    remote=self.client_address[0],
                    event="telemetry_reset",
                    result="success",
                    detail=f"deleted_samples={result['deleted_samples']}",
                )
                self._json(result)
            except (OSError, sqlite3.Error) as error:
                append_audit(
                    self.server.operator_audit_path,
                    remote=self.client_address[0],
                    event="telemetry_reset",
                    result="failed",
                    detail=str(error),
                )
                self._json({"ok": False, "error": str(error)}, HTTPStatus.BAD_REQUEST)
            return
        if route == "/api/applications":
            length = int(self.headers.get("Content-Length", "0"))
            if length > 65536:
                self._json({"ok": False, "error": "settings payload is too large"}, HTTPStatus.BAD_REQUEST)
                return
            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                settings = save_application_settings(self.server.application_settings_path, payload)
                self._json({"ok": True, **settings})
            except (ValueError, TypeError, json.JSONDecodeError, OSError) as error:
                self._json({"ok": False, "error": str(error)}, HTTPStatus.BAD_REQUEST)
            return
        if route == "/api/aprs-map/settings":
            length = int(self.headers.get("Content-Length", "0"))
            if length > 4096:
                self._json({"ok": False, "error": "settings payload is too large"}, HTTPStatus.BAD_REQUEST)
                return
            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                state = save_aprsfi_settings(self.server.aprsfi_settings_path, payload)
                self._json({"ok": True, **state})
            except (ValueError, TypeError, json.JSONDecodeError, OSError) as error:
                self._json({"ok": False, "error": str(error)}, HTTPStatus.BAD_REQUEST)
            return
        if route == "/api/aprs/alerts/settings":
            if self._operator_session(require_csrf=True) is None:
                self._json({"ok": False, "error": "valid operator session required"}, HTTPStatus.UNAUTHORIZED)
                return
            try:
                settings = save_alert_settings(self.server.aprs_alert_settings_path, self._read_json(4096))
                append_audit(self.server.operator_audit_path, remote=self.client_address[0], event="aprs_alert_settings", result="success", detail=f"enabled={settings['enabled']}")
                self._json({"ok": True, "enabled": settings["enabled"], "configured": bool(settings["recipient"]), "sender": settings["sender"], "recipient": settings["recipient"]})
            except (ValueError, TypeError, json.JSONDecodeError, OSError) as error:
                self._json({"ok": False, "error": str(error)}, HTTPStatus.BAD_REQUEST)
            return
        if route == "/api/aprs/alerts/send-test":
            if self._operator_session(require_csrf=True) is None:
                self._json({"ok": False, "error": "valid operator session required"}, HTTPStatus.UNAUTHORIZED)
                return
            settings = load_alert_settings(self.server.aprs_alert_settings_path)
            result = send_alert_email(settings["recipient"], "N0JCG APRS alert test", "This is a test alert from the N0JCG Radio Operations Center.") if settings["enabled"] else {"ok": False, "error": "APRS alerts are disabled"}
            self._json(result, HTTPStatus.OK if result.get("ok") else HTTPStatus.BAD_REQUEST)
            return
        if route == "/api/admin-report/settings":
            if self._operator_session(require_csrf=True) is None:
                self._json({"ok": False, "error": "valid operator session required"}, HTTPStatus.UNAUTHORIZED)
                return
            try:
                payload = self._read_json(4096)
                settings = save_report_settings(self.server.admin_report_settings_path, payload)
                append_audit(
                    self.server.operator_audit_path,
                    remote=self.client_address[0],
                    event="admin_report_settings",
                    result="success",
                    detail=f"enabled={settings['enabled']} interval_hours={settings['interval_hours']}",
                )
                self._json({
                    "ok": True,
                    **safe_report_status(
                        self.server.admin_report_settings_path,
                        self.server.admin_report_state_path,
                        self.server.admin_report_trigger_path,
                    ),
                })
            except (ValueError, TypeError, json.JSONDecodeError, UnicodeError, OSError) as error:
                append_audit(
                    self.server.operator_audit_path,
                    remote=self.client_address[0],
                    event="admin_report_settings",
                    result="failed",
                    detail=str(error),
                )
                self._json({"ok": False, "error": str(error)}, HTTPStatus.BAD_REQUEST)
            return
        if route == "/api/admin-report/send-now":
            if self._operator_session(require_csrf=True) is None:
                self._json({"ok": False, "error": "valid operator session required"}, HTTPStatus.UNAUTHORIZED)
                return
            try:
                self._read_json(256)
                request = queue_report_now(
                    self.server.admin_report_settings_path,
                    self.server.admin_report_trigger_path,
                )
                append_audit(
                    self.server.operator_audit_path,
                    remote=self.client_address[0],
                    event="admin_report_send_now",
                    result="queued",
                )
                self._json({"ok": True, "message": "Operator report queued for immediate delivery.", **request})
            except (ValueError, TypeError, json.JSONDecodeError, UnicodeError, OSError) as error:
                append_audit(
                    self.server.operator_audit_path,
                    remote=self.client_address[0],
                    event="admin_report_send_now",
                    result="failed",
                    detail=str(error),
                )
                self._json({"ok": False, "error": str(error)}, HTTPStatus.CONFLICT)
            return
        self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)

    def log_message(self, format: str, *args: object) -> None:
        print(f"{self.address_string()} - {format % args}")

    def _read_json(self, limit: int) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length < 0 or length > limit:
            raise ValueError("request payload is too large")
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("JSON object required")
        return payload

    def _operator_session(self, require_csrf: bool = False) -> dict | None:
        token = session_cookie(self.headers)
        csrf_token = self.headers.get("X-CSRF-Token") if require_csrf else None
        if require_csrf and not csrf_token:
            return None
        return self.server.operator_auth.verify_session(token, csrf_token=csrf_token)

    def _login_allowed(self) -> bool:
        remote = self.client_address[0]
        cutoff = time.monotonic() - 600
        with self.server.login_lock:
            attempts = [value for value in self.server.login_failures.get(remote, []) if value >= cutoff]
            self.server.login_failures[remote] = attempts
            return len(attempts) < 5

    def _record_login_failure(self) -> None:
        with self.server.login_lock:
            self.server.login_failures.setdefault(self.client_address[0], []).append(time.monotonic())

    def _clear_login_failures(self) -> None:
        with self.server.login_lock:
            self.server.login_failures.pop(self.client_address[0], None)

    def _json(self, payload: object, status: HTTPStatus = HTTPStatus.OK, headers: dict[str, str] | None = None) -> None:
        content = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _download_json(self, payload: object, filename: str) -> None:
        content = (json.dumps(payload, indent=2) + "\n").encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _static(self, route: str) -> None:
        static_root = self.server.web_root
        relative = "index.html" if route == "/" else route.lstrip("/")
        candidate = (static_root / relative).resolve()
        try:
            candidate.relative_to(static_root.resolve())
        except ValueError:
            self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            return
        if not candidate.is_file():
            self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            return
        content = candidate.read_bytes()
        media_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"{media_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)


class RocServer(ThreadingHTTPServer):
    web_root: Path
    station_config: dict
    application_settings_path: Path
    aprsfi_settings_path: Path
    aprsfi_cache_path: Path
    station_settings_path: Path
    cwop_settings_path: Path
    admin_report_settings_path: Path
    admin_report_state_path: Path
    admin_report_trigger_path: Path
    telemetry_path: Path
    operator_auth: OperatorAuth
    operator_audit_path: Path
    operator_socket_path: Path
    maintenance_path: Path
    login_failures: dict[str, list[float]]
    login_lock: threading.Lock
    trial_controller: RocTrialController
    telemetry_stop: threading.Event
    telemetry_thread: threading.Thread | None

    def server_close(self) -> None:
        self.telemetry_stop.set()
        if self.telemetry_thread:
            self.telemetry_thread.join(timeout=3)
        self.trial_controller.close()
        super().server_close()


def create_server(
    host: str = "127.0.0.1",
    port: int = 8095,
    *,
    web_root: Path = DEFAULT_WEB_ROOT,
    config_path: Path = DEFAULT_CONFIG_PATH,
    application_settings_path: Path = DEFAULT_APPLICATION_SETTINGS_PATH,
    aprsfi_settings_path: Path = DEFAULT_APRSFI_SETTINGS_PATH,
    aprsfi_cache_path: Path = DEFAULT_APRSFI_CACHE_PATH,
    aprs_alert_settings_path: Path = DEFAULT_APRS_ALERT_SETTINGS_PATH,
    station_settings_path: Path = DEFAULT_STATION_SETTINGS_PATH,
    cwop_settings_path: Path = DEFAULT_CWOP_SETTINGS_PATH,
    admin_report_settings_path: Path = DEFAULT_ADMIN_REPORT_SETTINGS_PATH,
    admin_report_state_path: Path = DEFAULT_ADMIN_REPORT_STATE_PATH,
    admin_report_trigger_path: Path = DEFAULT_ADMIN_REPORT_TRIGGER_PATH,
    telemetry_path: Path = DEFAULT_TELEMETRY_PATH,
    operator_auth: OperatorAuth | None = None,
    operator_audit_path: Path = DEFAULT_OPERATOR_AUDIT_PATH,
    operator_socket_path: Path = DEFAULT_OPERATOR_SOCKET_PATH,
    maintenance_path: Path = DEFAULT_MAINTENANCE_PATH,
    license_state_path: Path = DEFAULT_LICENSE_STATE_PATH,
    trial_controller: RocTrialController | None = None,
    start_telemetry_collector: bool = True,
) -> RocServer:
    server = RocServer((host, port), RocRequestHandler)
    server.web_root = web_root
    server.station_config = load_station_config(config_path)
    server.application_settings_path = application_settings_path
    server.aprsfi_settings_path = aprsfi_settings_path
    server.aprsfi_cache_path = aprsfi_cache_path
    server.aprs_alert_settings_path = aprs_alert_settings_path
    server.station_settings_path = station_settings_path
    server.cwop_settings_path = cwop_settings_path
    server.admin_report_settings_path = admin_report_settings_path
    server.admin_report_state_path = admin_report_state_path
    server.admin_report_trigger_path = admin_report_trigger_path
    server.telemetry_path = telemetry_path
    server.operator_auth = operator_auth or OperatorAuth(
        os.environ.get("ROC_OPERATOR_PASSWORD_HASH", ""),
        os.environ.get("ROC_OPERATOR_SESSION_SECRET", ""),
    )
    server.operator_audit_path = operator_audit_path
    server.operator_socket_path = operator_socket_path
    server.maintenance_path = maintenance_path
    def enforce_trial_service_access(enabled: bool) -> None:
        result = set_trial_services_enabled(enabled, server.operator_socket_path)
        if not result.get("ok"):
            raise OSError(str(result.get("error") or "trial service operation failed"))

    server.trial_controller = trial_controller or RocTrialController(
        LicenseClient(app_version=__version__, state_root=license_state_path),
        service_access_changed=enforce_trial_service_access,
    )
    server.login_failures = {}
    server.login_lock = threading.Lock()
    server.telemetry_stop = threading.Event()
    server.telemetry_thread = None
    if start_telemetry_collector:
        server.telemetry_thread = threading.Thread(
            target=run_telemetry_collector,
            args=(server,),
            name="n0jcg-telemetry",
            daemon=True,
        )
        server.telemetry_thread.start()
    return server


def main() -> None:
    parser = argparse.ArgumentParser(description="N0JCG Radio Operations Center")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8095)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    args = parser.parse_args()
    server = create_server(args.host, args.port, config_path=args.config)
    print(f"N0JCG-ROC {__version__} listening on http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
