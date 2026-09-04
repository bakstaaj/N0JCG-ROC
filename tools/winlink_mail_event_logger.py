#!/usr/bin/env python3
"""Record privacy-safe LinBPQ application mail events.

LinBPQ invokes executables named MailNewMsg and MailMsgRead from its working
directory when application event reporting is enabled.  Event arguments can
contain message metadata or user supplied text, so this logger deliberately
records only the event name, timestamp, argument count, and a numeric message
identifier when the first argument is unambiguously numeric.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from datetime import datetime, timezone


DEFAULT_LOG_PATH = Path("/var/lib/n0jcg-roc/winlink-application-events.jsonl")
EVENT_NAMES = {
    "mailnewmsg": "message_new",
    "mailmsgread": "message_read",
}


def event_record(argv: list[str], *, now: datetime | None = None) -> dict:
    name = Path(argv[0] if argv else "").name.lower()
    event_type = EVENT_NAMES.get(name, "application_event")
    record = {
        "timestamp_utc": (now or datetime.now(timezone.utc)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "event": event_type,
        "source": "linbpq",
        "argument_count": max(0, len(argv) - 1),
    }
    if len(argv) > 1 and argv[1].isdigit():
        record["message_id"] = int(argv[1])
    return record


def append_record(record: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, separators=(",", ":"), sort_keys=True) + "\n")


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv if argv is None else argv)
    path = Path(os.environ.get("WINLINK_APPLICATION_EVENT_LOG", str(DEFAULT_LOG_PATH)))
    try:
        append_record(event_record(args), path)
    except OSError:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
