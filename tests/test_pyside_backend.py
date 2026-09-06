import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


@unittest.skipUnless(importlib.util.find_spec("PySide6"), "PySide6 is optional")
class PySideBackendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        from pyside_app.window import FrlgWindow
        cls.app = QApplication.instance() or QApplication(["backend-tests", "-platform", "offscreen"])
        cls.window_class = FrlgWindow

    def setUp(self):
        from pyside_app.services import AppPaths
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.window = self.window_class(paths=AppPaths(user=self.root, output=self.root / "runtime"), auto_detect=False)
        self.errors = []
        self.window.show_error = self.errors.append
        self.window.fields["wild_tid"].setText("12345")
        self.window.fields["wild_sid"].setText("54321")

    def tearDown(self):
        if self.window.job:
            self.window.job.cancelled.set()
            self.wait_until(lambda: self.window.job is None)
        if self.window.running:
            self.window.stop_run()
            self.wait_until(lambda: not self.window.running)
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
        self.assertTrue(predicate(), "Qt task did not complete")

    def prepared(self):
        from automation import EasyConRuntimeCheck
        from pyside_app.services import PreparedWild
        from tests.test_pyside_services import sample_result
        inputs = self.window.collect_inputs()
        return PreparedWild(inputs, sample_result(), self.root / "main.ecs", self.root / "plan.json", EasyConRuntimeCheck(True, (), ()))

    def test_real_catalog_and_form_keep_bounds_and_post_capture_options(self):
        w = self.window
        self.assertEqual(w.fields["wild_species"].currentData(), "Pikachu")
        self.assertTrue(w.fields["wild_ability"].isEnabled())
        w.fields["wild_min"].setText("8123")
        w.capture_checks[0].setChecked(True)
        w.capture_checks[2].setChecked(True)
        w.item_check.setChecked(True)
        w.fields["wild_slots"].setValue(4)
        inputs = w.collect_inputs()
        self.assertEqual(inputs.request.min_advances, 8123)
        self.assertTrue(inputs.options.continue_capture_after_shiny)
        self.assertTrue(inputs.options.false_swipe)
        self.assertFalse(inputs.options.paralysis)
        self.assertEqual(inputs.options.party_empty_slots, 4)
        w.fields["wild_method"].setCurrentIndex(1)
        self.assertEqual(w.collect_inputs().request.method, "Static 1")
        self.assertFalse(w.item_check.isChecked())

    def test_no_placeholder_device_is_treated_as_connected(self):
        w = self.window
        w.prepared = self.prepared()
        w.refresh_state()
        self.assertFalse(w.start_button.isEnabled())
        self.assertIsNone(w.fields["video"].currentData())
        with patch("pyside_app.window.probe_easycon_devices", return_value=(set(), {}, "none")):
            w.detect_devices()
            self.wait_until(lambda: w.job is None)
        self.assertFalse(w.start_button.isEnabled())
        self.assertEqual(w.ready_values[0].text(), "未发现串口")

    def test_changed_input_rejects_stale_background_result(self):
        w = self.window
        stale = self.prepared()
        w.fields["wild_min"].setText("8000")
        w._search_finished(stale)
        self.assertIsNone(w.prepared)
        self.assertFalse(w.start_button.isEnabled())

    def test_detected_devices_do_not_clear_an_unchanged_plan(self):
        w = self.window
        devices = ({"COM4"}, {3: "Capture"}, "ok")
        with patch("pyside_app.window.probe_easycon_devices", return_value=devices):
            w.detect_devices()
            self.wait_until(lambda: w.job is None)
            w.prepared = self.prepared()
            original = w.prepared
            w.detect_devices()
            self.wait_until(lambda: w.job is None)
        self.assertIs(w.prepared, original)
        self.assertTrue(w.start_button.isEnabled())
        w.fields["wild_min"].setText("8123")
        self.assertFalse(w.start_button.isEnabled())
        self.assertIsNone(w.prepared)

    def test_profile_application_preserves_tid_delays_and_shares_identity(self):
        w = self.window
        w.fields["tid_op_delay"].setText("31234")
        profile = w.profile_store.add("Test", "叶绿", "00007", 123, 2, language="日文")
        w.reload_profiles(apply=True)
        self.assertEqual(w.fields["wild_tid"].text(), "7")
        self.assertEqual(w.fields["tid_target"].text(), "00007")
        self.assertEqual(w.fields["tid_op_delay"].text(), "31234")
        self.assertEqual(w.fields["profile_language"].currentIndex(), 1)
        self.assertEqual(w.fields["egg_nx"].currentText(), "Switch 2")
        self.assertEqual(w.profile_store.get(profile.profile_id).tid, 7)

    def test_cancellation_discards_completed_job_result(self):
        from PySide6.QtTest import QTest
        w = self.window
        results = []
        def work(cancel, status):
            while not cancel():
                import time
                time.sleep(0.005)
            return "must not commit"
        w.launch_job(work, results.append, "working")
        w.cancel()
        self.wait_until(lambda: w.job is None)
        self.assertEqual(results, [])

    def test_real_log_wrapper_streams_split_utf8_without_starting_easycon(self):
        from pyside_app.services import RunCommand
        from app_paths import RESOURCE_ROOT
        from automation import EasyConRuntimeCheck
        w = self.window
        log = self.root / "process.log"
        stop = self.root / "stop"
        payload = "你好\nTIDPROGRESS|V=3|COUNT=4|END=1\nfinal\n".encode("utf-8")
        code = f"import sys,time; b={payload!r}; sys.stdout.buffer.write(b[:2]); sys.stdout.buffer.flush(); time.sleep(.05); sys.stdout.buffer.write(b[2:]); sys.stdout.buffer.flush()"
        arguments = ("-u", str(RESOURCE_ROOT / "run_easycon_logged.py"), "--log-path", str(log), "--cwd", str(self.root), "--stop-file", str(stop), "--", sys.executable, "-u", "-c", code)
        w.run_command = RunCommand(sys.executable, arguments, log, stop, "", EasyConRuntimeCheck(True, (), ()))
        w.process.start(sys.executable, list(arguments))
        self.wait_until(lambda: log.is_file() and w.process.state().value == 0)
        self.app.processEvents()
        self.assertIn("你好", w.log_view.toPlainText())
        self.assertNotIn("TIDPROGRESS", w.log_view.toPlainText())
        self.assertIn("TIDPROGRESS", log.read_text(encoding="utf-8"))
        self.assertEqual(w.current_page, "logs")
        self.assertFalse(w.running)

    def test_pending_log_is_visible_then_replaced_without_duplicate_lines(self):
        w = self.window
        w.log_view.clear()
        w._append_log("目标")
        self.assertEqual(w.log_view.toPlainText(), "目标")
        w._append_log("信息\nTIDPROG")
        self.assertEqual(w.log_view.toPlainText(), "目标信息\nTIDPROG")
        w._append_log("RESS|V=3|COUNT=4|END=1\n当前")
        self.assertEqual(w.log_view.toPlainText(), "目标信息\n当前")
        w._append_log("进度", final=True)
        self.assertEqual(w.log_view.toPlainText(), "目标信息\n当前进度")

    def test_stop_and_close_terminate_only_owned_benign_worker(self):
        from pyside_app.services import RunCommand
        from app_paths import RESOURCE_ROOT
        from automation import EasyConRuntimeCheck
        w = self.window
        log, stop = self.root / "stop-test.log", self.root / "stop-test.stop"
        arguments = ("-u", str(RESOURCE_ROOT / "run_easycon_logged.py"), "--log-path", str(log),
                     "--cwd", str(self.root), "--stop-file", str(stop), "--", sys.executable,
                     "-u", "-c", "import time; print('ready', flush=True); time.sleep(30)")
        w.run_command = RunCommand(sys.executable, arguments, log, stop, "", EasyConRuntimeCheck(True, (), ()))
        w.show()
        w.process.start(sys.executable, list(arguments))
        self.wait_until(lambda: "ready" in w.log_view.toPlainText())
        w.close()
        self.wait_until(lambda: not w.running)
        self.assertTrue(stop.is_file())
        self.assertEqual(w.process.exitCode(), 130)
        self.assertFalse(w.isVisible())

    def test_start_button_uses_checked_command_and_locks_inputs_until_finished(self):
        from automation import EasyConRuntimeCheck
        from PySide6.QtWidgets import QMessageBox
        from pyside_app.services import RunCommand
        w = self.window
        w.devices = ({"COM4"}, {3: "Capture"})
        w._fill(w.fields["port"], [("COM4", "COM4")])
        w._fill(w.fields["video"], [("Capture", 3)])
        w.prepared = self.prepared()
        checked = w.prepared
        command = RunCommand(sys.executable, ("-u", "-c", "import time; print('checked command'); time.sleep(.2)"),
                             self.root / "no-hardware.log", self.root / "stop", "", EasyConRuntimeCheck(True, (), ()))
        w.refresh_state()
        self.assertTrue(w.start_button.isEnabled())
        with patch("pyside_app.window.prepare_run", return_value=command) as prepare, \
             patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            w.start_button.click()
            self.wait_until(lambda: w.running)
            self.assertFalse(w.fields["wild_game"].isEnabled())
            self.assertFalse(w.fields["video"].isEnabled())
            self.assertTrue(w.stop_button.isEnabled())
            self.wait_until(lambda: not w.running)
        prepare.assert_called_once_with(checked, "COM4", 3, "Capture")
        self.assertIn("checked command", w.log_view.toPlainText())
        self.assertTrue(w.fields["wild_game"].isEnabled())
        self.assertTrue(w.start_button.isEnabled())
