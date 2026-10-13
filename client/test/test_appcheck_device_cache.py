"""Live ADB JWT session vs identity-only disk profile; no phone or credentials."""
import json
import os
import runpy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from moneymin.roglife_appcheck import provider


class DeviceCacheTests(unittest.TestCase):
    def setUp(self):
        provider.clear_live_token()

    def tearDown(self):
        provider.clear_live_token()

    def test_windows_cli_and_desktop_resolve_same_cache(self):
        with tempfile.TemporaryDirectory() as temp:
            local = Path(temp) / "local"
            with patch.dict(os.environ, {"LOCALAPPDATA": str(local), "QMONEY_USER_ROOT": ""}), \
                 patch.object(provider.sys, "platform", "win32"):
                cli_path = provider.cache_path()
                with patch.dict(os.environ, {"QMONEY_USER_ROOT": str(local / "QMoney")}):
                    self.assertEqual(cli_path, provider.cache_path())
                self.assertEqual(cli_path, local / "QMoney/data/appcheck_device.json")

    def test_capture_entrypoint_does_not_redirect_to_temporary_profile(self):
        script = Path(__file__).resolve().parents[1] / "app/examples/refresh_device_appcheck.py"
        with tempfile.TemporaryDirectory() as temp, \
             patch.dict(os.environ, {"LOCALAPPDATA": temp}), \
             patch.object(provider.sys, "platform", "win32"), \
             patch.object(provider.sys, "path", list(provider.sys.path)):
            os.environ.pop("QMONEY_USER_ROOT", None)
            runpy.run_path(str(script), run_name="capture_entrypoint_fixture")
            self.assertNotIn("QMONEY_USER_ROOT", os.environ)
            self.assertEqual(provider.cache_path(), Path(temp) / "QMoney/data/appcheck_device.json")

    def test_live_obtain_does_not_authorize_from_disk_jwt(self):
        with tempfile.TemporaryDirectory() as temp, \
             patch.dict(os.environ, {"QMONEY_USER_ROOT": temp, "QMONEY_APPCHECK_SOURCE": "device"}), \
             patch.object(provider, "load_config", return_value={"package": "fixture.app"}), \
             patch.object(provider, "pick_device", return_value="fixture-serial"), \
             patch.object(provider, "collect_device_info", return_value={
                 "device_id": "android.ssaid:fixture", "serial": "fixture-serial", "model": "Fixture"}), \
             patch.object(provider, "ensure_appcheck", return_value={
                 "token": "private-fixture-canary", "provider": "fixture-provider",
                 "iat": 1, "exp": 9_999_999_999, "left": 1200}) as ensure, \
             patch.object(provider, "_jwt_left_s", return_value=1200):
            token = provider.obtain_token(force=True)
            self.assertEqual(token, "private-fixture-canary")
            ensure.assert_called_once_with("fixture-serial", {"package": "fixture.app"}, force=True)
            on_disk = json.loads((Path(temp) / "data/appcheck_device.json").read_text(encoding="utf-8"))
            self.assertNotIn("token", on_disk)
            self.assertEqual(on_disk["device_id"], "android.ssaid:fixture")
            status = provider.status_snapshot()
            self.assertEqual(status["device_id"], "android.ssaid:fixture")
            self.assertEqual(status["provider"], "fixture-provider")
            self.assertEqual(status["token_source"], "adb_live")
            self.assertTrue(status["token_available"])
            self.assertNotIn("private-fixture-canary", json.dumps(status))
            with patch.dict(os.environ, {"QMONEY_APPCHECK_SOURCE": "off", "QMONEY_APPCHECK_DEVICE": "0"}):
                status = provider.status_snapshot()
                self.assertFalse(status["enabled"])
                self.assertEqual(status["device_id"], "android.ssaid:fixture")

    def test_disk_jwt_alone_never_reports_validity_or_availability(self):
        with tempfile.TemporaryDirectory() as temp, \
             patch.dict(os.environ, {"QMONEY_USER_ROOT": temp, "QMONEY_APPCHECK_SOURCE": "device"}), \
             patch.object(provider, "load_config", return_value={"min_appcheck_left_s": 600}):
            provider._write_cache({
                "device_id": "android.ssaid:fixture",
                "serial": "fixture-serial",
                "token": "expired.jwt.should-not-surface",
                "provider": "play_integrity",
                "exp": 1,
                "left": -99999,
            })
            status = provider.status_snapshot()
            self.assertFalse(status["token_available"])
            self.assertIsNone(status["left_s"])
            self.assertEqual(status["token_len"], 0)
            self.assertIsNone(status["provider"])
            self.assertIsNone(status["token_source"])
            self.assertEqual(status["device_id"], "android.ssaid:fixture")
            self.assertIsNone(provider.read_cached_token(min_left_s=1))

    def test_obtain_without_force_still_streams_from_device(self):
        with tempfile.TemporaryDirectory() as temp, \
             patch.dict(os.environ, {"QMONEY_USER_ROOT": temp, "QMONEY_APPCHECK_SOURCE": "device"}), \
             patch.object(provider, "load_config", return_value={"package": "fixture.app"}), \
             patch.object(provider, "pick_device", return_value="fixture-serial"), \
             patch.object(provider, "collect_device_info", return_value={
                 "device_id": "android.ssaid:fixture", "serial": "fixture-serial"}), \
             patch.object(provider, "ensure_appcheck", return_value={
                 "token": "live-token", "provider": "play_integrity", "left": 1800}) as ensure, \
             patch.object(provider, "_jwt_left_s", return_value=1800):
            self.assertEqual(provider.obtain_token(force=False), "live-token")
            ensure.assert_called_once_with("fixture-serial", {"package": "fixture.app"}, force=False)

    def test_explicit_profiles_do_not_read_each_others_cache(self):
        with tempfile.TemporaryDirectory() as temp:
            first, second = Path(temp) / "one", Path(temp) / "two"
            with patch.dict(os.environ, {"QMONEY_USER_ROOT": str(first)}):
                provider._write_cache({"device_id": "android.ssaid:fixture"})
            with patch.dict(os.environ, {"QMONEY_USER_ROOT": str(second)}):
                self.assertIsNone(provider._read_cache_file())

    def test_local_edition_enables_device_mode_unless_explicitly_disabled(self):
        base = {
            "QMONEY_APPCHECK_SOURCE": "",
            "QMONEY_APPCHECK_DEVICE": "",
            "QMONEY_LOCAL_EDITION": "",
        }
        with patch.dict(os.environ, {**base, "QMONEY_LOCAL_EDITION": "1"}):
            self.assertTrue(provider.device_mode_enabled())
        with patch.dict(os.environ, base):
            self.assertFalse(provider.device_mode_enabled())
        with patch.dict(os.environ, {
                **base,
                "QMONEY_LOCAL_EDITION": "1",
                "QMONEY_APPCHECK_SOURCE": "off",
                "QMONEY_APPCHECK_DEVICE": "0"}):
            self.assertFalse(provider.device_mode_enabled())
