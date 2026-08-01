from __future__ import annotations

import json
from pathlib import Path
import sys
from threading import Thread
import unittest
from urllib.error import HTTPError
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from n0jcg_roc.config import DEFAULT_CONFIG, transmit_interlock  # noqa: E402
from n0jcg_roc.server import create_server  # noqa: E402


class SafetyTests(unittest.TestCase):
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
        self.assertTrue((ROOT / "deploy" / "install_base_tools_remote.sh").is_file())


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = create_server(port=0)
        cls.thread = Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def get(self, path: str) -> tuple[int, str, bytes]:
        with urlopen(self.base_url + path, timeout=2) as response:
            return response.status, response.headers.get_content_type(), response.read()

    def test_health_api_reports_locked_transmit(self) -> None:
        status, media_type, body = self.get("/api/health")
        payload = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(media_type, "application/json")
        self.assertEqual(payload["status"], "ok")
        self.assertFalse(payload["transmit"]["ready"])

    def test_service_inventory_contains_initial_modules(self) -> None:
        _, _, body = self.get("/api/services")
        service_ids = {service["id"] for service in json.loads(body)["services"]}
        self.assertTrue({"winlink", "aprs", "adsb", "uat", "noaa", "airband"} <= service_ids)

    def test_dashboard_and_assets_are_served(self) -> None:
        status, media_type, body = self.get("/")
        self.assertEqual(status, 200)
        self.assertEqual(media_type, "text/html")
        self.assertIn(b"Radio Operations Center", body)
        self.assertEqual(self.get("/styles.css")[0], 200)
        self.assertEqual(self.get("/app.js")[0], 200)

    def test_missing_asset_returns_404(self) -> None:
        with self.assertRaises(HTTPError) as caught:
            self.get("/missing.txt")
        self.assertEqual(caught.exception.code, 404)
        caught.exception.close()


if __name__ == "__main__":
    unittest.main()
