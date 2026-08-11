"""Signed N0JCG Gateway registration and manual five-minute trial state."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Mapping


LICENSE_API_URL = "https://www.n0jcg.com/api/v1/licenses/validate"
LICENSE_PATTERN = re.compile(r"^N0JCG-[A-Z0-9]{3}(?:-[A-Z2-9]{4}){4}$")
EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
PUBLIC_KEYS = {
    "n0jcg-license-rsa-2026-01": {
        "exponent": 65537,
        "modulus_hex": (
            "D32C74548CC99C5F8955E5EFABD02BEF79C5B7D937B7EB8265AABB0EFAA2D907"
            "C5EF3C23E7BD68EE54505F57A98E6C451AA2E1EDEFBBCB8BA6BC18DF71BDC6083"
            "A3305CC180380B29A3D5C5A129762FB548629433C2E576BA1FD8F5FA5413758853"
            "ECD22D5D842A6AA43A4151BD9FF526135874EAFF2168B739CB3B5164534837766D"
            "EB99252D83077AAE70FAAD10B47D24E93E8C3DEF1E237E6A0EC86772669E68C7E"
            "B32DD873CF3024B71AAE132AAC70AF505C8D3D32BA79B3B6706C959508DD39AC59"
            "34EF5353236FFA8DF9DB2327F9B4137EFB6A664B7E922742948AF5D499C5C30C69"
            "033F4CF3132E8327874E6DE3C8316F1BBCAD334A443A326EDA22A5"
        ),
    },
}
_SHA256_DIGEST_INFO_PREFIX = bytes.fromhex("3031300d060960864801650304020105000420")


class LicenseError(RuntimeError):
    """Raised when registration input or a signed lease is invalid."""


def installation_serial_from_identity(identity: str) -> str:
    clean = str(identity or "").strip() or "unknown-installation"
    digest = hashlib.sha256(f"N0JCG-INSTALLATION\0{clean}".encode("utf-8")).hexdigest()
    return "N0JCG-" + "-".join(digest[index:index + 4].upper() for index in range(0, 16, 4))


def installation_serial(environment: Mapping[str, str] | None = None) -> str:
    values = os.environ if environment is None else environment
    identity = str(values.get("N0JCG_INSTALLATION_ID", "")).strip()
    if not identity:
        try:
            identity = Path("/etc/machine-id").read_text(encoding="utf-8").strip()
        except OSError:
            identity = ""
    return installation_serial_from_identity(identity)


def canonical_lease_json(lease: Mapping[str, Any]) -> bytes:
    canonical = {
        key: lease.get(key)
        for key in (
            "version", "key_id", "license_id", "license_suffix", "product_slug",
            "installation_serial", "email_hash", "issued_at", "expires_at", "grace_until",
        )
    }
    return json.dumps(canonical, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _b64url_decode(value: str) -> bytes:
    raw = str(value or "").replace("-", "+").replace("_", "/")
    return base64.b64decode(raw + "=" * (-len(raw) % 4), validate=True)


def verify_rsa_sha256_signature(message: bytes, signature: bytes, *, modulus_hex: str, exponent: int) -> bool:
    modulus = int(modulus_hex, 16)
    width = (modulus.bit_length() + 7) // 8
    if len(signature) != width:
        return False
    encoded = pow(int.from_bytes(signature, "big"), int(exponent), modulus).to_bytes(width, "big")
    digest_info = _SHA256_DIGEST_INFO_PREFIX + hashlib.sha256(message).digest()
    padding_length = width - len(digest_info) - 3
    if padding_length < 8:
        return False
    expected = b"\x00\x01" + (b"\xff" * padding_length) + b"\x00" + digest_info
    return hmac.compare_digest(encoded, expected)


class LicenseClient:
    """Validate, cache, and refresh one signed N0JCG Gateway license."""

    def __init__(
        self,
        *,
        app_version: str,
        state_root: Path,
        environment: Mapping[str, str] | None = None,
        opener: Callable[..., Any] = urllib.request.urlopen,
        now: Callable[[], float] = time.time,
    ) -> None:
        self.product_slug = "gateway"
        self.app_version = str(app_version).strip()
        self.state_root = Path(state_root)
        self.environment = os.environ if environment is None else environment
        self.api_url = LICENSE_API_URL
        self.credentials_path = self.state_root / "license_credentials.json"
        self.lease_path = self.state_root / "license_lease.json"
        self._opener = opener
        self._now = now
        self._lock = threading.RLock()
        self._last_validation_error = ""
        self._last_validation_epoch: float | None = None
        self._stop_event = threading.Event()
        self._refresh_thread: threading.Thread | None = None

    @property
    def serial_number(self) -> str:
        return installation_serial(self.environment)

    @staticmethod
    def _normalize_credentials(license_serial: str, email: str) -> dict[str, str]:
        normalized_license = str(license_serial or "").strip().upper()
        normalized_email = str(email or "").strip().lower()
        if not LICENSE_PATTERN.fullmatch(normalized_license):
            raise LicenseError("license S/N format is invalid")
        if len(normalized_email) > 254 or not EMAIL_PATTERN.fullmatch(normalized_email):
            raise LicenseError("email address is invalid")
        return {"license_serial": normalized_license, "email": normalized_email}

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _write_private_json(path: Path, value: Mapping[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        temporary.write_text(json.dumps(dict(value), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        try:
            temporary.chmod(0o600)
        except OSError:
            pass
        os.replace(temporary, path)
        try:
            path.chmod(0o600)
        except OSError:
            pass

    def _verify_response(self, response: Mapping[str, Any], email: str) -> dict[str, Any]:
        lease = response.get("lease")
        signature_text = str(response.get("signature") or "")
        if not isinstance(lease, dict) or not signature_text:
            raise LicenseError("validation response did not contain a signed lease")
        key = PUBLIC_KEYS.get(str(lease.get("key_id") or ""))
        if not key:
            raise LicenseError("unknown license signing key")
        try:
            valid = verify_rsa_sha256_signature(
                canonical_lease_json(lease),
                _b64url_decode(signature_text),
                modulus_hex=str(key["modulus_hex"]),
                exponent=int(key["exponent"]),
            )
        except Exception as exc:
            raise LicenseError("license lease signature is invalid") from exc
        if not valid:
            raise LicenseError("license lease signature is invalid")
        if lease.get("product_slug") != self.product_slug:
            raise LicenseError("license lease is for a different product")
        if lease.get("installation_serial") != self.serial_number:
            raise LicenseError("license lease is for a different installation")
        expected_email_hash = hashlib.sha256(email.encode("utf-8")).hexdigest()
        if lease.get("email_hash") != expected_email_hash:
            raise LicenseError("license lease email binding does not match")
        return dict(lease)

    def _request_validation(self, credentials: Mapping[str, str]) -> dict[str, Any]:
        request = urllib.request.Request(
            self.api_url,
            data=json.dumps({
                **credentials,
                "installation_serial": self.serial_number,
                "product_slug": self.product_slug,
                "app_version": self.app_version,
            }).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": f"N0JCG-Gateway/{self.app_version}",
            },
            method="POST",
        )
        try:
            response = self._opener(request, timeout=10)
            body = response.read()
        except urllib.error.HTTPError as exc:
            body = exc.read()
            try:
                error_payload = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                error_payload = {}
            reason = str(error_payload.get("error") or error_payload.get("reason") or f"HTTP {exc.code}")
            if exc.code not in (400, 401, 403):
                raise ConnectionError(f"license server unavailable: {reason}") from exc
            raise LicenseError(reason) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ConnectionError(f"license server unavailable: {exc}") from exc
        try:
            result = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ConnectionError("license server returned invalid JSON") from exc
        if not isinstance(result, dict) or not result.get("valid"):
            raise LicenseError(str(result.get("error") or "license was rejected"))
        return result

    def activate(self, license_serial: str, email: str) -> dict[str, Any]:
        credentials = self._normalize_credentials(license_serial, email)
        response = self._request_validation(credentials)
        lease = self._verify_response(response, credentials["email"])
        with self._lock:
            self._write_private_json(self.credentials_path, credentials)
            self._write_private_json(self.lease_path, {"lease": lease, "signature": response["signature"]})
            self._last_validation_error = ""
            self._last_validation_epoch = self._now()
        return self.status()

    def refresh(self) -> dict[str, Any]:
        credentials = self._read_json(self.credentials_path)
        if not credentials:
            return self.status()
        try:
            normalized = self._normalize_credentials(
                str(credentials.get("license_serial") or ""),
                str(credentials.get("email") or ""),
            )
            response = self._request_validation(normalized)
            lease = self._verify_response(response, normalized["email"])
        except ConnectionError as exc:
            with self._lock:
                self._last_validation_error = str(exc)
                self._last_validation_epoch = self._now()
            return self.status()
        except LicenseError as exc:
            with self._lock:
                self._last_validation_error = str(exc)
                self._last_validation_epoch = self._now()
                self.lease_path.unlink(missing_ok=True)
            return self.status()
        with self._lock:
            self._write_private_json(self.lease_path, {"lease": lease, "signature": response["signature"]})
            self._last_validation_error = ""
            self._last_validation_epoch = self._now()
        return self.status()

    def status(self) -> dict[str, Any]:
        now = int(self._now())
        credentials = self._read_json(self.credentials_path)
        cached = self._read_json(self.lease_path)
        lease = cached.get("lease") if isinstance(cached.get("lease"), dict) else {}
        signature = str(cached.get("signature") or "")
        verified = False
        if lease and signature and credentials:
            try:
                normalized = self._normalize_credentials(
                    str(credentials.get("license_serial") or ""),
                    str(credentials.get("email") or ""),
                )
                self._verify_response({"lease": lease, "signature": signature}, normalized["email"])
                verified = True
            except LicenseError:
                verified = False
        expires_at = int(lease.get("expires_at") or 0) if verified else 0
        grace_until = int(lease.get("grace_until") or 0) if verified else 0
        registered = verified and now <= grace_until
        return {
            "serial_number": self.serial_number,
            "registered": registered,
            "mode": "registered" if registered else "trial",
            "license_configured": bool(credentials),
            "license_suffix": str(lease.get("license_suffix") or "") if verified else "",
            "online_valid": registered and now <= expires_at,
            "offline_grace": registered and now > expires_at,
            "lease_expires_epoch": expires_at or None,
            "grace_until_epoch": grace_until or None,
            "last_validation_epoch": self._last_validation_epoch,
            "validation_error": self._last_validation_error or None,
        }

    def start_background_refresh(self, interval_seconds: int = 24 * 60 * 60) -> None:
        if self._refresh_thread and self._refresh_thread.is_alive():
            return

        def worker() -> None:
            self.refresh()
            while not self._stop_event.wait(max(300, int(interval_seconds))):
                self.refresh()

        self._refresh_thread = threading.Thread(
            target=worker,
            name="n0jcg-license-gateway",
            daemon=True,
        )
        self._refresh_thread.start()

    def close(self) -> None:
        self._stop_event.set()


class RocTrialController:
    """Track the manually restartable display trial without stopping ROC services."""

    def __init__(
        self,
        client: LicenseClient,
        *,
        trial_seconds: int = 300,
        now: Callable[[], float] = time.time,
        start_background_refresh: bool = True,
        service_access_changed: Callable[[bool], None] | None = None,
        start_trial_monitor: bool | None = None,
    ) -> None:
        self.client = client
        self.trial_seconds = max(1, int(trial_seconds))
        self._now = now
        self._lock = threading.RLock()
        self._started_epoch: float | None = None
        self._deadline_epoch: float | None = None
        self._expired = False
        self._service_access_changed = service_access_changed
        self._last_notified_access: bool | None = None
        self._monitor_stop = threading.Event()
        self._monitor_thread: threading.Thread | None = None
        if start_background_refresh:
            self.client.start_background_refresh()
        self.status()
        if start_trial_monitor if start_trial_monitor is not None else start_background_refresh:
            self._monitor_thread = threading.Thread(
                target=self._monitor_trial,
                name="n0jcg-gateway-trial",
                daemon=True,
            )
            self._monitor_thread.start()

    def _monitor_trial(self) -> None:
        while not self._monitor_stop.wait(1.0):
            self.status()

    def _notify_service_access_locked(self, registration: Mapping[str, Any]) -> None:
        allowed = bool(registration.get("data_updates_allowed"))
        if self._service_access_changed is None or allowed == self._last_notified_access:
            return
        try:
            self._service_access_changed(allowed)
        except (OSError, ValueError, RuntimeError) as error:
            print(f"Gateway trial service control failed: {error}")
            return
        self._last_notified_access = allowed

    def _clear_trial_locked(self) -> None:
        self._started_epoch = None
        self._deadline_epoch = None
        self._expired = False

    def _status_locked(self, *, start_trial: bool) -> dict[str, Any]:
        registration = dict(self.client.status())
        if registration.get("registered"):
            self._clear_trial_locked()
        elif start_trial and self._deadline_epoch is None and not self._expired:
            self._started_epoch = self._now()
            self._deadline_epoch = self._started_epoch + self.trial_seconds
        if self._deadline_epoch is not None and self._now() >= self._deadline_epoch:
            self._expired = True
        remaining = None
        if self._deadline_epoch is not None:
            remaining = 0 if self._expired else max(0, int(self._deadline_epoch - self._now() + 0.999))
        registration.update({
            "trial_limit_seconds": None if registration.get("registered") else self.trial_seconds,
            "trial_active": bool(not registration.get("registered") and self._deadline_epoch is not None and not self._expired),
            "trial_started_epoch": self._started_epoch,
            "trial_expires_epoch": self._deadline_epoch,
            "trial_remaining_seconds": remaining,
            "trial_expired": bool(not registration.get("registered") and self._expired),
            "data_updates_allowed": bool(registration.get("registered") or not self._expired),
        })
        self._notify_service_access_locked(registration)
        return registration

    def status(self, *, start_trial: bool = True) -> dict[str, Any]:
        with self._lock:
            return self._status_locked(start_trial=start_trial)

    def activate(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        self.client.activate(str(payload.get("license_serial") or ""), str(payload.get("email") or ""))
        with self._lock:
            self._clear_trial_locked()
            return self._status_locked(start_trial=False)

    def reset_trial(self) -> dict[str, Any]:
        with self._lock:
            current = self._status_locked(start_trial=False)
            if current.get("registered"):
                raise LicenseError("registered systems do not use trial resets")
            if not current.get("trial_expired"):
                raise LicenseError("the free trial can only be restarted after it expires")
            self._started_epoch = self._now()
            self._deadline_epoch = self._started_epoch + self.trial_seconds
            self._expired = False
            return self._status_locked(start_trial=False)

    def close(self) -> None:
        self._monitor_stop.set()
        if self._monitor_thread is not None:
            self._monitor_thread.join(timeout=2)
        self.client.close()
