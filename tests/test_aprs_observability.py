import tempfile
import unittest
from pathlib import Path

from n0jcg_roc.aprs_observability import aprs_is_health, packet_quality, update_rf_history
from n0jcg_roc.aprs_alerts import load_alert_settings, save_alert_settings


class AprsObservabilityTests(unittest.TestCase):
    def test_packet_quality_counts_rf_internet_duplicates_and_stations(self):
        records = [
            {"origin": "rf", "frame": "[0.3] N0JCG-1>APRS:frame", "timestamp_utc": "2026-08-18T00:00:00Z"},
            {"origin": "rf", "frame": "[0.1] N0JCG-1>APRS:frame", "timestamp_utc": "2026-08-18T00:01:00Z"},
            {"origin": "internet", "frame": "[ig] N0JCG-5>APDW17:position", "timestamp_utc": "2026-08-18T00:02:00Z"},
        ]
        result = packet_quality(records)
        self.assertEqual(result["rf_frames"], 2)
        self.assertEqual(result["internet_frames"], 1)
        self.assertEqual(result["unique_stations"], 1)
        self.assertEqual(result["duplicate_frames"], 1)
        self.assertEqual(result["decode_confidence"]["average"], 0.2)

    def test_aprs_is_health_reports_verified_connection(self):
        result = aprs_is_health([], journal_lines=[
            "Now connected to IGate server rotate.aprs2.net (1.2.3.4)",
            "[ig] # logresp N0JCG-5 verified",
        ])
        self.assertEqual(result["state"], "healthy")
        self.assertEqual(result["authentication"], "verified")
        self.assertEqual(result["server"], "rotate.aprs2.net")

    def test_packet_quality_handles_equal_timestamps(self):
        records = [
            {"origin": "rf", "frame": "[0.2] N0AAA>APRS:one", "timestamp_utc": "2026-08-18T00:00:00Z"},
            {"origin": "rf", "frame": "[0.3] N0BBB>APRS:two", "timestamp_utc": "2026-08-18T00:00:00Z"},
        ]
        result = packet_quality(records)
        self.assertEqual(result["last_rf_frame_utc"], "2026-08-18T00:00:00Z")

    def test_rf_history_is_bounded_and_hourly(self):
        with tempfile.TemporaryDirectory() as directory:
            result = update_rf_history(Path(directory) / "history.json", [
                {"origin": "rf", "frame": "N0JCG-1>APRS:frame", "timestamp_utc": "2026-08-18T00:05:00Z"},
            ], now=1776470400, keep_hours=168)
            self.assertEqual(len(result["points"]), 1)
            self.assertEqual(result["points"][0]["rf_frames"], 1)

    def test_alert_settings_validate_recipient_and_fixed_sender(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "alerts.json"
            result = save_alert_settings(path, {"enabled": True, "recipient": "operator@example.com"})
            self.assertEqual(result["sender"], "roc@n0jcg.com")
            self.assertEqual(load_alert_settings(path)["recipient"], "operator@example.com")
            with self.assertRaises(ValueError):
                save_alert_settings(path, {"enabled": True, "recipient": "not-an-email"})


if __name__ == "__main__":
    unittest.main()
