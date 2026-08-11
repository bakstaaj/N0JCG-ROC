#!/usr/bin/env python3
from __future__ import annotations

import grp
import json
import os
from pathlib import Path
import socket
import subprocess

try:
    from operator_activity import probe_rf_session
except ModuleNotFoundError:  # Repository test/runtime path before root-owned installation.
    from n0jcg_roc.operator_activity import probe_rf_session


SOCKET_PATH = Path("/run/n0jcg-operator-helper/control.sock")
MAINTENANCE_PATH = Path("/var/lib/n0jcg-roc/winlink-maintenance")
CMS_TEST = "/home/n0jcg/sdrdev/N0JCG-ROC/tools/test_linbpq_cms.py"
SERVICES = ("n0jcg-winlink-modem.service", "n0jcg-winlink-rms.service")
TRIAL_SERVICES = (
    "n0jcg-aprs-rx.service",
    "n0jcg-weather.service",
    "n0jcg-winlink-modem.service",
    "n0jcg-winlink-rms.service",
)


def run(command: list[str], timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=False, capture_output=True, text=True, timeout=timeout)


def service_states(services: tuple[str, ...] = SERVICES) -> dict:
    return {
        service: run(["systemctl", "is-active", service], timeout=5).stdout.strip() or "unknown"
        for service in services
    }


def perform(action: str) -> dict:
    if action == "restart":
        commands = [
            ["systemctl", "restart", "n0jcg-winlink-modem.service"],
            ["systemctl", "restart", "n0jcg-winlink-rms.service"],
        ]
        MAINTENANCE_PATH.unlink(missing_ok=True)
    elif action == "maintenance_on":
        commands = [
            ["systemctl", "stop", "n0jcg-winlink-rms.service"],
            ["systemctl", "stop", "n0jcg-winlink-modem.service"],
        ]
    elif action == "maintenance_off":
        commands = [
            ["systemctl", "start", "n0jcg-winlink-modem.service"],
            ["systemctl", "start", "n0jcg-winlink-rms.service"],
        ]
    elif action == "trial_services_stop":
        commands = [
            ["systemctl", "stop", "n0jcg-winlink-rms.service"],
            ["systemctl", "stop", "n0jcg-winlink-modem.service"],
            ["systemctl", "stop", "n0jcg-aprs-rx.service"],
            ["systemctl", "stop", "n0jcg-weather.service"],
        ]
    elif action == "trial_services_start":
        commands = [
            ["systemctl", "start", "n0jcg-aprs-rx.service"],
            ["systemctl", "start", "n0jcg-weather.service"],
            ["systemctl", "start", "n0jcg-winlink-modem.service"],
            ["systemctl", "start", "n0jcg-winlink-rms.service"],
        ]
    elif action == "cms_test":
        activity = probe_rf_session()
        if not activity["available"]:
            return {
                "ok": False,
                "action": action,
                "error": "CMS test blocked: unable to verify that the RF channel is idle",
                "rf_activity": activity,
                "services": service_states(),
            }
        if activity["active"]:
            return {
                "ok": False,
                "action": action,
                "error": "CMS test blocked: an RF session is active",
                "rf_activity": activity,
                "services": service_states(),
            }
        completed = run(["runuser", "-u", "n0jcg", "--", "/usr/bin/python3", CMS_TEST], timeout=30)
        return {
            "ok": completed.returncode == 0,
            "action": action,
            "message": "Authenticated CMS session established" if completed.returncode == 0 else "CMS connectivity test failed",
            "rf_activity": activity,
            "services": service_states(),
        }
    else:
        return {"ok": False, "error": "action not allowed"}

    for command in commands:
        completed = run(command)
        if completed.returncode != 0:
            services = TRIAL_SERVICES if action.startswith("trial_services_") else SERVICES
            return {"ok": False, "action": action, "error": "service operation failed", "services": service_states(services)}
    if action == "maintenance_on":
        MAINTENANCE_PATH.touch(mode=0o640, exist_ok=True)
    elif action == "maintenance_off":
        MAINTENANCE_PATH.unlink(missing_ok=True)
    services = TRIAL_SERVICES if action.startswith("trial_services_") else SERVICES
    return {"ok": True, "action": action, "services": service_states(services)}


def handle(connection: socket.socket) -> None:
    try:
        request = connection.recv(4096)
        payload = json.loads(request.split(b"\n", 1)[0].decode("utf-8"))
        response = perform(str(payload.get("action", "")))
    except (OSError, ValueError, TypeError, json.JSONDecodeError, subprocess.TimeoutExpired):
        response = {"ok": False, "error": "operator helper request failed"}
    connection.sendall((json.dumps(response, separators=(",", ":")) + "\n").encode("utf-8"))


def main() -> None:
    SOCKET_PATH.unlink(missing_ok=True)
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(SOCKET_PATH))
    os.chown(SOCKET_PATH, 0, grp.getgrnam("n0jcg").gr_gid)
    os.chmod(SOCKET_PATH, 0o660)
    server.listen(4)
    while True:
        connection, _ = server.accept()
        with connection:
            handle(connection)


if __name__ == "__main__":
    main()
