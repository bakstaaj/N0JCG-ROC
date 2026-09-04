"""APRS operational metrics and bounded RF survey history.

This module is deliberately read-only with respect to radio hardware.  It
summarizes evidence already produced by Dire Wolf and the listener service.
"""
from __future__ import annotations

import json
import re
import subprocess
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

_CALL_RE = re.compile(r"^(?:\[[^\]]+\]\s*)?([^>]+)>")
_CONFIDENCE_RE = re.compile(r"^\[([0-9]+(?:\.[0-9]+)?)\]")


def _epoch(value: str | None) -> float | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def packet_quality(records: list[dict], now: float | None = None) -> dict:
    """Return counts and decode evidence for locally recorded frames."""
    now = time.time() if now is None else now
    rf = [item for item in records if item.get("origin") == "rf"]
    internet = [item for item in records if item.get("origin") == "internet"]
    sources: list[str] = []
    confidence: list[float] = []
    for item in rf:
        frame = str(item.get("frame") or "")
        match = _CALL_RE.match(frame)
        if match:
            sources.append(match.group(1).upper())
        c = _CONFIDENCE_RE.match(frame)
        if c:
            confidence.append(float(c.group(1)))
    normalized = [re.sub(r"^\[[^\]]+\]\s*", "", str(i.get("frame") or "")) for i in rf]
    duplicates = len(normalized) - len(set(normalized))
    # Use an explicit key so packets sharing a timestamp do not cause Python
    # to compare the record dictionaries as a tie-breaker.
    last_rf = max(rf, key=lambda item: _epoch(item.get("timestamp_utc")) or 0, default=None)
    return {
        "window": "loaded listener history",
        "rf_frames": len(rf),
        "internet_frames": len(internet),
        "unique_stations": len(set(sources)),
        "stations": sorted(set(sources)),
        "duplicate_frames": max(0, duplicates),
        "duplicate_rate_percent": round((duplicates / len(normalized)) * 100, 1) if normalized else 0.0,
        "decode_confidence": {
            "samples": len(confidence),
            "average": round(sum(confidence) / len(confidence), 2) if confidence else None,
            "minimum": min(confidence) if confidence else None,
            "maximum": max(confidence) if confidence else None,
        },
        "last_rf_frame_utc": last_rf.get("timestamp_utc") if last_rf else None,
        "collected_at_utc": datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def aprs_is_health(records: list[dict], *, journal_lines: list[str] | None = None) -> dict:
    """Infer APRS-IS connection evidence without treating a beacon as RF."""
    lines = journal_lines or []
    joined = "\n".join(lines)
    connected = bool(re.search(r"Now connected to IGate server|logresp .* verified", joined, re.I))
    failures = len(re.findall(r"Connect to IGate server .* failed|connection .* failed", joined, re.I))
    reconnects = len(re.findall(r"Now connected to IGate server", joined, re.I))
    uploads = [i for i in records if i.get("origin") == "internet"]
    last_upload = uploads[-1].get("timestamp_utc") if uploads else None
    # A successfully recorded internet-origin frame is authoritative evidence
    # that Dire Wolf reached APRS-IS, even when the bounded journal excerpt no
    # longer contains the original connection banner.
    upload_evidence = bool(uploads)
    connected = connected or upload_evidence
    if failures and not connected:
        state = "fault"
    elif connected:
        state = "healthy"
    else:
        state = "unknown"
    server = None
    match = re.search(r"Now connected to IGate server\s+([^\s(]+)", joined, re.I)
    if match:
        server = match.group(1)
    if server is None and upload_evidence:
        server = "APRS-IS"
    return {"state": state, "connected": connected, "server": server,
            "reconnect_count": max(reconnects, 1 if upload_evidence else 0), "failed_connections": failures,
            "last_successful_upload_utc": last_upload,
            "authentication": "verified" if re.search(r"logresp .* verified", joined, re.I) else ("upload observed" if upload_evidence else "unknown")}


def update_rf_history(path: Path, records: list[dict], *, now: float | None = None, keep_hours: int = 168) -> dict:
    """Persist hourly RF counts; history is bounded and safe to regenerate."""
    now = time.time() if now is None else now
    try:
        existing = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        existing = {}
    buckets = existing if isinstance(existing, dict) else {}
    for item in records:
        if item.get("origin") != "rf":
            continue
        epoch = _epoch(item.get("timestamp_utc"))
        if epoch is None:
            continue
        key = datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%dT%H:00:00Z")
        bucket = buckets.setdefault(key, {"rf_frames": 0, "stations": [], "confidence_sum": 0.0, "confidence_samples": 0})
        bucket["rf_frames"] += 1
        match = _CALL_RE.match(str(item.get("frame") or ""))
        if match and match.group(1).upper() not in bucket["stations"]:
            bucket["stations"].append(match.group(1).upper())
        confidence = _CONFIDENCE_RE.match(str(item.get("frame") or ""))
        if confidence:
            bucket["confidence_sum"] += float(confidence.group(1))
            bucket["confidence_samples"] += 1
    cutoff = now - keep_hours * 3600
    result = {}
    for key, value in buckets.items():
        epoch = _epoch(key)
        if epoch is None or epoch < cutoff:
            continue
        result[key] = {**value, "stations": sorted(value.get("stations", [])),
                       "average_confidence": round(value["confidence_sum"] / value["confidence_samples"], 2) if value.get("confidence_samples") else None}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    ordered = sorted(result)
    latest = result[ordered[-1]] if ordered else {}
    recent = []
    for key in ordered:
        epoch = _epoch(key)
        if epoch is not None and epoch >= now - 24 * 3600:
            recent.append(result[key])
    stations = sorted({station for point in recent for station in point.get("stations", [])})
    return {
        "hours": ordered,
        "points": [result[k] | {"hour_utc": k} for k in ordered],
        "retention_hours": keep_hours,
        "coverage_hours": len(ordered),
        "last_24h_rf_frames": sum(point.get("rf_frames", 0) for point in recent),
        "last_24h_stations": len(stations),
        "last_24h_station_names": stations,
        "latest_hour_rf_frames": latest.get("rf_frames", 0),
        "latest_hour_average_confidence": latest.get("average_confidence"),
    }
