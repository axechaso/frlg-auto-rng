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

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QRect, Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QFormLayout, QGridLayout, QGroupBox,
    QHBoxLayout, QLabel, QMessageBox, QPushButton, QSpinBox, QVBoxLayout,
    QWidget,
)

from automation.easycon118 import prepare_compat_runner
from device_label_overrides import LabelOverrideStore
from label_incidents import LabelIncidentStore
from label_verification import verify_label
from .label_canvas import LabelCanvas


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
        self.runtime = prepare_compat_runner(window.paths.ezcon)
        self.payload: dict[str, object] = {}
        self.original_payload: dict[str, object] = {}
        self.original_image = QImage()
        self._updating_fields = False
        self._same_image_ok = False
        self._fresh_frames_ok = False
        self._same_image_results: tuple[dict[str, object], ...] = ()
        self._fresh_frame_results: tuple[dict[str, object], ...] = ()
        self._fresh_frame_path: Path | None = None
        self._fresh_frames_dir: Path | None = None
        self._adjacent_frame_path: Path | None = None
        self._adjacent_results: tuple[dict[str, object], ...] = ()
        self._adjacent_ok: bool | None = None
        self._candidate_sha256: str | None = None
        self._verification_session = uuid.uuid4().hex
        self._dirty = False
        self.setWindowTitle("EasyCon 标签制作与修复")
        self.resize(1180, 790)
        self._build_ui()
        self._load_incident_labels()

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
        body = QHBoxLayout()
        self.canvas = LabelCanvas(self)
        self.canvas.selectionFinished.connect(self._selection_finished)
        self.canvas.imageOpenRequested.connect(self._choose_frame)
        body.addWidget(self.canvas, 3)

        panel = QWidget(self)
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        self.label_choice = QComboBox()
        self.label_choice.currentIndexChanged.connect(self._load_selected_label)
        panel_layout.addWidget(QLabel("标签"))
        panel_layout.addWidget(self.label_choice)
        self.method_text = QLabel("搜索方法：—")
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
        self.result_text = QLabel("先确认故障画面确实处于目标界面，再执行原生测试。")
        self.result_text.setWordWrap(True)
        self.result_text.setMinimumHeight(86)
        panel_layout.addWidget(self.result_text)
        self.adjacent_state = QLabel("相邻页面误识别：尚未验证")
        self.adjacent_state.setStyleSheet("color:#8a5a00;")
        panel_layout.addWidget(self.adjacent_state)
        panel_layout.addStretch(1)
        body.addWidget(panel, 2)
        layout.addLayout(body, 1)

        actions = QHBoxLayout()
        for title, callback in (
            ("载入截图", self._choose_frame),
            ("搜索测试", self.test_same_image),
            ("动态测试（3 张新帧）", self.test_fresh_frames),
            ("测试相邻页面截图", self.test_adjacent_state),
            ("保存草稿", self.save_draft),
            ("恢复上一版", self.restore_previous),
            ("保存并用于当前设备", self.save_and_apply),
        ):
            button = QPushButton(title)
            button.clicked.connect(callback)
            actions.addWidget(button)
            if title == "保存并用于当前设备":
                self.apply_button = button
        close = QPushButton("关闭")
        close.clicked.connect(self.close)
        actions.addWidget(close)
        layout.addLayout(actions)
        self._update_context()

    def _load_incident_labels(self) -> None:
        if self.record:
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
                QMessageBox.warning(self, "缺少当次标签", "故障资料中没有当次实际加载的标签备份，不能直接修复。")
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
            self.label_choice.addItem(self.original_path.name, str(self.original_path))
        self._load_selected_label()

    def _load_selected_label(self, *_args) -> None:
        raw = self.label_choice.currentData()
        if not raw:
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
            self.method_text.setText(f"搜索方法：{method}" + ("（修复模式锁定）" if self.record else ""))
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
            self.result_text.setText(f"无法载入标签：{exc}")

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
        self._same_image_ok = False
        self._fresh_frames_ok = False
        self._adjacent_ok = None
        self._adjacent_results = ()
        self.adjacent_state.setText("相邻页面误识别：尚未验证")
        self.adjacent_state.setStyleSheet("color:#8a5a00;")
        self._update_apply_button()

    def _condition_changed(self, *_args) -> None:
        self._same_image_ok = False
        self._fresh_frames_ok = False
        self._adjacent_ok = None
        self._same_image_results = ()
        self._fresh_frame_results = ()
        self._adjacent_results = ()
        self.adjacent_state.setText("相邻页面误识别：尚未验证")
        self.adjacent_state.setStyleSheet("color:#8a5a00;")
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
        path = QFileDialog.getOpenFileName(self, "载入原始截图", str(self.frame_path.parent if self.frame_path else Path.home()),
                                           "图像 (*.png *.bmp *.jpg *.jpeg)")[0]
        if path:
            self.frame_path = Path(path).resolve()
            self._refresh_frame()
            self._same_image_ok = False
            self._fresh_frames_ok = False
            self._adjacent_ok = None
            self._adjacent_results = ()
            self.adjacent_state.setText("相邻页面误识别：尚未验证")
            self.adjacent_state.setStyleSheet("color:#8a5a00;")
            self._update_context()
            self._update_apply_button()

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
        if self.frame_path is None or not self.frame_path.is_file():
            raise ValueError("请先载入正确界面的原始截图")
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
            self.result_text.setText("请先载入原始截图。")
            return
        try:
            operator, threshold = self._condition()
            payload = self._candidate_payload()
            with tempfile.TemporaryDirectory(prefix="frlg-label-native-") as temp:
                candidate = self._write_temp_label(payload, Path(temp))
                self._candidate_sha256 = hashlib.sha256(candidate.read_bytes()).hexdigest()
                result = verify_label(self.runtime, candidate, frame=self.frame_path,
                                      operator=operator, threshold=threshold)
            self._same_image_results = result
            self._same_image_ok = bool(result[0].get("passed"))
            self._dirty = True
            self._save_verification()
            self.result_text.setText(self._format_results("同图原生测试", result, operator, threshold))
        except (OSError, RuntimeError, ValueError) as exc:
            self._same_image_ok = False
            self.result_text.setText(f"同图原生测试失败：{exc}")
        self._update_apply_button()

    def test_fresh_frames(self) -> None:
        try:
            self._check_capture_selection()
            if hasattr(self.w, "accessories") and not self.w.accessories.release_for_run():
                raise RuntimeError("监视窗口仍在释放采集卡，请稍后重试")
            operator, threshold = self._condition()
            payload = self._candidate_payload()
            self._fresh_frames_dir = self._verification_directory() / f"fresh-frames-{uuid.uuid4().hex}"
            self._fresh_frames_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix="frlg-label-native-") as temp:
                candidate = self._write_temp_label(payload, Path(temp))
                self._candidate_sha256 = hashlib.sha256(candidate.read_bytes()).hexdigest()
                results = verify_label(
                    self.runtime, candidate, device=int(self.w.fields["video"].currentData()),
                    frames=3, interval_ms=250, operator=operator, threshold=threshold,
                    save_frames_directory=self._fresh_frames_dir,
                )
            self._fresh_frame_results = results
            self._fresh_frames_ok = all(bool(item.get("passed")) for item in results)
            first_saved = results[0].get("saved_frame") if results else None
            self._fresh_frame_path = Path(str(first_saved)) if first_saved else None
            self._save_verification()
            self.result_text.setText(self._format_results("3 张新帧原生动态测试", results, operator, threshold))
        except (OSError, RuntimeError, ValueError) as exc:
            self._fresh_frames_ok = False
            self.result_text.setText(f"动态测试失败：{exc}")
        finally:
            if hasattr(self.w, "accessories"):
                self.w.accessories.run_finished()
        self._update_apply_button()

    def test_adjacent_state(self) -> None:
        path = QFileDialog.getOpenFileName(
            self, "选择应与此标签区分的相邻页面截图",
            str(self.frame_path.parent if self.frame_path else Path.home()),
            "图像 (*.png *.bmp *.jpg *.jpeg)",
        )[0]
        if not path:
            return
        try:
            operator, threshold = self._condition()
            payload = self._candidate_payload()
            with tempfile.TemporaryDirectory(prefix="frlg-label-adjacent-") as temp:
                candidate = self._write_temp_label(payload, Path(temp))
                self._candidate_sha256 = hashlib.sha256(candidate.read_bytes()).hexdigest()
                result = verify_label(self.runtime, candidate, frame=path,
                                      operator=operator, threshold=threshold)
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
            self.adjacent_state.setText(f"相邻页面原生测试失败：{exc}")
            self.adjacent_state.setStyleSheet("color:#b42318;")

    def _check_capture_selection(self) -> None:
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
            "incident_id": self.incident_id,
            "label": self.original_path.name if self.original_path else None,
            "candidate_sha256": self._candidate_sha256,
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
                path = QFileDialog.getSaveFileName(self, "保存标签草稿", self.original_path.name,
                                                   "EasyCon 标签 (*.IL)")[0]
                if not path:
                    return
                draft = Path(path)
                draft.write_bytes(data)
            self.result_text.setText(f"草稿已保存：{draft}\n状态：未应用到当前设备。")
        except (OSError, RuntimeError, ValueError) as exc:
            QMessageBox.warning(self, "草稿保存失败", str(exc))

    def restore_previous(self) -> None:
        try:
            self._check_capture_selection()
            result = self.store.restore_previous(self.device_name, self.original_path.name)
            applied = self._apply_profile_and_rebuild()
            self.result_text.setText(
                f"{result}；" + ("运行工程已按原目标重建。" if applied else "设备覆盖已恢复，当前没有可重建的已选方案。")
            )
        except (OSError, RuntimeError, ValueError) as exc:
            QMessageBox.warning(self, "恢复失败", str(exc))

    def save_and_apply(self) -> None:
        if self._adjacent_ok is False:
            QMessageBox.information(self, "相邻页面被误识别", "当前标签会在相邻页面触发；请调整模板或范围后重新完成测试。")
            return
        if not self._same_image_ok or not self._fresh_frames_ok:
            QMessageBox.information(self, "尚未完成验证", "先通过同图原生测试和 3 张新帧动态测试；相邻页面检查仍会明确标为未验证。")
            return
        try:
            self._check_capture_selection()
            payload = self._candidate_payload()
            with tempfile.TemporaryDirectory(prefix="frlg-label-apply-") as temp:
                candidate = self._write_temp_label(payload, Path(temp))
                data = candidate.read_bytes()
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
                    provenance = {}
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
            QMessageBox.warning(self, "保存或重新准备失败", f"标签内容仍保留在故障资料中。\n{exc}")

    def _known_label_directories(self) -> tuple[Path, ...]:
        return tuple(Path(self.w.fields[key].text()) / "ImgLabel" for key in (
            "source", "sid_source", "tid_source"))

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
            self.context.setText(f"标签：{self.original_path or '未选择'}　设备：{self.device_name or '待选择'}\n"
                                 "确认截图处于该标签应识别的游戏页面。坐标始终使用原图像素。")

    def _update_apply_button(self) -> None:
        if hasattr(self, "apply_button"):
            self.apply_button.setEnabled(
                self._same_image_ok and self._fresh_frames_ok and self._adjacent_ok is not False
            )
