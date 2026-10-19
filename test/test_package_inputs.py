from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest
import zipfile
import sys


SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "package-client.ps1"
POWERSHELL = shutil.which("pwsh.exe") or shutil.which("powershell.exe")


class PackageArchiveTests(unittest.TestCase):
    def test_embedded_zipper_preserves_nested_files_and_refuses_overwrite(self):
        script = SCRIPT.read_text(encoding="utf-8-sig")
        zipper = script.split("$zipper = @'\n", 1)[1].split("\n'@", 1)[0]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "app"
            (root / "runtime").mkdir(parents=True)
            (root / "runtime/service.bin").write_bytes(b"service-fixture")
            archive = Path(temporary) / "package.zip"
            command = [sys.executable, "-c", zipper, str(root), str(archive)]
            subprocess.run(command, check=True, capture_output=True)
            with zipfile.ZipFile(archive) as package:
                self.assertEqual(package.namelist(), ["runtime/service.bin"])
                self.assertEqual(package.read("runtime/service.bin"), b"service-fixture")
            original = archive.read_bytes()
            self.assertNotEqual(subprocess.run(command, capture_output=True).returncode, 0)
            self.assertEqual(archive.read_bytes(), original)


@unittest.skipUnless(os.name == "nt" and POWERSHELL, "Windows PowerShell is required for package preflight tests")
class PackageClientPreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="farry-package-preflight-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "farry"
        self.script = self.repo / "tools" / "package-client.ps1"
        self.project = self.root / "project"
        self.build = self.root / "build"
        self.qt = self.root / "qt"
        self.output = self.root / "release"
        self.version = f"8.0.{time.time_ns() % 900000 + 100000}"
        self.work = self.repo / "work" / f"package-{self.version}"
        (self.repo / "tools").mkdir(parents=True)
        (self.repo / "secrets").mkdir()
        (self.repo / "work" / "build-dependencies").mkdir(parents=True)
        shutil.copy2(SCRIPT, self.script)
        for relative in (
            "app.js",
            "secrets/update-private.pem",
            "tools/sign-internal.ps1",
            "tools/sign-release.mjs",
            "tools/check-release.mjs",
        ):
            path = self.repo / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"test placeholder")

        for relative in (
            ".venv/Scripts",
            "packaging",
            "desktop/resources",
            "moneymin/resources",
            "scripts",
            "tools/ffmpeg",
            "tools/ms-playwright",
            "dist-local",
        ):
            (self.project / relative).mkdir(parents=True, exist_ok=True)
        (self.build).mkdir()
        (self.qt / "bin").mkdir(parents=True)

        for relative in (
            ".venv/Scripts/python.exe",
            "packaging/qmoney_service.py",
            "desktop/resources/qmoney.ico",
            "moneymin/samsung_uw_calibration.json",
            "moneymin/minute_task_names.json",
            "scripts/verify_packaged_service.py",
            "scripts/browser_parts.ps1",
            "tools/ffmpeg/ffmpeg.exe",
            "tools/ffmpeg/ffprobe.exe",
            "tools/ms-playwright/browsers.json",
            "tools/platform-tools/adb.exe",
            "tools/platform-tools/AdbWinApi.dll",
            "tools/platform-tools/AdbWinUsbApi.dll",
            "tools/platform-tools/NOTICE.txt",
            "tools/platform-tools/source.properties",
        ):
            path = self.project / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"fixture")
        (self.qt / "bin" / "windeployqt.exe").write_bytes(b"fixture")

        system_gui = Path(os.environ["WINDIR"]) / "System32" / "whoami.exe"
        self.assertTrue(system_gui.is_file(), "Windows whoami.exe is needed as a mismatched PE fixture")
        shutil.copy2(system_gui, self.build / "QMoney.exe")
        (self.build / "QMoneyUpdater.exe").write_bytes(b"fixture")
        self.sentinel = self.project / "dist-local/QMoney.exe"
        self.sentinel.write_bytes(b"preserve-dist-local")

    def run_package(self, *, mocked_versions=False):
        script = self.script
        if mocked_versions:
            script = self.root / "run-package-with-version-fixture.ps1"
            script.write_text(
                f'''function Get-Item {{
    param([string]$LiteralPath)
    if ([IO.Path]::GetFileName($LiteralPath) -eq 'QMoney.exe') {{
        return [pscustomobject]@{{ VersionInfo = [pscustomobject]@{{ ProductVersion = '{self.version}' }} }}
    }}
    if ([IO.Path]::GetFileName($LiteralPath) -eq 'FarrySetup.exe') {{
        return [pscustomobject]@{{ VersionInfo = [pscustomobject]@{{ ProductVersion = '1.0.0' }} }}
    }}
    Microsoft.PowerShell.Management\\Get-Item -LiteralPath $LiteralPath
}}
& '{self.script}' -ProjectRoot '{self.project}' -BuildDirectory '{self.build}' -QtRoot '{self.qt}' `
    -Version '{self.version}' -OutputDirectory '{self.output}'
''',
                encoding="utf-8",
            )
        return subprocess.run(
            [
                POWERSHELL,
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
                "-ProjectRoot",
                str(self.project),
                "-BuildDirectory",
                str(self.build),
                "-QtRoot",
                str(self.qt),
                "-Version",
                self.version,
                "-OutputDirectory",
                str(self.output),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

    def assert_preflight_left_artifacts_untouched(self):
        self.assertFalse(self.output.exists())
        self.assertFalse(self.work.exists())
        self.assertEqual(self.sentinel.read_bytes(), b"preserve-dist-local")

    def test_missing_compiled_updater_fails_before_writing(self):
        (self.build / "QMoneyUpdater.exe").unlink()

        result = self.run_package()

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("QMoneyUpdater.exe", result.stdout + result.stderr)
        self.assert_preflight_left_artifacts_untouched()

    def test_missing_platform_tools_dll_fails_before_writing(self):
        (self.project / "tools/platform-tools/AdbWinApi.dll").unlink()

        result = self.run_package()

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("AdbWinApi.dll", result.stdout + result.stderr)
        self.assert_preflight_left_artifacts_untouched()

    def test_wrong_compiled_gui_version_fails_before_writing(self):
        result = self.run_package()

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("10.0.", result.stdout + result.stderr)
        self.assertIn(self.version, result.stdout + result.stderr)
        self.assert_preflight_left_artifacts_untouched()

    def test_stale_installer_version_fails_before_writing(self):
        self.output.mkdir()
        (self.output / "FarrySetup.exe").write_bytes(b"installer-fixture")

        result = self.run_package(mocked_versions=True)

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("1.0.0", result.stdout + result.stderr)
        self.assertFalse(self.work.exists())
        self.assertEqual(self.sentinel.read_bytes(), b"preserve-dist-local")


if __name__ == "__main__":
    unittest.main()
