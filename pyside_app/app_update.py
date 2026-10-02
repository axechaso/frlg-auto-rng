"""PySide6 controller for verified incremental application updates."""

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
    plan_incremental_update,
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
        self.incremental_plan = None
        self.button = window.actions["检查程序更新"]
        self.source_combo = window.fields["update_source"]
        self.source_combo.currentIndexChanged.connect(self._source_changed)
        self.status = self._find_status_label()
        self.status.setObjectName("appUpdateStatus")
        self.status.setText(
            f"程序版本 {APP_VERSION} · "
            + ("尚未检查程序更新。" if self.frozen else "源码模式不使用程序自更新。")
        )
        self.button.setToolTip(
            "可选自动（GitHub 优先）、仅 GitHub 或仅 Gitee；"
            "手动指定更新源时不会跨源回退；"
            "配置、日志、进度和 Seed 表保留在用户目录。"
        )
        self.auto_timer = QTimer(self)
        self.auto_timer.setSingleShot(True)
        self.auto_timer.timeout.connect(lambda: self.check(force=False))
        if self.frozen:
            self.auto_timer.start(1800)

    def selected_source(self) -> str:
        source = self.source_combo.currentData()
        return source if source in {"auto", "github", "gitee"} else "auto"

    def _source_changed(self, *_args) -> None:
        self.candidate = None
        self.incremental_plan = None
        labels = {
            "auto": "自动（GitHub 优先）",
            "github": "GitHub",
            "gitee": "Gitee",
        }
        self.status.setText(
            f"程序版本 {APP_VERSION} · 更新源已选择 {labels[self.selected_source()]}。"
        )

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
    def description(candidate: UpdateCandidate, plan=None) -> str:
        manifest = candidate.manifest
        size_mib = manifest.bytes / (1024 * 1024)
        notes = manifest.notes.strip() or "本版未提供额外更新说明。"
        source = (
            ("Gitee（增量更新）" if candidate.incremental else f"Gitee（{len(candidate.parts)} 个分卷）")
            if candidate.source == "gitee"
            else "GitHub"
        )
        if plan is not None:
            download = (
                f"增量下载：{plan.download_bytes / (1024 * 1024):.1f} MiB\n"
                f"复用本地文件：{len(plan.reuse)}/{len(plan.manifest.files)}\n"
                f"完整包大小：{size_mib:.1f} MiB（供比较）"
            )
            action = "将仅下载所需数据包，组装并校验新版后退出安装。是否继续？"
        else:
            download = f"下载大小：{size_mib:.1f} MiB"
            action = "此版本未提供增量资源，将下载完整绿色版、校验后退出并安装。是否继续？"
        return (
            f"当前版本：{APP_VERSION}\n"
            f"新版本：{manifest.version}\n"
            f"发布时间：{candidate.published_at}\n"
            f"下载来源：{source}\n"
            f"{download}\n\n"
            f"{notes}\n\n"
            f"{action}"
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
        source = self.selected_source()
        self.status.setText("正在检查程序更新……")
        started = self.w.launch_job(
            lambda _cancel, _status: check_for_update(
                current_version_code=APP_VERSION_CODE,
                cache_dir=self.w.paths.user / "updates",
                force=force,
                source=source,
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
        self.incremental_plan = None
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
        if result.candidate.incremental is not None:
            self.status.setText("正在比对本地文件，计算增量下载大小……")
            self.w.launch_job(
                lambda cancel, status: plan_incremental_update(
                    result.candidate, install_dir=self.executable.parent,
                    updates_root=self.w.paths.user / "updates", cancelled=cancel, status=status,
                ),
                lambda plan: self._offer_update(result.candidate, plan),
                "正在计算增量下载大小……",
            )
            return
        self._offer_update(result.candidate)

    def _offer_update(self, candidate: UpdateCandidate, plan=None) -> None:
        self.incremental_plan = plan
        if plan is not None:
            self.status.setText(f"增量更新需下载 {plan.download_bytes / (1024 * 1024):.1f} MiB。")
        if (
            QMessageBox.question(
                self.w,
                "发现程序更新",
                self.description(candidate, plan),
            )
            == QMessageBox.StandardButton.Yes
        ):
            self.download(candidate)

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
        source = self.selected_source()

        def work(cancel, status):
            last_percent = -1

            def progress(received: int, total: int) -> None:
                nonlocal last_percent
                percent = min(100, int(received * 100 / total)) if total else 100
                if percent != last_percent:
                    last_percent = percent
                    kind = "增量数据包" if candidate.incremental else "完整绿色版"
                    status(f"正在下载{kind}：{percent}%（{received / (1024 * 1024):.1f}/{total / (1024 * 1024):.1f} MiB）")

            try:
                return (
                    "prepared",
                    prepare_update(
                        candidate,
                        install_dir=self.executable.parent,
                        updates_root=self.w.paths.user / "updates",
                        progress=progress,
                        cancelled=cancel,
                        allow_gitee_fallback=source == "auto",
                        incremental_plan=self.incremental_plan,
                        status=status,
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
        QMessageBox.information(
            self.w,
            "安装前请关闭程序文件夹",
            "即将退出当前版本并安装更新。\n\n"
            "请先关闭绿色版程序目录的资源管理器窗口，并确认 EasyCon、监视窗口及其他"
            "相关程序已经退出。目录若被短暂占用，更新器会自动等待并重试 60 秒。\n\n"
            f"程序目录：\n{prepared.install_dir}",
        )
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
        self.source_combo.setEnabled(self.w.job is None)

    def close(self) -> None:
        self.auto_timer.stop()
