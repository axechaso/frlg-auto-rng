"""PySide6 controller for verified whole-package application updates."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QLabel, QMessageBox

from app_updater import (
    PreparedUpdate,
    UpdateCancelled,
    UpdateCandidate,
    UpdateCheckResult,
    UpdateError,
    check_for_update,
    is_frozen_build,
    prepare_update,
    write_install_request,
)
from app_version import APP_VERSION, APP_VERSION_CODE, UPDATER_EXECUTABLE


class AppUpdateController(QObject):
    """Keep update networking and installation outside the Qt window class."""

    def __init__(self, window, *, frozen: bool | None = None):
        super().__init__(window)
        self.w = window
        self.frozen = is_frozen_build() if frozen is None else bool(frozen)
        self.executable = Path(sys.executable).resolve()
        self.candidate: UpdateCandidate | None = None
        self.button = window.actions["检查程序更新"]
        self.status = self._find_status_label()
        self.status.setObjectName("appUpdateStatus")
        self.status.setText(
            f"程序版本 {APP_VERSION} · "
            + ("尚未检查程序更新。" if self.frozen else "源码模式不使用程序自更新。")
        )
        self.button.setToolTip(
            "冻结绿色版通过 GitHub 正式 Release 整包更新；"
            "配置、日志、进度和 Seed 表保留在用户目录。"
        )
        self.auto_timer = QTimer(self)
        self.auto_timer.setSingleShot(True)
        self.auto_timer.timeout.connect(lambda: self.check(force=False))
        if self.frozen:
            self.auto_timer.start(1800)

    def _find_status_label(self) -> QLabel:
        labels = [
            label
            for label in self.w.settings_dialog.findChildren(QLabel)
            if "程序自更新" in label.text()
        ]
        if len(labels) != 1:
            raise RuntimeError("程序更新状态文本不唯一")
        return labels[0]

    @staticmethod
    def description(candidate: UpdateCandidate) -> str:
        manifest = candidate.manifest
        size_mib = manifest.bytes / (1024 * 1024)
        notes = manifest.notes.strip() or "本版未提供额外更新说明。"
        return (
            f"当前版本：{APP_VERSION}\n"
            f"新版本：{manifest.version}\n"
            f"发布时间：{candidate.published_at}\n"
            f"下载大小：{size_mib:.1f} MiB\n\n"
            f"{notes}\n\n"
            "将下载完整绿色版、校验后退出并安装。是否继续？"
        )

    def check(self, *, force: bool = True) -> None:
        if not self.frozen:
            message = "源码模式不使用程序自更新；请通过 Git 获取更新。"
            self.status.setText(message)
            if force:
                QMessageBox.information(self.w, "程序更新", message)
            return
        if self.w.job is not None:
            return
        self.status.setText("正在检查程序更新……")
        started = self.w.launch_job(
            lambda _cancel, _status: check_for_update(
                current_version_code=APP_VERSION_CODE,
                cache_dir=self.w.paths.user / "updates",
                force=force,
            ),
            lambda result: self._checked(result, manual=force),
            "正在检查程序更新……",
            allow_while_running=True,
        )
        if not started:
            self.status.setText("当前有其他后台操作，稍后再检查程序更新。")

    def _checked(self, result: UpdateCheckResult, *, manual: bool) -> None:
        self.status.setText(result.message)
        self.candidate = result.candidate
        if result.status == "error":
            if manual:
                QMessageBox.warning(self.w, "程序更新检查失败", result.message)
            return
        if result.status != "available" or result.candidate is None:
            if manual:
                QMessageBox.information(self.w, "程序更新", result.message)
            return
        if self.w.running:
            self.status.setText(
                f"发现新版本 {result.candidate.manifest.version}；"
                "当前任务结束后可手动更新。"
            )
            return
        if (
            QMessageBox.question(
                self.w,
                "发现程序更新",
                self.description(result.candidate),
            )
            == QMessageBox.StandardButton.Yes
        ):
            self.download(result.candidate)

    def download(self, candidate: UpdateCandidate | None = None) -> None:
        candidate = candidate or self.candidate
        if candidate is None:
            self.check(force=True)
            return
        if self.w.running:
            QMessageBox.warning(
                self.w,
                "无法安装程序更新",
                "请先停止 EasyCon，再安装程序更新。",
            )
            return

        def work(cancel, status):
            last_percent = -1

            def progress(received: int, total: int) -> None:
                nonlocal last_percent
                percent = min(100, int(received * 100 / total)) if total else 0
                if percent != last_percent:
                    last_percent = percent
                    status(f"正在下载完整绿色版：{percent}%")

            try:
                return (
                    "prepared",
                    prepare_update(
                        candidate,
                        install_dir=self.executable.parent,
                        updates_root=self.w.paths.user / "updates",
                        progress=progress,
                        cancelled=cancel,
                    ),
                )
            except UpdateCancelled as exc:
                return "cancelled", str(exc)

        self.status.setText("正在下载并验证程序更新……")
        self.w.launch_job(
            work,
            self._prepared,
            "正在下载并验证程序更新……",
        )

    def _prepared(self, outcome) -> None:
        kind, value = outcome
        if kind == "cancelled":
            message = "程序更新已取消；当前版本未改变。"
            self.status.setText(message)
            self.w.set_status(message)
            return
        self.status.setText("更新包验证通过，正在启动独立更新器……")
        self.install_prepared_update(value)

    def install_prepared_update(self, prepared: PreparedUpdate) -> None:
        if self.w.running:
            message = "EasyCon 仍在运行，请停止后重新检查更新。"
            self.status.setText(message)
            QMessageBox.warning(self.w, "无法安装程序更新", message)
            return
        try:
            updates_root = self.w.paths.user / "updates"
            request_path = write_install_request(
                prepared,
                current_pid=os.getpid(),
                updates_root=updates_root,
            )
            source_updater = prepared.install_dir / UPDATER_EXECUTABLE
            if not source_updater.is_file():
                raise UpdateError(f"当前绿色版缺少独立更新器：{source_updater}")
            copied_updater = request_path.parent / UPDATER_EXECUTABLE
            shutil.copy2(source_updater, copied_updater)
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            subprocess.Popen(
                [str(copied_updater), "--request", str(request_path)],
                cwd=request_path.parent,
                creationflags=flags,
                close_fds=True,
            )
        except (OSError, UpdateError) as exc:
            message = f"独立更新器启动失败：{exc}"
            self.status.setText(message)
            self.w.set_status(message)
            QMessageBox.warning(self.w, "程序更新失败", str(exc))
            return
        self.status.setText("独立更新器已启动，正在退出当前版本……")
        self.w.set_status("正在退出当前版本并安装程序更新……")
        self.w.closing_for_update = True
        QTimer.singleShot(0, self.w.close)

    def refresh(self) -> None:
        self.button.setEnabled(self.w.job is None)

    def close(self) -> None:
        self.auto_timer.stop()
