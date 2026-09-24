"""Device utilities and label management for the Qt shell."""
from pathlib import Path
import json

from PySide6.QtCore import QObject, QEvent, QTimer, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QFileDialog, QLabel, QMessageBox, QPushButton, QTableWidgetItem

from device_label_overrides import LabelOverrideStore, diagnose_label_log
from label_incidents import LabelIncidentStore
from pyside_preview import Card
from .manual import ControllerWindow, MonitorWindow


class Accessories(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.w = window
        self.controller = self.monitor = None
        self.store = LabelOverrideStore(window.paths.user / "device_label_overrides")
        self.incidents = LabelIncidentStore(window.paths.user / "label_incidents")
        self.active_incident_id = None
        self.loaded_incidents: set[str] = set()
        self.card = window.label_issues.parentWidget()
        while not isinstance(self.card, Card):
            self.card = self.card.parentWidget()
        self.card.toggle.setToolTip("按采集卡名称保存覆盖；原始脚本包中的标签保留。")
        self.label_status = self.card.layout.itemAt(0).widget()
        self.drop = next(
            widget for widget in self.card.findChildren(QLabel)
            if widget.text().startswith("拖放 .IL")
        )
        self.drop.setText("拖放 .IL 文件或文件夹到这里")
        self.drop.setAcceptDrops(True)
        self.drop.installEventFilter(self)
        self.last_log = ""
        self.ignored_prefix = ""
        for title, action in (("虚拟手柄", self.open_controller), ("监视窗口", self.open_monitor),
            ("手柄键位", self.open_controller_mapping),
            ("制作 / 修复标签", self.open_label_editor),
            ("检查/更新 Seed 表", self.update_seeds), ("选择标签文件（可多选）", self.choose_labels),
            ("选择标签文件夹", self.choose_label_directory), ("清除当前设备覆盖", self.clear_overrides)):
            window._bind(title, action)
        window.actions["虚拟手柄"].setToolTip("使用顶部所选串口打开手柄浮窗；键位在共通设置中修改。")
        window.actions["手柄键位"].setToolTip("按手柄位置设置键盘映射，不打开手柄主窗口。")
        clear = next(button for button in self.card.findChildren(QPushButton) if button.text() == "清空诊断列表")
        clear.clicked.disconnect()
        clear.clicked.connect(self.clear_issues)
        window.label_incident_open.clicked.connect(self.open_active_incident)
        window.fields["video"].currentIndexChanged.connect(self.refresh_labels)
        window.fields["port"].currentIndexChanged.connect(self.port_changed)
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.diagnose)
        self.timer.start()
        self.refresh_labels()
        self.poll_incidents()

    def device_name(self):
        name = self.w.devices[1].get(self.w.fields["video"].currentData(), "")
        if not name:
            raise ValueError("请先检测并选择采集卡")
        return name

    def refresh_labels(self, *_):
        try:
            name = self.device_name()
            files = self.store.list_overrides(name)
            self.label_status.setText(f"{name} · {len(files)} 个标签覆盖\n" + "、".join(str(item["name"]) for item in files))
        except (ValueError, OSError) as exc:
            self.label_status.setText(str(exc))

    def import_labels(self, paths):
        if self.w.running or self.w.job or not paths:
            return
        try:
            name = self.device_name()
            directories = [Path(self.w.fields[key].text()) / "ImgLabel" for key in ("source", "sid_source", "tid_source")]
            result = self.store.import_paths(name, paths, directories)
            self.w.invalidate()
            self.refresh_labels()
            self.w.set_status(f"已为 {name} 导入 {len(result.imported)} 个标签；请重新生成方案。")
        except (ValueError, OSError) as exc:
            self.w.show_error(str(exc))

    def choose_labels(self):
        paths = QFileDialog.getOpenFileNames(self.w, "选择设备标签", "", "EasyCon 标签 (*.IL *.il)")[0]
        self.import_labels(paths)

    def choose_label_directory(self):
        path = QFileDialog.getExistingDirectory(self.w, "选择标签文件夹")
        if path:
            self.import_labels([path])

    def clear_overrides(self):
        try:
            name = self.device_name()
            if QMessageBox.question(self.w, "清除设备覆盖", f"清除 {name} 的全部标签覆盖？原脚本包中的标签不受影响。") != QMessageBox.StandardButton.Yes:
                return
            self.store.clear(name)
            self.w.invalidate()
            self.refresh_labels()
        except (ValueError, OSError) as exc:
            self.w.show_error(str(exc))

    def eventFilter(self, obj, event):
        if obj is self.drop and event.type() in (QEvent.Type.DragEnter, QEvent.Type.Drop):
            urls = event.mimeData().urls()
            if urls and all(url.isLocalFile() for url in urls) and not self.w.running and not self.w.job:
                event.acceptProposedAction()
                if event.type() == QEvent.Type.Drop:
                    self.import_labels([url.toLocalFile() for url in urls])
                return True
        return super().eventFilter(obj, event)

    def clear_issues(self):
        self.w.label_issues.setRowCount(0)
        self.ignored_prefix = self.w.log_view.toPlainText()
        self.last_log = self.ignored_prefix

    def diagnose(self):
        self.poll_incidents()
        text = self.w.log_view.toPlainText()
        if text == self.last_log:
            return
        self.last_log = text
        if self.ignored_prefix and text.startswith(self.ignored_prefix):
            text = text[len(self.ignored_prefix):]
        else:
            self.ignored_prefix = ""
        issues = diagnose_label_log(text)
        self.w.label_issues.setRowCount(len(issues))
        for i, issue in enumerate(issues):
            values = ("、".join(issue.labels), issue.score, issue.threshold, issue.occurrences, f"{issue.context} · {issue.reason}")
            for j, value in enumerate(values):
                self.w.label_issues.setItem(i, j, QTableWidgetItem("—" if value is None else str(value)))

    def poll_incidents(self):
        try:
            records = self.incidents.list(include_resolved=False)
        except (OSError, ValueError):
            return
        if not records:
            self.active_incident_id = None
            self._incident_signature = None
            self.w.label_incident_banner.hide()
            return
        run_id = getattr(self.w.run_command, "run_id", "") if self.w.run_command else ""
        record = next((item for item in records if run_id and item.get("run_id") == run_id), records[0])
        incident_id = str(record["incident_id"])
        resolution = record.get("resolution", {})
        status = resolution.get("status", "pending") if isinstance(resolution, dict) else "pending"
        note = resolution.get("note", "") if isinstance(resolution, dict) else ""
        signature = (incident_id, status, note, resolution.get("updated_at_utc") if isinstance(resolution, dict) else "")
        if getattr(self, "_incident_signature", None) == signature:
            return
        self._incident_signature = signature
        self.active_incident_id = incident_id
        labels = "、".join(str(item.get("name")) for item in record.get("labels", []) if isinstance(item, dict)) or "标签尚未识别"
        capture = record.get("capture_device", {})
        device = capture.get("name", "未知采集卡") if isinstance(capture, dict) else "未知采集卡"
        self.w.label_incident_summary.setText(
            f"故障事件：{record.get('stage_id')} · {record.get('failure_kind')}\n"
            f"设备：{device}　标签：{labels}\n"
            f"状态：{status}　{note}"
        )
        bundle = Path(str(record["bundle_path"]))
        screenshots = record.get("screenshot", {})
        image_path = None
        if isinstance(screenshots, dict):
            relative = screenshots.get("match") or screenshots.get("stop")
            if relative:
                candidate = bundle / str(relative)
                if candidate.is_file():
                    image_path = candidate
        if image_path:
            pixmap = QPixmap(str(image_path)).scaled(
                self.w.label_incident_thumbnail.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.w.label_incident_thumbnail.setPixmap(pixmap)
            self.w.label_incident_thumbnail.setToolTip(str(image_path))
        else:
            self.w.label_incident_thumbnail.setPixmap(QPixmap())
            errors = screenshots.get("errors", []) if isinstance(screenshots, dict) else []
            self.w.label_incident_thumbnail.setText("没有可解码截图\n" + ("；".join(errors) if errors else ""))
        self.w.label_incident_banner.show()

    def open_active_incident(self):
        if not self.active_incident_id:
            return
        if self.w.running or self.w.job:
            self.w.show_error("请先等待运行或设备任务结束，再打开标签修复。")
            return
        from .label_editor import LabelEditorDialog
        try:
            dialog = LabelEditorDialog(self.w, incident_id=self.active_incident_id)
            dialog.exec()
        except (OSError, RuntimeError, ValueError) as exc:
            self.w.show_error(f"无法打开故障标签修复：{exc}")
        self.poll_incidents()
        self.refresh_labels()

    def open_label_editor(self):
        if self.w.running or self.w.job:
            self.w.show_error("请先等待运行或设备任务结束，再打开标签制作。")
            return
        label = QFileDialog.getOpenFileName(
            self.w, "选择待制作 / 修复的 EasyCon 标签", "", "EasyCon 标签 (*.IL *.il)",
        )[0]
        if not label:
            return
        frame = QFileDialog.getOpenFileName(
            self.w, "选择标签应识别的原始游戏截图", str(Path(label).parent),
            "图像 (*.png *.bmp *.jpg *.jpeg)",
        )[0]
        if not frame:
            return
        from .label_editor import LabelEditorDialog
        try:
            LabelEditorDialog(self.w, label_path=label, frame_path=frame).exec()
        except (OSError, RuntimeError, ValueError) as exc:
            self.w.show_error(f"无法打开标签制作：{exc}")
        self.refresh_labels()

    def open_controller(self):
        if self.controller is None:
            self.controller = ControllerWindow(self.w)
        self.controller.open_overlay()

    def open_controller_mapping(self):
        if self.controller is None:
            self.controller = ControllerWindow(self.w)
        self.controller.edit_mapping()

    def port_changed(self, *_):
        if self.controller and (self.controller.controller or self.controller.job):
            self.controller.overlay.exit_control()
            self.w.set_status("串口已切换；点击顶部“虚拟手柄”连接新串口。")

    def open_monitor(self):
        if self.monitor is None:
            self.monitor = MonitorWindow(self.w)
        self.monitor.show()
        self.monitor.raise_()
        self.monitor.restart()

    def release_for_run(self):
        if self.controller:
            if self.controller.job:
                raise ValueError("虚拟手柄正在连接，请待连接结束后开始运行。")
            self.controller.disconnect()
        if self.monitor:
            self.monitor.stop_capture()
            if self.monitor.old_readers:
                return False
        return True

    def run_started(self):
        if self.monitor and self.monitor.isVisible():
            self.monitor.restart()

    def run_finished(self):
        if self.monitor and self.monitor.isVisible():
            self.monitor.restart()
        self.diagnose()

    def mark_project_loaded(self, prepared) -> None:
        project = getattr(prepared, "project", None)
        if project is None:
            return
        project = Path(project).resolve()
        sidecar = next((parent / "label-overrides.json" for parent in project.parents
                        if (parent / "label-overrides.json").is_file()), None)
        if sidecar is None:
            return
        try:
            payload = json.loads(sidecar.read_text(encoding="utf-8"))
            files = payload.get("files", []) if isinstance(payload, dict) else []
        except (OSError, UnicodeError, json.JSONDecodeError):
            return
        for item in files if isinstance(files, list) else []:
            if not isinstance(item, dict) or not item.get("incident_id"):
                continue
            incident_id = str(item["incident_id"])
            try:
                self.incidents.set_status(
                    incident_id, "loaded",
                    note=f"{item.get('name')} 已进入本次启动的运行工程。",
                )
                self.loaded_incidents.add(incident_id)
            except (OSError, ValueError, FileNotFoundError):
                continue
        self.poll_incidents()

    def finish_loaded_incidents(self, exit_code: int) -> None:
        if exit_code == 0:
            for incident_id in tuple(self.loaded_incidents):
                try:
                    self.incidents.set_status(
                        incident_id, "resolved", note="加载该设备覆盖的运行已正常完成。",
                    )
                except (OSError, ValueError, FileNotFoundError):
                    continue
        self.loaded_incidents.clear()
        self.poll_incidents()

    def latest_frame(self):
        """Return a detached copy of the most recent cached game frame."""
        if not self.monitor or not self.monitor.reader:
            return None
        frame = self.monitor.reader.frame
        if frame is None or frame.isNull():
            return None
        return frame.copy()

    def update_seeds(self):
        if self.w.job or self.w.running:
            return
        if QMessageBox.question(self.w, "检查/更新 Seed 表", "将读取 Ten Lines 官方 Seed 表，生成 Python / EasyCon 表并执行 1.6.4-a 校验；全部通过后切换。继续？") != QMessageBox.StandardButton.Yes:
            return
        from tenlines_seed_updater import update_seed_tables
        source, ezcon = (Path(self.w.fields[key].text()) for key in ("source", "ezcon"))
        advanced = self.w.advanced_check.isChecked()
        def done(result):
            if result.updated:
                from rng.tenlines import clear_frlg_seed_cache
                clear_frlg_seed_cache()
                self.w.invalidate()
            self.w.result_panel.setPlainText(result.message + f"\n生效目录：{result.active_directory}")
            self.w.set_status(result.message)
        self.w.launch_job(lambda cancel, status: update_seed_tables(source_directory=source, ezcon_path=ezcon,
            progress=status, fingerprint_warning_only=advanced), done, "正在检查官方 Seed 表……")

    def close(self):
        if self.monitor:
            self.monitor.close()
        if self.controller:
            self.controller.close()
            if self.controller.job:
                return False
        return True
