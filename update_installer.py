"""Transactional directory swap used by the standalone frozen updater."""

from __future__ import annotations

import ctypes
import json
import os
import re
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from app_version import MAIN_EXECUTABLE, UPDATE_SCHEMA, UPDATER_EXECUTABLE


TOKEN_PATTERN = re.compile(r"^[0-9a-f]{32}$")
REQUEST_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")


class InstallError(RuntimeError):
    pass


def _atomic_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _absolute_normalized(value: object, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise InstallError(f"{label}无效")
    raw = Path(value)
    if not raw.is_absolute() or any(part in ("..", ".") for part in raw.parts):
        raise InstallError(f"{label}必须是规范化绝对路径")
    resolved = raw.resolve()
    if os.path.normcase(str(raw)) != os.path.normcase(str(resolved)):
        raise InstallError(f"{label}必须是规范化绝对路径")
    return resolved


@dataclass(frozen=True)
class InstallRequest:
    request_path: Path
    request_id: str
    token: str
    version: str
    version_code: int
    current_pid: int
    install_dir: Path
    stage_dir: Path
    backup_dir: Path
    failed_dir: Path
    result_path: Path
    health_path: Path
    log_path: Path
    main_executable: str
    updater_executable: str

    @classmethod
    def from_path(
        cls, request_path: Path, *, allowed_updates_root: Path
    ) -> "InstallRequest":
        request_path = Path(request_path).resolve()
        allowed_updates_root = Path(allowed_updates_root).resolve()
        if not request_path.is_file() or not _is_relative_to(request_path, allowed_updates_root):
            raise InstallError("安装请求不在允许的更新目录")
        try:
            data = json.loads(request_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise InstallError("无法读取安装请求") from exc
        if not isinstance(data, dict):
            raise InstallError("安装请求格式无效")
        expected = {
            "schema", "request_id", "token", "version", "version_code",
            "current_pid", "install_dir", "stage_dir", "backup_dir", "failed_dir",
            "result_path", "health_path", "log_path", "main_executable",
            "updater_executable",
        }
        if set(data) != expected or data.get("schema") != UPDATE_SCHEMA:
            raise InstallError("安装请求字段或协议版本无效")
        request_id = data["request_id"]
        token = data["token"]
        if not isinstance(request_id, str) or not REQUEST_ID_PATTERN.fullmatch(request_id):
            raise InstallError("安装请求 ID 无效")
        if not isinstance(token, str) or not TOKEN_PATTERN.fullmatch(token):
            raise InstallError("安装请求令牌无效")
        version = data["version"]
        version_code = data["version_code"]
        current_pid = data["current_pid"]
        if not isinstance(version, str) or type(version_code) is not int or version_code <= 0:
            raise InstallError("目标版本无效")
        if type(current_pid) is not int or current_pid <= 0:
            raise InstallError("主程序 PID 无效")
        install_dir = _absolute_normalized(data["install_dir"], "安装目录")
        stage_dir = _absolute_normalized(data["stage_dir"], "暂存目录")
        backup_dir = _absolute_normalized(data["backup_dir"], "备份目录")
        failed_dir = _absolute_normalized(data["failed_dir"], "失败目录")
        result_path = _absolute_normalized(data["result_path"], "结果文件")
        health_path = _absolute_normalized(data["health_path"], "健康文件")
        log_path = _absolute_normalized(data["log_path"], "日志文件")
        parent = install_dir.parent
        if install_dir == Path(install_dir.anchor) or parent == Path(parent.anchor):
            raise InstallError("安装目录范围过大")
        for path in (stage_dir, backup_dir, failed_dir):
            if path.parent != parent:
                raise InstallError("暂存和回滚目录必须是安装目录的直接同级目录")
        if stage_dir.name != f".frlg-update-stage-{request_id}":
            raise InstallError("暂存目录名称与请求不一致")
        if backup_dir.name != f".frlg-update-backup-{request_id}":
            raise InstallError("备份目录名称与请求不一致")
        if failed_dir.name != f".frlg-update-failed-{request_id}":
            raise InstallError("失败目录名称与请求不一致")
        request_dir = request_path.parent
        expected_request_dir = allowed_updates_root / "requests" / request_id
        if request_dir != expected_request_dir:
            raise InstallError("安装请求目录与请求 ID 不一致")
        for path in (result_path, health_path, log_path):
            if path.parent != request_dir:
                raise InstallError("安装结果文件必须位于本次请求目录")
        if not install_dir.is_dir() or not stage_dir.is_dir():
            raise InstallError("安装目录或暂存目录不存在")
        if backup_dir.exists() or failed_dir.exists():
            raise InstallError("回滚目录已存在，拒绝覆盖")
        main_executable = data["main_executable"]
        updater_executable = data["updater_executable"]
        if main_executable != MAIN_EXECUTABLE or updater_executable != UPDATER_EXECUTABLE:
            raise InstallError("可执行文件名称无效")
        if not (install_dir / main_executable).is_file():
            raise InstallError("旧版主程序不存在")
        if not (stage_dir / main_executable).is_file() or not (stage_dir / updater_executable).is_file():
            raise InstallError("暂存包缺少必要可执行文件")
        marker_path = stage_dir / ".frlg-update-stage.json"
        try:
            marker = json.loads(marker_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise InstallError("暂存目录验证标记无效") from exc
        if not isinstance(marker, dict) or any(
            marker.get(key) != expected_value
            for key, expected_value in (
                ("schema", UPDATE_SCHEMA),
                ("request_id", request_id),
                ("token", token),
                ("version", version),
                ("version_code", version_code),
            )
        ):
            raise InstallError("暂存目录验证标记与请求不一致")
        return cls(
            request_path, request_id, token, version, version_code, current_pid,
            install_dir, stage_dir, backup_dir, failed_dir, result_path,
            health_path, log_path, main_executable, updater_executable,
        )


@dataclass(frozen=True)
class InstallResult:
    status: str
    message: str
    launched_pid: int | None = None


def wait_for_pid_exit(pid: int, timeout: float) -> bool:
    if os.name == "nt":
        synchronize = 0x00100000
        handle = ctypes.windll.kernel32.OpenProcess(synchronize, False, pid)
        if not handle:
            return True
        try:
            wait_ms = max(0, min(int(timeout * 1000), 0xFFFFFFFE))
            return ctypes.windll.kernel32.WaitForSingleObject(handle, wait_ms) == 0
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except OSError:
            return True
        time.sleep(0.1)
    return False


def launch_new_version(executable: Path, arguments: list[str]) -> subprocess.Popen:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.Popen(
        [str(executable), *arguments],
        cwd=executable.parent,
        creationflags=flags,
    )


def wait_for_health(path: Path, token: str, version_code: int, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload == {"token": token, "version_code": version_code}:
                return True
        except (OSError, json.JSONDecodeError):
            pass
        time.sleep(0.2)
    return False


def _terminate_launched(process: object | None) -> None:
    if process is None:
        return
    try:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
    except (OSError, subprocess.SubprocessError, AttributeError):
        try:
            process.kill()
        except (OSError, AttributeError):
            pass


def apply_update(
    request: InstallRequest,
    *,
    wait_pid: Callable[[int, float], bool] = wait_for_pid_exit,
    launch: Callable[[Path, list[str]], object] = launch_new_version,
    wait_health: Callable[[Path, str, int, float], bool] = wait_for_health,
) -> InstallResult:
    request.log_path.parent.mkdir(parents=True, exist_ok=True)

    def log(message: str) -> None:
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with request.log_path.open("a", encoding="utf-8") as stream:
            stream.write(f"[{timestamp}] {message}\n")

    if not wait_pid(request.current_pid, 60.0):
        result = InstallResult("failed", "主程序在 60 秒内没有退出，未替换任何文件。")
        _atomic_json(request.result_path, {"status": result.status, "message": result.message})
        log(result.message)
        return result

    backup_created = False
    new_installed = False
    launched = None
    try:
        log("主程序已退出，开始交换绿色版目录。")
        request.install_dir.replace(request.backup_dir)
        backup_created = True
        request.stage_dir.replace(request.install_dir)
        new_installed = True
        executable = request.install_dir / request.main_executable
        arguments = [
            "--update-health-file", str(request.health_path),
            "--update-health-token", request.token,
        ]
        launched = launch(executable, arguments)
        launched_pid = getattr(launched, "pid", None)
        if not wait_health(request.health_path, request.token, request.version_code, 30.0):
            raise InstallError("新版程序没有在 30 秒内完成启动确认")
        payload = {
            "status": "installed",
            "message": f"已安装 FRLG Auto RNG {request.version}。",
            "launched_pid": launched_pid,
            "version": request.version,
            "version_code": request.version_code,
        }
        _atomic_json(request.result_path, payload)
        shutil.rmtree(request.backup_dir)
        log(payload["message"])
        return InstallResult("installed", payload["message"], launched_pid)
    except BaseException as exc:
        log(f"安装失败，开始回滚：{exc}")
        _terminate_launched(launched)
        rollback_error: BaseException | None = None
        try:
            if new_installed and request.install_dir.exists():
                request.install_dir.replace(request.failed_dir)
            if backup_created and request.backup_dir.exists():
                request.backup_dir.replace(request.install_dir)
        except BaseException as rollback_exc:
            rollback_error = rollback_exc
        if rollback_error is None:
            message = f"更新失败，已恢复旧版：{exc}"
            status = "rolled_back"
        else:
            message = (
                f"更新和自动恢复均失败：{exc}；恢复错误：{rollback_error}。"
                f"旧版或新版目录已保留在 {request.install_dir.parent}。"
            )
            status = "rollback_failed"
        try:
            _atomic_json(
                request.result_path,
                {"status": status, "message": message, "version": request.version},
            )
        except OSError:
            pass
        log(message)
        return InstallResult(status, message)
