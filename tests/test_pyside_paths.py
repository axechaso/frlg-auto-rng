import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from automation import probe_easycon_devices
from pyside_app.path_settings import restore_resource_path


class ResourcePathTests(unittest.TestCase):
    def test_existing_custom_paths_are_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            custom = root / "custom" / "ezcon.exe"
            custom.parent.mkdir()
            custom.touch()
            for frozen in (False, True):
                with self.subTest(frozen=frozen), patch(
                    "pyside_app.path_settings.sys", SimpleNamespace(frozen=frozen)
                ):
                    self.assertEqual(restore_resource_path(
                        str(custom), root / "default.exe",
                        bundled_suffix="_internal/easycon/publish/ezcon.exe", file=True,
                    ), str(custom))

    def test_missing_custom_paths_only_fall_back_to_usable_defaults(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            missing = str(root / "removed" / "custom")
            default = root / "default"
            self.assertEqual(restore_resource_path(missing, default, bundled_suffix="_internal/source"), missing)
            default.mkdir()
            self.assertEqual(restore_resource_path(missing, default, bundled_suffix="_internal/source"), str(default))
            # A directory does not satisfy an executable-file default.
            self.assertEqual(restore_resource_path(missing, default, bundled_suffix="_internal/ezcon.exe", file=True), missing)

    def test_source_mode_keeps_existing_bundle_selected_by_user(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            saved = root / "old" / "_internal" / "local_assets" / "easycon118"
            saved.mkdir(parents=True)
            with patch("pyside_app.path_settings.sys", SimpleNamespace(frozen=False)):
                self.assertEqual(restore_resource_path(
                    str(saved), root / "current", bundled_suffix="_internal/local_assets/easycon118",
                ), str(saved))

    def test_frozen_bundle_never_uses_previous_install_as_missing_resource_fallback(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            saved = root / "old" / "_internal" / "easycon" / "publish" / "ezcon.exe"
            saved.parent.mkdir(parents=True)
            saved.touch()
            current = root / "current" / "ezcon.exe"
            with patch("pyside_app.path_settings.sys", SimpleNamespace(frozen=True)):
                self.assertEqual(restore_resource_path(
                    str(saved), current, bundled_suffix="_internal/easycon/publish/ezcon.exe", file=True,
                ), str(current))

    def test_missing_executable_names_path_and_recovery_without_launch(self):
        with tempfile.TemporaryDirectory() as temp, patch("automation.easycon118.subprocess.run") as run:
            missing = Path(temp) / "removed" / "ezcon.exe"
            with self.assertRaises(FileNotFoundError) as caught:
                probe_easycon_devices(missing)
            self.assertIn(str(missing), str(caught.exception))
            self.assertIn("共通设置", str(caught.exception))
            self.assertIn("完整解压", str(caught.exception))
            run.assert_not_called()


@unittest.skipUnless(importlib.util.find_spec("PySide6"), "PySide6 is optional")
class StartupPathTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(["path-tests", "-platform", "offscreen"])

    def check_startup(self, old_exists):
        from PySide6.QtTest import QTest
        from pyside_app.migration import CompleteWindow
        from pyside_app.services import AppPaths

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            suffixes = {
                "source": "_internal/local_assets/easycon118",
                "ezcon": "_internal/easycon/publish/ezcon.exe",
                "sid_source": "_internal/local_assets/easycon118",
                "tid_source": "_internal/local_assets/tid_rng137",
            }
            defaults = {key: root / "0.9.1 中文" / suffix for key, suffix in suffixes.items()}
            saved = {key: root / "0.9" / suffix for key, suffix in suffixes.items()}
            for locations in (defaults, saved) if old_exists else (defaults,):
                for key, path in locations.items():
                    if key == "ezcon":
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.touch()
                    else:
                        path.mkdir(parents=True, exist_ok=True)
            settings = root / "pyside6_settings.json"
            settings.write_text(json.dumps({key: str(path) for key, path in saved.items()}), encoding="utf-8")
            # The original saved configuration remains untouched while loading.
            original_settings = settings.read_bytes()
            paths = AppPaths(user=root, output=root / "runtime", source=defaults["source"],
                             ezcon=defaults["ezcon"], tid_source=defaults["tid_source"])
            errors = []
            response = subprocess.CompletedProcess([], 0, stdout="", stderr="")
            with patch("pyside_app.path_settings.sys", SimpleNamespace(frozen=True)), \
                 patch("automation.easycon118.subprocess.run", return_value=response) as run:
                window = CompleteWindow(paths=paths, auto_detect=True)
                window.show_error = errors.append
                try:
                    for _ in range(200):
                        QTest.qWait(10)
                        if window.devices_checked or errors:
                            break
                    self.assertEqual(errors, [])
                    self.assertTrue(window.devices_checked)
                    self.assertEqual(settings.read_bytes(), original_settings)
                    for key, value in defaults.items():
                        self.assertEqual(window.fields[key].text(), str(value), key)
                    self.assertEqual([call.args[0] for call in run.call_args_list], [
                        [str(defaults["ezcon"]), "port", "--list"],
                        [str(defaults["ezcon"]), "video", "--list"],
                    ])
                finally:
                    window.close()
                    window.deleteLater()
                    self.app.processEvents()
            restored = json.loads(settings.read_text(encoding="utf-8"))
            self.assertEqual(restored, {key: str(value) for key, value in defaults.items()})

    def test_startup_recovers_after_previous_package_is_removed(self):
        self.check_startup(old_exists=False)

    def test_startup_uses_current_bundle_when_previous_package_still_exists(self):
        self.check_startup(old_exists=True)
