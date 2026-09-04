#!/usr/bin/env python3
"""Preserve per-frame receive timestamps when the system journal is unavailable."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys


FRAME = re.compile(r"^(?:\[[^\]]+\]\s*)?[A-Z0-9][A-Z0-9-]{1,8}>[^:]+:.+$", re.IGNORECASE)


def frame_origin(frame: str) -> str:
    if frame.startswith("[ig]") or re.search(r"(?:^|[>,])qA[A-Za-z0-9*,-]*", frame) or "TCPIP*" in frame:
        return "internet"
    return "rf"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--log", required=True)
    parser.add_argument("--records", required=True)
    args = parser.parse_args()
    log_path = Path(args.log)
    records_path = Path(args.records)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    records_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8", buffering=1) as log, records_path.open(
        "a", encoding="utf-8", buffering=1
    ) as records:
        # Dire Wolf may emit extended APRS text (for example a degree symbol)
        # using a locale-dependent byte. Decode defensively so one malformed
        # byte cannot terminate the receive pipeline.
        for raw_bytes in sys.stdin.buffer:
            raw = raw_bytes.decode("utf-8", errors="replace")
            line = raw.rstrip("\n")
            log.write(line + "\n")
            sys.stdout.write(raw)
            sys.stdout.flush()
            if FRAME.match(line.strip()):
                records.write(json.dumps({
                    "timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "frame": line.strip(),
                    "origin": frame_origin(line.strip()),
                }) + "\n")
                records.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
