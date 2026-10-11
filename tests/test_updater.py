"""Unit tests for the self-update logic (pure logic only - no network, no GUI, no installer is ever run).
Run: python -m unittest discover tests"""
import hashlib
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config, update_checker as uc

GOOD = "a" * 64


def _asset(name="Scriptly-PC-Setup-0.19.0.exe", digest=f"sha256:{GOOD}", size=10, url=None):
    return {
        "name": name,
        "size": size,
        "digest": digest,
        "browser_download_url": url or f"{uc.ALLOWED_ASSET_PREFIX}v0.19.0/{name}",
    }


class TestVersionAndAsset(unittest.TestCase):
    def test_is_newer(self):
        self.assertTrue(uc.is_newer("v0.18.1", "0.18.0"))
        self.assertFalse(uc.is_newer("0.18.0", "0.18.0"))
        self.assertFalse(uc.is_newer("0.17.9", "0.18.0"))
        self.assertTrue(uc.is_newer("1.0", "0.99.9"))

    def test_extract_sha256(self):
        self.assertEqual(uc._extract_sha256(f"sha256:{GOOD.upper()}"), GOOD)
        for bad in (None, "", "md5:abc", "sha256:xyz", "sha256:" + "a" * 63, GOOD):
            self.assertEqual(uc._extract_sha256(bad), "")

    def test_find_asset_picks_cpu_installer_and_digest(self):
        data = {"assets": [
            _asset("notes.txt"),
            _asset("Scriptly-PC-Setup-0.19.0-gpu.exe"),
            _asset("Scriptly-PC-Setup-0.19.0.exe", size=123),
        ]}
        a = uc._find_installer_asset(data)
        self.assertEqual(a["name"], "Scriptly-PC-Setup-0.19.0.exe")
        self.assertEqual(a["size"], 123)
        self.assertEqual(a["sha256"], GOOD)

    def test_find_asset_missing_digest_is_not_blocking(self):
        a = uc._find_installer_asset({"assets": [_asset(digest=None)]})
        self.assertIsNotNone(a)
        self.assertEqual(a["sha256"], "")

    def test_find_asset_none(self):
        self.assertIsNone(uc._find_installer_asset({"assets": []}))
        self.assertIsNone(uc._find_installer_asset({}))
        self.assertIsNone(uc._find_installer_asset({"assets": [_asset("other.exe")]}))

    def test_trusted_url(self):
        self.assertTrue(uc.is_trusted_asset_url(uc.ALLOWED_ASSET_PREFIX + "v1/x.exe"))
        self.assertFalse(uc.is_trusted_asset_url("http://github.com/ofirshudari1-ship-it/scriptly-pc/releases/download/x"))
        self.assertFalse(uc.is_trusted_asset_url("https://evil.example/releases/download/x.exe"))
        self.assertFalse(uc.is_trusted_asset_url(None))


class TestVerify(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _file(self, data: bytes) -> Path:
        p = self.dir / "setup.exe"
        p.write_bytes(data)
        return p

    def test_ok_with_and_without_digest(self):
        data = b"MZ" + b"\x00" * 50
        p = self._file(data)
        self.assertEqual(uc.verify_installer_file(p, len(data), hashlib.sha256(data).hexdigest()), "")
        self.assertEqual(uc.verify_installer_file(p, len(data), ""), "")
        self.assertEqual(uc.verify_installer_file(p, 0, ""), "")

    def test_rejections(self):
        data = b"MZ" + b"\x00" * 50
        p = self._file(data)
        self.assertIn("size", uc.verify_installer_file(p, len(data) + 1, ""))
        self.assertIn("sha256", uc.verify_installer_file(p, len(data), GOOD))
        self.assertIn("MZ", uc.verify_installer_file(self._file(b"<html>captive portal</html>"), 0, ""))
        self.assertIn("empty", uc.verify_installer_file(self._file(b""), 0, ""))
        self.assertIn("cannot read", uc.verify_installer_file(self.dir / "missing.exe", 0, ""))

    def test_download_rejects_untrusted_url_without_network(self):
        with mock.patch.object(uc.requests, "get") as get:
            with self.assertRaises(uc.UpdateDownloadError):
                uc.download_installer({"name": "x.exe", "download_url": "https://evil.example/x.exe", "size": 1}, dest_dir=self.dir)
            get.assert_not_called()

    def test_download_deletes_non_exe(self):
        resp = mock.MagicMock()
        resp.__enter__.return_value = resp
        resp.headers = {}
        resp.iter_content.return_value = [b"<html>not an exe</html>"]
        with mock.patch.object(uc.requests, "get", return_value=resp):
            with self.assertRaises(uc.UpdateDownloadError):
                uc.download_installer(uc._find_installer_asset({"assets": [_asset(size=0, digest=None)]}), dest_dir=self.dir)
        self.assertEqual(list(self.dir.iterdir()), [])

    def test_download_success(self):
        payload = b"MZ" + b"\x01" * 100
        resp = mock.MagicMock()
        resp.__enter__.return_value = resp
        resp.headers = {"Content-Length": str(len(payload))}
        resp.iter_content.return_value = [payload[:50], payload[50:]]
        a = uc._find_installer_asset({"assets": [_asset(size=len(payload), digest="sha256:" + hashlib.sha256(payload).hexdigest())]})
        with mock.patch.object(uc.requests, "get", return_value=resp):
            path = uc.download_installer(a, dest_dir=self.dir)
        self.assertEqual(path.read_bytes(), payload)


class TestLaunch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.exe = Path(self.tmp.name) / "Scriptly-PC-Setup-9.9.9.exe"
        self.exe.write_bytes(b"MZ")

    def tearDown(self):
        self.tmp.cleanup()

    def test_args(self):
        self.assertEqual(uc.build_installer_args("C:/x y", True), ["--silent", "--relaunch", "--install-dir=C:/x y"])
        self.assertNotIn("--relaunch", uc.build_installer_args("C:/x", False))

    def test_plain_launch(self):
        popen, shell = mock.Mock(), mock.Mock()
        self.assertTrue(uc.launch_silent_installer(self.exe, "C:/app", popen=popen, shell_execute=shell))
        argv = popen.call_args[0][0]
        self.assertEqual(argv[0], str(self.exe))
        self.assertIn("--silent", argv)
        self.assertIn("--relaunch", argv)
        shell.assert_not_called()

    def test_winerror_740_falls_back_to_uac(self):
        err = OSError(740, "requires elevation")
        err.winerror = 740
        popen, shell = mock.Mock(side_effect=err), mock.Mock(return_value=True)
        self.assertTrue(uc.launch_silent_installer(self.exe, "C:/Program Files/Scriptly PC", popen=popen, shell_execute=shell))
        exe_arg, params = shell.call_args[0]
        self.assertEqual(exe_arg, str(self.exe))
        self.assertIn("--silent", params)
        self.assertIn('"--install-dir=C:/Program Files/Scriptly PC"', params)

    def test_uac_declined_returns_false(self):
        err = OSError(740, "x")
        err.winerror = 740
        self.assertFalse(uc.launch_silent_installer(
            self.exe, popen=mock.Mock(side_effect=err), shell_execute=mock.Mock(return_value=False)))

    def test_other_oserror_and_missing_file_do_not_raise(self):
        shell = mock.Mock()
        self.assertFalse(uc.launch_silent_installer(self.exe, popen=mock.Mock(side_effect=OSError(5, "denied")), shell_execute=shell))
        shell.assert_not_called()
        self.assertFalse(uc.launch_silent_installer(self.exe.with_name("nope.exe"), popen=mock.Mock(), shell_execute=shell))


class TestPendingAndPeriodic(unittest.TestCase):
    def test_pending_only_newer_and_existing(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "s.exe"
            f.write_bytes(b"MZ")
            with mock.patch.dict(uc._STAGED, {}, clear=True):
                self.assertIsNone(uc.pending_installer())
                uc._STAGED["0.0.1"] = str(f)  # older than current
                self.assertIsNone(uc.pending_installer())
                uc._STAGED["99.0.0"] = str(f)
                self.assertEqual(uc.pending_installer(), ("99.0.0", f))
                uc._STAGED["99.1.0"] = str(Path(d) / "gone.exe")  # missing file ignored
                self.assertEqual(uc.pending_installer()[0], "99.0.0")

    def test_periodic_checks_repeat_and_respect_toggle(self):
        calls, seen = [], threading.Event()

        def fake_check():
            calls.append(1)
            if len(calls) >= 3:
                seen.set()
            return {"version": "99.0.0", "url": "u", "asset": None}

        cfg = {"check_for_updates_enabled": True}
        got = []
        uc._stop_event.clear()
        with mock.patch.object(uc, "check_for_update_sync", fake_check):
            th = uc.start_periodic_checks(lambda: cfg, lambda *a: got.append(a), first_delay=0.01, interval=0.02)
            self.assertTrue(seen.wait(3), "periodic check did not repeat")
            cfg["check_for_updates_enabled"] = False
            n = len(calls)
            threading.Event().wait(0.15)
            self.assertLessEqual(len(calls) - n, 1)  # at most one in-flight tick after disabling
            uc.stop_periodic_checks()
            th.join(2)
            self.assertFalse(th.is_alive())
        uc._stop_event.clear()
        self.assertGreaterEqual(len(got), 3)


class TestConfigMigration(unittest.TestCase):
    def test_default_is_on(self):
        self.assertTrue(config.DEFAULTS["auto_update_enabled"])
        self.assertEqual(config.DEFAULTS["settings_version"], config.SETTINGS_VERSION)

    def test_old_saved_false_is_migrated_once(self):
        data, changed = config.migrate_config({"auto_update_enabled": False})
        self.assertTrue(changed)
        self.assertTrue(data["auto_update_enabled"])
        self.assertEqual(data["settings_version"], config.SETTINGS_VERSION)

    def test_later_opt_out_sticks(self):
        data, changed = config.migrate_config({"auto_update_enabled": False, "settings_version": config.SETTINGS_VERSION})
        self.assertFalse(changed)
        self.assertFalse(data["auto_update_enabled"])

    def test_garbage_version_is_treated_as_old(self):
        data, changed = config.migrate_config({"auto_update_enabled": False, "settings_version": "x"})
        self.assertTrue(changed)
        self.assertTrue(data["auto_update_enabled"])

    def test_load_config_persists_migration(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            cfg_path = d / "config.json"
            cfg_path.write_text('{"auto_update_enabled": false}', encoding="utf-8")
            with mock.patch.object(config, "APPDATA_DIR", d), mock.patch.object(config, "CONFIG_PATH", cfg_path):
                first = config.load_config()
                self.assertTrue(first["auto_update_enabled"])
                config.save_config({**first, "auto_update_enabled": False})  # user opts out
                second = config.load_config()
                self.assertFalse(second["auto_update_enabled"])


if __name__ == "__main__":
    unittest.main()
