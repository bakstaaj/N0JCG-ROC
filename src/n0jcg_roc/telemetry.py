from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import os
from pathlib import Path
import sqlite3
from threading import Lock
import time
from typing import Any


DEFAULT_TELEMETRY_PATH = Path(
    os.environ.get("ROC_TELEMETRY_DB", "/var/lib/n0jcg-roc/telemetry.sqlite3")
)
METRICS = (
    "cpu", "memory", "temperature", "aprsFrames", "aircraft", "voiceCalls", "vhfLocks", "uhfLocks",
    "weatherTemperature", "weatherHumidity", "weatherPressure", "weatherWind", "weatherRain",
    "weatherSolar", "weatherLightning",
)
MIN_SAMPLE_INTERVAL_MS = 25_000
DISPLAY_POINT_LIMIT = 600
_LOCK = Lock()


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=5)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS telemetry_samples (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp INTEGER NOT NULL,
            cpu REAL,
            memory REAL,
            temperature REAL,
            aprsFrames REAL,
            aircraft REAL,
            voiceCalls REAL,
            vhfLocks REAL,
            uhfLocks REAL,
            weatherTemperature REAL,
            weatherHumidity REAL,
            weatherPressure REAL,
            weatherWind REAL,
            weatherRain REAL,
            weatherSolar REAL,
            weatherLightning REAL
        )
        """
    )
    existing_columns = {row[1] for row in connection.execute("PRAGMA table_info(telemetry_samples)").fetchall()}
    for metric in METRICS:
        if metric not in existing_columns:
            connection.execute(f"ALTER TABLE telemetry_samples ADD COLUMN {metric} REAL")
    connection.execute("CREATE INDEX IF NOT EXISTS telemetry_timestamp_idx ON telemetry_samples(timestamp)")
    return connection


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    number = float(value)
    if not (-1_000_000_000 <= number <= 1_000_000_000):
        raise ValueError("telemetry value is outside the supported range")
    return number


def _point(row: sqlite3.Row) -> dict[str, int | float | None]:
    point: dict[str, int | float | None] = {"timestamp": int(row["timestamp"])}
    for metric in METRICS:
        point[metric] = row[metric]
    return point


def read_telemetry(path: Path = DEFAULT_TELEMETRY_PATH, *, display_limit: int = DISPLAY_POINT_LIMIT) -> dict:
    display_limit = max(10, min(5000, int(display_limit)))
    with _LOCK, closing(_connect(path)) as connection:
        with connection:
            connection.row_factory = sqlite3.Row
            count, first_timestamp, last_timestamp = connection.execute(
                "SELECT COUNT(*), MIN(timestamp), MAX(timestamp) FROM telemetry_samples"
            ).fetchone()
            if count <= display_limit:
                rows = connection.execute("SELECT * FROM telemetry_samples ORDER BY id").fetchall()
            else:
                stride = max(1, count // (display_limit - 1))
                rows = connection.execute(
                    """
                    SELECT * FROM telemetry_samples
                    WHERE id = (SELECT MIN(id) FROM telemetry_samples)
                       OR id = (SELECT MAX(id) FROM telemetry_samples)
                       OR id % ? = 0
                    ORDER BY id
                    """,
                    (stride,),
                ).fetchall()
                if len(rows) > display_limit:
                    rows = rows[-display_limit:]
        return {
            "persistent": True,
            "sample_count": int(count),
            "first_sample_utc": _utc_from_ms(first_timestamp),
            "last_sample_utc": _utc_from_ms(last_timestamp),
            "points": [_point(row) for row in rows],
        }


def record_telemetry(payload: object, path: Path = DEFAULT_TELEMETRY_PATH) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("telemetry sample must be a JSON object")
    timestamp = payload.get("timestamp", int(time.time() * 1000))
    if isinstance(timestamp, bool):
        raise ValueError("telemetry timestamp is invalid")
    timestamp = int(timestamp)
    now_ms = int(time.time() * 1000)
    if timestamp < 0 or abs(timestamp - now_ms) > 300_000:
        raise ValueError("telemetry timestamp is outside the accepted clock window")
    values = [_number(payload.get(metric)) for metric in METRICS]
    with _LOCK, closing(_connect(path)) as connection:
        with connection:
            last = connection.execute("SELECT MAX(timestamp) FROM telemetry_samples").fetchone()[0]
            if last is None or timestamp - int(last) >= MIN_SAMPLE_INTERVAL_MS:
                columns = ", ".join(("timestamp", *METRICS))
                placeholders = ", ".join("?" for _ in range(len(METRICS) + 1))
                connection.execute(
                    f"INSERT INTO telemetry_samples ({columns}) VALUES ({placeholders})",
                    (timestamp, *values),
                )
    return read_telemetry(path)


def reset_telemetry(path: Path = DEFAULT_TELEMETRY_PATH) -> dict:
    with _LOCK, closing(_connect(path)) as connection:
        with connection:
            deleted = int(connection.execute("SELECT COUNT(*) FROM telemetry_samples").fetchone()[0])
            connection.execute("DELETE FROM telemetry_samples")
            connection.execute("DELETE FROM sqlite_sequence WHERE name = 'telemetry_samples'")
    return {"ok": True, "deleted_samples": deleted, "points": [], "sample_count": 0, "persistent": True}


def _utc_from_ms(value: int | None) -> str | None:
    if value is None:
        return None
    return datetime.fromtimestamp(int(value) / 1000, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
