"""Safe discovery and staging for frozen whole-package updates."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Callable

from app_version import (
    APP_VERSION_CODE,
    GITHUB_REPOSITORY,
    MAIN_EXECUTABLE,
    UPDATE_SCHEMA,
    UPDATER_EXECUTABLE,
)


GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPOSITORY}/releases/latest"
AUTO_CHECK_INTERVAL_SECONDS = 24 * 60 * 60
DOWNLOAD_CHUNK_BYTES = 1024 * 1024
MAX_PACKAGE_BYTES = 4 * 1024 * 1024 * 1024
MAX_UNPACKED_BYTES = 12 * 1024 * 1024 * 1024
MAX_ZIP_ENTRIES = 100_000
TOKEN_PATTERN = re.compile(r"^[0-9a-f]{32}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class UpdateError(RuntimeError):
    """Base class for update failures safe to show to the user."""


class UpdateCancelled(UpdateError):
    pass


# Public name used by the release plan; callers may catch either name.
UpdatePreparationError = UpdateError


@dataclass(frozen=True)
class UpdateManifest:
    schema: int
    version: str
    version_code: int
    package: str
    sha256: str
    bytes: int
    unpacked_bytes: int
    release_url: str
    notes: str


@dataclass(frozen=True)
class UpdateCandidate:
    manifest: UpdateManifest
    package_url: str
    published_at: str
    tag_name: str = ""


@dataclass(frozen=True)
class UpdateCheckResult:
    status: str
    message: str
    candidate: UpdateCandidate | None = None
    from_cache: bool = False


@dataclass(frozen=True)
class PreparedUpdate:
    request_id: str
    token: str
    install_dir: Path
    stage_dir: Path
    package_path: Path
    manifest: UpdateManifest
    updates_root: Path | None = None
    updater_source: Path | None = None
    expected_version_code: int | None = None


def is_frozen_build() -> bool:
    return bool(getattr(sys, "frozen", False))


def _read_json_object(payload: bytes, label: str) -> dict[str, object]:
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UpdateError(f"{label}不是有效的 UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise UpdateError(f"{label}必须是 JSON 对象")
    return value


def _validate_https_url(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise UpdateError(f"{label}必须是字符串")
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise UpdateError(f"{label}必须是 HTTPS 地址")
    return value


def parse_manifest(payload: bytes) -> UpdateManifest:
    data = _read_json_object(payload, "更新清单")
    expected = {
        "schema",
        "version",
        "version_code",
        "package",
        "sha256",
        "bytes",
        "unpacked_bytes",
        "release_url",
        "notes",
    }
    if set(data) != expected:
        missing = sorted(expected - set(data))
        unknown = sorted(set(data) - expected)
        details = []
        if missing:
            details.append("缺少 " + ", ".join(missing))
        if unknown:
            details.append("未知 " + ", ".join(unknown))
        raise UpdateError("更新清单字段不符：" + "；".join(details))

    schema = data["schema"]
    version = data["version"]
    version_code = data["version_code"]
    package = data["package"]
    sha256 = data["sha256"]
    package_bytes = data["bytes"]
    unpacked_bytes = data["unpacked_bytes"]
    notes = data["notes"]
    if type(schema) is not int or schema != UPDATE_SCHEMA:
        raise UpdateError(f"不支持的更新清单版本：{schema!r}")
    if not isinstance(version, str) or not re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,3}", version):
        raise UpdateError("更新版本号格式无效")
    if type(version_code) is not int or version_code <= 0:
        raise UpdateError("更新版本代码无效")
    if not isinstance(package, str) or not package.endswith(".zip"):
        raise UpdateError("更新包文件名无效")
    if Path(package).name != package or "/" in package or "\\" in package:
        raise UpdateError("更新包必须是单一 ZIP 文件名")
    if package != f"FRLG-Auto-RNG-{version}-windows-x64.zip":
        raise UpdateError("更新包文件名与版本不一致")
    if not isinstance(sha256, str) or not SHA256_PATTERN.fullmatch(sha256):
        raise UpdateError("更新包 SHA-256 无效")
    if type(package_bytes) is not int or not 0 < package_bytes <= MAX_PACKAGE_BYTES:
        raise UpdateError("更新包大小无效")
    if type(unpacked_bytes) is not int or not 0 < unpacked_bytes <= MAX_UNPACKED_BYTES:
        raise UpdateError("更新包解压大小无效")
    release_url = _validate_https_url(data["release_url"], "Release 地址")
    if not isinstance(notes, str) or len(notes) > 20_000:
        raise UpdateError("更新说明无效")
    return UpdateManifest(
        schema=schema,
        version=version,
        version_code=version_code,
        package=package,
        sha256=sha256,
        bytes=package_bytes,
        unpacked_bytes=unpacked_bytes,
        release_url=release_url,
        notes=notes,
    )


def _asset_map(release: dict[str, object]) -> dict[str, dict[str, object]]:
    assets = release.get("assets")
    if not isinstance(assets, list):
        raise UpdateError("GitHub Release 缺少资产列表")
    result: dict[str, dict[str, object]] = {}
    for item in assets:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            raise UpdateError("GitHub Release 资产信息无效")
        name = item["name"]
        if name in result:
            raise UpdateError(f"GitHub Release 含重复资产：{name}")
        result[name] = item
    return result


def _validated_asset_url(asset: dict[str, object], expected_name: str) -> str:
    if asset.get("name") != expected_name:
        raise UpdateError(f"Release 资产名称不符：{expected_name}")
    url = _validate_https_url(asset.get("browser_download_url"), f"{expected_name} 下载地址")
    parsed = urllib.parse.urlparse(url)
    expected_prefix = f"/{GITHUB_REPOSITORY}/releases/download/"
    if parsed.hostname != "github.com" or not parsed.path.startswith(expected_prefix):
        raise UpdateError(f"{expected_name} 不是目标仓库的 Release 资产")
    if urllib.parse.unquote(PurePosixPath(parsed.path).name) != expected_name:
        raise UpdateError(f"{expected_name} 下载地址文件名不符")
    return url


def candidate_from_release(
    release: dict[str, object], manifest: UpdateManifest
) -> UpdateCandidate:
    if release.get("draft") is not False or release.get("prerelease") is not False:
        raise UpdateError("只允许使用正式 GitHub Release")
    tag_name = release.get("tag_name")
    if tag_name != f"v{manifest.version}":
        raise UpdateError("Release 标签与更新清单版本不一致")
    html_url = _validate_https_url(release.get("html_url"), "Release 页面")
    expected_release_url = f"https://github.com/{GITHUB_REPOSITORY}/releases/tag/{tag_name}"
    if html_url != expected_release_url or manifest.release_url != expected_release_url:
        raise UpdateError("Release 页面与目标仓库或更新清单不一致")
    published_at = release.get("published_at")
    if not isinstance(published_at, str) or not published_at:
        raise UpdateError("Release 发布时间无效")

    assets = _asset_map(release)
    package_asset = assets.get(manifest.package)
    sha_name = f"{manifest.package}.sha256"
    sha_asset = assets.get(sha_name)
    if package_asset is None or sha_asset is None or "update-manifest.json" not in assets:
        raise UpdateError("Release 必须同时包含 ZIP、更新清单和 SHA-256 文件")
    package_size = package_asset.get("size")
    if type(package_size) is not int or package_size != manifest.bytes:
        raise UpdateError("Release ZIP 大小与更新清单不一致")
    package_url = _validated_asset_url(package_asset, manifest.package)
    _validated_asset_url(sha_asset, sha_name)
    _validated_asset_url(assets["update-manifest.json"], "update-manifest.json")
    return UpdateCandidate(
        manifest=manifest,
        package_url=package_url,
        published_at=published_at,
        tag_name=tag_name,
    )


def _atomic_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _candidate_to_json(candidate: UpdateCandidate | None) -> dict[str, object] | None:
    if candidate is None:
        return None
    return {
        "manifest": asdict(candidate.manifest),
        "package_url": candidate.package_url,
        "published_at": candidate.published_at,
        "tag_name": candidate.tag_name,
    }


def _candidate_from_json(value: object) -> UpdateCandidate | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise UpdateError("更新缓存候选格式无效")
    manifest_value = value.get("manifest")
    if not isinstance(manifest_value, dict):
        raise UpdateError("更新缓存清单无效")
    manifest = parse_manifest(json.dumps(manifest_value).encode("utf-8"))
    package_url = _validate_https_url(value.get("package_url"), "缓存下载地址")
    published_at = value.get("published_at")
    tag_name = value.get("tag_name")
    if not isinstance(published_at, str) or not isinstance(tag_name, str):
        raise UpdateError("更新缓存字段无效")
    return UpdateCandidate(manifest, package_url, published_at, tag_name)


def _response_header(response: object, name: str) -> str | None:
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    try:
        value = headers.get(name)
    except AttributeError:
        return None
    return value if isinstance(value, str) and value else None


def _cached_result(
    cache: dict[str, object], *, current_version_code: int, from_cache: bool = True
) -> UpdateCheckResult | None:
    if cache.get("current_version_code") != current_version_code:
        return None
    try:
        candidate = _candidate_from_json(cache.get("candidate"))
    except UpdateError:
        return None
    status = cache.get("status")
    message = cache.get("message")
    if not isinstance(status, str) or not isinstance(message, str):
        return None
    return UpdateCheckResult(status, message, candidate, from_cache)


def _read_response(response: object, maximum: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = response.read(min(64 * 1024, maximum - total + 1))
        if not chunk:
            break
        total += len(chunk)
        if total > maximum:
            raise UpdateError("服务器响应超出允许大小")
        chunks.append(chunk)
    return b"".join(chunks)


def _open(opener: Callable, request: urllib.request.Request, timeout: float):
    try:
        return opener(request, timeout=timeout)
    except TypeError:
        return opener(request)


def check_for_update(
    *,
    current_version_code: int = APP_VERSION_CODE,
    cache_dir: Path,
    force: bool = False,
    opener: Callable = urllib.request.urlopen,
    now: float | None = None,
) -> UpdateCheckResult:
    now_value = time.time() if now is None else now
    cache_path = Path(cache_dir) / "check-cache.json"
    cache: dict[str, object] = {}
    try:
        raw_cache = json.loads(cache_path.read_text(encoding="utf-8"))
        if isinstance(raw_cache, dict):
            cache = raw_cache
    except (OSError, json.JSONDecodeError):
        pass

    if not force:
        last_checked = cache.get("last_checked", cache.get("checked_at"))
        if (
            isinstance(last_checked, (int, float))
            and 0 <= now_value - last_checked < AUTO_CHECK_INTERVAL_SECONDS
        ):
            cached = _cached_result(cache, current_version_code=current_version_code)
            if cached is not None:
                return cached

    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "FRLG-Auto-RNG-Updater",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if isinstance(cache.get("etag"), str) and cache["etag"]:
        headers["If-None-Match"] = cache["etag"]
    request = urllib.request.Request(GITHUB_API_URL, headers=headers)
    response_etag = None
    try:
        try:
            with _open(opener, request, 15.0) as response:
                response_etag = _response_header(response, "ETag")
                release_payload = _read_response(response, 2 * 1024 * 1024)
        except urllib.error.HTTPError as exc:
            if exc.code != 304:
                raise
            cached = _cached_result(cache, current_version_code=current_version_code)
            if cached is None:
                raise UpdateError("GitHub 返回 304，但没有可用的更新缓存") from exc
            cache["last_checked"] = now_value
            cache["checked_at"] = now_value
            _atomic_json(cache_path, cache)
            return UpdateCheckResult(cached.status, cached.message, cached.candidate, True)
        release = _read_json_object(release_payload, "GitHub Release")
        if release.get("draft") is not False or release.get("prerelease") is not False:
            raise UpdateError("GitHub 最新 Release 不是稳定版")
        assets = _asset_map(release)
        manifest_asset = assets.get("update-manifest.json")
        if manifest_asset is None:
            result = UpdateCheckResult(
                "unsupported",
                "最新版本不支持应用内更新，请从 Release 页面手动下载。",
            )
        else:
            manifest_url = _validated_asset_url(manifest_asset, "update-manifest.json")
            manifest_request = urllib.request.Request(manifest_url, headers=headers)
            with _open(opener, manifest_request, 12.0) as response:
                manifest_payload = _read_response(response, 256 * 1024)
            manifest = parse_manifest(manifest_payload)
            candidate = candidate_from_release(release, manifest)
            if manifest.version_code > current_version_code:
                result = UpdateCheckResult(
                    "available", f"发现新版本 {manifest.version}。", candidate
                )
            else:
                result = UpdateCheckResult("current", "当前已是最新正式版。")
    except (OSError, urllib.error.URLError, urllib.error.HTTPError, UpdateError) as exc:
        # Keep the last good cache intact.  The GUI can show this result for a
        # manual check without turning a transient network failure into a crash.
        return UpdateCheckResult("error", f"检查程序更新失败：{exc}")

    _atomic_json(
        cache_path,
        {
            "last_checked": now_value,
            "checked_at": now_value,
            "current_version_code": current_version_code,
            "etag": response_etag or cache.get("etag"),
            "release_url": result.candidate.manifest.release_url if result.candidate else None,
            "status": result.status,
            "message": result.message,
            "candidate": _candidate_to_json(result.candidate),
        },
    )
    return result


def required_free_space(manifest: UpdateManifest) -> int:
    safety = max(256 * 1024 * 1024, manifest.unpacked_bytes // 10)
    return manifest.bytes + manifest.unpacked_bytes + safety


def required_free_bytes(manifest: UpdateManifest) -> int:
    """Compatibility alias for callers using the release-plan name."""
    return required_free_space(manifest)


def download_package(
    candidate: UpdateCandidate,
    destination: Path,
    *,
    opener: Callable = urllib.request.urlopen,
    progress: Callable[[int, int], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> Path:
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + ".part")
    if partial.exists():
        partial.unlink()
    request = urllib.request.Request(
        candidate.package_url,
        headers={"User-Agent": "FRLG-Auto-RNG-Updater"},
    )
    digest = hashlib.sha256()
    received = 0
    try:
        with _open(opener, request, 30.0) as response, partial.open("xb") as output:
            while True:
                if cancelled is not None and cancelled():
                    raise UpdateCancelled("程序更新下载已取消")
                chunk = response.read(DOWNLOAD_CHUNK_BYTES)
                if not chunk:
                    break
                received += len(chunk)
                if received > candidate.manifest.bytes:
                    raise UpdateError("下载大小超过更新清单")
                output.write(chunk)
                digest.update(chunk)
                if progress is not None:
                    progress(received, candidate.manifest.bytes)
        if received != candidate.manifest.bytes:
            raise UpdateError(
                f"更新包大小不符：应为 {candidate.manifest.bytes}，实际 {received}"
            )
        if digest.hexdigest() != candidate.manifest.sha256:
            raise UpdateError("更新包 SHA-256 校验失败")
        partial.replace(destination)
        return destination
    except BaseException:
        try:
            partial.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _safe_member_path(name: str) -> tuple[str, ...]:
    if not name or "\x00" in name or "\\" in name:
        raise UpdateError(f"ZIP 含无效路径：{name!r}")
    if name.startswith("/") or re.match(r"^[A-Za-z]:", name):
        raise UpdateError(f"ZIP 含绝对路径：{name!r}")
    parts = PurePosixPath(name).parts
    if not parts or any(part in ("", ".", "..") for part in parts):
        raise UpdateError(f"ZIP 含路径穿越：{name!r}")
    return tuple(parts)


def validate_zip(package_path: Path, manifest: UpdateManifest) -> list[zipfile.ZipInfo]:
    try:
        archive = zipfile.ZipFile(package_path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise UpdateError("更新包不是有效 ZIP") from exc
    with archive:
        infos = archive.infolist()
        if not infos or len(infos) > MAX_ZIP_ENTRIES:
            raise UpdateError("更新包文件数量无效")
        names: set[str] = set()
        total = 0
        top_level: set[str] = set()
        for info in infos:
            parts = _safe_member_path(info.filename)
            normalized = "/".join(parts).rstrip("/").casefold()
            if normalized in names:
                raise UpdateError(f"ZIP 含重复路径：{info.filename}")
            names.add(normalized)
            top_level.add(parts[0].casefold())
            mode = (info.external_attr >> 16) & 0xFFFF
            if stat.S_ISLNK(mode):
                raise UpdateError(f"ZIP 不允许符号链接：{info.filename}")
            if not info.is_dir():
                total += info.file_size
                if total > MAX_UNPACKED_BYTES:
                    raise UpdateError("更新包解压大小超出限制")
        if total != manifest.unpacked_bytes:
            raise UpdateError(
                f"更新包解压大小不符：应为 {manifest.unpacked_bytes}，实际 {total}"
            )
        required = {MAIN_EXECUTABLE.casefold(), UPDATER_EXECUTABLE.casefold(), "_internal"}
        if not required.issubset(top_level):
            raise UpdateError("更新包缺少主程序、独立更新器或 _internal 目录")
        return infos


def safe_extract(package_path: Path, stage_dir: Path, manifest: UpdateManifest) -> None:
    stage_dir = Path(stage_dir)
    if stage_dir.exists():
        raise UpdateError(f"更新暂存目录已存在：{stage_dir}")
    infos = validate_zip(package_path, manifest)
    stage_dir.mkdir(parents=False)
    root = stage_dir.resolve()
    try:
        with zipfile.ZipFile(package_path) as archive:
            for info in infos:
                parts = _safe_member_path(info.filename)
                target = root.joinpath(*parts)
                resolved = target.resolve()
                if root not in resolved.parents and resolved != root:
                    raise UpdateError(f"ZIP 路径越界：{info.filename}")
                if info.is_dir():
                    resolved.mkdir(parents=True, exist_ok=True)
                    continue
                resolved.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info, "r") as source, resolved.open("xb") as output:
                    shutil.copyfileobj(source, output, DOWNLOAD_CHUNK_BYTES)
    except BaseException:
        shutil.rmtree(stage_dir, ignore_errors=True)
        raise


def _probe_staged_version(stage_dir: Path, manifest: UpdateManifest) -> None:
    executable = stage_dir / MAIN_EXECUTABLE
    probe_path = stage_dir / ".frlg-version-probe.json"
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    payload: dict[str, object] | None = None
    try:
        completed = subprocess.run(
            [str(executable), "--version-json-file", str(probe_path)],
            cwd=stage_dir,
            check=False,
            timeout=30,
            creationflags=flags,
        )
        if completed.returncode != 0:
            raise UpdateError(f"新版程序版本检查退出码为 {completed.returncode}")
        raw_payload = json.loads(probe_path.read_text(encoding="utf-8"))
        if not isinstance(raw_payload, dict):
            raise UpdateError("新版程序版本探针不是 JSON 对象")
        payload = raw_payload
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        raise UpdateError(f"无法验证新版程序版本：{exc}") from exc
    finally:
        probe_path.unlink(missing_ok=True)
    if payload is None or (
        payload.get("version") != manifest.version
        or payload.get("version_code") != manifest.version_code
        or payload.get("update_schema") != manifest.schema
        or payload.get("repository") != GITHUB_REPOSITORY
    ):
        raise UpdateError("新版程序内嵌版本与更新清单不一致")


def prepare_update(
    candidate: UpdateCandidate,
    *,
    install_dir: Path,
    updates_root: Path,
    updater_source: Path | None = None,
    opener: Callable = urllib.request.urlopen,
    progress: Callable[[int, int], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
    probe: Callable[[Path, UpdateManifest], None] = _probe_staged_version,
    cancel_event: object | None = None,
    version_probe: Callable[[Path], dict[str, object]] | None = None,
) -> PreparedUpdate:
    install_dir = Path(install_dir).resolve()
    updates_root = Path(updates_root).resolve()
    if not install_dir.is_dir() or not (install_dir / MAIN_EXECUTABLE).is_file():
        raise UpdateError("当前绿色版安装目录无效")
    if updater_source is None:
        updater_source = install_dir / UPDATER_EXECUTABLE
    updater_source = Path(updater_source).resolve()
    if not updater_source.is_file():
        raise UpdateError("当前绿色版缺少独立更新器")
    if cancel_event is not None:
        cancelled = getattr(cancel_event, "is_set", cancelled)
    request_id = uuid.uuid4().hex
    token = secrets.token_hex(16)
    stage_dir = install_dir.parent / f".frlg-update-stage-{request_id}"
    if stage_dir.exists():
        raise UpdateError("更新暂存目录已存在")
    needed = required_free_space(candidate.manifest)
    if shutil.disk_usage(install_dir.parent).free < needed:
        raise UpdateError("安装盘剩余空间不足，无法安全保留回滚副本")
    updates_root.mkdir(parents=True, exist_ok=True)
    download_dir = updates_root / "downloads" / str(candidate.manifest.version_code)
    package_path = download_dir / candidate.manifest.package
    if package_path.is_file():
        actual_size = package_path.stat().st_size
        digest = hashlib.sha256(package_path.read_bytes()).hexdigest()
        if actual_size != candidate.manifest.bytes or digest != candidate.manifest.sha256:
            package_path.unlink()
    if not package_path.is_file():
        download_package(
            candidate,
            package_path,
            opener=opener,
            progress=progress,
            cancelled=cancelled,
        )
    if cancelled is not None and cancelled():
        raise UpdateCancelled("程序更新已取消")
    safe_extract(package_path, stage_dir, candidate.manifest)
    try:
        if version_probe is not None:
            probed = version_probe(stage_dir)
            if not isinstance(probed, dict):
                raise UpdateError("新版程序版本探针结果无效")
            if (
                probed.get("version_code") != candidate.manifest.version_code
                or probed.get("version") != candidate.manifest.version
                or probed.get("update_schema") != candidate.manifest.schema
                or probed.get("repository") != GITHUB_REPOSITORY
            ):
                raise UpdateError("新版程序内嵌版本与更新清单不一致")
        else:
            probe(stage_dir, candidate.manifest)
        marker = {
            "schema": UPDATE_SCHEMA,
            "request_id": request_id,
            "token": token,
            "version": candidate.manifest.version,
            "version_code": candidate.manifest.version_code,
        }
        _atomic_json(stage_dir / ".frlg-update-stage.json", marker)
    except BaseException:
        shutil.rmtree(stage_dir, ignore_errors=True)
        raise
    return PreparedUpdate(
        request_id=request_id,
        token=token,
        install_dir=install_dir,
        stage_dir=stage_dir,
        package_path=package_path,
        manifest=candidate.manifest,
        updates_root=updates_root,
        updater_source=updater_source,
        expected_version_code=candidate.manifest.version_code,
    )


def write_install_request(
    prepared: PreparedUpdate,
    *,
    current_pid: int,
    updates_root: Path | None = None,
    result_path: Path | None = None,
    health_path: Path | None = None,
) -> Path:
    if current_pid <= 0:
        raise UpdateError("主程序 PID 无效")
    if updates_root is None:
        if prepared.updates_root is None:
            raise UpdateError("缺少更新目录")
        updates_root = prepared.updates_root
    updates_root = Path(updates_root).resolve()
    request_dir = updates_root / "requests" / prepared.request_id
    request_dir.mkdir(parents=True, exist_ok=False)
    parent = prepared.install_dir.parent
    backup_dir = parent / f".frlg-update-backup-{prepared.request_id}"
    failed_dir = parent / f".frlg-update-failed-{prepared.request_id}"
    result_path = Path(result_path).resolve() if result_path is not None else request_dir / "install-result.json"
    health_path = Path(health_path).resolve() if health_path is not None else request_dir / "health.json"
    if result_path.parent != request_dir or health_path.parent != request_dir:
        raise UpdateError("安装结果和健康文件必须位于本次请求目录")
    payload = {
        "schema": UPDATE_SCHEMA,
        "request_id": prepared.request_id,
        "token": prepared.token,
        "version": prepared.manifest.version,
        "version_code": prepared.manifest.version_code,
        "current_pid": current_pid,
        "install_dir": str(prepared.install_dir),
        "stage_dir": str(prepared.stage_dir),
        "backup_dir": str(backup_dir),
        "failed_dir": str(failed_dir),
        "result_path": str(result_path),
        "health_path": str(health_path),
        "log_path": str(request_dir / "updater.log"),
        "main_executable": MAIN_EXECUTABLE,
        "updater_executable": UPDATER_EXECUTABLE,
    }
    request_path = request_dir / "install-request.json"
    _atomic_json(request_path, payload)
    return request_path
