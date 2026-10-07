import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pyside_app.diagnostics import brief_error, explain_error, explain_popup_error, parse_integer


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

    def test_popup_advice_covers_actual_error_categories(self):
        cases = (
            ("检查程序更新失败: <urlopen error [SSL: CERTIFICATE_VERIFY_FAILED] unable to get local issuer certificate>", "network_certificate"),
            ("ImportError: DLL load failed while importing QtCore: 找不到指定的程序。", "runtime_dll"),
            ("采集卡编号或名称已改变，请重新检测并生成方案", "device_changed"),
            ("采集卡打开失败", "capture_connection"),
            ("采集卡被占用", "capture_connection"),
            ("未检测到串口 COM4，请重新检测设备", "serial_connection"),
            ("could not open port COM4: PermissionError: Access is denied", "serial_connection"),
            ("No space left on device", "disk_space"),
            ("OSError: disk full", "disk_space"),
            ("[WinError 32] 另一个程序正在使用此文件", "file_access"),
            ("TID 标签数量应为 1155，当前为 328", "label_package"),
            ("标签 JSON 损坏", "label_package"),
            ("2.0 模板字段 $孵蛋Held无蛋表Seed 应出现 1 次，实际为 0 次", "template_version"),
            ("2.0 脚本指纹不一致", "integrity"),
            ("预检后文件已改变，请重新生成 / 预检：main.ecs", "plan_preflight"),
            ("FileNotFoundError: [Errno 2] No such file or directory: old/main.ecs", "path_missing"),
            ("HTTP Error 403: Forbidden", "network_http"),
            ("检查程序更新失败: <urlopen error timed out>", "network_connection"),
            ("Seed 表未加载", "seed_table_missing"),
            ("指定 Seed 1234 在 fr_nx 的所有可用 Seed 模式中均不可达", "seed_unreachable"),
            ("指定 Seed 1234 不在 fr_nx 的 Seed 表/模式 6 中", "seed_unreachable"),
            ("找到了 20 个个体结果，但没有初始 Seed 方案落在 Advance 0-1000", "seed_unreachable"),
            ("Ten Lines 没有找到满足宝可梦、闪光、性格、个体值条件的结果", "search_no_result"),
            ("HOME_BUFFER calibration timeout", "home_buffer"),
            ("HOME_BUFFER校准失败：短/长边界之间没有达到当前识图阈值的整数延迟", "home_buffer"),
            ("反查失败：没有候选", "reverse_search"),
            ("性格识别失败，最高匹配度:65", "recognition"),
            ("JSONDecodeError: Expecting value", "config_format"),
            ("当前目标仅支持搜索，不能重建自动运行工程", "route_unsupported"),
            ("请检查输入：“当前 TID”为空，请填写整数。", "input_or_precondition"),
            ("运行进程无法启动：系统找不到指定的程序", "process_start"),
            ("当前标签会在相邻页面触发", "label_false_positive"),
            ("先通过同图原生测试和 3 张新帧动态测试", "label_verification_pending"),
            ("故障资料中没有当次实际加载的标签备份，不能直接修复。", "label_evidence_missing"),
        )
        for text, expected in cases:
            with self.subTest(text=text):
                issue = explain_popup_error(text)
                self.assertEqual(issue.key, expected)
                self.assertIn("可能原因（需核对）", issue.message)
                self.assertIn("建议排查", issue.message)
                self.assertTrue(issue.possible_causes)

    def test_specific_hardware_and_certificate_errors_win_over_outer_text(self):
        self.assertEqual(explain_popup_error("程序更新失败: certificate verify failed: timed out").key, "network_certificate")
        self.assertEqual(explain_popup_error("标签操作失败：could not open COM4: Access is denied").key, "serial_connection")
        self.assertEqual(explain_popup_error("标签草稿保存失败：[WinError 5] 拒绝访问").key, "file_access")
        self.assertEqual(explain_popup_error(ROI_ERROR + "\n标签 JSON 损坏").key, "capture_roi:错误退出")

    def test_timeout_alone_and_success_headers_do_not_invent_network_or_serial_cause(self):
        self.assertEqual(explain_popup_error("未知阶段 timeout").key, "unknown")
        self.assertEqual(explain_popup_error("单片机串口COM4连接成功\nHOME_BUFFER calibration timeout").key, "home_buffer")
        self.assertEqual(explain_popup_error("单片机串口COM4连接成功\n性格识别失败，最高匹配度65").key, "recognition")
        for text in ("HOME_BUFFER锁定值识别失败:1/3，保持1200ms重试", "性格识别失败，最高匹配度65", "正在检查程序更新", "单片机连接成功"):
            self.assertIsNone(explain_error(text))

    def test_unknown_popup_does_not_blame_equipment_or_propose_reset(self):
        issue = explain_popup_error("unclassified error 123")
        self.assertEqual(issue.key, "unknown")
        self.assertIn("不能确定", issue.message)
        self.assertIn("历史日志", issue.action)
        self.assertIn("保留资料", issue.action)
        self.assertNotIn("设备故障", issue.message)
        self.assertNotIn("删除旧配置后", issue.action)

    def test_advice_preserves_network_security_and_known_version_policies(self):
        cert = explain_popup_error("CERTIFICATE_VERIFY_FAILED").message
        self.assertIn("不要关闭证书验证", cert)
        timeout = explain_popup_error("timed out", context="程序更新检查失败").message
        self.assertIn("不代表账号凭据已失效", timeout)
        integrity = explain_popup_error("SHA256不一致").message
        self.assertIn("现有指纹警告策略", integrity)
        self.assertIn("不由此弹窗自动放宽", integrity)

    def test_visible_excerpt_is_bounded_and_retains_traceback_exception(self):
        long = "Traceback (most recent call last):\n" + "  frame\n" * 100 + "ValueError: 当前 TID 不正确"
        self.assertIn("ValueError: 当前 TID 不正确", brief_error(long))
        self.assertIn("完整原始错误", brief_error(long))
        self.assertLess(len(brief_error("x" * 10000)), 550)
        self.assertEqual(brief_error("当前 TID 为空"), "当前 TID 为空")

    def test_update_file_access_advice_names_explorer_only_in_update_context(self):
        generic = explain_popup_error("PermissionError: Access is denied").action
        update = explain_popup_error("PermissionError: Access is denied", context="程序更新失败").action
        self.assertNotIn("绿色版程序目录", generic)
        self.assertIn("资源管理器", update)


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
        # This parser test supplies unrelated advanced options explicitly;
        # public CI has no user ECS assets from which to read those defaults.
        for i in range(1,4):
            w.fields[f"expansion_{i}_seed"].setText("1")
            w.fields[f"expansion_{i}_adv"].setText("100")
        w.fields["togepi_reverse_adv"].setText("1000")
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
        self.w.show_error(ROI_ERROR)
        dialog = self.w.accessories.repair_prompts.dialog
        self.assertIsNotNone(dialog)
        self.assertIn("采集画面不可用", dialog.detail_label.text())
        self.assertIn(ROI_ERROR, dialog.detail_label.text())
        self.assertTrue(dialog.isVisible())

    def test_generic_error_dialog_keeps_exact_raw_details_and_plain_text(self):
        from PySide6.QtCore import Qt
        from pyside_app.error_dialog import create_error_dialog
        raw = "<urlopen error [SSL: CERTIFICATE_VERIFY_FAILED]>\nD:\\old\\配置.json"
        dialog = create_error_dialog(self.w, "程序更新检查失败", raw)
        self.assertEqual(dialog.detailedText(), raw)
        self.assertIn(raw, dialog.informativeText())
        self.assertIn("可能原因", dialog.informativeText())
        self.assertIn("建议排查", dialog.informativeText())
        self.assertEqual(dialog.textFormat(), Qt.TextFormat.PlainText)
        dialog.deleteLater()

    def test_error_details_buttons_stay_chinese_when_toggled(self):
        from PySide6.QtWidgets import QMessageBox, QTextEdit
        from pyside_app.error_dialog import create_error_dialog
        dialog = create_error_dialog(self.w, "操作未完成", "PermissionError: 拒绝访问")
        details = next(b for b in dialog.buttons() if dialog.buttonRole(b) == QMessageBox.ButtonRole.ActionRole)
        dialog.show()
        self.app.processEvents()
        self.assertEqual(dialog.button(QMessageBox.StandardButton.Ok).text(), "确定")
        self.assertEqual(details.text(), "查看详细信息")
        details.click()
        self.assertEqual(details.text(), "收起详细信息")
        self.assertTrue(dialog.findChild(QTextEdit).isVisible())
        details.click()
        self.assertEqual(details.text(), "查看详细信息")
        self.assertFalse(dialog.findChild(QTextEdit).isVisible())
        dialog.close()
        dialog.deleteLater()

    def test_general_window_error_adds_advice_without_mutating_inputs(self):
        before = self.w.settings_payload()
        raw = "请检查输入：“当前 TID”为空，请填写整数。"
        with patch("pyside_app.window.show_error_dialog") as popup, patch.object(self.w.process, "start") as run:
            self.w.show_error(raw)
            popup.assert_called_once_with(self.w, "操作未完成", raw)
            run.assert_not_called()
        self.assertIn(raw, self.w.result_panel.toPlainText())
        self.assertIn("可能原因", self.w.result_panel.toPlainText())
        self.assertEqual(self.w.settings_payload(), before)

    def test_recognition_retry_logs_do_not_gain_new_popup_diagnoses(self):
        raw = "HOME_BUFFER锁定值识别失败:1/3，保持1200ms重试\n性格识别失败，最高匹配度65\n"
        with patch("pyside_app.window.show_error_dialog") as popup:
            self.w._append_log(raw)
            popup.assert_not_called()
        self.assertFalse(self.w.runtime_issues)
        self.assertNotIn("[问题说明]", self.w.log_view.toPlainText())

    def test_long_raw_error_is_complete_in_details_but_excerpt_is_short(self):
        from pyside_app.error_dialog import create_error_dialog
        raw = "unknown error\n" + "frame at source/path.py\n" * 100
        dialog = create_error_dialog(self.w, "操作未完成", raw)
        self.assertEqual(dialog.detailedText(), raw)
        self.assertLess(len(dialog.informativeText()), 1000)
        self.assertIn("完整原始错误", dialog.informativeText())
        dialog.deleteLater()

    def test_profile_save_failure_uses_shared_dialog_and_keeps_draft(self):
        from pyside_app.profiles import ProfileManager
        from save_profiles import SaveProfileStore
        manager = ProfileManager(SaveProfileStore(self.root / "isolated_profiles.json"), self.w)
        manager.name.setText("待保存的草稿")
        def fail():
            raise PermissionError("拒绝访问")
        with patch("pyside_app.profiles.show_error_dialog") as popup:
            manager.mutate(fail)
            popup.assert_called_once_with(manager, "无法保存存档", "拒绝访问")
        self.assertEqual(manager.name.text(), "待保存的草稿")
        manager.deleteLater()

    def test_notice_preference_failure_uses_shared_dialog_without_false_persistence(self):
        from pyside_app.startup_notice import StartupNoticeDialog
        dialog = StartupNoticeDialog(self.root / "notice", self.w)
        dialog.hide_checkbox.setChecked(True)
        with patch("pyside_app.startup_notice.write_json_atomic", side_effect=PermissionError("拒绝访问")), patch("pyside_app.startup_notice.show_error_dialog") as popup:
            dialog.accept()
            popup.assert_called_once_with(dialog, "公告设置未保存", "拒绝访问")
        self.assertFalse((self.root / "notice/startup_notice.json").exists())
        dialog.deleteLater()

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
            w._begin_run_notification()
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
