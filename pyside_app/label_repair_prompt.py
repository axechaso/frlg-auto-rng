"""Conservative final-failure prompts; complete current-run evidence only."""
import time
from pathlib import Path
from PySide6.QtCore import QObject, Signal, Slot, QTimer, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea, QCheckBox
from .jobs import Job
from device_label_overrides import diagnose_label_log
from .diagnostics import brief_error, explain_popup_error


def incident_summary(record):
    unknown = "未采集"
    capture = record.get("capture_device", {})
    dimensions = record.get("capture",{})
    lines = [f"流程：{record.get('workflow', unknown)} · 阶段：{record.get('stage_id',unknown)}",
             f"故障类型：{record.get('failure_kind',unknown)}",
             f"ROM 语言：{record.get('rom_language', record.get('language',unknown))} · 主机：{record.get('nx_model',unknown)}",
             f"采集卡：{capture.get('name',unknown)} · 分辨率：{dimensions.get('width') or unknown} × {dimensions.get('height') or unknown}",
             f"判定组：{record.get('predicate',{}).get('group_operator',unknown)} · 标签来源/覆盖：{record.get('script_path',unknown)}"]
    for item in record.get("labels", []):
        score = item.get("score")
        lines.append(f"{item.get('name',unknown)}：{unknown if score is None else score}，要求 {item.get('operator',unknown)}{item.get('threshold',unknown)}")
    lines.append("先确认画面处于预期页面且已稳定，再检查语言、分辨率和实际标签。OR 候选的低分不单独代表坏标签；最高分也不保证正确。")
    symptom = {"capture_unavailable": "采集画面不可用", "label_invalid": "标签结构损坏"}.get(
        record.get("failure_kind"), "识图等待失败：没有通过当前阶段的标签判定")
    lines.append(explain_popup_error(symptom).message)
    return "\n".join(lines)


class LabelFailureDialog(QDialog):
    def __init__(self, controller, records, diagnostic, log_path):
        super().__init__(controller.w)
        self.controller = controller
        self.setWindowTitle("识别故障检查与修复")
        self.setModal(False)
        self.resize(740, 600)
        layout = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QLabel("\n\n".join(incident_summary(r) for r in records) if records else diagnostic)
        self.detail_label = content
        content.setTextFormat(Qt.TextFormat.PlainText)
        content.setWordWrap(True)
        content.setMargin(12)
        scroll.setWidget(content)
        layout.addWidget(scroll,1)
        if records:
            record = records[0]
            screenshot = record.get("screenshot",{})
            relative = screenshot.get("match") or screenshot.get("stop")
            image = QLabel("未采集截图；请补采集或导入后再编辑。")
            if relative:
                path = Path(record["bundle_path"]) / str(relative)
                pixmap = QPixmap(str(path))
                if not pixmap.isNull():
                    image.setPixmap(pixmap.scaled(680,240,Qt.AspectRatioMode.KeepAspectRatio))
            layout.addWidget(image)
        buttons = QHBoxLayout()
        self.repair_button = None
        for title, callback in (("开始修复", lambda: controller.repair(records)),
                                ("查看完整日志", lambda: controller.open_log(log_path)),
                                ("稍后处理", self.close)):
            button = QPushButton(title)
            button.clicked.connect(callback)
            if title == "开始修复":
                self.repair_button = button
            buttons.addWidget(button)
        if any(record.get("input_released") is False for record in records):
            layout.addWidget(QLabel("本次事件报告控制器归零失败；请先手动确认输入已停止。"))
            self.release_confirm = QCheckBox("已手动确认控制器归零及画面稳定")
            self.repair_button.setEnabled(False)
            self.release_confirm.toggled.connect(self.repair_button.setEnabled)
            layout.addWidget(self.release_confirm)
        layout.addLayout(buttons)


class LabelRepairPrompts(QObject):
    delivered = Signal(int, object)
    finished = Signal()
    def __init__(self, accessories):
        super().__init__(accessories)
        self.a, self.w = accessories, accessories.w
        self.job = None
        self.token = 0
        self.seen = set()
        self.dialog = None
        self.pending = None
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._scan)
        self.delivered.connect(self._received)
        self.finished.connect(self._finished)

    def after_exit(self, code, run_id, *, log_path=None, text="", cancelled=False):
        self.token += 1
        if cancelled or self.w.closing or not self.w.label_repair_prompt_check.isChecked() or not run_id:
            return
        # Wait for native final incident publication. A normal exit / retry is silent.
        if code == 20:
            self.pending = (self.token, run_id, log_path, time.monotonic()+3.0)
            self.timer.start(0)
        elif code != 0:
            issues = diagnose_label_log(text)
            capture_failure = any(marker in text.casefold() for marker in ("采集卡打开失败", "capture unavailable", "capture failed", "cannot open camera"))
            if issues or capture_failure:
                explanation = explain_popup_error("采集卡打开失败" if capture_failure else "识图等待失败：没有完整阶段证据")
                self._show([], explanation.message + "\n\n原始输出摘录：\n" + brief_error(text), log_path, run_id)

    def preflight(self, message):
        if self.w.label_repair_prompt_check.isChecked() and any(word in message for word in ("标签", ".IL", "采集卡", "画面")):
            explanation = explain_popup_error(message)
            detail = explanation.message + "\n\n原始错误：\n" + message
            self._show([], "预检未通过，尚未运行。\n" + detail + "\n先检查标签结构或采集设置；未采集分数与截图。", None, "preflight:"+message)
            return True
        return False

    def _scan(self):
        if not self.pending or self.job or self.w.closing:
            return
        token = self.pending[0]
        self.job = Job(lambda cancel,status: self.a.incidents.list(include_resolved=False) if not cancel() else (), self)
        self.job.succeeded.connect(lambda records: self.delivered.emit(token, records))
        self.job.failed.connect(lambda error: self.delivered.emit(token, ()))
        self.job.finished.connect(self.finished.emit)
        self.job.start()

    @Slot(int, object)
    def _received(self, token, records):
        if token != self.token or not self.pending or self.w.running or self.w.job or self.w.closing:
            return
        _,run_id,path,deadline = self.pending
        matching = [r for r in records if r.get("run_id") == run_id and (run_id,r["incident_id"]) not in self.seen and r.get("complete") is True]
        if matching:
            self._show(matching,"",path,run_id)
            self.pending = None
        elif time.monotonic() < deadline:
            self.timer.start(200)
        else:
            self.pending = None
            self._show([],"识别保护已停止，但完整故障资料未到达；截图、分数及标签来源未采集。请先查看日志，再补采集或导入。",path,run_id)

    @Slot()
    def _finished(self):
        job,self.job = self.job,None
        if job:
            job.deleteLater()
        if self.pending and not self.timer.isActive():
            self.timer.start(200)

    def _show(self, records, diagnostic, path, run_id):
        if self.w.running or self.w.job or self.w.closing:
            return
        key = (run_id,"prompt")
        if key in self.seen:
            return
        self.seen.add(key)
        self.seen.update((run_id,r["incident_id"]) for r in records)
        if hasattr(self.w,"page_guides"):
            self.w.page_guides.minimize()
        if records:
            self.a.active_incident_id = records[0]["incident_id"]
            self.a.poll_incidents()
        self.dialog = LabelFailureDialog(self,records,diagnostic,path)
        self.dialog.show()

    def repair(self, records):
        if self.dialog:
            self.dialog.close()
        if records:
            self.a.active_incident_id = records[0]["incident_id"]
            self.a.open_active_incident()
        else:
            self.a.open_label_editor()

    def open_log(self, path):
        if path and Path(path).is_file():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).resolve())))

    def close(self):
        self.token += 1
        self.pending = None
        self.timer.stop()
        if self.dialog:
            self.dialog.close()
        if self.job:
            self.job.cancelled.set()
        return self.job is None
