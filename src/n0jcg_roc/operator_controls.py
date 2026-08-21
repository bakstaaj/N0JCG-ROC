from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
import hmac
import json
from pathlib import Path
import secrets
import socket
import threading
import time


SESSION_SECONDS = 30 * 60
PASSWORD_ITERATIONS = 600_000
ALLOWED_ACTIONS = {
    "restart", "rms_recover", "maintenance_on", "maintenance_off", "cms_test", "repair_service",
    "wifi_scan", "wifi_connect", "ethernet_status", "ethernet_set", "ethernet_confirm",
}
TRIAL_SERVICE_ACTIONS = {"trial_services_start", "trial_services_stop"}
_AUDIT_LOCK = threading.Lock()


def make_password_record(password: str, *, salt: bytes | None = None, iterations: int = PASSWORD_ITERATIONS) -> str:
    if len(password) < 10:
        raise ValueError("operator password must contain at least 10 characters")
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${digest.hex()}"


class OperatorAuth:
    def __init__(self, password_record: str = "", session_secret: str = "") -> None:
        self.password_record = password_record.strip()
        self.session_secret = session_secret.strip()

    @property
    def configured(self) -> bool:
        try:
            self._password_parts()
            return len(bytes.fromhex(self.session_secret)) >= 32
        except (ValueError, TypeError):
            return False

    def _password_parts(self) -> tuple[int, bytes, bytes]:
        algorithm, iterations, salt, digest = self.password_record.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            raise ValueError("unsupported password record")
        return int(iterations), bytes.fromhex(salt), bytes.fromhex(digest)

    def verify_password(self, password: str) -> bool:
        if not self.configured:
            return False
        try:
            iterations, salt, expected = self._password_parts()
            actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
            return hmac.compare_digest(actual, expected)
        except (ValueError, TypeError, UnicodeError):
            return False

    @staticmethod
    def _encode(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")

    @staticmethod
    def _decode(value: str) -> bytes:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))

    def issue_session(self, now: int | None = None) -> tuple[str, str, int]:
        issued = int(now if now is not None else time.time())
        csrf_token = secrets.token_urlsafe(24)
        payload = json.dumps(
            {"iat": issued, "exp": issued + SESSION_SECONDS, "csrf": csrf_token},
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        encoded = self._encode(payload)
        signature = hmac.new(bytes.fromhex(self.session_secret), encoded.encode("ascii"), hashlib.sha256).digest()
        return f"{encoded}.{self._encode(signature)}", csrf_token, SESSION_SECONDS

    def verify_session(self, token: str, *, csrf_token: str | None = None, now: int | None = None) -> dict | None:
        if not self.configured or not token:
            return None
        try:
            encoded, supplied_signature = token.split(".", 1)
            expected = hmac.new(bytes.fromhex(self.session_secret), encoded.encode("ascii"), hashlib.sha256).digest()
            if not hmac.compare_digest(self._decode(supplied_signature), expected):
                return None
            payload = json.loads(self._decode(encoded).decode("utf-8"))
            current = int(now if now is not None else time.time())
            if int(payload.get("exp", 0)) <= current:
                return None
            if csrf_token is not None and not hmac.compare_digest(str(payload.get("csrf", "")), csrf_token):
                return None
            return payload
        except (ValueError, TypeError, KeyError, json.JSONDecodeError, UnicodeError):
            return None


def session_cookie(headers) -> str:
    raw = headers.get("Cookie", "")
    for part in raw.split(";"):
        name, separator, value = part.strip().partition("=")
        if separator and name == "n0jcg_operator":
            return value
    return ""


def append_audit(path: Path, *, remote: str, event: str, result: str, detail: str = "") -> None:
    record = {
        "timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "remote": remote,
        "event": event,
        "result": result,
    }
    if detail:
        record["detail"] = detail[:160]
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with _AUDIT_LOCK, path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, separators=(",", ":")) + "\n")
    except OSError:
        pass


def recent_audit(path: Path, limit: int = 25) -> list[dict]:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]
    except OSError:
        return []
    records = []
    for line in lines:
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def _request_helper(action: str, socket_path: Path, timeout: float, parameters: dict | None = None) -> dict:
    if action not in ALLOWED_ACTIONS | TRIAL_SERVICE_ACTIONS:
        raise ValueError("operator action is not allowed")
    request = {"action": action}
    if parameters:
        request["parameters"] = parameters
    encoded = (json.dumps(request) + "\n").encode("utf-8")
    if len(encoded) > 4096:
        raise ValueError("operator helper request is too large")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(timeout)
        connection.connect(str(socket_path))
        connection.sendall(encoded)
        response = bytearray()
        while len(response) < 65536:
            chunk = connection.recv(4096)
            if not chunk:
                break
            response.extend(chunk)
            if b"\n" in chunk:
                break
    payload = json.loads(bytes(response).decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("invalid operator helper response")
    return payload


def request_helper(
    action: str,
    socket_path: Path,
    timeout: float = 35.0,
    parameters: dict | None = None,
) -> dict:
    if action not in ALLOWED_ACTIONS:
        raise ValueError("operator action is not allowed")
    return _request_helper(action, socket_path, timeout, parameters)


def set_trial_services_enabled(enabled: bool, socket_path: Path, timeout: float = 35.0) -> dict:
    action = "trial_services_start" if enabled else "trial_services_stop"
    return _request_helper(action, socket_path, timeout)
