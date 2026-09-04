#!/usr/bin/env python3
"""Compare captured APRS audio around decoded packets with quiet windows."""
from datetime import datetime
import math, re, sys, wave
from array import array
from pathlib import Path

root = Path(sys.argv[1])
timestamp_offset_seconds = float(sys.argv[2]) if len(sys.argv) > 2 else -0.8
phases = [root] if (root / "metadata.txt").exists() and root.name.startswith("phase-") else sorted(root.glob("phase-*"))
for phase in phases:
    meta = dict(x.split("=", 1) for x in (phase / "metadata.txt").read_text().splitlines() if "=" in x)
    start = datetime.fromisoformat(meta["started_utc"].replace("Z", "+00:00"))
    raw = bytearray()
    rate = 48000
    for path in sorted(phase.glob("audio-*.wav")):
        with wave.open(str(path), "rb") as stream:
            rate = stream.getframerate()
            raw.extend(stream.readframes(stream.getnframes()))
    samples = array("h")
    samples.frombytes(raw)
    near_clip = sum(abs(x) >= 32700 for x in samples)
    clip = sum(abs(x) >= 32767 for x in samples)

    def metrics(center, width=1.0):
        lo = max(0, int((center - width / 2) * rate))
        hi = min(len(samples), int((center + width / 2) * rate))
        window = samples[lo:hi]
        if len(window) == 0:
            return (0.0, 0.0)
        peak = max(abs(x) for x in window)
        return (float(peak), math.sqrt(sum(x * x for x in window) / len(window)))

    events = []
    for line in (phase / "service-journal.log").read_text(errors="replace").splitlines():
        if "] " not in line or ">" not in line:
            continue
        try:
            timestamp = datetime.fromisoformat(line.split()[0].replace("Z", "+00:00"))
        except ValueError:
            continue
        offset = (timestamp - start).total_seconds() + timestamp_offset_seconds
        if 0.5 <= offset < len(samples) / rate - 0.5 and (not events or offset - events[-1] > 0.25):
            events.append(offset)
    packet = [metrics(x) for x in events]
    quiet = [metrics(x) for x in range(1, int(len(samples) / rate) - 1) if all(abs(x - event) > 1 for event in events)]

    def summary(values):
        if not values:
            return "n=0"
        peaks = [x[0] for x in values]
        rms = [x[1] for x in values]
        return "n=%d peak_max=%.0f rms_median=%.0f rms_mean=%.0f rms_max=%.0f" % (
            len(values), max(peaks), sorted(rms)[len(rms) // 2], sum(rms) / len(rms), max(rms))

    print("%s samples=%d near_clip=%.4f%% hard_clip=%.4f%% decoded_events=%d" % (
        phase.name, len(samples), 100 * near_clip / len(samples), 100 * clip / len(samples), len(events)))
    print("  packet  ", summary(packet))
    print("  silence ", summary(quiet))
