#!/usr/bin/env python3
"""Inspect a captured 48 kHz mono APRS audio WAV for AFSK activity."""
import cmath
import math
import struct
import sys
import wave


def tone_mag(samples, frequency, sample_rate):
    return abs(sum(
        value * cmath.exp(-2j * math.pi * frequency * index / sample_rate)
        for index, value in enumerate(samples)
    )) / len(samples)


def main(path):
    with wave.open(path, "rb") as source:
        if source.getnchannels() != 1 or source.getsampwidth() != 2:
            raise SystemExit("expected mono 16-bit PCM WAV")
        rate = source.getframerate()
        samples = struct.unpack("<%dh" % source.getnframes(), source.readframes(source.getnframes()))

    window = int(rate * 0.02)
    rows = []
    for offset in range(0, len(samples) - window, window):
        block = samples[offset : offset + window]
        rms = math.sqrt(sum(value * value for value in block) / window)
        rows.append((offset / rate, rms, offset))

    active = [row for row in rows if row[1] > 6800]
    print("sample_rate=%d duration=%.2fs active_windows=%d" % (rate, len(samples) / rate, len(active)))
    for time, rms, offset in active:
        block = samples[offset : offset + window]
        low = tone_mag(block, 1200, rate)
        high = tone_mag(block, 2200, rate)
        print("t=%7.2f rms=%6.0f 1200=%6.0f 2200=%6.0f dominant=%s" % (
            time, rms, low, high, "1200" if low >= high else "2200"
        ))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: analyze_aprs_rf.py capture.wav")
    main(sys.argv[1])
