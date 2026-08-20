#!/usr/bin/env python3
from __future__ import annotations

import grp
import ipaddress
import json
import os
from pathlib import Path
import socket
import subprocess
import time

try:
    from operator_activity import probe_rf_session
except ModuleNotFoundError:  # Repository test/runtime path before root-owned installation.
    from n0jcg_roc.operator_activity import probe_rf_session


SOCKET_PATH = Path("/run/n0jcg-operator-helper/control.sock")
MAINTENANCE_PATH = Path("/var/lib/n0jcg-roc/winlink-maintenance")
CMS_TEST = "/home/n0jcg/sdrdev/N0JCG-ROC/tools/test_linbpq_cms.py"
WIFI_SCRIPT = "/home/n0jcg/sdrdev/N0JCG-ROC/tools/configure_wifi.sh"
ETHERNET_SCRIPT = "/home/n0jcg/sdrdev/N0JCG-ROC/tools/configure_ethernet.sh"
SERVICES = ("n0jcg-winlink-modem.service", "n0jcg-winlink-rms.service")
TRIAL_SERVICES = (
    "n0jcg-aprs-rx.service",
    "n0jcg-weather.service",
    "n0jcg-winlink-modem.service",
    "n0jcg-winlink-rms.service",
)


def run(command: list[str], timeout: int = 30, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
        input=input_text,
    )


def service_states(services: tuple[str, ...] = SERVICES) -> dict:
    return {
        service: run(["systemctl", "is-active", service], timeout=5).stdout.strip() or "unknown"
        for service in services
    }


def current_wifi() -> dict:
    completed = run(["/usr/sbin/iw", "dev", "wlp2s0", "link"], timeout=5)
    ssid = None
    signal_dbm = None
    for line in completed.stdout.splitlines():
        field = line.strip()
        if field.startswith("SSID: "):
            ssid = field.removeprefix("SSID: ")
        elif field.startswith("signal: "):
            try:
                signal_dbm = float(field.split()[1])
            except (ValueError, IndexError):
                pass
    address = run(["/usr/sbin/ip", "-brief", "-4", "address", "show", "dev", "wlp2s0"], timeout=5).stdout.split()
    return {"ssid": ssid, "signal_dbm": signal_dbm, "address": address[2] if len(address) >= 3 else None}


def wifi_parameters(payload: object) -> tuple[str, str]:
    if not isinstance(payload, dict):
        raise ValueError("Wi-Fi parameters are required")
    ssid = str(payload.get("ssid", ""))
    password = str(payload.get("password", ""))
    if not ssid or len(ssid.encode("utf-8")) > 32 or any(ord(character) < 32 for character in ssid):
        raise ValueError("SSID is invalid")
    if len(password.encode("utf-8")) > 64 or "\n" in password or "\r" in password or "\x00" in password:
        raise ValueError("Wi-Fi password is invalid")
    return ssid, password


def ethernet_parameters(payload: object) -> tuple[str, str, str, str]:
    if not isinstance(payload, dict):
        raise ValueError("Ethernet parameters are required")
    interface = str(payload.get("interface", ""))
    address_cidr = str(payload.get("address_cidr", ""))
    gateway = str(payload.get("gateway", ""))
    dns_values = [item.strip() for item in str(payload.get("dns", "")).split(",") if item.strip()]
    if not interface or len(interface) > 32 or not all(character.isalnum() or character in "_.:-" for character in interface):
        raise ValueError("Ethernet interface is invalid")
    address = ipaddress.IPv4Interface(address_cidr)
    gateway_address = ipaddress.IPv4Address(gateway)
    if gateway_address not in address.network or gateway_address in {
        address.ip, address.network.network_address, address.network.broadcast_address,
    }:
        raise ValueError("gateway must be a usable address in the static IP subnet")
    if not 1 <= len(dns_values) <= 4:
        raise ValueError("provide one to four IPv4 DNS servers")
    dns = ",".join(str(ipaddress.IPv4Address(value)) for value in dns_values)
    return interface, str(address), str(gateway_address), dns


def ethernet_result(action: str, arguments: list[str], timeout: int = 30) -> dict:
    completed = run(
        ["/usr/bin/env", "STATE_DIR=/run/n0jcg-operator-helper", ETHERNET_SCRIPT, *arguments],
        timeout=timeout,
    )
    try:
        status = json.loads(completed.stdout) if completed.returncode == 0 else None
    except json.JSONDecodeError:
        status = None
    if completed.returncode != 0 or not isinstance(status, dict):
        detail = (completed.stderr.strip().splitlines() or ["Ethernet operation failed"])[-1]
        return {"ok": False, "action": action, "error": detail.removeprefix("ERROR: ")[:200]}
    return {"ok": True, "action": action, "ethernet": status}


def perform(action: str, parameters: object = None) -> dict:
    if action == "rms_recover":
        activity = probe_rf_session()
        if not activity.get("available"):
            return {"ok": False, "action": action, "error": "RMS recovery blocked: RF activity state is unavailable", "rf_activity": activity}
        if activity.get("active"):
            return {"ok": False, "action": action, "error": "RMS recovery blocked: an RF session is active", "rf_activity": activity}
        stopped = run(["systemctl", "stop", "n0jcg-winlink-rms.service"], timeout=20)
        if stopped.returncode != 0:
            return {"ok": False, "action": action, "error": "RMS stop failed", "services": service_states()}
        time.sleep(5)
        started = run(["systemctl", "start", "n0jcg-winlink-rms.service"], timeout=20)
        if started.returncode != 0:
            return {"ok": False, "action": action, "error": "RMS start failed", "services": service_states()}
        return {"ok": True, "action": action, "message": "RMS session recovered; modem and RF configuration were left unchanged", "services": service_states()}
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
    elif action == "wifi_scan":
        completed = run(
            ["/usr/bin/env", "ROLLBACK_DIR=/run/n0jcg-operator-helper", WIFI_SCRIPT, "--scan-json"],
            timeout=20,
        )
        try:
            networks = json.loads(completed.stdout) if completed.returncode == 0 else []
        except json.JSONDecodeError:
            networks = []
        if completed.returncode != 0 or not isinstance(networks, list):
            detail = (completed.stderr.strip().splitlines() or ["Wi-Fi scan failed"])[-1]
            return {"ok": False, "action": action, "error": detail[:200]}
        return {"ok": True, "action": action, "networks": networks, "current": current_wifi()}
    elif action == "wifi_connect":
        try:
            ssid, password = wifi_parameters(parameters)
        except ValueError as error:
            return {"ok": False, "action": action, "error": str(error)}
        completed = run(
            ["/usr/bin/env", "ROLLBACK_DIR=/run/n0jcg-operator-helper", WIFI_SCRIPT, "--connect", ssid],
            timeout=75,
            input_text=password + "\n",
        )
        if completed.returncode != 0:
            detail = (completed.stderr.strip().splitlines() or ["Wi-Fi connection failed and was rolled back"])[-1]
            return {"ok": False, "action": action, "error": detail[:200], "current": current_wifi()}
        return {
            "ok": True,
            "action": action,
            "message": f"Connected Wi-Fi to {ssid}",
            "current": current_wifi(),
        }
    elif action == "ethernet_status":
        return ethernet_result(action, ["--status-json"])
    elif action == "ethernet_set":
        try:
            interface, address_cidr, gateway, dns = ethernet_parameters(parameters)
        except (ValueError, ipaddress.AddressValueError, ipaddress.NetmaskValueError) as error:
            return {"ok": False, "action": action, "error": str(error)}
        result = ethernet_result(
            action,
            ["--set", interface, address_cidr, gateway, dns],
            timeout=60,
        )
        if result.get("ok"):
            result["message"] = "Static Ethernet address applied; confirm it within 3 minutes"
        return result
    elif action == "ethernet_confirm":
        result = ethernet_result(action, ["--confirm"])
        if result.get("ok"):
            result["message"] = "Static Ethernet address confirmed"
        return result
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
        response = perform(str(payload.get("action", "")), payload.get("parameters"))
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
