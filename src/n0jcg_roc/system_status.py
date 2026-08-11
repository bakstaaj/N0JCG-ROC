from __future__ import annotations

import os
from pathlib import Path
import platform
import shutil
import socket
import sys
import threading


REQUIRED_TOOLS = (
    "aplay",
    "arecord",
    "axcall",
    "curl",
    "direwolf",
    "git",
    "jq",
    "make",
    "python3",
    "rsync",
    "rtl_eeprom",
    "rtl_test",
    "socat",
    "sox",
)

RTL_USB_IDS = {
    ("0bda", "2832"),
    ("0bda", "2838"),
}

_CPU_SAMPLE_LOCK = threading.Lock()
_CPU_SAMPLE: tuple[int, int] | None = None


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return None


def _uptime_seconds() -> int | None:
    raw = _read_text(Path("/proc/uptime"))
    if raw is None:
        return None
    try:
        return int(float(raw.split()[0]))
    except (ValueError, IndexError):
        return None


def _memory_status() -> dict[str, int | float | None]:
    values: dict[str, int] = {}
    raw = _read_text(Path("/proc/meminfo"))
    if raw:
        for line in raw.splitlines():
            name, separator, remainder = line.partition(":")
            if not separator:
                continue
            fields = remainder.split()
            if fields and fields[0].isdigit():
                values[name] = int(fields[0]) * 1024
    total = values.get("MemTotal")
    available = values.get("MemAvailable")
    used = total - available if total is not None and available is not None else None
    used_percent = round(used / total * 100, 1) if used is not None and total else None
    return {"total_bytes": total, "available_bytes": available, "used_bytes": used, "used_percent": used_percent}


def _cpu_status(load_1m: float | None) -> dict[str, int | float | None]:
    global _CPU_SAMPLE
    utilization = None
    raw = _read_text(Path("/proc/stat"))
    if raw:
        fields = raw.splitlines()[0].split()
        try:
            values = [int(value) for value in fields[1:]]
            idle = values[3] + (values[4] if len(values) > 4 else 0)
            total = sum(values)
            with _CPU_SAMPLE_LOCK:
                previous = _CPU_SAMPLE
                _CPU_SAMPLE = (idle, total)
            if previous and total > previous[1]:
                idle_delta = idle - previous[0]
                total_delta = total - previous[1]
                utilization = round(max(0.0, min(100.0, (1 - idle_delta / total_delta) * 100)), 1)
        except (ValueError, IndexError, ZeroDivisionError):
            pass
    processors = os.cpu_count() or 1
    if utilization is None and load_1m is not None:
        utilization = round(max(0.0, min(100.0, load_1m / processors * 100)), 1)
    return {"utilization_percent": utilization, "logical_processors": processors, "load_1m": load_1m}


def _temperature_status() -> dict[str, str | float | None]:
    candidates: list[tuple[int, str, float]] = []
    for zone in Path("/sys/class/thermal").glob("thermal_zone*"):
        raw = _read_text(zone / "temp")
        if raw is None:
            continue
        try:
            celsius = float(raw) / 1000
        except ValueError:
            continue
        source = _read_text(zone / "type") or zone.name
        priority = 0 if any(word in source.lower() for word in ("cpu", "package", "x86_pkg")) else 1
        if -20 <= celsius <= 150:
            candidates.append((priority, source, celsius))
    for sensor in Path("/sys/class/hwmon").glob("hwmon*/temp*_input"):
        raw = _read_text(sensor)
        if raw is None:
            continue
        try:
            celsius = float(raw) / 1000
        except ValueError:
            continue
        label = _read_text(sensor.with_name(sensor.name.replace("_input", "_label")))
        source = label or sensor.parent.name
        priority = 0 if any(word in source.lower() for word in ("cpu", "package", "core")) else 2
        if -20 <= celsius <= 150:
            candidates.append((priority, source, celsius))
    if not candidates:
        return {"celsius": None, "source": None}
    _, source, celsius = sorted(candidates, key=lambda item: (item[0], -item[2]))[0]
    return {"celsius": round(celsius, 1), "source": source}


def _disk_status() -> dict[str, int]:
    root = Path(os.path.abspath(os.sep))
    usage = shutil.disk_usage(root)
    return {
        "total_bytes": usage.total,
        "used_bytes": usage.used,
        "free_bytes": usage.free,
    }


def _tool_status() -> dict:
    commands = {command: shutil.which(command) for command in REQUIRED_TOOLS}
    missing = [command for command, path in commands.items() if path is None]
    return {
        "ready": not missing,
        "commands": commands,
        "missing": missing,
    }


def _serial_devices() -> list[str]:
    serial_root = Path("/dev/serial/by-id")
    try:
        return sorted(item.name for item in serial_root.iterdir() if item.is_symlink())
    except OSError:
        return []


def _alsa_cards() -> list[str]:
    raw = _read_text(Path("/proc/asound/cards"))
    if not raw or raw.startswith("--- no soundcards"):
        return []
    cards = []
    for line in raw.splitlines():
        stripped = line.strip()
        if stripped and stripped[0].isdigit() and "[" in stripped:
            cards.append(stripped)
    return cards


def _rtl_sdr_count() -> int:
    usb_root = Path("/sys/bus/usb/devices")
    try:
        devices = list(usb_root.iterdir())
    except OSError:
        return 0
    count = 0
    for device in devices:
        vendor = _read_text(device / "idVendor")
        product = _read_text(device / "idProduct")
        if (vendor, product) in RTL_USB_IDS:
            count += 1
    return count


def collect_system_status() -> dict:
    try:
        load_1m = round(os.getloadavg()[0], 2)
    except (AttributeError, OSError):
        load_1m = None

    serial_devices = _serial_devices()
    alsa_cards = _alsa_cards()
    usb_audio_cards = [card for card in alsa_cards if "usb" in card.lower()]
    rtl_sdr_count = _rtl_sdr_count()
    hardware_present = bool(serial_devices or usb_audio_cards or rtl_sdr_count)

    return {
        "host": {
            "hostname": socket.gethostname(),
            "operating_system": platform.system(),
            "kernel": platform.release(),
            "architecture": platform.machine(),
            "python": platform.python_version(),
        },
        "resources": {
            "uptime_seconds": _uptime_seconds(),
            "load_1m": load_1m,
            "cpu": _cpu_status(load_1m),
            "temperature": _temperature_status(),
            "memory": _memory_status(),
            "disk": _disk_status(),
        },
        "tooling": _tool_status(),
        "hardware": {
            "state": "devices-present" if hardware_present else "bare-server",
            "serial_by_id": serial_devices,
            "alsa_cards": alsa_cards,
            "usb_audio_cards": usb_audio_cards,
            "rtl_sdr_count": rtl_sdr_count,
        },
        "process": {
            "pid": os.getpid(),
            "executable": sys.executable,
        },
    }
