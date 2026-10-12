"""Live, automatic results for the opt-in EonTimer timing experiment."""
from __future__ import annotations

import json
from dataclasses import replace

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QDialog, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout

from automation.eontimer_test_report import EonTestReport
from automation.fixed_timeline_test import FixedTestReport, find_successful_timeline


class EonTimerController:
    def __init__(self, window):
        self.window = window
        self.report = EonTestReport()
        self.active = False
        self.command = None
        self.dialog = None
        self.view = None
        self.export_note = ""
        self.fixed = None
        self.load_note = ""
        self.timer = QTimer(window)
        self.timer.setSingleShot(True)
        self.timer.setInterval(150)
        self.timer.timeout.connect(self.refresh)
        window.eontimer_report_button.clicked.connect(self.show)
        window.eontimer_test_check.toggled.connect(self.changed)
        window.eontimer_mode.currentIndexChanged.connect(self.mode_changed)
        window.eontimer_repeat_limit.valueChanged.connect(self.changed)
        window.eontimer_load_button.clicked.connect(lambda: self.load())
        window.advanced_check.toggled.connect(self.availability)
        self.availability()

    def availability(self, *_):
        window = self.window
        enabled = window.advanced_check.isChecked() and not window.running and window.job is None
        window.eontimer_test_check.setEnabled(enabled)
        checked = enabled and window.eontimer_test_check.isChecked()
        for widget in (window.eontimer_mode, window.eontimer_load_button, window.eontimer_repeat_limit):
            widget.setEnabled(checked)
        if not window.advanced_check.isChecked() and window.eontimer_test_check.isChecked() and not window.running:
            window.eontimer_test_check.setChecked(False)

    def changed(self, *_):
        self.window.invalidate()
        if (self.window.eontimer_test_check.isChecked() and self.window.eontimer_mode.currentIndex() == 1
                and self.fixed is None):
            self.load(silent=True)
        self.refresh()

    def mode_changed(self, *_):
        self.window.eontimer_fixed_box.setVisible(self.window.eontimer_mode.currentIndex() == 1)
        self.changed()

    def fixed_config(self, request, options):
        if self.fixed is None:
            raise ValueError("固定时长测试尚未取得同目标的成功时长，请在运行日志页点击“自动读取同目标最近成功时长”")
        config = replace(self.fixed, repeat_limit=self.window.eontimer_repeat_limit.value())
        config.validate_request(request, options)
        return config

    def load(self, *, silent=False):
        window = self.window
        if window.running or window.job is not None or not window.eontimer_test_check.isChecked():
            return
        try:
            inputs = window.collect_inputs(require_fixed=False)
            inputs.request.validate()
        except ValueError as exc:
            self.load_note = f"请先填写野生 / 静态目标，再读取成功时长：{exc}"
            if not silent:
                window.show_error(self.load_note)
            self.refresh()
            return
        from .log_history import discover_logs
        self.fixed = None
        self.load_note = "正在后台读取同目标的成功日志……"
        window.eontimer_fixed_values.setText(self.load_note)
        window.invalidate()

        def work(cancelled, status):
            entries = discover_logs(window.paths.output, window.paths.user, cancelled=cancelled, status=status)
            return find_successful_timeline(entries, inputs.request, inputs.options, cancelled=cancelled)

        def success(result):
            if result is None:
                return
            current = window.collect_inputs(require_fixed=False)
            result.validate_request(current.request, current.options)
            self.fixed = result
            self.load_note = ""
            window.eontimer_fixed_values.setText(
                f"Seed {result.seed_ms} ms · F1 {result.f1_ms} ms · F2 总 {result.f2_total_ms} ms（已包含 F1）\n"
                f"源目标：Seed {result.initial_seed} / ADV {result.advances} / 模式 {result.seed_mode}\n"
                f"来源：{result.source_log}\n请保持存档、游戏设置、采集设备与源运行一致，重新生成方案。")
            window.invalidate()
            self.refresh()
        if window.launch_job(work, success, "正在后台读取固定测试时长……") and window.job is not None:
            def loaded():
                if window.closing:
                    return
                if self.fixed is None:
                    self.load_note = "未取得成功时长；请检查目标与启动方式，确认运行完整结束后重新读取。"
                    window.eontimer_fixed_values.setText(self.load_note)
                    self.refresh()
            window.job.finished.connect(loaded)

    def begin(self, command, prepared):
        self.timer.stop()
        self.active = bool(prepared and getattr(prepared.inputs, "eontimer_test", False))
        self.command = command if self.active else None
        # Ordinary runs must never consume test markers from unrelated output.
        if self.active:
            fixed = getattr(prepared.inputs, "fixed_timeline", None)
            self.report = FixedTestReport(command.run_id, fixed) if fixed else EonTestReport(command.run_id)
            self.export_note = ""
        self.refresh()

    def consume(self, line):
        if self.active and self.report.consume(line) and not self.timer.isActive():
            self.timer.start()

    def finish(self):
        if self.active:
            self.report.finished = True
            if self.report.initial and self.command:
                path = self.command.log_path.with_suffix(
                    ".fixed-timeline.json" if isinstance(self.report, FixedTestReport) else ".eontimer.json")
                try:
                    # A run UUID owns this new file; never overwrite old evidence.
                    with path.open("x", encoding="utf-8", newline="\n") as file:
                        json.dump(self.report.payload(), file, ensure_ascii=False, indent=2)
                    self.export_note = f"自动对照报告：{path}"
                except (OSError, ValueError) as exc:
                    self.export_note = f"对照报告未保存：{exc}；原始日志不变。"
            self.active = False
        self.timer.stop()
        self.refresh()

    def refresh(self):
        self.availability()
        if self.report.error:
            status = self.report.error
        elif isinstance(self.report, FixedTestReport) and self.report.initial:
            status = ("固定时长测试运行中" if self.active else "最近一次固定时长测试") + f" · 已启动 {self.report.attempts} 轮，不校准"
        elif self.active:
            status = f"EonTimer 测试运行中 · 已更新 {self.report.updated} 轮，非唯一跳过 {self.report.skipped} 轮"
        elif self.report.initial:
            status = f"最近一次测试 · 已更新 {self.report.updated} 轮，非唯一跳过 {self.report.skipped} 轮"
        elif self.window.eontimer_test_check.isChecked():
            status = self.load_note or (
                "固定时长测试已开启 · 读取同目标成功时长后重新生成；每轮保持不变"
                if self.window.eontimer_mode.currentIndex() == 1 else
                "测试已开启 · 请回野生 / 静态页重新生成；自动使用时间轴，普通预校准不参与")
        else:
            status = "未开启 · 普通计时不受影响"
        self.window.eontimer_test_status.setText(status)
        if self.view:
            self.view.setPlainText(self.report.render() + ("\n\n" + self.export_note if self.export_note else ""))

    def show(self):
        if self.dialog is None:
            self.dialog = QDialog(self.window)
            self.dialog.setWindowTitle("自动计时与反查对照（临时测试）")
            self.dialog.resize(1000, 660)
            layout = QVBoxLayout(self.dialog)
            hint = QLabel("工具自动取得参数并记录反查：自动模式会校准，固定模式只观察、不校准。本页可在运行中查看，不会暂停脚本。")
            hint.setWordWrap(True)
            layout.addWidget(hint)
            self.view = QPlainTextEdit()
            self.view.setObjectName("logView")
            self.view.setReadOnly(True)
            self.view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
            layout.addWidget(self.view, 1)
            close = QPushButton("关闭对照窗口（脚本继续）")
            close.clicked.connect(self.dialog.hide)
            layout.addWidget(close)
        self.refresh()
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()
