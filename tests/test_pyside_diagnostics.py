import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pyside_app.diagnostics import explain_error, parse_integer


ROI_ERROR = (
    "System.Exception: 搜图标签[错误退出]执行异常: "
    "0 <= roi.x && 0 <= roi.width && roi.x + roi.width <= m.cols && "
    "0 <= roi.y && 0 <= roi.height && roi.y + roi.height <= m.rows"
)


class DiagnosticTests(unittest.TestCase):
    def test_integer_errors_name_field_and_distinguish_empty_from_invalid(self):
        for value in ("", "  "):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "OP 穷举起点.*为空.*整数"):
                parse_integer(value, "OP 穷举起点")
        for value in ("abc", "1.5"):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "OP 穷举起点.*填写了.*整数"):
                parse_integer(value, "OP 穷举起点")
        self.assertEqual(parse_integer(" 00000 ", "目标 TID"), 0)
        self.assertEqual(parse_integer("-2", "OP 修正"), -2)

    def test_roi_diagnosis_names_label_without_inventing_dimensions(self):
        issue = explain_error(ROI_ERROR)
        self.assertIn("错误退出", issue.summary)
        self.assertIn("采集画面不可用", issue.summary)
        self.assertIn("监视窗口", issue.action)
        self.assertIn("优先检查采集卡是否被其他程序占用", issue.action)
        self.assertIn("仅凭此错误无法区分", issue.action)
        self.assertIn("阈值不能修复", issue.action)
        self.assertNotIn("1920", issue.message)
        self.assertIsNotNone(explain_error("OpenCvSharp.OpenCVException: 0 <= roi.y && roi.y + roi.height <= m.rows"))

    def test_other_recognition_errors_are_not_misdiagnosed_as_roi(self):
        for text in ("搜图标签[错误退出]执行异常: missing label", "roi.x = 10; roi.width = 20",
                     "识图失败，最高分 90 < 95", "OperationCanceledException", "未知错误"):
            with self.subTest(text=text):
                self.assertIsNone(explain_error(text))

    def test_old_integer_exception_does_not_guess_missing_field_name(self):
        issue = explain_error("invalid literal for int() with base 10: ''")
        self.assertIn("空值", issue.summary)
        self.assertIn("没有提供字段名", issue.action)
        self.assertNotIn("OP", issue.message)


@unittest.skipUnless(importlib.util.find_spec("PySide6"), "PySide6 is optional")
class QtDiagnosticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(["diagnostics-tests", "-platform", "offscreen"])

    def setUp(self):
        from pyside_app.migration import CompleteWindow
        from pyside_app.services import AppPaths
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.w = CompleteWindow(paths=AppPaths(user=self.root, output=self.root / "runtime"), auto_detect=False)
        self.w.tid_state.poll_timer.stop()

    def tearDown(self):
        self.w.close()
        self.w.deleteLater()
        self.app.processEvents()
        self.temp.cleanup()

    def test_tid_generate_and_refresh_report_same_empty_field(self):
        w = self.w
        w.select_page("tid")
        w.fields["tid_op_start"].clear()
        with patch.object(w, "show_error") as error, patch.object(w, "launch_job") as job:
            w.search()
            job.assert_not_called()
        message = error.call_args.args[0]
        self.assertIn("OP 穷举起点", message)
        self.assertIn("为空", message)
        w.tid_state.refresh_progress(fill_starts=True)
        self.assertIn(message, w.tid_progress_status.text())

    def test_wild_and_egg_numeric_inputs_name_the_field(self):
        w = self.w
        with self.assertRaisesRegex(ValueError, "当前 TID.*为空"):
            w.collect_inputs()
        w.egg_ack.setChecked(True)
        w.fields["egg_held"].clear()
        with self.assertRaisesRegex(ValueError, "Held.*为空"):
            w.reader.egg()

    def test_sid_level_error_identifies_active_party_slot(self):
        w = self.w
        w.select_page("sid")
        w.sid_ack.setChecked(True)
        w.fields["sid_tid"].setText("12345")
        w.fields["sid_count"].setValue(2)
        for row in w.sid_party_widgets[:2]:
            row[0].setText("皮卡丘")
            row[1].setText("3")
        w.sid_party_widgets[1][1].clear()
        with self.assertRaisesRegex(ValueError, "第 2 只.*初始等级.*为空"):
            w.reader.sid()
        w.fields["sid_count"].setValue(1)
        self.assertEqual(w.reader.sid().initial_levels, (3, 1, 1, 1, 1, 1))

    def test_optional_traversal_start_still_inherits_but_invalid_value_names_field(self):
        w = self.w
        w.advanced_check.setChecked(True)
        w.named_rival = True
        w.traversal_check.setChecked(True)
        w.fields["wild_tid"].setText("12345")
        w.fields["wild_sid"].setText("54321")
        self.assertIsNone(w.collect_workflow().extra["start_advance"])
        w.fields["wild_traversal_start"].setText("abc")
        with self.assertRaisesRegex(ValueError, "高级起点.*abc.*整数"):
            w.collect_workflow()

    def test_split_utf8_error_is_explained_once_and_original_lines_stay_visible(self):
        w = self.w
        raw = (ROI_ERROR + "\n   at EasyCon.Capture.ILExt.Search()\n" + ROI_ERROR).encode("utf-8")
        for offset in range(0, len(raw), 7):
            w._append_log(w.decoder.decode(raw[offset:offset + 7]))
        w._append_log(w.decoder.decode(b"", final=True), final=True)
        shown = w.log_view.toPlainText()
        self.assertEqual(shown.count("[问题说明]"), 1)
        self.assertEqual(shown.count(ROI_ERROR), 2, repr(shown))
        self.assertIn("at EasyCon.Capture.ILExt.Search()", shown)
        self.assertIn("错误退出", w.status_text)

    def test_runtime_popup_keeps_technical_details(self):
        from PySide6.QtWidgets import QMessageBox
        messages = []
        def inspect(dialog):
            messages.append((dialog.text(), dialog.detailedText()))
        with patch.object(QMessageBox, "exec", inspect):
            self.w.show_error(ROI_ERROR)
        self.assertIn("采集画面不可用", messages[0][0])
        self.assertEqual(messages[0][1], ROI_ERROR)

    def test_real_logged_child_preserves_raw_file_and_next_run_clears_diagnosis(self):
        from PySide6.QtCore import QEventLoop, QTimer
        w = self.w
        raw = ROI_ERROR + "\n   at EasyCon.Capture.ILExt.Search()\n[流程错误] 固定延迟检测被取消或发生异常"
        log = self.root / "raw.log"
        script = self.root / "child.py"
        script.write_text(f"import sys\nsys.stdout.buffer.write({raw.encode('utf-8')!r})\nsys.exit(7)\n", encoding="utf-8")
        def run(arguments):
            loop = QEventLoop()
            w.process.finished.connect(loop.quit)
            timer = QTimer()
            timer.setSingleShot(True)
            timer.timeout.connect(loop.quit)
            timer.start(10000)
            w.process.start(sys.executable, arguments)
            loop.exec()
            timer.stop()
            w.process.finished.disconnect(loop.quit)
            self.assertFalse(w.running)
        wrapper = Path(__file__).resolve().parents[1] / "run_easycon_logged.py"
        run(["-u", str(wrapper), "--cwd", str(self.root), "--log-path", str(log), "--", sys.executable, str(script)])
        self.assertEqual(log.read_text(encoding="utf-8"), raw)
        self.assertIn("[本次运行问题]", w.log_view.toPlainText())
        self.assertIn("错误退出", w.status_text)
        self.assertIn("退出码 7", w.status_text)
        w.decoder.reset()
        run(["-c", "print('next run')"])
        self.assertFalse(w.runtime_issues)
        self.assertNotIn("错误退出", w.status_text)
