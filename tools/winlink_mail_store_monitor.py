#!/usr/bin/env python3
"""Privacy-safe watcher for LinBPQ mailbox changes (CMS/RMS delivery)."""
from __future__ import annotations
import json
import os
from pathlib import Path
import time
from datetime import datetime, timezone

MAIL_DIR = Path(os.environ.get("WINLINK_MAIL_DIR", "/var/lib/n0jcg-winlink/Mail"))
LOG_PATH = Path(os.environ.get("WINLINK_APPLICATION_EVENT_LOG", "/var/lib/n0jcg-roc/winlink-application-events.jsonl"))
STATE_PATH = Path(os.environ.get("WINLINK_MAIL_STORE_STATE", "/var/lib/n0jcg-roc/winlink-mail-store-state.json"))
INTERVAL = max(1.0, float(os.environ.get("WINLINK_MAIL_MONITOR_INTERVAL", "5")))

def stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def snapshot() -> dict[str, int]:
    result = {}
    try:
        for path in MAIL_DIR.glob("m_*.mes"):
            try:
                result[path.name] = path.stat().st_size
            except OSError:
                continue
    except OSError:
        pass
    try:
        index = MAIL_DIR.parent / "DIRMES.SYS"
        stat = index.stat()
        result["__DIRMES.SYS__"] = stat.st_size ^ stat.st_mtime_ns
    except OSError:
        pass
    return result

def load_state() -> dict[str, int]:
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return {str(k): int(v) for k, v in data.items()} if isinstance(data, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}

def save_state(state: dict[str, int]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp = STATE_PATH.with_suffix(".tmp")
    temp.write_text(json.dumps(state, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(STATE_PATH)

def emit(change: str, count: int, size_bytes: int) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    record = {"timestamp_utc": stamp(), "event": "message_store_change", "source": "linbpq-mail-store", "change": change, "count": count, "size_bytes_total": size_bytes}
    with LOG_PATH.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, separators=(",", ":"), sort_keys=True) + "\n")

def main() -> int:
    previous = load_state()
    current = snapshot()
    if not previous:
        save_state(current)  # baseline existing mail; do not create false events
    while True:
        time.sleep(INTERVAL)
        current = snapshot()
        created = [(name, size) for name, size in current.items() if name not in previous]
        updated = [(name, size) for name, size in current.items() if name in previous and previous[name] != size]
        mail_created = [(name, size) for name, size in created if not name.startswith("__")]
        index_changed = "__DIRMES.SYS__" in updated or "__DIRMES.SYS__" in created
        if mail_created:
            emit("created", len(mail_created), sum(size for _, size in mail_created))
        if index_changed and not mail_created:
            emit("index_changed", 1, 0)
        if updated:
            emit("updated", len(updated), sum(size for _, size in updated))
        previous = current
        try:
            save_state(previous)
        except OSError:
            pass
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
