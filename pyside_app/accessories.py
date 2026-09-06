"""Device utilities and label management for the Qt shell."""
from pathlib import Path

from PySide6.QtCore import QObject, QEvent, QTimer
from PySide6.QtWidgets import QFileDialog, QLabel, QMessageBox, QPushButton, QTableWidgetItem

from device_label_overrides import LabelOverrideStore, diagnose_label_log
from pyside_preview import Card
from .manual import ControllerWindow, MonitorWindow


class Accessories(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.w = window
        self.controller = self.monitor = None
        self.store = LabelOverrideStore(window.paths.user / "device_label_overrides")
        self.card = window.label_issues.parentWidget()
        while not isinstance(self.card, Card):
            self.card = self.card.parentWidget()
        self.card.toggle.setToolTip("按采集卡名称保存覆盖；原始脚本包中的标签保留。")
        self.label_status = self.card.layout.itemAt(0).widget()
        self.drop = self.card.layout.itemAt(2).widget()
        self.drop.setText("拖放 .IL 文件或文件夹到这里")
        self.drop.setAcceptDrops(True)
        self.drop.installEventFilter(self)
        self.last_log = ""
        self.ignored_prefix = ""
        for title, action in (("虚拟手柄", self.open_controller), ("监视窗口", self.open_monitor),
            ("手柄键位", self.open_controller_mapping),
            ("检查/更新 Seed 表", self.update_seeds), ("选择标签文件（可多选）", self.choose_labels),
            ("选择标签文件夹", self.choose_label_directory), ("清除当前设备覆盖", self.clear_overrides)):
            window._bind(title, action)
        window.actions["虚拟手柄"].setToolTip("使用顶部所选串口打开手柄浮窗；键位在共通设置中修改。")
        window.actions["手柄键位"].setToolTip("按手柄位置设置键盘映射，不打开手柄主窗口。")
        clear = next(button for button in self.card.findChildren(QPushButton) if button.text() == "清空诊断列表")
        clear.clicked.disconnect()
        clear.clicked.connect(self.clear_issues)
        update = next(button for button in window.findChildren(QPushButton) if button.text() == "检查程序更新")
        update.setToolTip("当前为源码运行的 Qt 入口；程序更新仍通过 Git 获取。发布版更新器会替换正式 Tk 包，不能用于此入口。")
        window.fields["video"].currentIndexChanged.connect(self.refresh_labels)
        window.fields["port"].currentIndexChanged.connect(self.port_changed)
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.diagnose)
        self.timer.start()
        self.refresh_labels()

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
