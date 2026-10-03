import json
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication
from pyside_app.migration import CompleteWindow
from pyside_app.services import AppPaths


class FreshDefaultsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_first_start_and_saved_preferences_survive_restart_with_matching_titles(self):
        for values in (None, {}, {"update_precalibration": False, "record_shiny_video": False},
                       {"update_precalibration": True, "record_shiny_video": False},
                       {"update_precalibration": False, "record_shiny_video": True}):
            with self.subTest(values=values), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                settings = root / "pyside6_settings.json"
                self.assertFalse(settings.exists())
                if values is not None:
                    settings.write_text(json.dumps(values), encoding="utf-8")
                for _ in range(2):
                    w = CompleteWindow(paths=AppPaths(user=root, output=root / "runtime"), auto_detect=False)
                    try:
                        for key, button in (("update_precalibration", w.precalibration_check),
                                            ("record_shiny_video", w.record_shiny_video_check)):
                            expected = (values or {}).get(key, True)
                            self.assertEqual(button.isChecked(), expected)
                            self.assertEqual(button.text().count("✓"), int(expected))
                            self.assertEqual(w.settings_payload()[key], expected)
                    finally:
                        w.close()
                        w.deleteLater()
                        self.app.processEvents()

    def test_invalid_preferences_are_preserved(self):
        for raw in ('{"update_precalibration":"false"}', '{broken'):
            with tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                path = root / "pyside6_settings.json"
                path.write_text(raw, encoding="utf-8")
                w = CompleteWindow(paths=AppPaths(user=root, output=root / "runtime"), auto_detect=False)
                self.assertTrue(w._settings_invalid)
                w.close()
                w.deleteLater()
                self.app.processEvents()
                self.assertEqual(path.read_text(encoding="utf-8"), raw)
