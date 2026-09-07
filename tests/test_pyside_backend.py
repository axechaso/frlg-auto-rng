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

    def test_profile_application_preserves_tid_targets_and_delays_and_shares_current_identity(self):
        w = self.window
        w.fields["tid_target"].setText("00123")
        w.fields["tid_sid"].setText("00456")
        w.fields["tid_op_delay"].setText("31234")
        profile = w.profile_store.add("Test", "叶绿", "00007", 123, 2, language="日文")
        w.reload_profiles(apply=True)
        self.assertEqual(w.fields["wild_tid"].text(), "7")
        self.assertEqual(w.fields["wild_sid"].text(), "123")
        self.assertEqual(w.fields["sid_tid"].text(), "7")
        self.assertEqual(w.fields["tid_target"].text(), "00123")
        self.assertEqual(w.fields["tid_sid"].text(), "00456")
        self.assertEqual(w.fields["tid_op_delay"].text(), "31234")
        self.assertEqual(w.fields["profile_language"].currentIndex(), 1)
        self.assertEqual(w.fields["egg_nx"].currentText(), "Switch 2")
        self.assertEqual(w.profile_store.get(profile.profile_id).tid, 7)

    def test_profile_selection_does_not_fill_empty_or_default_tid_targets(self):
        w = self.window
        first = w.profile_store.add("English", "火红", 12345, 54321, 1)
        second = w.profile_store.add("Japanese", "叶绿", 7, 8, 2, language="日文")
        w.reload_profiles()
        for targets in (("", ""), ("00000", "38449")):
            with self.subTest(targets=targets):
                for field, value in zip(("tid_target", "tid_sid"), targets):
                    w.fields[field].setText(value)
                for profile in (first, second):
                    w.profile_selector.setCurrentIndex(w.profile_selector.findData(profile.profile_id))
                    self.assertEqual(tuple(w.fields[key].text() for key in ("tid_target", "tid_sid")), targets)
                    self.assertEqual(w.fields["wild_tid"].text(), str(profile.tid))
                    self.assertEqual(w.fields["wild_sid"].text(), str(profile.sid))
                    self.assertEqual(w.fields["tid_language"].currentText(), profile.language)
        self.assertEqual(self.errors, [])

    def test_records_show_saved_tid_game_settings_independent_of_current_forms(self):
        from dataclasses import replace
        from PySide6.QtWidgets import QLabel
        from tid_records import TidLogParser, TidRecordStore
        from tests.test_tid_records import context, observation
        w = self.window
        settings = {
            (0, 0, 0): ("MONO", "HELP", "A"),
            (1, 1, 1): ("STEREO", "LR", "START"),
            (1, 2, 2): ("STEREO", "L=A", "L(L=A)"),
        }
        for index, (sound, button, seed_button) in enumerate(settings):
            saved = replace(context(), sound=sound, button_mode=button, seed_button=seed_button)
            entry = TidLogParser(saved).feed(observation("00007"))[0]
            w.record_store.append(str(index), [(1, entry)], self.root / "test.log")
        w.record_store = TidRecordStore(w.record_store.path)
        for field in ("tid_sound", "tid_button", "tid_seed_button"):
            w.fields[field].setCurrentIndex(0)
        for field in ("starter_sound", "starter_button", "starter_seed_button"):
            w.fields[field].setCurrentIndex(1)
        w.refresh_records()
        self.wait_until(lambda: w.job is None)
        self.assertEqual(w.records_table.rowCount(), 3)
        for index, row in enumerate(w.record_rows):
            labels = settings[(row["sound"], row["button_mode"], row["seed_button"])]
            expected = ("00007", row["game"], "Switch 1", row["language"], *labels,
                        "3693", "2693", "2105", "1", row["player_name"], "0", row["last_seen"])
            self.assertEqual(tuple(w.records_table.item(index, column).text() for column in range(14)), expected)
            w.records_table.setCurrentCell(index, 0)
            detail = w.findChild(QLabel, "liveRecordDetails").text()
            self.assertIn(f"声音：{labels[0]}　按键模式：{labels[1]}　Seed 启动键：{labels[2]}", detail)
        self.assertEqual(self.errors, [])

    def test_entering_tid_records_page_reads_existing_database_rows(self):
        from tid_records import TidLogParser
        from tests.test_tid_records import context, observation
        w = self.window
        entry = TidLogParser(context()).feed(observation("00007"))[0]
        w.record_store.append("existing", [(1, entry)], self.root / "existing.log")

        w.select_page("tid_records")
        self.wait_until(lambda: w.job is None)

        self.assertEqual(w.records_table.rowCount(), 1)
        self.assertEqual(w.records_table.item(0, 0).text(), "00007")

    def test_open_tid_records_page_refreshes_after_external_database_write(self):
        from tid_records import TidLogParser, TidRecordStore
        from tests.test_tid_records import context, observation
        w = self.window
        w.select_page("tid_records")
        self.wait_until(lambda: w.job is None)
        self.assertEqual(w.records_table.rowCount(), 0)

        entry = TidLogParser(context()).feed(observation("54321"))[0]
        TidRecordStore(w.record_store.path).append("live", [(1, entry)], self.root / "live.log")
        self.wait_until(lambda: w.records_table.rowCount() == 1, limit=3000)

        self.assertEqual(w.records_table.item(0, 0).text(), "54321")
        self.assertEqual(self.errors, [])

    def test_open_tid_records_page_keeps_refreshing_while_easycon_is_running(self):
        from tid_records import TidLogParser, TidRecordStore
        from tests.test_tid_records import context, observation
        w = self.window
        w.running = True
        try:
            w.select_page("tid_records")
            self.wait_until(lambda: w.job is None)
            entry = TidLogParser(context()).feed(observation("24223"))[0]
            TidRecordStore(w.record_store.path).append("running", [(1, entry)], self.root / "running.log")
            self.wait_until(lambda: w.records_table.rowCount() == 1, limit=3000)
            self.assertEqual(w.records_table.item(0, 0).text(), "24223")
        finally:
            w.running = False
        self.assertEqual(self.errors, [])

    def test_record_settings_missing_or_invalid_are_not_replaced_by_current_defaults(self):
        from PySide6.QtWidgets import QLabel
        from tid_records import TidLogParser
        from tests.test_tid_records import context, observation
        w = self.window
        entry = TidLogParser(context()).feed(observation())[0]
        w.record_store.append("test", [(1, entry)], self.root / "test.log")
        saved = w.record_store.rows()[0]
        cases = (
            ({}, ("未记录", "未记录", "未记录")),
            ({"sound": None, "button_mode": -1, "seed_button": 3}, ("未记录", "未知(-1)", "未知(3)")),
            ({"sound": "bad", "button_mode": True, "seed_button": 1.5}, ("未知(bad)", "未知(True)", "未知(1.5)")),
        )
        for settings, expected in cases:
            with self.subTest(settings=settings):
                row = {key: value for key, value in saved.items() if key not in ("sound", "button_mode", "seed_button")}
                row.update(settings)
                with patch.object(w.record_store, "rows", return_value=[row]):
                    w.refresh_records()
                    self.wait_until(lambda: w.job is None)
                self.assertEqual(tuple(w.records_table.item(0, column).text() for column in (4, 5, 6)), expected)
                w.records_table.setCurrentCell(0, 0)
                detail = w.findChild(QLabel, "liveRecordDetails").text()
                self.assertIn(f"声音：{expected[0]}　按键模式：{expected[1]}　Seed 启动键：{expected[2]}", detail)
        self.assertEqual(self.errors, [])

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
