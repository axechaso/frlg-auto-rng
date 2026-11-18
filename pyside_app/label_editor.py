"""PySide6 label repair editor backed by the pinned native EasyCon matcher."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import tempfile
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
import uuid

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QRect, Qt, QTimer, Signal, Slot, QSignalBlocker
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QFormLayout, QGridLayout, QGroupBox,
    QHBoxLayout, QLabel, QMessageBox, QPushButton, QSpinBox, QVBoxLayout,
    QWidget, QCheckBox, QLineEdit, QScrollArea, QFrame,
)

from automation.easycon118 import prepare_compat_runner, EASYCON170_TEST
from device_label_overrides import LabelOverrideStore
from label_incidents import LabelIncidentStore
from label_verification import verify_label
from pyside_preview import _combo
from .label_canvas import LabelCanvas
from .error_dialog import show_error_dialog
from .label_catalog import script_choices, label_choices
from .label_testing import label_frame, verify_preview


COORDINATE_FIELDS = (
    "RangeX", "RangeY", "RangeWidth", "RangeHeight",
    "TargetX", "TargetY", "TargetWidth", "TargetHeight",
)


def _qimage_png_bytes(image: QImage) -> bytes:
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not image.save(buffer, "PNG"):
        raise ValueError("无法把模板保存为 PNG")
    return bytes(buffer.data())


def _qimage_from_bytes(data: bytes) -> QImage:
    image = QImage.fromData(QByteArray(data))
    if image.isNull():
        raise ValueError("图片不能由 Qt 解码")
    return image


class LabelEditorDialog(QDialog):
    nativeDelivery = Signal(object)
    nativeFinished = Signal()
    def __init__(self, window, *, incident_id: str | None = None,
                 label_path: str | Path | None = None,
                 frame_path: str | Path | None = None):
        super().__init__(window)
        self.w = window
        self.incident_id = incident_id
        self.incidents = LabelIncidentStore(window.paths.user / "label_incidents")
        self.store = LabelOverrideStore(window.paths.user / "device_label_overrides")
        self.record = self.incidents.read(incident_id) if incident_id else None
        self.bundle = Path(str(self.record["bundle_path"])) if self.record else None
        self.original_path: Path | None = Path(label_path).resolve() if label_path else None
        self.frame_path: Path | None = Path(frame_path).resolve() if frame_path else None
        self.device_name = self._incident_device_name()
        # Making a label must also work before the CLI runtime is installed.
        self.runtime = None
        self._catalog = ()
        self._catalog_directory = None
        self.payload: dict[str, object] = {}
        self.original_payload: dict[str, object] = {}
        self.original_image = QImage()
        self._updating_fields = False
        self._same_image_ok = False
        self._fresh_frames_ok = False
        self._same_image_results: tuple[dict[str, object], ...] = ()
        self._fresh_frame_results: tuple[dict[str, object], ...] = ()
        self._fresh_request = None
        self._fresh_frame_path: Path | None = None
        self._fresh_frames_dir: Path | None = None
        self._adjacent_frame_path: Path | None = None
        self._adjacent_results: tuple[dict[str, object], ...] = ()
        self._adjacent_ok: bool | None = None
        self._candidate_sha256: str | None = None
        self._verification_session = uuid.uuid4().hex
        self._dirty = False
        self.native_job = None
        self.nativeDelivery.connect(self._fresh_verified)
        self.nativeFinished.connect(self._native_finished)
        self.fresh_timer = QTimer(self)
        self.fresh_timer.setInterval(100)
        self.fresh_timer.timeout.connect(self._collect_fresh)
        self.setWindowTitle("EasyCon 标签制作与修复")
        self.resize(1180, 790)
        self.setAcceptDrops(True)
        self._build_ui()
        self._load_incident_labels()
        self.w.fields["video"].currentIndexChanged.connect(self._device_changed)

    def _device_changed(self,*_):
        self._condition_changed()
        self.scene_confirm.setChecked(False)
        self.frame_path = None
        self.canvas.set_image(QImage())
        if not self.record:
            self.device_name = self._incident_device_name()
            self._load_script_labels()
        self._update_context()
        self.result_text.setText("采集设备已变化，旧验证结果失效；请重新核对设备、原图和标签。")

    def _incident_device_name(self) -> str:
        if self.record:
            capture = self.record.get("capture_device", {})
            if isinstance(capture, dict) and capture.get("name"):
                return str(capture["name"])
        try:
            return self.w.accessories.device_name()
        except (AttributeError, ValueError):
            return ""

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        self.context = QLabel()
        self.context.setWordWrap(True)
        self.context.setStyleSheet("background:#f0f5fc; padding:8px; border-radius:5px;")
        layout.addWidget(self.context)
        self.context.setTextFormat(Qt.TextFormat.PlainText)
        self.scene_confirm = QCheckBox("我确认截图是预期且稳定的页面，语言与分辨率正确")
        self.scene_confirm.toggled.connect(self._update_apply_button)
        layout.addWidget(self.scene_confirm)
        guide_row = QHBoxLayout()
        guide = QPushButton("制作步骤引导")
        guide.clicked.connect(lambda: self.w.page_guides.start("label", child=self))
        guide_row.addWidget(guide)
        self.monitor_button = QPushButton("启动修复共享预览" if self.record and not EASYCON170_TEST else "打开监视器")
        self.monitor_button.clicked.connect(self.open_monitor)
        guide_row.addWidget(self.monitor_button)
        self.capture_button = QPushButton("截图")
        self.capture_button.clicked.connect(self.capture_monitor_frame)
        guide_row.addWidget(self.capture_button)
        if self.record:
            imported = QPushButton("逐项导入 IL")
            imported.clicked.connect(self.import_candidates)
            guide_row.addWidget(imported)
        guide_row.addStretch(1)
        layout.addLayout(guide_row)
        body = QHBoxLayout()
        self.canvas = LabelCanvas(self)
        self.canvas.selectionFinished.connect(self._selection_finished)
        self.canvas.imageOpenRequested.connect(self.capture_monitor_frame)
        body.addWidget(self.canvas, 3)

        panel = QWidget(self)
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        self.script_choice = _combo()
        self.script_choice.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.script_choice.setMinimumContentsLength(20)
        self.script_choice.currentIndexChanged.connect(self._load_script_labels)
        panel_layout.addWidget(QLabel("脚本"))
        panel_layout.addWidget(self.script_choice)
        self.label_filter = QLineEdit()
        self.label_filter.setPlaceholderText("搜索脚本使用的标签…")
        self.label_filter.textChanged.connect(self._filter_labels)
        panel_layout.addWidget(self.label_filter)
        self.label_count = QLabel()
        panel_layout.addWidget(self.label_count)
        self.label_choice = _combo()
        self.label_choice.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.label_choice.setMinimumContentsLength(20)
        self.label_choice.setMaxVisibleItems(14)
        for combo in (self.script_choice, self.label_choice):
            combo.view().setStyleSheet("""
                QScrollBar:vertical { width:18px; margin:2px; background:#edf1f7; border-radius:7px; }
                QScrollBar::handle:vertical { min-height:40px; background:#91a3bf; border-radius:7px; }
                QScrollBar::handle:vertical:hover { background:#637ee5; }
                QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }
            """)
        self.label_choice.currentIndexChanged.connect(self._load_selected_label)
        panel_layout.addWidget(QLabel("标签"))
        panel_layout.addWidget(self.label_choice)
        self.method_text = QComboBox()
        for title, method in (("标准差匹配", 1), ("标准相关匹配", 3), ("标准相关系数匹配", 5),
                              ("XY 平均值边缘检测", 11), ("透明背景标准差匹配", 14)):
            self.method_text.addItem(title, method)
        self.method_text.setEnabled(False)
        self.method_text.setToolTip("沿用脚本原标签的搜索方法，保证设备覆盖与原标签兼容。")
        self.method_text.currentIndexChanged.connect(self._method_changed)
        panel_layout.addWidget(QLabel("搜索方法"))
        panel_layout.addWidget(self.method_text)
        condition_row = QHBoxLayout()
        condition_row.addWidget(QLabel("通过条件"))
        self.condition_operator = QComboBox()
        self.condition_operator.addItems((">", ">=", "<", "<="))
        self.condition_operator.setEnabled(not bool(self.record))
        self.condition_operator.currentIndexChanged.connect(self._condition_changed)
        condition_row.addWidget(self.condition_operator)
        self.condition_threshold = QSpinBox()
        self.condition_threshold.setRange(0, 1000)
        self.condition_threshold.setValue(95)
        self.condition_threshold.setEnabled(not bool(self.record))
        self.condition_threshold.valueChanged.connect(self._condition_changed)
        condition_row.addWidget(self.condition_threshold)
        panel_layout.addLayout(condition_row)

        coordinates = QGroupBox("坐标（原图像素）")
        grid = QGridLayout(coordinates)
        self.spins: dict[str, QSpinBox] = {}
        titles = (("RangeX", "搜索范围 X"), ("RangeY", "搜索范围 Y"),
                  ("RangeWidth", "搜索范围宽"), ("RangeHeight", "搜索范围高"),
                  ("TargetX", "模板位置 X"), ("TargetY", "模板位置 Y"),
                  ("TargetWidth", "模板宽"), ("TargetHeight", "模板高"))
        for index, (key, title) in enumerate(titles):
            row, col = divmod(index, 2)
            grid.addWidget(QLabel(title), row, col * 2)
            spin = QSpinBox()
            spin.setRange(0, 32768)
            spin.setKeyboardTracking(False)
            spin.valueChanged.connect(self._coordinates_changed)
            self.spins[key] = spin
            grid.addWidget(spin, row, col * 2 + 1)
        panel_layout.addWidget(coordinates)

        select_row = QHBoxLayout()
        self.range_button = QPushButton("右键圈选搜索范围")
        self.target_button = QPushButton("右键圈选模板目标")
        self.range_button.clicked.connect(lambda: self.canvas.set_selection_mode("range"))
        self.target_button.clicked.connect(lambda: self.canvas.set_selection_mode("target"))
        select_row.addWidget(self.range_button)
        select_row.addWidget(self.target_button)
        panel_layout.addLayout(select_row)

        previews = QHBoxLayout()
        self.old_preview = QLabel("原模板")
        self.new_preview = QLabel("新模板")
        for label in (self.old_preview, self.new_preview):
            label.setMinimumSize(130, 90)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setStyleSheet("background:#202b3a; color:#e5edf7; border:1px solid #69788c;")
            previews.addWidget(label)
        panel_layout.addLayout(previews)
        self.result_text = QLabel("选择脚本和标签 → 打开监视器 → 截图 → 圈选范围和目标 → 测试并保存。")
        self.result_text.setWordWrap(True)
        self.result_text.setMinimumHeight(86)
        panel_layout.addWidget(self.result_text)
        self.adjacent_state = QLabel("相邻页面误识别：尚未验证")
        self.adjacent_state.setStyleSheet("color:#8a5a00;")
        panel_layout.addWidget(self.adjacent_state)
        panel_layout.addStretch(1)
        panel_scroll = QScrollArea(self)
        panel_scroll.setWidgetResizable(True)
        panel_scroll.setFrameShape(QFrame.Shape.NoFrame)
        panel_scroll.setMinimumWidth(450)
        panel_scroll.setWidget(panel)
        body.addWidget(panel_scroll, 2)
        layout.addLayout(body, 1)

        actions = QGridLayout()
        for index, (title, callback) in enumerate((
            ("搜索测试", self.test_same_image),
            ("动态测试（3 张新帧）", self.test_fresh_frames),
            ("截取相邻页面并测试", self.test_adjacent_state),
            ("保存草稿", self.save_draft),
            ("恢复上一版", self.restore_previous),
            ("保存并用于当前设备", self.save_and_apply),
        )):
            button = QPushButton(title)
            button.clicked.connect(callback)
            actions.addWidget(button, index // 3, index % 3)
            if title == "保存并用于当前设备":
                self.apply_button = button
            elif title == "搜索测试":
                self.same_button = button
            elif title == "动态测试（3 张新帧）":
                self.fresh_button = button
            elif title == "截取相邻页面并测试":
                self.negative_button = button
        self.manual_confirm_button = QPushButton("我已在实机确认原故障阶段通过")
        self.manual_confirm_button.setEnabled(bool(self.record))
        self.manual_confirm_button.setVisible(bool(self.record))
        self.manual_confirm_button.clicked.connect(self.confirm_hardware)
        layout.addWidget(self.manual_confirm_button)
        close = QPushButton("关闭")
        close.clicked.connect(self.close)
        actions.addWidget(close, 2, 2)
        layout.addLayout(actions)
        self._update_context()

    def _load_incident_labels(self) -> None:
        if self.record:
            self.script_choice.addItem("故障当次实际使用的标签")
            self.script_choice.setEnabled(False)
            self.label_filter.hide()
            labels = self.record.get("labels", [])
            available = []
            original_dir = self.bundle / "original-labels"
            for item in labels if isinstance(labels, list) else []:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name", ""))
                filename = Path(name).name
                if not filename.lower().endswith(".il"):
                    filename += ".IL"
                source = original_dir / filename
                if source.is_file() and all(existing[0] != filename for existing in available):
                    available.append((filename, item))
            if not available:
                show_error_dialog(self, "缺少当次标签", "故障资料中没有当次实际加载的标签备份，不能直接修复。")
                return
            for filename, info in available:
                score = info.get("score")
                score_text = "本次未评估" if score is None else f"{score} {info.get('operator', '>')} {info.get('threshold')}"
                self.label_choice.addItem(f"{filename} · {score_text}", filename)
            wanted = str(self.record.get("failure_label") or "")
            if wanted:
                index = self.label_choice.findData(Path(wanted).name)
                if index >= 0:
                    self.label_choice.setCurrentIndex(index)
            screenshot = self.record.get("screenshot", {})
            if isinstance(screenshot, dict):
                rel = screenshot.get("match") or screenshot.get("stop")
                if rel:
                    candidate = self.bundle / str(rel)
                    if candidate.is_file():
                        self.frame_path = candidate
            self.device_name = str((self.record.get("capture_device") or {}).get("name") or self.device_name)
        elif self.original_path:
            with QSignalBlocker(self.script_choice):
                self.script_choice.addItem("指定标签")
            self.script_choice.setEnabled(False)
            self.label_filter.hide()
            self.label_choice.addItem(self.original_path.name, str(self.original_path))
        else:
            with QSignalBlocker(self.script_choice):
                for item in script_choices(self.w):
                    self.script_choice.addItem(item.title, str(item.path))
                    self.script_choice.setItemData(self.script_choice.count() - 1, str(item.path), Qt.ItemDataRole.ToolTipRole)
            self._load_script_labels()
            return
        self._load_selected_label()

    def _load_script_labels(self, *_):
        if self.record or not hasattr(self, "label_choice"):
            return
        raw = self.script_choice.currentData()
        self._catalog = ()
        self._catalog_directory = None
        error = "没有找到可用脚本。请先在共通设置中配置脚本包，或准备一个运行方案。"
        if raw:
            try:
                script = Path(raw)
                self._catalog_directory = script.parent / "ImgLabel"
                profile = self.store.profile(self.device_name) if self.device_name else None
                self._catalog = label_choices(script, profile.label_dir if profile else None)
                error = "此脚本及 lib 中没有找到直接引用的标签。"
            except (OSError, UnicodeError, ValueError) as exc:
                error = f"无法读取脚本标签列表：{exc}"
        self._filter_labels()
        if not self._catalog:
            self.label_choice.clear()
            self.label_count.setText("脚本引用 0 个可用标签")
            self._load_selected_label()
            self.result_text.setText(error)

    def _filter_labels(self, *_):
        if self.record or not self.script_choice.currentData():
            return
        previous = self.label_choice.currentData()
        query = self.label_filter.text().strip().casefold()
        choices = [item for item in self._catalog if query in item.name.casefold()]
        with QSignalBlocker(self.label_choice):
            self.label_choice.clear()
            for item in choices:
                exists = item.path.is_file()
                suffix = " · 当前设备覆盖" if item.overridden else "" if exists else " · 文件缺失"
                self.label_choice.addItem(item.name + suffix, str(item.path))
                index = self.label_choice.count() - 1
                self.label_choice.setItemData(index, str(item.path), Qt.ItemDataRole.ToolTipRole)
                if not exists:
                    self.label_choice.model().item(index).setEnabled(False)
            index = self.label_choice.findData(previous)
            if index < 0:
                index = next((i for i, item in enumerate(choices) if item.path.is_file()), -1)
            self.label_choice.setCurrentIndex(index)
        missing = sum(not item.path.is_file() for item in self._catalog)
        self.label_count.setText(f"脚本及 lib 引用 {len(self._catalog)} 个标签 · 显示 {len(choices)} 个"
                                 + (f" · 缺失 {missing} 个" if missing else ""))
        if self.label_choice.currentData() != previous or not self.payload:
            self._load_selected_label()

    def _load_selected_label(self, *_args) -> None:
        raw = self.label_choice.currentData()
        self._condition_changed()
        self.payload = {}
        self.original_payload = {}
        self.original_image = QImage()
        self.old_preview.clear()
        self.new_preview.clear()
        if not raw:
            self.original_path = None
            self.canvas.set_overlays(QRect(), QRect())
            self._update_context()
            self._update_apply_button()
            return
        if self.record:
            self.original_path = self.bundle / "original-labels" / str(raw)
        else:
            self.original_path = Path(str(raw)).resolve()
        try:
            from device_label_overrides import inspect_label_file
            inspect_label_file(self.original_path)
            self.original_payload = json.loads(self.original_path.read_text(encoding="utf-8-sig"))
            if not isinstance(self.original_payload, dict):
                raise ValueError("标签 JSON 根结构必须是对象")
            draft_path = (self.bundle / "repair-draft" / self.original_path.name) if self.bundle else None
            self.payload = dict(self.original_payload)
            if draft_path and draft_path.is_file():
                inspect_label_file(draft_path)
                draft_payload = json.loads(draft_path.read_text(encoding="utf-8-sig"))
                if isinstance(draft_payload, dict):
                    self.payload = dict(draft_payload)
            self._updating_fields = True
            for key in COORDINATE_FIELDS:
                self.spins[key].setValue(int(self.payload[key]))
            self._updating_fields = False
            method = int(self.payload["searchMethod"])
            with QSignalBlocker(self.method_text):
                self.method_text.setCurrentIndex(self.method_text.findData(method))
            operator, threshold = self._condition_for_label(self.original_path.name)
            self.condition_operator.setCurrentText(operator)
            self.condition_threshold.setValue(threshold)
            image_bytes = base64.b64decode(str(self.original_payload["ImgBase64"]), validate=True)
            self.original_image = _qimage_from_bytes(image_bytes)
            self._refresh_frame()
            self._refresh_previews()
            self._same_image_ok = False
            self._fresh_frames_ok = False
            self._same_image_results = ()
            self._fresh_frame_results = ()
            self._adjacent_ok = None
            self._adjacent_results = ()
            self._candidate_sha256 = None
            self.adjacent_state.setText("相邻页面误识别：尚未验证")
            self.adjacent_state.setStyleSheet("color:#8a5a00;")
            self._update_context()
            self._update_apply_button()
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            self.payload = {}
            self.result_text.setText(f"无法载入标签：{exc}")
            self._update_apply_button()

    def _method_changed(self, *_):
        if not self.payload or self._updating_fields:
            return
        self.payload["searchMethod"] = self.method_text.currentData()
        self._coordinates_changed()

    def open_monitor(self):
        if self.record and not EASYCON170_TEST:
            self.start_shared_preview()
            return
        try:
            if self.w.running or self.w.job:
                raise ValueError("请先等待脚本或设备任务结束，再打开监视器制作标签")
            self.w.accessories.open_monitor()
            monitor = self.w.accessories.monitor
            monitor.capture_button.show()
            if monitor.reader is None:
                self.result_text.setText("请先在工具顶部检测并选择采集卡，再点击监视器的“重连”。")
        except (OSError, RuntimeError, ValueError) as exc:
            self.result_text.setText(f"监视器未打开：{exc}")

    def _monitor_reader(self):
        self._check_capture_selection()
        monitor = self.w.accessories.monitor
        reader = monitor.reader if monitor else None
        if reader is None or reader.stop.is_set():
            raise ValueError("没有可用的监视画面，请先打开监视器并等待连接")
        if self.record and not EASYCON170_TEST and not isinstance(reader.source, str):
            raise ValueError("请先启动修复共享预览")
        if reader.source != monitor.current_source():
            raise ValueError("监视器设备已切换，请等待新设备画面")
        return reader

    def _frame_for_label(self, image: QImage) -> QImage:
        if self.record and not EASYCON170_TEST:
            return image.copy()
        return label_frame(image)

    def _monitor_frame(self):
        _, image = self._monitor_reader().latest
        if image is None or image.isNull():
            raise ValueError("监视器尚未收到画面，请等待视频连接后再截图")
        return self._frame_for_label(image)

    def _save_monitor_frame(self, prefix):
        image = self._monitor_frame()
        folder = self._verification_directory() / "captures"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{prefix}-{uuid.uuid4().hex}.png"
        if not image.save(str(path), "PNG"):
            raise ValueError("无法保存监视器截图")
        return path

    def capture_monitor_frame(self):
        try:
            path = self._save_monitor_frame("source")
            self._condition_changed()
            self.frame_path = path
            self.scene_confirm.setChecked(False)
            self._refresh_frame()
            self._refresh_previews()
            self._update_context()
            size = self.canvas.image_size
            self.result_text.setText(f"已从监视器截图（{size.width()} × {size.height()}）。确认页面后，圈选红色搜索范围和绿色模板目标。")
            self.show()
            self.raise_()
            self.activateWindow()
        except (OSError, RuntimeError, ValueError) as exc:
            self.open_monitor()
            self.result_text.setText(f"截图失败：{exc}")

    def _verifier(self):
        if EASYCON170_TEST:
            return verify_preview
        if self.runtime is None:
            self.runtime = prepare_compat_runner(self.w.paths.ezcon)
        from functools import partial
        return partial(verify_label, self.runtime)

    @property
    def _test_kind(self):
        return "本地匹配" if EASYCON170_TEST else "原生"

    def _refresh_frame(self) -> None:
        if self.frame_path and self.frame_path.is_file():
            image = QImage(str(self.frame_path))
            if image.isNull():
                self.canvas.set_image(QImage())
                self.result_text.setText(f"无法解码原图：{self.frame_path}")
                return
            self.canvas.set_image(image)
        self._refresh_overlays()

    def _rect_from_fields(self, prefix: str) -> QRect:
        if prefix == "Range":
            return QRect(self.spins["RangeX"].value(), self.spins["RangeY"].value(),
                         self.spins["RangeWidth"].value(), self.spins["RangeHeight"].value())
        return QRect(self.spins["TargetX"].value(), self.spins["TargetY"].value(),
                     self.spins["TargetWidth"].value(), self.spins["TargetHeight"].value())

    def _refresh_overlays(self) -> None:
        self.canvas.set_overlays(self._rect_from_fields("Range"), self._rect_from_fields("Target"))

    def _coordinates_changed(self, *_args) -> None:
        if self._updating_fields:
            return
        self._dirty = True
        self._refresh_overlays()
        self._refresh_previews()
        self._condition_changed()

    def _condition_changed(self, *_args) -> None:
        was_testing = self.fresh_timer.isActive() or self.native_job is not None
        self.fresh_timer.stop()
        self._fresh_request = None
        if self.native_job:
            self.native_job.cancelled.set()
        self._same_image_ok = False
        self._fresh_frames_ok = False
        self._adjacent_ok = None
        self._same_image_results = ()
        self._fresh_frame_results = ()
        self._fresh_frame_path = None
        self._fresh_frames_dir = None
        self._adjacent_frame_path = None
        self._adjacent_results = ()
        self._candidate_sha256 = None
        self.adjacent_state.setText("相邻页面误识别：尚未验证")
        self.adjacent_state.setStyleSheet("color:#8a5a00;")
        if was_testing:
            self.result_text.setText("标签或验证条件已变化，请重新测试。")
        self._update_apply_button()

    def _selection_finished(self, mode: str, rect: QRect) -> None:
        keys = ("RangeX", "RangeY", "RangeWidth", "RangeHeight") if mode == "range" else (
            "TargetX", "TargetY", "TargetWidth", "TargetHeight")
        values = (rect.x(), rect.y(), rect.width(), rect.height())
        self._updating_fields = True
        for key, value in zip(keys, values):
            self.spins[key].setValue(value)
        self._updating_fields = False
        self._coordinates_changed()
        self.canvas.set_selection_mode("")

    def _choose_frame(self) -> None:
        self.capture_monitor_frame()

    def _refresh_previews(self) -> None:
        if not self.original_image.isNull():
            self.old_preview.setPixmap(QPixmap.fromImage(self.original_image).scaled(
                self.old_preview.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        self.new_preview.setPixmap(QPixmap())
        if self.frame_path and self.frame_path.is_file():
            image = QImage(str(self.frame_path))
            rect = self._rect_from_fields("Target")
            if not image.isNull() and image.rect().contains(rect) and not rect.isEmpty():
                crop = image.copy(rect)
                self.new_preview.setPixmap(QPixmap.fromImage(crop).scaled(
                    self.new_preview.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def _candidate_payload(self) -> dict[str, object]:
        if not self.payload or self.original_path is None:
            raise ValueError("请先从脚本标签列表选择一个可用标签")
        if self.frame_path is None or not self.frame_path.is_file():
            raise ValueError("请先打开监视器，在正确游戏页面点击“截图”")
        frame = QImage(str(self.frame_path))
        rect = self._rect_from_fields("Target")
        search = self._rect_from_fields("Range")
        if frame.isNull():
            raise ValueError("原始截图无法解码")
        if not frame.rect().contains(rect) or not frame.rect().contains(search):
            raise ValueError("搜索范围或模板超出原始截图像素范围")
        if rect.isEmpty() or search.isEmpty():
            raise ValueError("搜索范围和模板尺寸必须大于 0")
        if not search.contains(rect):
            raise ValueError("模板目标必须完整位于红色搜索范围内")
        method = int(self.payload["searchMethod"])
        image_format = QImage.Format.Format_RGBA8888 if method == 14 else QImage.Format.Format_RGB888
        crop = frame.copy(rect).convertToFormat(image_format)
        template_bytes = _qimage_png_bytes(crop)
        payload = dict(self.payload)
        payload.update({
            "RangeX": search.x(), "RangeY": search.y(),
            "RangeWidth": search.width(), "RangeHeight": search.height(),
            "TargetX": rect.x(), "TargetY": rect.y(),
            "TargetWidth": rect.width(), "TargetHeight": rect.height(),
            "ImgBase64": base64.b64encode(template_bytes).decode("ascii"),
        })
        return payload

    def _write_temp_label(self, payload: dict[str, object], folder: Path) -> Path:
        from device_label_overrides import inspect_label_file
        filename = self.original_path.name if self.original_path else str(self.label_choice.currentData())
        destination = folder / filename
        destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        inspect_label_file(destination)
        return destination

    def _condition(self) -> tuple[str, int]:
        if not self.record:
            return self.condition_operator.currentText(), self.condition_threshold.value()
        return self._condition_for_label(self.original_path.name if self.original_path else "")

    def _condition_for_label(self, filename: str) -> tuple[str, int]:
        if self.record:
            for item in self.record.get("labels", []):
                if isinstance(item, dict) and Path(str(item.get("name", ""))).name == filename:
                    operator = str(item.get("operator", ">"))
                    threshold = int(item.get("threshold", 95))
                    if operator not in {">", ">=", "<", "<="}:
                        raise ValueError(f"故障记录中的判定符无效：{operator}")
                    return operator, threshold
        return ">", 95

    def test_same_image(self) -> None:
        if self.frame_path is None:
            self.result_text.setText("请先从监视器截图。")
            return
        try:
            self._check_capture_selection()
            operator, threshold = self._condition()
            payload = self._candidate_payload()
            with tempfile.TemporaryDirectory(prefix="frlg-label-native-") as temp:
                candidate = self._write_temp_label(payload, Path(temp))
                self._candidate_sha256 = hashlib.sha256(candidate.read_bytes()).hexdigest()
                result = self._verifier()(candidate, frame=self.frame_path, operator=operator, threshold=threshold)
            self._same_image_results = result
            self._same_image_ok = bool(result[0].get("passed"))
            self._dirty = True
            self._save_verification()
            self.result_text.setText(self._format_results(f"同图{self._test_kind}测试", result, operator, threshold))
        except (OSError, RuntimeError, ValueError) as exc:
            self._same_image_ok = False
            self.result_text.setText(f"同图{self._test_kind}测试失败：{exc}")
        self._update_apply_button()

    def test_fresh_frames(self) -> None:
        try:
            if self.native_job or self.fresh_timer.isActive():
                raise ValueError("新帧测试正在进行")
            reader = self._monitor_reader()
            operator, threshold = self._condition()
            payload = self._candidate_payload()
            self._fresh_frames_dir = self._verification_directory() / f"fresh-frames-{uuid.uuid4().hex}"
            self._fresh_frames_dir.mkdir(parents=True, exist_ok=True)
            candidate = self._write_temp_label(payload, self._fresh_frames_dir)
            self._candidate_sha256 = hashlib.sha256(candidate.read_bytes()).hexdigest()
            source_digest = self._sha256_path(self.frame_path)
            self._fresh_request = (candidate, self._candidate_sha256, self.device_name, operator, threshold, reader, source_digest)
            self._fresh_last_seq = reader.latest[0]
            self._fresh_paths = []
            self._fresh_sequences = []
            import time
            self._fresh_deadline = time.monotonic()+8
            self._fresh_frames_ok = False
            self.fresh_timer.start()
            self.result_text.setText("正在从监视器等待 3 张新帧……")
        except (OSError, RuntimeError, ValueError) as exc:
            self._fresh_frames_ok = False
            self.result_text.setText(f"动态测试失败：{exc}")
        self._update_apply_button()

    def _collect_fresh(self):
        import time
        if self._fresh_request is None:
            return
        candidate, digest, device, operator, threshold, reader, source_digest = self._fresh_request
        try:
            if reader is not self._monitor_reader():
                raise ValueError("监视器已切换，请重新测试")
            if self._sha256_path(self.frame_path) != source_digest:
                raise ValueError("原图已变化；请重新执行新帧测试")
            if time.monotonic() > self._fresh_deadline:
                raise ValueError("监视器未及时提供三张新帧；原验证未通过")
            seq, frame = reader.latest
            if seq <= self._fresh_last_seq or frame is None or frame.isNull():
                return
            self._fresh_last_seq = seq
            frame = self._frame_for_label(frame)
            if frame.size() != self.canvas.image_size:
                raise ValueError("新帧分辨率与原图不同；请重新核对设备和模板")
            path = self._fresh_frames_dir / f"frame-{len(self._fresh_paths)}.png"
            if not frame.save(str(path), "PNG"):
                raise ValueError("新帧无法保存")
            self._fresh_paths.append(path)
            self._fresh_sequences.append((seq, time.monotonic()))
            if len(self._fresh_paths) < 3:
                return
            self.fresh_timer.stop()
            from .jobs import Job
            paths = tuple(self._fresh_paths)
            sequences = tuple(self._fresh_sequences)
            verify_candidate = self._verifier()
            def verify(cancel,status):
                results = []
                for i,path in enumerate(paths):
                    if cancel():
                        raise ValueError("验证已取消")
                    item = dict(verify_candidate(candidate,frame=path,operator=operator,threshold=threshold)[0])
                    item.update(frame_index=i,saved_frame=str(path),monitor_sequence=sequences[i][0],
                                shared_preview_sequence=sequences[i][0] if isinstance(reader.source, str) else None,
                                received_monotonic=sequences[i][1])
                    results.append(item)
                return digest,device,tuple(results),operator,threshold,source_digest,reader
            self.native_job = Job(verify,self)
            self.native_job.succeeded.connect(self.nativeDelivery.emit)
            self.native_job.failed.connect(lambda error: self.nativeDelivery.emit(error))
            self.native_job.finished.connect(self.nativeFinished.emit)
            self.native_job.start()
        except (OSError,RuntimeError,ValueError) as exc:
            self.fresh_timer.stop()
            self._fresh_frames_ok = False
            self.result_text.setText(str(exc))

    @Slot(object)
    def _fresh_verified(self, result):
        if self._fresh_request is None:
            return
        try:
            if isinstance(result,str):
                raise ValueError(result)
            digest,device,results,operator,threshold,source_digest,reader = result
            if reader is not self._monitor_reader():
                raise ValueError("监视器已切换，请重新测试")
            if self._sha256_path(self.frame_path) != source_digest:
                raise ValueError("原图已变化；旧新帧验证失效")
            with tempfile.TemporaryDirectory() as temp:
                current = self._write_temp_label(self._candidate_payload(),Path(temp))
                if hashlib.sha256(current.read_bytes()).hexdigest()!=digest or device != self.device_name or self._condition()!=(operator,threshold):
                    raise ValueError("标签、设备或条件已变化；旧新帧验证失效")
            self._fresh_frame_results = results
            self._fresh_frames_ok = len(results)==3 and all(item.get("passed") for item in results)
            self._fresh_frame_path = Path(results[0]["saved_frame"])
            self._save_verification()
            self.result_text.setText(self._format_results(f"监视器 3 张新帧{self._test_kind}测试",results,operator,threshold))
        except (OSError,RuntimeError,ValueError) as exc:
            self._fresh_frames_ok = False
            self.result_text.setText(f"动态测试失败：{exc}")
        self._update_apply_button()

    @Slot()
    def _native_finished(self):
        job,self.native_job = self.native_job,None
        if job:
            job.deleteLater()
        self._update_apply_button()

    def start_shared_preview(self):
        from .repair_preview import RepairPreview
        if not hasattr(self.w.accessories,"repair_preview"):
            self.w.accessories.repair_preview = RepairPreview(self.w.accessories)
        try:
            self._check_capture_selection()
            self.w.accessories.repair_preview.start()
            self.w.accessories.monitor.capture_button.show()
        except (OSError,RuntimeError,ValueError) as exc:
            self.result_text.setText(f"共享预览未启动：{exc}")

    def import_candidates(self, paths=None):
        from device_label_overrides import inspect_label_file
        if not isinstance(paths,(tuple,list)):
            paths = QFileDialog.getOpenFileNames(self,"逐项校验导入标签","","EasyCon 标签 (*.IL *.il)")[0]
        messages = []
        allowed = {item["name"] for item in self.record.get("labels",[])} if self.record else None
        for name in paths:
            path = Path(name).resolve()
            try:
                inspect_label_file(path)
                if allowed is not None and path.name not in allowed:
                    raise ValueError("文件名不属于本次故障候选，请在独立标签编辑器处理")
                duplicate = next((i for i in range(self.label_choice.count()) if Path(str(self.label_choice.itemData(i))).name == path.name),None)
                if duplicate is not None:
                    if QMessageBox.question(self,"候选冲突",f"以导入文件替换编辑候选 {path.name}？该候选须重新单独测试。") != QMessageBox.StandardButton.Yes:
                        messages.append(f"{path.name}：已取消")
                        continue
                    self.label_choice.setItemData(duplicate,str(path))
                    self.label_choice.setCurrentIndex(duplicate)
                    self._load_selected_label()
                else:
                    self.label_choice.addItem(path.name,str(path))
                messages.append(f"{path.name}：结构通过；原图、新帧及负样本尚未验证")
            except (OSError,ValueError) as exc:
                messages.append(f"{path.name}：失败，{exc}")
        self.result_text.setText("\n".join(messages) or "未导入文件")

    def dragEnterEvent(self,event):
        urls=event.mimeData().urls()
        if urls and all(u.isLocalFile() and Path(u.toLocalFile()).suffix.casefold()==".il" for u in urls) and self.native_job is None:
            event.acceptProposedAction()

    def dropEvent(self,event):
        paths=[u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        self.import_candidates(paths)
        event.acceptProposedAction()

    def confirm_hardware(self):
        try:
            self._check_capture_selection()
            record = self.incidents.read(self.incident_id)
            if record.get("resolution",{}).get("status") not in {"applied","loaded"}:
                raise ValueError("覆盖尚未应用到工程，不能确认实机复测")
            proof = json.loads((self.bundle / "verification.json").read_text(encoding="utf-8"))
            overrides = self.store.list_overrides(self.device_name)
            matching = next((item for item in overrides if item["name"]==proof.get("label") and item["sha256"]==proof.get("candidate_sha256")),None)
            if matching is None:
                raise ValueError("当前覆盖摘要与已验证候选不一致；请重新测试并应用")
            if QMessageBox.question(self,"人工实机确认",f"确认使用相同设备和覆盖，在实机中已通过原故障阶段 {record['stage_id']}？\n覆盖 SHA256：{matching['sha256']}\n此确认来自你的实际观察。") != QMessageBox.StandardButton.Yes:
                return
            proof["manual_confirmation"] = {"source":"user_explicit_hardware_confirmation", "stage_id":record["stage_id"], "device":self.device_name,"sha256":matching["sha256"],"at":datetime.now(timezone.utc).isoformat()}
            self.incidents.write_verification(self.incident_id,proof)
            self.incidents.set_status(self.incident_id,"resolved",note="用户明确确认相同覆盖与原阶段实机复测通过；来源及摘要见 verification.json。")
            self.result_text.setText("已记录人工实机确认。")
        except (OSError,ValueError,TypeError) as exc:
            self.result_text.setText(f"未确认解决：{exc}")

    def test_adjacent_state(self) -> None:
        try:
            path = self._save_monitor_frame("adjacent")
            operator, threshold = self._condition()
            payload = self._candidate_payload()
            with tempfile.TemporaryDirectory(prefix="frlg-label-adjacent-") as temp:
                candidate = self._write_temp_label(payload, Path(temp))
                self._candidate_sha256 = hashlib.sha256(candidate.read_bytes()).hexdigest()
                result = self._verifier()(candidate, frame=path, operator=operator, threshold=threshold)
            self._adjacent_frame_path = Path(path).resolve()
            self._adjacent_results = result
            self._adjacent_ok = not bool(result[0].get("passed"))
            self.adjacent_state.setText(
                ("相邻页面未误识别 · 通过" if self._adjacent_ok else "相邻页面被误识别 · 未通过")
                + f" · {self._adjacent_frame_path.name} · 分数 {result[0]['integer_score']}"
            )
            self.adjacent_state.setStyleSheet("color:#137547;" if self._adjacent_ok else "color:#b42318;")
            self._save_verification()
        except (OSError, RuntimeError, ValueError) as exc:
            self._adjacent_ok = False
            self.adjacent_state.setText(f"相邻页面{self._test_kind}测试失败：{exc}")
            self.adjacent_state.setStyleSheet("color:#b42318;")

    def _check_capture_selection(self) -> None:
        if self.w.running or self.w.job:
            raise ValueError("请先等待脚本或设备任务结束，再制作或测试标签")
        selected_id = self.w.fields["video"].currentData()
        current_name = self.w.devices[1].get(selected_id, "")
        if selected_id is None or not current_name:
            raise ValueError("请先检测并选择采集卡")
        if self.device_name and current_name.casefold() != self.device_name.casefold():
            raise ValueError("当前采集卡与故障时设备名称不同；请先核对设备档案")

    @staticmethod
    def _format_results(title: str, results, operator: str, threshold: int) -> str:
        rows = []
        for item in results:
            passed = "通过" if item.get("passed") else "未通过"
            rows.append(
                f"第 {int(item.get('frame_index', 0)) + 1} 帧：原始 {float(item['raw_score']):.3f}，"
                f"整数 {item['integer_score']} {operator} {threshold} · {passed} · "
                f"{float(item['elapsed_ms']):.1f} ms"
            )
        return title + "\n" + "\n".join(rows)

    def _save_verification(self) -> None:
        payload = {
            "schema": "frlg-label-verification/v1",
            "engine": "local-opencv-preview" if EASYCON170_TEST else "native-cli",
            "native_verified": not EASYCON170_TEST,
            "incident_id": self.incident_id,
            "label": self.original_path.name if self.original_path else None,
            "candidate_sha256": self._candidate_sha256,
            "device": self.device_name,
            "resolution": [self.canvas.image_size.width(),self.canvas.image_size.height()],
            "operator": self._condition()[0], "threshold": self._condition()[1],
            "search_method": self.payload.get("searchMethod"),
            "source_frame": str(self.frame_path) if self.frame_path else None,
            "source_frame_sha256": self._sha256_path(self.frame_path),
            "same_image": {"passed": self._same_image_ok, "results": list(self._same_image_results)},
            "fresh_frames": {"passed": self._fresh_frames_ok, "results": list(self._fresh_frame_results)},
            "adjacent_state": {
                "passed": self._adjacent_ok,
                "source_frame": str(self._adjacent_frame_path) if self._adjacent_frame_path else None,
                "source_frame_sha256": self._sha256_path(self._adjacent_frame_path),
                "results": list(self._adjacent_results),
                "note": "没有相邻页面样本，尚未验证。" if self._adjacent_ok is None else None,
            },
            "fresh_frames_directory": str(self._fresh_frames_dir) if self._fresh_frames_dir else None,
            "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        if self.incident_id:
            self.incidents.write_verification(self.incident_id, payload)
            return
        destination_dir = self._verification_directory()
        destination_dir.mkdir(parents=True, exist_ok=True)
        path = destination_dir / "verification.json"
        temporary = path.with_name(path.name + f".{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("w", encoding="utf-8", newline="\n") as stream:
                stream.write(json.dumps(payload, ensure_ascii=False, indent=2))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def _verification_directory(self) -> Path:
        root = self.bundle / "verification" if self.bundle else self.w.paths.user / "label_verifications"
        return root / f"session-{self._verification_session}"

    @staticmethod
    def _sha256_path(path: Path | None) -> str | None:
        if path is None or not path.is_file():
            return None
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def save_draft(self) -> None:
        try:
            payload = self._candidate_payload()
            with tempfile.TemporaryDirectory(prefix="frlg-label-draft-") as temp:
                candidate = self._write_temp_label(payload, Path(temp))
                data = candidate.read_bytes()
            if self.bundle and self.incident_id:
                draft = self.incidents.write_draft(self.incident_id, self.original_path.name, data)
            else:
                directory = self._verification_directory() / "drafts"
                directory.mkdir(parents=True, exist_ok=True)
                draft = directory / self.original_path.name
                draft.write_bytes(data)
            self.result_text.setText(f"草稿已保存：{draft}\n状态：未应用到当前设备。")
        except (OSError, RuntimeError, ValueError) as exc:
            show_error_dialog(self, "草稿保存失败", str(exc))

    def restore_previous(self) -> None:
        try:
            self._check_capture_selection()
            if self.original_path is None:
                raise ValueError("请先选择要恢复的标签")
            result = self.store.restore_previous(self.device_name, self.original_path.name)
            applied = self._apply_profile_and_rebuild()
            self.result_text.setText(
                f"{result}；" + ("运行工程已按原目标重建。" if applied else "设备覆盖已恢复，当前没有可重建的已选方案。")
            )
        except (OSError, RuntimeError, ValueError) as exc:
            show_error_dialog(self, "恢复失败", str(exc))

    def save_and_apply(self) -> None:
        if not self.scene_confirm.isChecked():
            show_error_dialog(self,"现场尚未确认","请先确认截图确实是预期页面，错误页面应先修复启动位置。")
            return
        if self._adjacent_ok is False:
            show_error_dialog(self, "相邻页面被误识别", "当前标签会在相邻页面触发；请调整模板或范围后重新完成测试。")
            return
        if not self._same_image_ok or not self._fresh_frames_ok:
            show_error_dialog(self, "尚未完成验证", f"先通过同图{self._test_kind}测试和 3 张新帧动态测试；相邻页面检查仍会明确标为未验证。")
            return
        try:
            self._check_capture_selection()
            payload = self._candidate_payload()
            with tempfile.TemporaryDirectory(prefix="frlg-label-apply-") as temp:
                candidate = self._write_temp_label(payload, Path(temp))
                data = candidate.read_bytes()
                digest = hashlib.sha256(data).hexdigest()
                if digest != self._candidate_sha256:
                    raise ValueError("标签摘要与测试结果不一致；请重新测试")
                if QMessageBox.question(self,"保存到当前设备",f"设备：{self.device_name}\n标签：{self.original_path.name}\n相邻页面测试：{'通过' if self._adjacent_ok else '未验证'}\n保存后用于这台设备，并更新当前已准备方案；上一版可恢复。") != QMessageBox.StandardButton.Yes:
                    return
                if self.incident_id:
                    self.incidents.write_draft(self.incident_id, self.original_path.name, data)
                    verification_path = self.bundle / "verification.json"
                    verification = json.loads(verification_path.read_text(encoding="utf-8")) if verification_path.is_file() else None
                    provenance = {
                        self.original_path.name: {
                            "incident_id": self.incident_id,
                            "verification": verification,
                            "operation": "label_editor",
                            "source": "in_app_label_editor",
                        }
                    }
                else:
                    provenance = {self.original_path.name: {
                        "operation": "label_editor", "source": "in_app_label_editor",
                        "verification": json.loads((self._verification_directory() / "verification.json").read_text(encoding="utf-8")),
                    }}
                self.store.import_paths(
                    self.device_name, [candidate], self._known_label_directories(),
                    provenance=provenance,
                )
            if self.incident_id:
                self.incidents.set_status(self.incident_id, "override_saved", note="设备覆盖已事务保存；等待同目标运行工程重建。")
            try:
                project_applied = self._apply_profile_and_rebuild()
            except (OSError, RuntimeError, ValueError) as exc:
                if self.incident_id:
                    self.incidents.set_status(self.incident_id, "failed", note=f"设备覆盖已保存，但运行工程重建未完成：{exc}")
                raise
            if self.incident_id and project_applied:
                adjacent_note = "相邻页面样本通过。" if self._adjacent_ok else "相邻页面没有样本，仍未验证。"
                self.incidents.set_status(self.incident_id, "applied", note="设备覆盖已保存，并按原已选目标重建工程且通过正式预检；" + adjacent_note)
            elif self.incident_id:
                self.incidents.set_status(self.incident_id, "override_saved", note="设备覆盖已保存；当前没有已选运行方案，因此尚未应用到运行工程。")
            self.result_text.setText(
                "制作草稿 → 设备覆盖已保存 → "
                + ("原目标运行工程已重建并预检通过。\n新运行会重新加载此标签。" if project_applied else "尚无运行工程可应用；下次准备时将使用此标签。")
                + ("\n相邻页面样本验证通过。" if self._adjacent_ok else "\n相邻页面误识别尚未验证。")
            )
            self._dirty = False
            self.accept()
        except (OSError, RuntimeError, ValueError) as exc:
            show_error_dialog(self, "保存或重新准备失败", f"标签内容仍保留在故障资料中。\n{exc}")

    def _known_label_directories(self) -> tuple[Path, ...]:
        directories = [Path(self.w.fields[key].text()) / "ImgLabel" for key in (
            "source", "sid_source", "tid_source") if self.w.fields[key].text().strip()]
        if self._catalog_directory:
            directories.insert(0, self._catalog_directory)
        if self.original_path:
            directories.insert(0, self.original_path.parent)
        return tuple(dict.fromkeys(directories))

    def _apply_profile_and_rebuild(self) -> bool:
        if getattr(self.w, "workflow", None) is not None:
            from .workflows import prepare_workflow
            old = self.w.workflow
            if old.inputs.mode in {"script_test", "sid_traversal"}:
                from automation import EasyConRuntimeCheck
                self.w.workflow = replace(old, check=EasyConRuntimeCheck(
                    False, ("当前流程不能安全应用设备标签覆盖；请重新准备流程。",), ()))
                self.w.refresh_state()
                raise ValueError("当前方案不能用同目标自动重建；设备覆盖已保存，运行入口已锁定。")
            try:
                rebuilt = prepare_workflow(old.inputs, self.w.paths, cancel=lambda: False)
            except Exception as exc:
                from automation import EasyConRuntimeCheck
                self.w.workflow = replace(old, check=EasyConRuntimeCheck(False, (str(exc),), ()))
                self.w.refresh_state()
                raise ValueError(f"同目标运行工程重建失败：{exc}") from exc
            if not rebuilt.check.ok:
                self.w.workflow = rebuilt
                self.w.refresh_state()
                raise ValueError("标签已保存，但同目标工程预检未通过：\n" + "\n".join(rebuilt.check.errors))
            self.w.workflow = rebuilt
            self.w.result_panel.setPlainText(rebuilt.details)
            self.w.set_status("新标签已保存；原已选目标的运行工程已重新生成并通过预检，等待开始运行。")
            self.w.refresh_state()
            return True
        if getattr(self.w, "prepared", None) is not None:
            from .services import rebuild_wild_with_override
            old = self.w.prepared
            try:
                rebuilt = rebuild_wild_with_override(old, self.w.paths)
            except Exception as exc:
                from automation import EasyConRuntimeCheck
                self.w.prepared = replace(old, check=EasyConRuntimeCheck(False, (str(exc),), ()))
                self.w.refresh_state()
                raise ValueError(f"原目标运行工程重建失败：{exc}") from exc
            if not rebuilt.check.ok:
                self.w.prepared = rebuilt
                self.w.refresh_state()
                raise ValueError("标签已保存，但原目标运行工程预检未通过：\n" + "\n".join(rebuilt.check.errors))
            self.w.prepared = rebuilt
            self.w.set_status("新标签已保存；原已选 Seed / Advance 的运行工程已重建并通过预检。")
            self.w.refresh_state()
            return True
        self.w.set_status("设备覆盖已保存。请用现有目标重新准备运行工程；此次没有可保留的已选方案。")
        return False

    def _update_context(self) -> None:
        if self.record:
            stage = self.record.get("stage_id", "未知阶段")
            kind = self.record.get("failure_kind", "未知故障")
            names = "、".join(str(item.get("name")) for item in self.record.get("labels", []) if isinstance(item, dict))
            frame_time = self.record.get("capture", {}).get("snapshot_at_utc", "") if isinstance(self.record.get("capture"), dict) else ""
            self.context.setText(f"故障：{stage} · {kind}　标签：{names or '暂无'}\n"
                                 f"设备：{self.device_name or '待选择'}　截图：{self.frame_path or '未载入'}　{frame_time}")
        else:
            self.context.setText(f"标签：{self.original_path.name if self.original_path else '从脚本列表选择'}　设备：{self.device_name or '请在主窗口选择采集卡'}\n"
                                 "监视器截图 → 圈选搜索范围和模板 → 测试 → 保存到当前设备。"
                                 + (" 170 使用本地匹配测试，实机效果需运行脚本确认。" if EASYCON170_TEST else ""))

    def _update_apply_button(self) -> None:
        if hasattr(self, "apply_button"):
            self.apply_button.setEnabled(
                bool(self.payload) and self.frame_path is not None and self._same_image_ok and self._fresh_frames_ok
                and self._adjacent_ok is not False and self.scene_confirm.isChecked()
                and not self.native_job and not self.fresh_timer.isActive()
            )

    def closeEvent(self,event):
        self.fresh_timer.stop()
        if self.native_job:
            self.native_job.cancelled.set()
            event.ignore()
            QTimer.singleShot(100,self.close)
            return
        if hasattr(self.w,"page_guides") and self.w.page_guides.child is self:
            self.w.page_guides.minimize()
        if hasattr(self.w.accessories,"repair_preview"):
            self.w.accessories.repair_preview.stop()
        super().closeEvent(event)

    def done(self,result):
        self.fresh_timer.stop()
        if self.native_job:
            self.native_job.cancelled.set()
            return
        if hasattr(self.w,"page_guides") and self.w.page_guides.child is self:
            self.w.page_guides.minimize()
        if hasattr(self.w.accessories,"repair_preview"):
            self.w.accessories.repair_preview.stop()
        super().done(result)
