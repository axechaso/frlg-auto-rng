"""Verify a frozen 0.2.2 package can transactionally upgrade to 0.9."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from app_updater import (
    UpdateCandidate,
    UpdateError,
    UpdateManifest,
    parse_manifest,
    prepare_update,
    validate_zip,
    write_install_request,
)
from app_version import GITHUB_REPOSITORY, MAIN_EXECUTABLE, UPDATER_EXECUTABLE
from update_installer import InstallRequest, apply_update


OLD_VERSION = "0.2.2"
NEW_VERSION = "0.9"
NEW_VERSION_CODE = 2026090701


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def persistent_user_snapshot(root: Path) -> dict[str, str]:
    """Hash persistent files while excluding updater-owned scratch data."""
    root = Path(root)
    if not root.exists():
        return {}
    snapshot: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if relative.parts and relative.parts[0].casefold() == "updates":
            continue
        snapshot[relative.as_posix()] = _sha256(path)
    return snapshot


def _probe(executable: Path) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="frlg-version-probe-") as temporary:
        output = Path(temporary) / "version.json"
        completed = subprocess.run(
            [str(executable), "--version-json-file", str(output)],
            cwd=executable.parent,
            check=False,
            timeout=60,
        )
        if completed.returncode != 0 or not output.is_file():
            raise UpdateError(
                f"版本探针失败：{executable}，退出码 {completed.returncode}"
            )
        try:
            payload = json.loads(output.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise UpdateError(f"版本探针输出无效：{executable}") from exc
    if not isinstance(payload, dict):
        raise UpdateError(f"版本探针不是 JSON 对象：{executable}")
    return payload


def _validate_inputs(
    old_root: Path, package: Path, manifest_path: Path, user_data: Path
) -> UpdateManifest:
    old_root = old_root.resolve()
    package = package.resolve()
    user_data = user_data.resolve()
    for name in (MAIN_EXECUTABLE, UPDATER_EXECUTABLE):
        if not (old_root / name).is_file():
            raise UpdateError(f"0.2.2 目录缺少 {name}")
    old_payload = _probe(old_root / MAIN_EXECUTABLE)
    if (
        old_payload.get("version") != OLD_VERSION
        or old_payload.get("repository") != GITHUB_REPOSITORY
    ):
        raise UpdateError("旧安装目录不是公开 0.2.2 发行合同")
    try:
        manifest = parse_manifest(manifest_path.read_bytes())
    except OSError as exc:
        raise UpdateError(f"无法读取更新清单：{manifest_path}") from exc
    if manifest.version != NEW_VERSION or manifest.version_code != NEW_VERSION_CODE:
        raise UpdateError("更新清单不是 0.9 / 2026090701")
    if package.name != manifest.package:
        raise UpdateError("更新包文件名与清单不一致")
    if package.stat().st_size != manifest.bytes or _sha256(package) != manifest.sha256:
        raise UpdateError("更新包大小或 SHA-256 与清单不一致")
    validate_zip(package, manifest)
    if user_data.name.casefold() != "frlg-auto-rng":
        raise UpdateError("用户数据目录必须以 FRLG-Auto-RNG 命名")
    return manifest


def _cache_package(package: Path, manifest: UpdateManifest, user_data: Path) -> None:
    cached = (
        user_data
        / "updates"
        / "downloads"
        / str(manifest.version_code)
        / manifest.package
    )
    cached.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(package, cached)


def _prepare_local(
    candidate: UpdateCandidate, install: Path, user_data: Path
):
    return prepare_update(
        candidate,
        install_dir=install,
        updates_root=user_data / "updates",
        opener=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            UpdateError("本地验证不允许联网下载")
        ),
    )


def _request(prepared, user_data: Path) -> InstallRequest:
    request_path = write_install_request(
        prepared,
        current_pid=os.getpid(),
        updates_root=user_data / "updates",
    )
    return InstallRequest.from_path(
        request_path,
        allowed_updates_root=user_data / "updates",
    )


def _launch_offscreen(user_data: Path, processes: list[subprocess.Popen]):
    def launch(executable: Path, arguments: list[str]):
        environment = os.environ.copy()
        environment["QT_QPA_PLATFORM"] = "offscreen"
        environment["LOCALAPPDATA"] = str(user_data.parent)
        process = subprocess.Popen(
            [str(executable), *arguments],
            cwd=executable.parent,
            env=environment,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        processes.append(process)
        return process

    return launch


def _stop(processes: list[subprocess.Popen]) -> None:
    for process in processes:
        try:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)
        except (OSError, subprocess.SubprocessError):
            try:
                process.kill()
            except OSError:
                pass


def verify_upgrade(
    old_root: Path, package: Path, manifest_path: Path, user_data: Path
) -> dict[str, object]:
    old_root = old_root.resolve()
    package = package.resolve()
    user_data = user_data.resolve()
    manifest = _validate_inputs(old_root, package, manifest_path.resolve(), user_data)
    user_before = persistent_user_snapshot(user_data)
    _cache_package(package, manifest, user_data)
    candidate = UpdateCandidate(
        manifest=manifest,
        package_url=(
            f"https://github.com/{GITHUB_REPOSITORY}/releases/download/v{manifest.version}/"
            f"{manifest.package}"
        ),
        published_at="local verification",
        tag_name=f"v{manifest.version}",
    )

    with tempfile.TemporaryDirectory(
        prefix="frlg-upgrade-verification-", dir=old_root.parent
    ) as temporary:
        workspace = Path(temporary)
        success_install = workspace / "success" / old_root.name
        rollback_install = workspace / "rollback" / old_root.name
        success_install.parent.mkdir()
        rollback_install.parent.mkdir()
        shutil.copytree(old_root, success_install)
        shutil.copytree(old_root, rollback_install)

        success_prepared = _prepare_local(candidate, success_install, user_data)
        success_request = _request(success_prepared, user_data)
        success_processes: list[subprocess.Popen] = []
        try:
            success = apply_update(
                success_request,
                wait_pid=lambda _pid, _timeout: True,
                launch=_launch_offscreen(user_data, success_processes),
            )
        finally:
            _stop(success_processes)
        if success.status != "installed":
            raise UpdateError(f"0.2.2 → 0.9 安装失败：{success.message}")
        installed_payload = _probe(success_install / MAIN_EXECUTABLE)
        if (
            installed_payload.get("version") != NEW_VERSION
            or installed_payload.get("version_code") != NEW_VERSION_CODE
        ):
            raise UpdateError("安装后的主程序不是 0.9")

        rollback_prepared = _prepare_local(candidate, rollback_install, user_data)
        rollback_request = _request(rollback_prepared, user_data)
        rollback_processes: list[subprocess.Popen] = []
        rollback = apply_update(
            rollback_request,
            wait_pid=lambda _pid, _timeout: True,
            launch=_launch_offscreen(user_data, rollback_processes),
            wait_health=lambda *_args: False,
        )
        _stop(rollback_processes)
        if rollback.status != "rolled_back":
            raise UpdateError(f"失败回滚验证未通过：{rollback.message}")
        rolled_back_payload = _probe(rollback_install / MAIN_EXECUTABLE)
        if rolled_back_payload.get("version") != OLD_VERSION:
            raise UpdateError("健康检查失败后没有恢复 0.2.2")

    user_after = persistent_user_snapshot(user_data)
    if user_after != user_before:
        raise UpdateError("升级或回滚修改了持久用户数据")
    return {
        "from": OLD_VERSION,
        "to": NEW_VERSION,
        "version_code": NEW_VERSION_CODE,
        "installed": True,
        "user_data_unchanged": True,
        "rollback_verified": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--old-root", required=True, type=Path)
    parser.add_argument("--package", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--user-data", required=True, type=Path)
    args = parser.parse_args(argv)
    result = verify_upgrade(
        args.old_root, args.package, args.manifest, args.user_data
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
