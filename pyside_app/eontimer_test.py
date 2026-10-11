"""Live, automatic results for the opt-in EonTimer timing experiment."""
from __future__ import annotations

import json

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QDialog, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout

from automation.eontimer_test_report import EonTestReport


class EonTimerController:
    def __init__(self, window):
        self.window = window
        self.report = EonTestReport()
        self.active = False
        self.command = None
        self.dialog = None
        self.view = None
        self.export_note = ""
        self.timer = QTimer(window)
        self.timer.setSingleShot(True)
        self.timer.setInterval(150)
        self.timer.timeout.connect(self.refresh)
        window.eontimer_report_button.clicked.connect(self.show)
        window.eontimer_test_check.toggled.connect(self.changed)
        window.advanced_check.toggled.connect(self.availability)
        self.availability()

    def availability(self, *_):
        window = self.window
        enabled = window.advanced_check.isChecked() and not window.running and window.job is None
        window.eontimer_test_check.setEnabled(enabled)
        if not window.advanced_check.isChecked() and window.eontimer_test_check.isChecked() and not window.running:
            window.eontimer_test_check.setChecked(False)

    def changed(self, *_):
        self.window.invalidate()
        self.refresh()

    def begin(self, command, prepared):
        self.timer.stop()
        self.active = bool(prepared and getattr(prepared.inputs, "eontimer_test", False))
        self.command = command if self.active else None
        # Ordinary runs must never consume test markers from unrelated output.
        if self.active:
            self.report = EonTestReport(command.run_id)
            self.export_note = ""
        self.refresh()

    def consume(self, line):
        if self.active and self.report.consume(line) and not self.timer.isActive():
            self.timer.start()

    def finish(self):
        if self.active:
            self.report.finished = True
            if self.report.initial and self.command:
                path = self.command.log_path.with_suffix(".eontimer.json")
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
        elif self.active:
            status = f"EonTimer 测试运行中 · 已更新 {self.report.updated} 轮，非唯一跳过 {self.report.skipped} 轮"
        elif self.report.initial:
            status = f"最近一次测试 · 已更新 {self.report.updated} 轮，非唯一跳过 {self.report.skipped} 轮"
        elif self.window.eontimer_test_check.isChecked():
            status = "测试已开启 · 请回野生 / 静态页重新生成；自动使用时间轴，普通预校准不参与"
        else:
            status = "未开启 · 普通计时不受影响"
        self.window.eontimer_test_status.setText(status)
        if self.view:
            self.view.setPlainText(self.report.render() + ("\n\n" + self.export_note if self.export_note else ""))

    def show(self):
        if self.dialog is None:
            self.dialog = QDialog(self.window)
            self.dialog.setWindowTitle("EonTimer 自动计时与反查对照（临时测试）")
            self.dialog.resize(1000, 660)
            layout = QVBoxLayout(self.dialog)
            hint = QLabel("全部参数和每轮校准由工具自动处理。本页可在运行中查看，不会暂停脚本。")
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
