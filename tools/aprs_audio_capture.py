#!/usr/bin/env python3
"""Forward APRS audio while retaining a bounded rolling WAV capture."""

from __future__ import annotations

import argparse
import sys
import time
import wave
from collections import deque
from pathlib import Path


def write_wav(path: Path, chunks: deque[bytes], sample_rate: int) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with wave.open(str(temporary), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(b"".join(chunks))
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seconds", type=float, default=60.0)
    parser.add_argument("--sample-rate", type=int, default=48000)
    args = parser.parse_args()
    max_bytes = max(1, int(args.seconds * args.sample_rate * 2))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    chunks: deque[bytes] = deque()
    buffered = 0
    next_write = time.monotonic()
    while True:
        chunk = sys.stdin.buffer.read(4096)
        if not chunk:
            break
        sys.stdout.buffer.write(chunk)
        sys.stdout.buffer.flush()
        chunks.append(chunk)
        buffered += len(chunk)
        while buffered > max_bytes and chunks:
            buffered -= len(chunks.popleft())
        if time.monotonic() >= next_write:
            write_wav(args.output, chunks, args.sample_rate)
            next_write = time.monotonic() + 1.0
    if chunks:
        write_wav(args.output, chunks, args.sample_rate)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
