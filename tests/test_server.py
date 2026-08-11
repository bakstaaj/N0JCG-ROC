from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import sys
from tempfile import TemporaryDirectory
from threading import Thread
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from n0jcg_roc.config import DEFAULT_CONFIG, transmit_interlock  # noqa: E402
from n0jcg_roc.applications import load_application_settings, save_application_settings  # noqa: E402
from n0jcg_roc.aprs_map import (  # noqa: E402
    _heard_activity_from_lines,
    _station_entry,
    heard_callsigns,
    load_aprsfi_settings,
)
from n0jcg_roc.server import collect_aprs_frame_records, create_server, parse_aprs_frames  # noqa: E402
from n0jcg_roc.operator_controls import OperatorAuth, make_password_record  # noqa: E402
from n0jcg_roc.operator_activity import parse_rf_session_active  # noqa: E402
from n0jcg_roc.licensing import (  # noqa: E402
    LicenseClient,
    LicenseError,
    RocTrialController,
    installation_serial_from_identity,
)
from n0jcg_roc.station_settings import load_station_settings  # noqa: E402
from n0jcg_roc.weather import normalize_gateway_live_data, normalize_observation  # noqa: E402
from n0jcg_roc.winlink import (  # noqa: E402
    merge_sessions,
    parse_linbpq_journal,
    parse_runtime_config,
    summarize_mail_index,
    summarize_gateway_reliability,
    summarize_sessions,
)


class SafetyTests(unittest.TestCase):
    def test_operational_applications_are_direct_links_not_roc_proxies(self) -> None:
        server = (ROOT / "src" / "n0jcg_roc" / "server.py").read_text(encoding="utf-8")
        browser = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        self.assertNotIn("_proxy_path", server)
        self.assertNotIn("PI_SCANNER_WEB_ROOT", server)
        self.assertNotIn("/n0jcg-scanner/api/", browser)
        self.assertIn('fetch("/api/applications"', browser)

    def test_gateway_trial_is_manual_and_controls_operational_services(self) -> None:
        licensing = (ROOT / "src" / "n0jcg_roc" / "licensing.py").read_text(encoding="utf-8")
        server = (ROOT / "src" / "n0jcg_roc" / "server.py").read_text(encoding="utf-8")
        browser = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        self.assertIn('product_slug = "gateway"', licensing)
        self.assertIn('"data_updates_allowed"', licensing)
        self.assertNotIn("systemctl", licensing)
        self.assertNotIn("request_helper", licensing)
        self.assertIn("service_access_changed", licensing)
        self.assertIn("set_trial_services_enabled", server)
        self.assertIn('postRegistration("/api/license/trial/reset")', browser)
        self.assertIn("stopOperationalUpdates()", browser)
        self.assertIn('trialButton.hidden = registered', browser)
        self.assertIn('trialButton.disabled = !expired', browser)

    def test_default_configuration_cannot_transmit(self) -> None:
        state = transmit_interlock(DEFAULT_CONFIG)
        self.assertFalse(state["ready"])
        self.assertEqual(len(state["reasons"]), 3)

    def test_browser_has_no_transmit_route(self) -> None:
        browser_source = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        self.assertNotIn("/radio/tx", browser_source.lower())
        self.assertNotIn("TX_", browser_source)

    def test_base_package_manifest_is_unique_and_complete(self) -> None:
        package_lines = (ROOT / "config" / "base-packages.txt").read_text(encoding="utf-8").splitlines()
        packages = [line.strip() for line in package_lines if line.strip() and not line.lstrip().startswith("#")]
        self.assertEqual(len(packages), len(set(packages)))
        self.assertTrue({"alsa-utils", "rtl-sdr", "direwolf", "ax25-tools", "ax25-apps"} <= set(packages))

    def test_deployment_resources_are_application_specific(self) -> None:
        service = (ROOT / "deploy" / "n0jcg-roc.service").read_text(encoding="utf-8")
        deploy = (ROOT / "deploy" / "deploy.sh").read_text(encoding="utf-8")
        undeploy = (ROOT / "deploy" / "undeploy.sh").read_text(encoding="utf-8")
        expected_path = "/home/n0jcg/sdrdev/N0JCG-ROC"
        self.assertIn(expected_path, service)
        self.assertIn(expected_path, deploy)
        self.assertIn(expected_path, undeploy)
        self.assertIn("CONFIRM_REMOVE", undeploy)
        helper = (ROOT / "deploy" / "operator_helper.py").read_text(encoding="utf-8")
        helper_service = (ROOT / "deploy" / "n0jcg-operator-helper.service").read_text(encoding="utf-8")
        self.assertIn('action == "restart"', helper)
        self.assertIn('action == "maintenance_on"', helper)
        self.assertIn('action == "maintenance_off"', helper)
        self.assertIn('action == "cms_test"', helper)
        self.assertIn('action == "trial_services_stop"', helper)
        self.assertIn('action == "trial_services_start"', helper)
        self.assertIn('"n0jcg-aprs-rx.service"', helper)
        self.assertIn('"n0jcg-weather.service"', helper)
        self.assertIn("probe_rf_session", helper)
        self.assertNotIn("shell=True", helper)
        self.assertIn("NoNewPrivileges=true", helper_service)
        self.assertIn("ProtectSystem=strict", helper_service)
        deploy = (ROOT / "deploy" / "deploy.sh").read_text(encoding="utf-8")
        deployed_validator = (ROOT / "deploy" / "validate_deployed.sh").read_text(encoding="utf-8")
        self.assertNotIn("health[\"transmit\"][\"ready\"] is False", deployed_validator)
        self.assertNotIn("'\"ready\": false'", deploy)
        self.assertTrue((ROOT / "deploy" / "install_base_tools_remote.sh").is_file())
        self.assertTrue((ROOT / "deploy" / "validate_deployed.sh").is_file())
        self.assertTrue((ROOT / "tools" / "hardware_ownership_preflight.sh").is_file())
        self.assertTrue((ROOT / "tools" / "prepare_radio_permissions.sh").is_file())
        receive = (ROOT / "tools" / "hardware_receive_preflight.sh").read_text(encoding="utf-8")
        self.assertIn("arecord", receive)
        self.assertIn("rtl_fm", receive)
        self.assertNotIn("direwolf", receive.lower())
        self.assertNotIn("systemctl", receive.lower())
        aprs = (ROOT / "config" / "direwolf.aprs-rx.example.conf").read_text(encoding="utf-8")
        aprs_directives = "\n".join(line for line in aprs.splitlines() if not line.lstrip().startswith("#"))
        self.assertIn("MYCALL N0JCG-5", aprs)
        self.assertIn("MODEM 1200", aprs)
        self.assertNotIn("ADEVICE", aprs_directives.upper())
        self.assertIn("AGWPORT 18000", aprs_directives)
        self.assertIn("KISSPORT 18001", aprs_directives)
        self.assertNotIn("PTT", aprs_directives.upper())
        self.assertNotIn("IGSERVER", aprs_directives.upper())
        self.assertNotIn("DIGIPEAT", aprs_directives.upper())
        winlink_rx = (ROOT / "config" / "direwolf.winlink-rx.example.conf").read_text(encoding="utf-8")
        winlink_rx_directives = "\n".join(line for line in winlink_rx.splitlines() if not line.lstrip().startswith("#"))
        self.assertIn("ADEVICE plughw:CARD=Device,DEV=0", winlink_rx_directives)
        self.assertIn("ARATE 48000", winlink_rx_directives)
        self.assertIn("MODEM 1200", winlink_rx_directives)
        self.assertNotIn("PTT", winlink_rx_directives.upper())
        self.assertIn("AGWPORT 0", winlink_rx_directives)
        self.assertIn("KISSPORT 0", winlink_rx_directives)
        self.assertNotIn("IGSERVER", winlink_rx_directives.upper())
        winlink_modem = (ROOT / "config" / "direwolf.winlink-rms.example.conf").read_text(encoding="utf-8")
        active_modem = "\n".join(line for line in winlink_modem.splitlines() if not line.lstrip().startswith("#"))
        self.assertIn("KISSPORT 8010", active_modem)
        self.assertNotIn("PTT", active_modem.upper())
        self.assertNotIn("IGSERVER", active_modem.upper())
        bpq = (ROOT / "config" / "bpq32.winlink-rms.example.cfg").read_text(encoding="utf-8")
        self.assertIn("SIMPLE", bpq)
        self.assertIn("NODECALL=N0JCG-15", bpq)
        self.assertIn("NODEALIAS=N0ROC", bpq)
        self.assertIn("CMSPASS=CHANGE_ME", bpq)
        self.assertIn("TCPPORT=8010", bpq)
        self.assertIn("RELAYAPPL=BBS", bpq)
        self.assertIn("APPLICATION 1,RMS,C 1 CMS,N0JCG-10,N0RMS,255", bpq)
        self.assertIn("APPLICATION 2,BBS,,N0JCG-11", bpq)
        self.assertIn("LINMAIL", bpq)
        linmail = (ROOT / "config" / "linmail.winlink-postoffice.example.cfg").read_text(encoding="utf-8")
        self.assertIn('BBSName = "__POST_OFFICE_CALL__"', linmail)
        self.assertIn('ConnectScript = "c 1 CMS"', linmail)
        self.assertIn("FWDNewImmediately = 1", linmail)
        self.assertIn("SMTPPort = 0", linmail)
        self.assertIn("POP3Port = 0", linmail)
        configure_rms = (ROOT / "deploy" / "configure_winlink_rms.sh").read_text(encoding="utf-8")
        self.assertIn("WINLINK_POST_OFFICE_ENABLED", configure_rms)
        self.assertIn("WINLINK_NODE_CALL", configure_rms)
        self.assertIn("WINLINK_POST_OFFICE_CALL", configure_rms)
        self.assertIn('"${WINLINK_BASE_CALL}-9"', configure_rms)
        self.assertIn("reserved for an N0JCG mobile/APRS client", configure_rms)
        self.assertIn("Post Office configured on TCP port 8772", configure_rms)
        post_office_deploy = (ROOT / "deploy" / "configure_winlink_postoffice.sh").read_text(encoding="utf-8")
        self.assertIn("--enable|--disable", post_office_deploy)
        self.assertIn("/etc/n0jcg/backups/winlink-postoffice-", post_office_deploy)
        self.assertIn("BPQUsers.dat", post_office_deploy)
        self.assertIn("retained mail data was not deleted", post_office_deploy)
        post_office_user = (ROOT / "deploy" / "configure_winlink_postoffice_user.sh").read_text(encoding="utf-8")
        self.assertIn("--data-binary @-", post_office_user)
        self.assertIn("WINLINK_OPERATOR_NAME", post_office_user)
        self.assertNotIn('echo "${WINLINK_CMS_PASSWORD}"', post_office_user)
        self.assertIn("BPQMail user profile configured", post_office_user)
        modem_service = (ROOT / "deploy" / "n0jcg-winlink-modem.service").read_text(encoding="utf-8")
        rms_service = (ROOT / "deploy" / "n0jcg-winlink-rms.service").read_text(encoding="utf-8")
        self.assertIn("ConditionPathExists=/etc/n0jcg/winlink-rms-approved", modem_service)
        self.assertIn("ConditionPathExists=/etc/n0jcg/winlink-rms-approved", rms_service)
        listener = (ROOT / "tools" / "aprs_listener.sh").read_text(encoding="utf-8")
        self.assertIn("00014439", listener)
        self.assertIn("APRS_RTL_SERIAL", listener)
        self.assertIn("APRS_IGATE_PASSCODE", listener)
        self.assertIn("PBEACON SENDTO=IG", listener)
        self.assertIn("720:00", listener)
        self.assertIn('SYMBOL="igate"', listener)
        self.assertIn("RTL_GAIN_DB", listener)
        self.assertIn("direwolf -q h -r 48000", listener)
        self.assertNotIn("PTT", listener.upper())
        server = (ROOT / "src" / "n0jcg_roc" / "server.py").read_text(encoding="utf-8")
        self.assertIn('APRS_RTL_SERIAL = os.environ.get("APRS_RTL_SERIAL", "00014439")', server)
        self.assertTrue((ROOT / "deploy" / "n0jcg-aprs-rx.service").is_file())
        beacon = (ROOT / "tools" / "aprs_beacon_scheduler.py").read_text(encoding="utf-8")
        self.assertIn("I_UNDERSTAND_RF_TX", beacon)
        self.assertIn("max(600", beacon)
        self.assertTrue((ROOT / "deploy" / "n0jcg-aprs-beacon.service").is_file())
        digipeater = (ROOT / "config" / "direwolf-digipeater.example.conf").read_text(encoding="utf-8")
        self.assertIn("MYCALL N0JCG-1", digipeater)
        self.assertIn("DIGIPEAT 0 1", digipeater)
        self.assertNotIn("IGSERVER", digipeater)


class FakeLicenseClient:
    def __init__(self) -> None:
        self.registered = False
        self.activated = None

    def status(self) -> dict:
        return {
            "serial_number": "N0JCG-1111-2222-3333-4444",
            "registered": self.registered,
            "license_suffix": "TEST-TEST",
        }

    def activate(self, license_serial: str, email: str) -> dict:
        self.activated = (license_serial, email)
        self.registered = True
        return self.status()

    def start_background_refresh(self) -> None:
        pass

    def close(self) -> None:
        pass


class LicensingTests(unittest.TestCase):
    def test_installation_serial_is_stable_and_anonymous(self) -> None:
        first = installation_serial_from_identity("roc-machine-id")
        self.assertEqual(first, installation_serial_from_identity("roc-machine-id"))
        self.assertRegex(first, r"^N0JCG-[0-9A-F]{4}(?:-[0-9A-F]{4}){3}$")
        self.assertNotIn("roc-machine-id", first)

    def test_manual_trial_expires_resets_and_disappears_when_registered(self) -> None:
        clock = [1000.0]
        client = FakeLicenseClient()
        service_access = []
        controller = RocTrialController(
            client,
            trial_seconds=300,
            now=lambda: clock[0],
            start_background_refresh=False,
            service_access_changed=service_access.append,
        )
        initial = controller.status()
        self.assertTrue(initial["trial_active"])
        self.assertEqual(initial["trial_remaining_seconds"], 300)
        self.assertEqual(service_access, [True])
        with self.assertRaisesRegex(LicenseError, "only be restarted after it expires"):
            controller.reset_trial()
        clock[0] += 301
        expired = controller.status()
        self.assertTrue(expired["trial_expired"])
        self.assertFalse(expired["data_updates_allowed"])
        self.assertEqual(service_access, [True, False])
        reset = controller.reset_trial()
        self.assertTrue(reset["trial_active"])
        self.assertEqual(reset["trial_remaining_seconds"], 300)
        self.assertEqual(service_access, [True, False, True])
        registered = controller.activate({"license_serial": "N0JCG-GTW-ABCD-EFGH-JKLM-NPQR", "email": "operator@example.com"})
        self.assertTrue(registered["registered"])
        self.assertIsNone(registered["trial_limit_seconds"])
        self.assertFalse(registered["trial_active"])
        self.assertTrue(registered["data_updates_allowed"])
        self.assertEqual(service_access, [True, False, True])

    def test_invalid_gateway_credentials_are_rejected_before_network(self) -> None:
        called = []
        with TemporaryDirectory() as directory:
            client = LicenseClient(
                app_version="0.1.0-dev",
                state_root=Path(directory),
                environment={"N0JCG_INSTALLATION_ID": "roc-test"},
                opener=lambda *args, **kwargs: called.append((args, kwargs)),
            )
            with self.assertRaises(LicenseError):
                client.activate("not-a-license", "not-an-email")
        self.assertEqual(called, [])


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application_temp = TemporaryDirectory()
        cls.config_path = Path(cls.application_temp.name) / "station.toml"
        cls.application_settings_path = Path(cls.application_temp.name) / "applications.json"
        cls.aprsfi_settings_path = Path(cls.application_temp.name) / "aprs-fi.json"
        cls.aprsfi_cache_path = Path(cls.application_temp.name) / "aprs-fi-cache.json"
        cls.station_settings_path = Path(cls.application_temp.name) / "station.json"
        cls.operator_audit_path = Path(cls.application_temp.name) / "operator-audit.jsonl"
        cls.operator_socket_path = Path(cls.application_temp.name) / "operator.sock"
        cls.maintenance_path = Path(cls.application_temp.name) / "maintenance"
        cls.license_state_path = Path(cls.application_temp.name) / "licensing"
        cls.trial_controller = RocTrialController(
            LicenseClient(
                app_version="test",
                state_root=cls.license_state_path,
                environment={"N0JCG_INSTALLATION_ID": "roc-server-test"},
            ),
            start_background_refresh=False,
        )
        save_application_settings(cls.application_settings_path, {
            "applications": {
                "air_traffic": {"enabled": False},
                "scanner": {"enabled": False},
            }
        })
        cls.server = create_server(
            port=0,
            config_path=cls.config_path,
            application_settings_path=cls.application_settings_path,
            aprsfi_settings_path=cls.aprsfi_settings_path,
            aprsfi_cache_path=cls.aprsfi_cache_path,
            station_settings_path=cls.station_settings_path,
            operator_audit_path=cls.operator_audit_path,
            operator_socket_path=cls.operator_socket_path,
            maintenance_path=cls.maintenance_path,
            trial_controller=cls.trial_controller,
        )
        cls.thread = Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)
        cls.application_temp.cleanup()

    def get(self, path: str) -> tuple[int, str, bytes]:
        with urlopen(self.base_url + path, timeout=5) as response:
            return response.status, response.headers.get_content_type(), response.read()

    def post(self, path: str, payload: dict) -> tuple[int, str, bytes]:
        request = Request(
            self.base_url + path,
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urlopen(request, timeout=5) as response:
            return response.status, response.headers.get_content_type(), response.read()

    def test_health_api_reports_locked_transmit(self) -> None:
        status, media_type, body = self.get("/api/health")
        payload = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(media_type, "application/json")
        self.assertEqual(payload["status"], "ok")
        self.assertFalse(payload["transmit"]["ready"])

    def test_registration_status_rejects_trial_reset_until_expired(self) -> None:
        status, media_type, body = self.get("/api/license/status")
        registration = json.loads(body)["registration"]
        self.assertEqual(status, 200)
        self.assertEqual(media_type, "application/json")
        self.assertTrue(registration["trial_active"])
        self.assertEqual(registration["trial_limit_seconds"], 300)
        self.assertTrue(registration["data_updates_allowed"])
        with self.assertRaises(HTTPError) as failure:
            self.post("/api/license/trial/reset", {})
        self.assertEqual(failure.exception.code, 409)
        reset = json.loads(failure.exception.read())
        self.assertIn("only be restarted after it expires", reset["error"])
        self.assertTrue(reset["registration"]["trial_active"])
        failure.exception.close()

    def test_registration_activation_rejects_invalid_credentials(self) -> None:
        with self.assertRaises(HTTPError) as failure:
            self.post("/api/license/activate", {"license_serial": "invalid", "email": "invalid"})
        self.assertEqual(failure.exception.code, 400)
        self.assertIn(b"license S/N format is invalid", failure.exception.read())
        failure.exception.close()

    def test_operator_authentication_uses_signed_expiring_session_and_csrf(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least 10"):
            make_password_record("123456789", salt=b"0123456789abcdef", iterations=1000)
        auth = OperatorAuth(
            make_password_record("1234567890", salt=b"0123456789abcdef", iterations=1000),
            "ab" * 32,
        )
        self.assertTrue(auth.configured)
        self.assertTrue(auth.verify_password("1234567890"))
        self.assertFalse(auth.verify_password("wrong password"))
        token, csrf, _ = auth.issue_session(now=1000)
        self.assertIsNotNone(auth.verify_session(token, csrf_token=csrf, now=1001))
        self.assertIsNone(auth.verify_session(token, csrf_token="wrong", now=1001))
        self.assertIsNone(auth.verify_session(token, csrf_token=csrf, now=1000 + 1800))

    def test_linbpq_links_table_detects_active_rf_session(self) -> None:
        idle = "<h2 align=center>Links</h2><table><tr><th>Far Call</th><th>Our Call</th></tr></body></html>"
        active = "<h2 align=center>Links</h2><table><tr><th>Far Call</th><th>Our Call</th></tr><tr><td>N0JCG</td><td>N0JCG-10</td></tr></table>"
        self.assertFalse(parse_rf_session_active(idle))
        self.assertTrue(parse_rf_session_active(active))
        with self.assertRaisesRegex(ValueError, "heading"):
            parse_rf_session_active("<html></html>")

    def test_operator_login_action_diagnostics_and_logout_are_protected(self) -> None:
        password = "operator test password"
        self.server.operator_auth = OperatorAuth(
            make_password_record(password, salt=b"fedcba9876543210", iterations=1000),
            "cd" * 32,
        )
        self.server.login_failures.clear()
        try:
            with self.assertRaises(HTTPError) as unauthenticated:
                self.post("/api/operator/action", {"action": "cms_test"})
            self.assertEqual(unauthenticated.exception.code, 401)
            unauthenticated.exception.close()

            login_request = Request(
                self.base_url + "/api/operator/login",
                data=json.dumps({"password": password}).encode("utf-8"),
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urlopen(login_request, timeout=5) as login_response:
                login_payload = json.loads(login_response.read())
                cookie = login_response.headers["Set-Cookie"].split(";", 1)[0]
                self.assertIn("HttpOnly", login_response.headers["Set-Cookie"])
                self.assertIn("SameSite=Strict", login_response.headers["Set-Cookie"])

            action_request = Request(
                self.base_url + "/api/operator/action",
                data=b'{"action":"cms_test"}',
                method="POST",
                headers={"Content-Type": "application/json", "Cookie": cookie, "X-CSRF-Token": login_payload["csrf_token"]},
            )
            with patch("n0jcg_roc.server.probe_rf_session", return_value={"available": True, "active": False}), patch("n0jcg_roc.server.request_helper", return_value={"ok": True, "action": "cms_test", "message": "CMS test passed"}):
                with urlopen(action_request, timeout=5) as action_response:
                    self.assertTrue(json.loads(action_response.read())["ok"])

            with patch("n0jcg_roc.server.probe_rf_session", return_value={"available": True, "active": True}):
                with self.assertRaises(HTTPError) as active_session:
                    urlopen(action_request, timeout=5)
                self.assertEqual(active_session.exception.code, 409)
                self.assertIn(b"an RF session is active", active_session.exception.read())
                active_session.exception.close()

            diagnostics_request = Request(self.base_url + "/api/operator/diagnostics", headers={"Cookie": cookie})
            with urlopen(diagnostics_request, timeout=5) as diagnostics_response:
                diagnostics = json.loads(diagnostics_response.read())
                self.assertEqual(diagnostics_response.headers.get_content_disposition(), "attachment")
                def keys(value):
                    if isinstance(value, dict):
                        return {str(key).lower() for key in value} | set().union(*(keys(item) for item in value.values()))
                    if isinstance(value, list):
                        return set().union(*(keys(item) for item in value)) if value else set()
                    return set()
                diagnostic_keys = keys(diagnostics)
                self.assertNotIn("password", diagnostic_keys)
                self.assertNotIn("recipient", diagnostic_keys)

            logout_request = Request(
                self.base_url + "/api/operator/logout",
                data=b"{}",
                method="POST",
                headers={"Content-Type": "application/json", "Cookie": cookie, "X-CSRF-Token": login_payload["csrf_token"]},
            )
            with urlopen(logout_request, timeout=5) as logout_response:
                self.assertEqual(json.loads(logout_response.read())["authenticated"], False)
        finally:
            self.server.operator_auth = OperatorAuth()
            self.server.login_failures.clear()
            self.operator_socket_path.unlink(missing_ok=True)

    def test_service_inventory_contains_initial_modules(self) -> None:
        _, _, body = self.get("/api/services")
        services = json.loads(body)["services"]
        service_ids = {service["id"] for service in services}
        self.assertTrue({"winlink", "aprs", "adsb", "uat", "noaa", "airband"} <= service_ids)
        service_states = {service["id"]: service["state"] for service in services}
        self.assertEqual(service_states["winlink"], "commissioned")
        self.assertEqual(service_states["aprs"], "commissioned")

    def test_system_api_has_resources_tooling_and_hardware_boundaries(self) -> None:
        status, media_type, body = self.get("/api/system")
        payload = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(media_type, "application/json")
        self.assertTrue(payload["host"]["hostname"])
        self.assertGreater(payload["resources"]["disk"]["total_bytes"], 0)
        self.assertIn("utilization_percent", payload["resources"]["cpu"])
        self.assertGreaterEqual(payload["resources"]["cpu"]["logical_processors"], 1)
        self.assertIn("used_percent", payload["resources"]["memory"])
        self.assertIn("celsius", payload["resources"]["temperature"])
        self.assertIn("direwolf", payload["tooling"]["commands"])
        self.assertIn(payload["hardware"]["state"], {"bare-server", "devices-present"})
        self.assertIsInstance(payload["hardware"]["serial_by_id"], list)
        self.assertIsInstance(payload["hardware"]["alsa_cards"], list)
        self.assertIsInstance(payload["hardware"]["usb_audio_cards"], list)

    def test_dashboard_and_assets_are_served(self) -> None:
        status, media_type, body = self.get("/")
        self.assertEqual(status, 200)
        self.assertEqual(media_type, "text/html")
        self.assertIn(b"Radio Operations Center", body)
        self.assertIn(b"System readiness", body)
        self.assertIn(b"Performance trends", body)
        self.assertIn(b'id="chart-cpu"', body)
        self.assertIn(b'id="chart-memory"', body)
        self.assertIn(b'id="chart-temperature"', body)
        self.assertIn(b'id="chart-aprsFrames"', body)
        self.assertIn(b'id="metric-voice-calls"', body)
        self.assertIn(b'id="metric-vhf-locks"', body)
        self.assertIn(b'id="metric-uhf-locks"', body)
        self.assertIn(b'id="application-settings"', body)
        self.assertIn(b'id="station-settings-form"', body)
        self.assertIn(b'id="aprs-activity"', body)
        self.assertIn(b'id="aprs-map"', body)
        self.assertIn(b'id="winlink-gateway"', body)
        self.assertIn(b'id="winlink-session-caller"', body)
        self.assertIn(b'data-winlink-milestone="inbound_message_verified"', body)
        self.assertIn(b'id="winlink-hourly-chart"', body)
        self.assertIn(b'id="winlink-reliability-state"', body)
        self.assertIn(b'id="operator-controls"', body)
        self.assertIn(b'id="operator-login-form"', body)
        self.assertIn(b'id="registration"', body)
        self.assertIn(b'id="registration-trial-button"', body)
        self.assertIn(b"APRS, Weather, and Winlink services are stopped", body)
        self.assertIn(b'id="registration-form"', body)
        self.assertIn(b'Five-minute trial ended', body)
        self.assertIn(b'Checking RMS state', body)
        self.assertIn(b'id="winlink-sessions"', body)
        expected_navigation = [
            b'href="#overview"',
            b'href="#aprs-activity"',
            b'href="#winlink-gateway"',
            b'href="#weather-monitor"',
            b'href="#applications"',
            b'href="#registration"',
            b'href="#operator-controls"',
            b'href="#application-settings"',
        ]
        navigation = body[body.index(b'<nav>'):body.index(b'</nav>')]
        positions = [navigation.index(anchor) for anchor in expected_navigation]
        self.assertEqual(positions, sorted(positions))
        expected_sections = [
            b'id="overview"',
            b'id="radio-services"',
            b'id="system-readiness"',
            b'id="aprs-activity"',
            b'id="aprs-map-section"',
            b'id="winlink-gateway"',
            b'id="weather-monitor"',
            b'id="applications"',
            b'id="registration"',
            b'id="operator-controls"',
            b'id="application-settings"',
        ]
        section_positions = [body.index(section) for section in expected_sections]
        self.assertEqual(section_positions, sorted(section_positions))
        self.assertEqual(body.count(b'data-workspace-panel='), 8)
        self.assertIn(b'id="workspace-overview" class="workspace-panel"', body)
        self.assertIn(b'id="workspace-aprs" class="workspace-panel"', body)
        self.assertIn(b'data-workspace-panel="configuration"', body)
        self.assertNotIn(b'data-workspace-panel="overview" aria-labelledby="nav-overview" tabindex="-1" hidden', body)
        self.assertEqual(body.count(b'class="workspace-panel" data-workspace-panel='), 8)
        self.assertIn(b"Position data from", body)
        self.assertIn(b"OpenStreetMap contributors", body)
        self.assertIn(b"APRS listener", body)
        self.assertIn(b"N0JCG_Header_Dark_Approved.png", body)
        self.assertNotIn(b"n0jcg-primary-dark.svg", body)
        self.assertEqual(self.get("/styles.css")[0], 200)
        self.assertEqual(self.get("/app.js")[0], 200)
        app = self.get("/app.js")[2]
        self.assertIn(b"metrics.voice_calls", app)
        self.assertIn(b"metrics.vhf_locks", app)
        self.assertIn(b"metrics.uhf_locks", app)
        self.assertIn(b"/api/aprs-map", app)
        self.assertIn(b"/api/station/settings", app)
        self.assertIn(b"tile.openstreetmap.org", app)
        self.assertIn(b"distanceKm", app)
        self.assertIn(b"aprs-map-show-all", app)
        self.assertIn(b"aprs-map-zoom-in", app)
        self.assertIn(b"aprs-map-zoom-out", app)
        self.assertIn(b"aprs-map-roc-area", app)
        self.assertIn(b"aprsSymbolIcon", app)
        self.assertIn(b"initWorkspaceNavigation", app)
        self.assertIn(b"showWorkspacePanel", app)
        self.assertIn(b"aprsMap.invalidateSize()", app)
        self.assertIn(b"recordOverviewTelemetry", app)
        self.assertIn(b"refreshOverviewTelemetry", app)
        self.assertIn(b"TELEMETRY_WINDOW_MS", app)
        self.assertIn(b"showWinlink", app)
        self.assertIn(b'/api/gateway', app)
        self.assertIn(b'/api/winlink/sessions', app)
        self.assertIn(b"loadWinlinkSessions", app)
        self.assertIn(b"showWinlinkReliability", app)
        self.assertIn(b"initOperatorControls", app)
        self.assertIn(b"initRegistration", app)
        self.assertIn(b'/api/license/status', app)
        self.assertIn(b'/api/license/activate', app)
        self.assertIn(b'/api/license/trial/reset', app)
        self.assertIn(b'/api/operator/action', app)
        self.assertIn(b'Winlink RMS on air', app)
        self.assertIn(b'function formatFrequency(frequencyHz)', app)
        self.assertIn(b"aprs-symbols-48-${kind}.png", app)
        self.assertEqual(self.get("/assets/N0JCG_Header_Dark_Approved.png")[0], 200)
        self.assertEqual(self.get("/assets/N0JCG_Icon_Approved.png")[0], 200)
        self.assertEqual(self.get("/assets/N0JCG_Icon_Dark_Approved.png")[0], 200)
        self.assertEqual(self.get("/assets/aprs-symbols-48-primary.png")[0], 200)
        self.assertEqual(self.get("/assets/aprs-symbols-48-alternate.png")[0], 200)
        self.assertEqual(self.get("/assets/aprs-symbols-48-overlay.png")[0], 200)

    def test_operational_center_code_is_not_embedded_in_roc(self) -> None:
        self.assertFalse(any((ROOT / "web" / "air-traffic").glob("**/*")))
        self.assertFalse(any((ROOT / "web" / "pi-scanner").glob("**/*")))
        server = (ROOT / "src" / "n0jcg_roc" / "server.py").read_text(encoding="utf-8")
        self.assertNotIn("N0JCG-SCANNER/web", server)
        self.assertNotIn("N0JCG-AIR-TRAFFIC-CENTER/web", server)

    def test_application_settings_are_independent_and_persistent(self) -> None:
        status, media_type, body = self.post("/api/applications", {
            "applications": {
                "air_traffic": {"enabled": True, "host": "192.168.68.141", "port": 8090},
                "scanner": {"enabled": False, "host": "192.168.68.126", "port": 8070},
            }
        })
        self.assertEqual(status, 200)
        self.assertEqual(media_type, "application/json")
        self.assertTrue(json.loads(body)["ok"])
        stored = load_application_settings(self.application_settings_path)["applications"]
        self.assertTrue(stored["air_traffic"]["enabled"])
        self.assertEqual(stored["air_traffic"]["host"], "192.168.68.141")
        self.assertFalse(stored["scanner"]["enabled"])
        self.assertEqual(stored["scanner"]["host"], "192.168.68.126")

        save_application_settings(self.application_settings_path, {"applications": {"air_traffic": {"enabled": False}}})

    def test_application_settings_api_rejects_url_in_host_field(self) -> None:
        request = Request(
            self.base_url + "/api/applications",
            data=json.dumps({"applications": {"air_traffic": {"host": "http://bad/path"}}}).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with self.assertRaises(HTTPError) as caught:
            urlopen(request, timeout=2)
        self.assertEqual(caught.exception.code, 400)
        caught.exception.close()

    def test_station_overview_title_is_configurable_and_persistent(self) -> None:
        _, _, initial_body = self.get("/api/station")
        self.assertEqual(json.loads(initial_body)["display"]["overview_title"], "N0JCG · Cripple Creek, Colorado")
        status, media_type, body = self.post("/api/station/settings", {
            "overview_title": "N0JCG · Cripple Creek Mountain ROC",
        })
        self.assertEqual(status, 200)
        self.assertEqual(media_type, "application/json")
        self.assertEqual(json.loads(body)["overview_title"], "N0JCG · Cripple Creek Mountain ROC")
        stored = load_station_settings(self.station_settings_path, DEFAULT_CONFIG["station"])
        self.assertEqual(stored["overview_title"], "N0JCG · Cripple Creek Mountain ROC")

    def test_station_overview_title_rejects_empty_value(self) -> None:
        request = Request(
            self.base_url + "/api/station/settings",
            data=json.dumps({"overview_title": "   "}).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with self.assertRaises(HTTPError) as caught:
            urlopen(request, timeout=2)
        self.assertEqual(caught.exception.code, 400)
        caught.exception.close()

    def test_aprs_map_extracts_unique_recent_source_callsigns(self) -> None:
        log_path = Path(self.application_temp.name) / "heard.log"
        log_path.write_text(
            "Dire Wolf version 1.7\n"
            "N0CALL-1>APRS:old\n"
            "[0.3] K0ABC-9>APRS,WIDE1-1:new\n"
            "N0CALL-1>APRS:latest\n",
            encoding="utf-8",
        )
        self.assertEqual(heard_callsigns(log_path), ["N0CALL-1", "K0ABC-9"])

    def test_aprs_map_preserves_symbol_table_code_and_overlay(self) -> None:
        station = _station_entry({
            "name": "N0JCG",
            "lat": "38.8005",
            "lng": "-105.2001",
            "lasttime": "1785811200",
            "symbol": "Pa",
        })
        self.assertIsNotNone(station)
        self.assertEqual(station["symbol"], "Pa")

    def test_aprs_map_counts_recent_journal_frames_and_unique_callsigns(self) -> None:
        activity = _heard_activity_from_lines([
            "Dire Wolf version 1.7",
            "[0.3] N0JCG-1>APBTUV:position one",
            "[0.2] N0JCG-7>APBTUV:position two",
            "[0.3] N0JCG-1>APBTUV:position three",
        ])
        self.assertEqual(activity["frame_count"], 3)
        self.assertEqual(activity["callsigns"], ["N0JCG-1", "N0JCG-7"])

    def test_aprs_map_rejects_positions_older_than_window(self) -> None:
        station = _station_entry({
            "name": "OLD-1",
            "lat": "38.8",
            "lng": "-105.2",
            "lasttime": "1000",
            "symbol": "/>",
        }, cutoff_epoch=1001)
        self.assertIsNone(station)

    def test_aprsfi_key_is_saved_server_side_and_never_returned(self) -> None:
        status, media_type, body = self.post("/api/aprs-map/settings", {"enabled": True, "api_key": "example-secret-key"})
        payload = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(media_type, "application/json")
        self.assertTrue(payload["configured"])
        self.assertTrue(payload["enabled"])
        self.assertNotIn("example-secret-key", body.decode("utf-8"))
        self.assertEqual(load_aprsfi_settings(self.aprsfi_settings_path)["api_key"], "example-secret-key")
        _, _, settings_body = self.get("/api/aprs-map/settings")
        self.assertEqual(json.loads(settings_body), {"enabled": True, "configured": True})
        self.post("/api/aprs-map/settings", {"enabled": False, "api_key": ""})

    def test_aprs_map_waits_for_api_key_without_external_request(self) -> None:
        self.post("/api/aprs-map/settings", {"enabled": False, "api_key": ""})
        status, media_type, body = self.get("/api/aprs-map")
        payload = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(media_type, "application/json")
        self.assertFalse(payload["configured"])
        self.assertFalse(payload["enabled"])
        self.assertEqual(payload["source"], "aprs.fi")
        self.assertEqual(payload["max_callsigns"], 20)
        self.assertEqual(payload["window_hours"], 24)
        self.assertIn("window_start_utc", payload)
        self.assertAlmostEqual(payload["map_center"]["latitude"], 38.800788)

    def test_aprs_api_reports_receive_status(self) -> None:
        status, media_type, body = self.get("/api/aprs")
        payload = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(media_type, "application/json")
        self.assertTrue(payload["configured"])
        self.assertIn("active", payload)
        self.assertIsInstance(payload["packet_count"], int)
        self.assertIn("packets", payload)
        self.assertIn("last_packet", payload)
        self.assertIn("last_packet_origin", payload)
        self.assertIn("last_packet_timestamp_utc", payload)

    def test_aprs_frame_page_is_paginated_and_sorted(self) -> None:
        status, media_type, body = self.get("/api/aprs/frames?page=1&sort=newest")
        payload = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(media_type, "application/json")
        self.assertEqual(payload["page_size"], 25)
        self.assertIn("frames", payload)
        self.assertIn("timestamp_utc", payload["frames"][0]) if payload["frames"] else None
        self.assertIn("origin", payload["frames"][0]) if payload["frames"] else None

    def test_gateway_api_reports_receive_ready_and_tx_blocked(self) -> None:
        status, media_type, body = self.get("/api/gateway")
        payload = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(media_type, "application/json")
        self.assertEqual(payload["receive"]["aprs"]["kiss_port"], 18001)
        self.assertEqual(payload["receive"]["aprs"]["agw_port"], 18000)
        self.assertFalse(payload["transmit"]["ready"])
        self.assertIn(payload["winlink"]["state"], {"operational", "fault"})
        self.assertIn("last_rf_session", payload["winlink"])
        self.assertIn("queues", payload["winlink"])
        self.assertIn("commissioning", payload["winlink"])
        self.assertIn("reliability", payload["winlink"])
        self.assertNotIn("password", json.dumps(payload).lower())

    def test_winlink_runtime_parser_returns_only_safe_operational_fields(self) -> None:
        with TemporaryDirectory() as directory:
            config = Path(directory) / "bpq32.cfg"
            config.write_text(
                "NODECALL=N0JCG-15\n"
                "NODEALIAS=N0ROC\n"
                "CMSPASS=do-not-return-this\n"
                "APPLICATION 1,RMS,C 1 CMS,N0JCG-10,N0RMS,255\n"
                "APPLICATION 2,BBS,,N0JCG-11\n"
                "WL2KREPORT PUBLIC, api.winlink.org, 80, N0JCG-10, DM78JT, 00-23, 145070000, PKT1200, 5, 30, 3, 0\n",
                encoding="utf-8",
            )
            parsed = parse_runtime_config(config)
        self.assertEqual(parsed["node_call"], "N0JCG-15")
        self.assertEqual(parsed["rms_call"], "N0JCG-10")
        self.assertEqual(parsed["post_office_call"], "N0JCG-11")
        self.assertEqual(parsed["frequency_hz"], 145070000)
        self.assertNotIn("do-not-return-this", json.dumps(parsed))

    def test_bpqmail_index_reports_status_aware_message_counts(self) -> None:
        def record(status: str, flags: int = 0) -> bytes:
            value = bytearray(308)
            value[0] = ord("P")
            value[1] = ord(status)
            value[154] = flags
            return bytes(value)

        with TemporaryDirectory() as directory:
            path = Path(directory) / "DIRMES.SYS"
            control = bytearray(308)
            control[1] = 2
            path.write_bytes(
                bytes(control)
                + record("N")
                + record("$", 16)
                + record("F", 16)
                + record("D")
                + record("K", 8)
                + record("Y", 8)
            )
            counts = summarize_mail_index(path)

        self.assertTrue(counts["available"])
        self.assertEqual(counts["pending"], 2)
        self.assertEqual(counts["delivered"], 2)
        self.assertEqual(counts["received"], 4)
        self.assertEqual(counts["archived"], 1)
        self.assertEqual(counts["retained_total"], 6)

    def test_winlink_journal_parser_records_bidirectional_commissioning(self) -> None:
        lines = [
            '2026-08-10T18:37:15-06:00 roc LINBPQ[1]: Sending "Callsign":"N0JCG-10","Frequency":145070000,"ServiceCode":"PUBLIC"',
            "2026-08-10T18:37:16-06:00 roc LINBPQ[1]: WL2K Database update ok",
            '2026-08-10T18:38:00-06:00 roc LINBPQ[1]: Sending "Application":"BPQ32","Server":"N0JCG","Client":"N0JCG-2","Mode":"Packet 1200","Frequency":0,"LastCommand":"FQ","MessagesSent":0,"MessagesReceived":0,"BytesSent":88,"BytesReceived":160,"HoldingSeconds":3',
            '2026-08-10T18:39:23-06:00 roc LINBPQ[1]: Sending "Application":"BPQ32","Server":"N0JCG","Client":"N0JCG","Mode":"Packet 1200","Frequency":145070000,"LastCommand":"FQ","MessagesSent":1,"MessagesReceived":0,"BytesSent":343,"BytesReceived":59,"HoldingSeconds":35',
            '2026-08-10T18:44:12-06:00 roc LINBPQ[1]: Sending "Application":"BPQ32","Server":"N0JCG","Client":"N0JCG","Mode":"Packet 1200","Frequency":145070000,"LastCommand":"FQ","MessagesSent":0,"MessagesReceived":1,"BytesSent":95,"BytesReceived":831,"HoldingSeconds":69',
        ]
        parsed = parse_linbpq_journal(lines)
        self.assertEqual(parsed["session_count"], 2)
        self.assertEqual(parsed["last_session"]["messages_received"], 1)
        self.assertEqual(parsed["last_session"]["timestamp_utc"], "2026-08-11T00:44:12Z")
        self.assertTrue(all(parsed["commissioning"].values()))

    def test_winlink_session_ledger_deduplicates_and_summarizes_24_hours(self) -> None:
        sessions = [
            {"timestamp_utc": "2026-08-11T00:39:23Z", "caller": "N0JCG", "frequency_hz": 145070000, "duration_seconds": 35, "messages_sent": 1, "messages_received": 0, "bytes_sent": 343, "bytes_received": 59, "successful": True},
            {"timestamp_utc": "2026-08-11T00:44:12Z", "caller": "N0JCG", "frequency_hz": 145070000, "duration_seconds": 69, "messages_sent": 0, "messages_received": 1, "bytes_sent": 95, "bytes_received": 831, "successful": True},
        ]
        lan_session = {"timestamp_utc": "2026-08-11T00:30:00Z", "caller": "N0JCG-2", "frequency_hz": 0}
        merged = merge_sessions([lan_session, sessions[0]], sessions)
        self.assertEqual(len(merged), 2)
        stats = summarize_sessions(merged, datetime(2026, 8, 11, 1, 0, tzinfo=timezone.utc))
        self.assertEqual(stats["sessions"], 2)
        self.assertEqual(stats["unique_callsigns"], 1)
        self.assertEqual(stats["messages_sent"], 1)
        self.assertEqual(stats["messages_received"], 1)
        self.assertEqual(stats["success_percent"], 100.0)
        self.assertEqual(stats["average_duration_seconds"], 52.0)
        self.assertEqual(len(stats["hourly"]), 24)

    def test_winlink_reliability_summarizes_service_and_cms_events(self) -> None:
        rms_lines = [
            "2026-08-11T00:10:00+00:00 roc LINBPQ[1]: Connect to cms.example failed.",
            "2026-08-11T00:11:00+00:00 roc LINBPQ[1]: N0JCG Connected to CMS",
        ]
        modem_lines = [
            "2026-08-11T00:12:00+00:00 roc direwolf[2]: Device or resource busy",
        ]
        rms = {"active": True, "started_utc": "2026-08-10T20:00:00Z", "restart_count": 1}
        modem = {"active": True, "started_utc": "2026-08-10T20:00:01Z", "restart_count": 2}
        summary = summarize_gateway_reliability(
            rms_lines, modem_lines, rms, modem, datetime(2026, 8, 11, 1, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(summary["state"], "warning")
        self.assertEqual(summary["cms_connections"], 1)
        self.assertEqual(summary["cms_connection_failures"], 1)
        self.assertEqual(summary["modem_faults"], 1)
        self.assertTrue(summary["last_cms_event"]["successful"])
        self.assertEqual(summary["rms_restart_count"], 1)

    def test_winlink_session_history_api_is_paginated_and_private(self) -> None:
        status, media_type, body = self.get("/api/winlink/sessions?page=1&sort=newest&result=all")
        payload = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(media_type, "application/json")
        self.assertEqual(payload["page_size"], 25)
        self.assertIn("statistics_24h", payload)
        session_json = json.dumps(payload.get("sessions", [])).lower()
        self.assertNotIn("subject", session_json)
        self.assertNotIn("recipient", session_json)

    def test_aprs_context_uses_station_location_and_pc_time(self) -> None:
        status, media_type, body = self.get("/api/aprs/context")
        payload = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(media_type, "application/json")
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["latitude"], 38.800788)
        self.assertEqual(payload["longitude"], -105.2001)
        self.assertRegex(payload["utc"], r"^20\d\d-\d\d-\d\dT\d\d:\d\d:\d\dZ$")

    def test_weather_api_waits_for_station_data(self) -> None:
        status, media_type, body = self.get("/api/weather")
        payload = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(media_type, "application/json")
        self.assertTrue(payload["configured"])
        self.assertIn("available", payload)

    def test_weather_normalizes_ws90_fields(self) -> None:
        observation = normalize_observation({"tempinf": 19.5, "humidity": 40, "winddir": 180})
        self.assertEqual(observation["fields"]["temperature_c"], 19.5)
        self.assertEqual(observation["fields"]["wind_direction_deg"], 180)

    def test_weather_parses_gw1100_http_live_data(self) -> None:
        live = {
            "common_list": [
                {"id": "0x02", "val": "68.0", "unit": "F"},
                {"id": "0x07", "val": "40%"},
                {"id": "0x0A", "val": "225"},
                {"id": "0x0B", "val": "10.00 mph"},
                {"id": "0x0C", "val": "15.00 mph"},
                {"id": "0x15", "val": "250.00 w/m2"},
                {"id": "0x17", "val": "3"},
            ],
            "piezoRain": [{"id": "0x0E", "val": "0.10 in/Hr"}, {"id": "0x10", "val": "0.25 in"}],
            "wh25": [{"intemp": "77.0", "unit": "F", "inhumi": "30%", "rel": "24.00 inHg", "abs": "23.70 inHg"}],
        }
        payload = normalize_gateway_live_data(live, gateway_url="http://192.168.68.131")
        self.assertTrue(payload["outdoor_sensor_detected"])
        self.assertAlmostEqual(payload["temperature_c"], 20.0)
        self.assertAlmostEqual(payload["wind_speed_mps"], 4.4704)
        self.assertAlmostEqual(payload["rain_today_mm"], 6.35)
        self.assertAlmostEqual(payload["pressure_hpa"], 812.73328, places=4)
        self.assertAlmostEqual(payload["pressure_absolute_hpa"], 802.574114, places=4)

    def test_weather_dashboard_shows_relative_and_absolute_pressure(self) -> None:
        status, media_type, body = self.get("/")
        self.assertEqual(status, 200)
        self.assertEqual(media_type, "text/html")
        self.assertIn(b'id="weather-pressure"', body)
        self.assertIn(b'id="weather-pressure-detail"', body)
        app_status, _, app = self.get("/app.js")
        self.assertEqual(app_status, 200)
        self.assertIn(b"pressure_absolute_hpa", app)
        self.assertIn(b"Relative", app)
        self.assertIn(b"Absolute", app)

    def test_aprs_frame_parser_ignores_listener_noise(self) -> None:
        frames = parse_aprs_frames([
            "Dire Wolf version 1.7",
            "N0CALL>APRS,WIDE1-1:!3900.00N/10500.00W-Test",
            "[0.3] WB2OSZ-15>TEST:,The quick brown fox",
            "[ig] N0JCG-5>APDW17:!3848.05N\\10512.01W&N0JCG ROC RX-only iGate 144.390 MHz",
            "Ready to accept KISS TCP client application 0 on port 8001 ...",
        ])
        self.assertEqual(frames, [
            "N0CALL>APRS,WIDE1-1:!3900.00N/10500.00W-Test",
            "[0.3] WB2OSZ-15>TEST:,The quick brown fox",
            "[ig] N0JCG-5>APDW17:!3848.05N\\10512.01W&N0JCG ROC RX-only iGate 144.390 MHz",
        ])

    def test_aprs_frame_records_keep_each_journal_timestamp(self) -> None:
        entries = [
            {"__REALTIME_TIMESTAMP": "1786424201000000", "MESSAGE": "[0.2] N0JCG-1>APBTUV:First"},
            {"__REALTIME_TIMESTAMP": "1786424262000000", "MESSAGE": "Dire Wolf status noise"},
            {"__REALTIME_TIMESTAMP": "1786424323000000", "MESSAGE": "[ig] N0JCG-5>APDW17:Second"},
        ]
        records = collect_aprs_frame_records(runner=lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout="\n".join(json.dumps(entry) for entry in entries),
        ))
        self.assertEqual([record["timestamp_utc"] for record in records], [
            "2026-08-11T04:56:41Z",
            "2026-08-11T04:58:43Z",
        ])
        self.assertEqual([record["origin"] for record in records], ["rf", "internet"])
        self.assertEqual([record["frame"] for record in records], [
            "[0.2] N0JCG-1>APBTUV:First",
            "[ig] N0JCG-5>APDW17:Second",
        ])

    def test_missing_asset_returns_404(self) -> None:
        with self.assertRaises(HTTPError) as caught:
            self.get("/missing.txt")
        self.assertEqual(caught.exception.code, 404)
        caught.exception.close()


if __name__ == "__main__":
    unittest.main()
