import importlib.util
import ast
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PySidePreviewTests(unittest.TestCase):
    def test_preview_is_isolated_from_production_entry(self):
        source = (ROOT / "pyside_preview.py").read_text(encoding="utf-8")
        self.assertIn("class FrlgPreviewWindow(QMainWindow):", source)
        self.assertNotIn("from run_auto_rng_gui import", source)
        self.assertNotIn("EasyConController(", source)
        tree = ast.parse(source)
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.add((node.module or "").split(".")[0])
        self.assertFalse(imports & {"run_auto_rng_gui", "automation", "rng", "subprocess", "socket", "save_profiles", "tid_records", "tid_session"})
        self.assertEqual(
            (ROOT / "requirements-pyside-preview.txt").read_text(encoding="utf-8").splitlines()[-1],
            "PySide6>=6.7,<7",
        )

    @unittest.skipUnless(importlib.util.find_spec("PySide6"), "PySide6 is an optional preview dependency")
    def test_offscreen_preview_renders_a_real_png(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "preview.png"
            env = dict(os.environ)
            env["QT_QPA_PLATFORM"] = "offscreen"
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "pyside_preview.py"),
                    "--page",
                    "wild",
                    "--screenshot",
                    str(output),
                ],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            data = output.read_bytes()
            self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
            # Qt's Windows offscreen backend intentionally skips the system font
            # database, so its compressed PNG is much smaller than a real window
            # capture.  The header plus a non-trivial payload is enough here; the
            # Windows-backed screenshot is inspected separately during UI QA.
            self.assertGreater(len(data), 20_000)


@unittest.skipUnless(importlib.util.find_spec("PySide6"), "PySide6 is an optional preview dependency")
class PySidePreviewInteractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        from pyside_preview import FrlgPreviewWindow

        cls.app = QApplication.instance() or QApplication(["preview-tests", "-platform", "offscreen"])
        cls.window_class = FrlgPreviewWindow

    def setUp(self):
        self.window = self.window_class()

    def tearDown(self):
        self.window.settings_dialog.close()
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def test_auxiliary_pages_keep_input_mode_values_and_result(self):
        window = self.window
        self.assertEqual(window.input_mode, "sid")
        window.select_page("tid")
        window.fields["tid_target"].setText("00007")
        window.result_panel.setPlainText("Preserved result")
        action = window.search_button.text()
        for page in ("tid_records", "logs"):
            window.select_page(page)
            self.assertEqual(window.input_mode, "tid")
            self.assertEqual(window.search_button.text(), action)
            self.assertEqual(window.fields["tid_target"].text(), "00007")
            self.assertEqual(window.result_panel.toPlainText(), "Preserved result")
        self.assertEqual(window.records_table.rowCount(), 0)
        self.assertEqual(window.records_table.columnCount(), 11)

    def test_sid_count_disables_whole_slots_without_erasing_input(self):
        window = self.window
        window.fields["sid_count"].setValue(6)
        window.sid_party_widgets[5][0].setText("Saved species")
        self.assertTrue(all(w.isEnabled() for w in window.sid_party_widgets[5]))
        window.fields["sid_count"].setValue(1)
        self.assertTrue(all(w.isEnabled() for w in window.sid_party_widgets[0]))
        self.assertTrue(all(not w.isEnabled() for row in window.sid_party_widgets[1:] for w in row))
        window.fields["sid_count"].setValue(6)
        self.assertEqual(window.sid_party_widgets[5][0].text(), "Saved species")

    def test_iv_presets_are_exact_and_single_reset_is_local(self):
        expected = {
            "6V": [31, 31, 31, 31, 31, 31],
            "0A": [31, 0, 31, 31, 31, 31],
            "0S": [31, 31, 31, 31, 31, 0],
            "0A0S": [31, 0, 31, 31, 31, 0],
        }
        for name, values in expected.items():
            self.window._apply_iv_preset(name)
            self.assertEqual([(a.value(), b.value()) for a, b in self.window.iv_ranges], [(v, v) for v in values])
        self.window._reset_iv(2)
        self.assertEqual([(a.value(), b.value()) for a, b in self.window.iv_ranges], [(31, 31), (0, 0), (0, 31), (31, 31), (31, 31), (0, 0)])

    def test_wild_modes_and_shared_egg_identity(self):
        window = self.window
        window.item_check.setChecked(True)
        self.assertFalse(window.traversal_check.isEnabled())
        self.assertTrue(window.fields["wild_slots"].isEnabled())
        window.fields["wild_method"].setCurrentIndex(1)
        self.assertFalse(window.item_check.isChecked())
        self.assertFalse(window.item_check.isEnabled())
        self.assertEqual(window.fields["wild_category"].count(), 7)
        window.fields["wild_game"].setCurrentIndex(1)
        window.fields["egg_nx"].setCurrentIndex(1)
        self.assertEqual(window.fields["egg_game"].currentIndex(), 1)
        self.assertEqual(window.fields["wild_nx"].currentIndex(), 1)
        self.assertFalse(window.fields["wild_direct_seed"].isEnabled())
        window.fields["wild_search_mode"].setCurrentIndex(1)
        self.assertTrue(window.fields["wild_direct_seed"].isEnabled())

    def test_tid_exhaustive_flow_and_manual_delay(self):
        window = self.window
        self.assertTrue(window.tid_special_checks[2].isChecked())
        window.fields["tid_mode"].setCurrentIndex(1)
        self.assertEqual(window.fields["tid_sid_mode"].currentIndex(), 1)
        self.assertFalse(window.fields["tid_sid_mode"].isEnabled())
        self.assertFalse(window.fields["tid_sid"].isEnabled())
        self.assertFalse(window.fields["starter_retry"].isEnabled())
        window.tid_any_check.setChecked(True)
        self.assertFalse(window.fields["tid_target"].isEnabled())
        self.assertTrue(window.tid_denoise_check.isEnabled())
        self.assertTrue(all(not c.isEnabled() for c in window.tid_special_checks))
        window.tid_flow_check.setChecked(False)
        self.assertTrue(window.fields["tid_target"].isEnabled())
        self.assertFalse(window.fields["starter_species"].isEnabled())
        self.assertFalse(window.fields["tid_op_delay"].isEnabled())
        window.tid_manual_delay.setChecked(True)
        self.assertTrue(window.fields["tid_op_delay"].isEnabled())
        window.fields["tid_language"].setCurrentIndex(1)
        self.assertEqual(window.fields["tid_op_delay"].text(), "30650")
        self.assertEqual(window.fields["tid_f1_start"].text(), "0")
        self.assertEqual(window.fields["tid_target"].text(), "00001")

    def test_advanced_scope_and_egg_defaults(self):
        window = self.window
        self.assertTrue(window.nav_buttons["script_test"].isHidden())
        window.select_page("egg")
        self.assertEqual(window.fields["seed_calibration"].currentIndex(), 2)
        window.advanced_check.setChecked(True)
        self.assertFalse(window.nav_buttons["script_test"].isHidden())
        self.assertFalse(window.fields["parity"].isEnabled())
        self.assertEqual(window.fields["parity"].currentIndex(), 0)
        window.select_page("script_test")
        self.assertEqual(window.fields["script_entry"].count(), 3)
        self.assertTrue(window.advanced_options.isHidden())
        window.fields["script_entry"].setCurrentIndex(2)
        window.advanced_check.setChecked(False)
        self.assertEqual(window.input_mode, "wild")
        self.assertEqual(window.fields["script_entry"].currentIndex(), 0)
        self.assertEqual(window.fields["script_entry"].count(), 2)
        self.assertFalse(window.fields["tid_pid"].isEnabled())

    def test_backend_actions_stay_disabled_in_every_mode(self):
        from PySide6.QtWidgets import QPushButton
        window = self.window
        window.sid_ack.setChecked(True)
        window.egg_ack.setChecked(True)
        for advanced in (True, False):
            window.advanced_check.setChecked(advanced)
            for page in window.page_indices:
                if page == "script_test" and not advanced:
                    continue
                window.select_page(page)
                actions = [b for b in window.findChildren(QPushButton) if b.property("backendAction")]
                self.assertGreater(len(actions), 20)
                self.assertTrue(all(not button.isEnabled() for button in actions))

    def test_minimum_window_and_bottom_reachability(self):
        from PySide6.QtCore import QSize
        from pyside_preview import NAV_ITEMS
        window = self.window
        self.assertEqual([k for k, _, _ in NAV_ITEMS], ["sid", "tid", "tid_records", "wild", "egg", "script_test", "logs"])
        window.resize(900, 620)
        window.show()
        window.advanced_check.setChecked(True)
        for page in window.page_indices:
            window.select_page(page)
            self.app.processEvents()
            self.assertEqual(window.size(), QSize(900, 620), page)
            scroll = window.stack.currentWidget()
            self.assertEqual(scroll.horizontalScrollBar().maximum(), 0, page)
            bar = scroll.verticalScrollBar()
            bar.setValue(bar.maximum())
            self.app.processEvents()
            self.assertEqual(bar.value(), bar.maximum(), page)
            self.assertTrue(window.search_button.isVisible())


if __name__ == "__main__":
    unittest.main()
