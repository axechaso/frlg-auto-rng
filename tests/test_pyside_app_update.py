import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app_updater import (
    PreparedUpdate,
    UpdateCandidate,
    UpdateCheckResult,
    UpdateManifest,
)


def candidate() -> UpdateCandidate:
    manifest = UpdateManifest(
        schema=1,
        version="0.9",
        version_code=2026090701,
        package="FRLG-Auto-RNG-0.9-windows-x64.zip",
        sha256="a" * 64,
        bytes=123,
        unpacked_bytes=456,
        release_url="https://github.com/axechaso/frlg-auto-rng/releases/tag/v0.9",
        notes="PySide6 正式版。",
    )
    return UpdateCandidate(
        manifest=manifest,
        package_url=(
            "https://github.com/axechaso/frlg-auto-rng/releases/download/v0.9/"
            + manifest.package
        ),
        published_at="2026-09-07T12:00:00Z",
        tag_name="v0.9",
    )


@unittest.skipUnless(importlib.util.find_spec("PySide6"), "PySide6 is optional")
class PySideAppUpdateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication(
            ["pyside-update-tests", "-platform", "offscreen"]
        )

    def setUp(self):
        from pyside_app.migration import CompleteWindow
        from pyside_app.services import AppPaths

        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.window = CompleteWindow(
            paths=AppPaths(user=self.root / "user", output=self.root / "runtime"),
            auto_detect=False,
        )
        self.window.show()

    def tearDown(self):
        if getattr(self.window, "job", None):
            self.window.job.cancelled.set()
            self.wait_until(lambda: self.window.job is None)
        if self.window.isVisible():
            self.window.close()
        self.window.deleteLater()
        self.app.processEvents()
        self.temp.cleanup()

    def wait_until(self, predicate, limit=10000):
        from PySide6.QtTest import QTest

        elapsed = 0
        while not predicate() and elapsed < limit:
            QTest.qWait(20)
            elapsed += 20
        self.assertTrue(predicate(), "Qt update operation did not complete")

    def test_source_mode_button_explains_without_network(self):
        from PySide6.QtWidgets import QMessageBox

        with (
            patch(
                "pyside_app.app_update.check_for_update",
                side_effect=AssertionError("source mode must not use the network"),
            ),
            patch.object(QMessageBox, "information", return_value=QMessageBox.StandardButton.Ok),
        ):
            self.window.actions["检查程序更新"].click()

        self.assertIn("源码模式", self.window.app_update.status.text())

    def test_manual_current_check_reports_result(self):
        from PySide6.QtWidgets import QMessageBox

        self.window.app_update.frozen = True
        self.window.fields["update_source"].setCurrentIndex(
            self.window.fields["update_source"].findData("gitee")
        )
        with (
            patch(
                "pyside_app.app_update.check_for_update",
                return_value=UpdateCheckResult("current", "当前已是最新正式版。"),
            ) as check,
            patch.object(QMessageBox, "information", return_value=QMessageBox.StandardButton.Ok),
        ):
            self.window.actions["检查程序更新"].click()
            self.wait_until(lambda: self.window.job is None)

        self.assertEqual(self.window.app_update.status.text(), "当前已是最新正式版。")
        self.assertEqual(check.call_args.kwargs["source"], "gitee")

    def test_update_source_defaults_to_auto_and_persists_manual_choice(self):
        combo = self.window.fields["update_source"]
        self.assertEqual(combo.currentData(), "auto")
        self.assertEqual(
            [combo.itemData(index) for index in range(combo.count())],
            ["auto", "github", "gitee"],
        )
        combo.setCurrentIndex(combo.findData("gitee"))
        self.assertIsNone(self.window.app_update.candidate)
        self.window.close()
        saved = json.loads(
            (self.root / "user" / "pyside6_settings.json").read_text(encoding="utf-8")
        )
        self.assertEqual(saved["update_source"], "gitee")

    def test_label_supervision_defaults_off_and_persists_opt_in(self):
        self.assertFalse(self.window.label_supervision_check.isChecked())
        self.window.label_supervision_check.setChecked(True)
        self.window.close()
        saved = json.loads(
            (self.root / "user" / "pyside6_settings.json").read_text(encoding="utf-8")
        )
        self.assertIs(saved["label_supervision"], True)

        from pyside_app.migration import CompleteWindow
        from pyside_app.services import AppPaths

        self.window.deleteLater()
        self.app.processEvents()
        self.window = CompleteWindow(
            paths=AppPaths(user=self.root / "user", output=self.root / "runtime-2"),
            auto_detect=False,
        )
        self.assertTrue(self.window.label_supervision_check.isChecked())

    def test_running_process_defers_available_install(self):
        from PySide6.QtWidgets import QMessageBox

        self.window.app_update.frozen = True
        self.window.running = True
        self.window.refresh_state()
        with (
            patch(
                "pyside_app.app_update.check_for_update",
                return_value=UpdateCheckResult("available", "发现新版本 0.9。", candidate()),
            ),
            patch.object(QMessageBox, "question") as question,
        ):
            self.window.actions["检查程序更新"].click()
            self.wait_until(lambda: self.window.job is None)

        self.assertIn("当前任务结束后", self.window.app_update.status.text())
        question.assert_not_called()
        self.window.running = False

    def test_confirmed_update_prepares_launches_and_closes(self):
        from PySide6.QtWidgets import QMessageBox

        chosen = candidate()
        install = self.root / "install"
        stage = self.root / (".frlg-update-stage-" + "1" * 32)
        install.mkdir()
        stage.mkdir()
        (install / "FRLG-Auto-RNG.exe").write_bytes(b"old")
        (install / "FRLG-Auto-RNG-Updater.exe").write_bytes(b"updater")
        prepared = PreparedUpdate(
            request_id="1" * 32,
            token="2" * 32,
            install_dir=install.resolve(),
            stage_dir=stage.resolve(),
            package_path=self.root / chosen.manifest.package,
            manifest=chosen.manifest,
            updates_root=(self.root / "user" / "updates").resolve(),
            updater_source=(install / "FRLG-Auto-RNG-Updater.exe").resolve(),
            expected_version_code=2026090701,
        )
        prepared_marker = self.root / "prepared.txt"
        launched = self.root / "launched.json"

        def prepare(_candidate, **_kwargs):
            prepared_marker.write_text("0.9", encoding="utf-8")
            return prepared

        def popen(arguments, **kwargs):
            launched.write_text(
                json.dumps({"arguments": arguments, "cwd": str(kwargs["cwd"])}),
                encoding="utf-8",
            )
            return SimpleNamespace(pid=123)

        self.window.app_update.frozen = True
        self.window.app_update.executable = install / "FRLG-Auto-RNG.exe"
        with (
            patch(
                "pyside_app.app_update.check_for_update",
                return_value=UpdateCheckResult("available", "发现新版本 0.9。", chosen),
            ),
            patch("pyside_app.app_update.prepare_update", side_effect=prepare),
            patch("pyside_app.app_update.subprocess.Popen", side_effect=popen),
            patch.object(
                QMessageBox,
                "question",
                return_value=QMessageBox.StandardButton.Yes,
            ),
        ):
            self.window.actions["检查程序更新"].click()
            self.wait_until(lambda: not self.window.isVisible())

        self.assertEqual(prepared_marker.read_text(encoding="utf-8"), "0.9")
        launch = json.loads(launched.read_text(encoding="utf-8"))
        request_path = Path(launch["arguments"][2])
        request = json.loads(request_path.read_text(encoding="utf-8"))
        self.assertEqual(request["version_code"], 2026090701)
        self.assertTrue((request_path.parent / "FRLG-Auto-RNG-Updater.exe").is_file())


if __name__ == "__main__":
    unittest.main()
