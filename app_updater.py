"""Verified incremental staging with legacy whole-package update compatibility."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import ssl
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

import certifi
import truststore
import incremental_update

from app_version import (
    APP_VERSION_CODE,
    GITEE_REPOSITORY,
    GITHUB_REPOSITORY,
    MAIN_EXECUTABLE,
    UPDATE_SCHEMA,
    UPDATER_EXECUTABLE,
)


GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPOSITORY}/releases/latest"
GITEE_API_URL = f"https://gitee.com/api/v5/repos/{GITEE_REPOSITORY}/releases/latest"
GITEE_MANIFEST_NAME = "gitee-update-manifest.json"
AUTO_CHECK_INTERVAL_SECONDS = 24 * 60 * 60
DOWNLOAD_CHUNK_BYTES = 1024 * 1024
MAX_PACKAGE_BYTES = 4 * 1024 * 1024 * 1024
MAX_UNPACKED_BYTES = 12 * 1024 * 1024 * 1024
MAX_ZIP_ENTRIES = 100_000
MAX_GITEE_PART_BYTES = 95 * 1024 * 1024
MAX_GITEE_PARTS = 64
UPDATE_SOURCE_CHOICES = ("auto", "github", "gitee")
TOKEN_PATTERN = re.compile(r"^[0-9a-f]{32}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
CERTIFICATE_ERROR_MESSAGE = (
    "Windows 系统证书库和程序内置证书库都无法验证更新服务器的 HTTPS 证书。"
    "请检查系统时间、Windows 根证书更新或 HTTPS 代理证书后重试；"
    "程序不会关闭证书验证。"
)


class UpdateError(RuntimeError):
    """Base class for update failures safe to show to the user."""


class UpdateSourceUnavailable(UpdateError):
    """A verified update source could not be reached."""


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
class UpdatePackagePart:
    name: str
    sha256: str
    bytes: int
    url: str = ""


@dataclass(frozen=True)
class UpdateCandidate:
    manifest: UpdateManifest
    package_url: str | None
    published_at: str
    tag_name: str = ""
    source: str = "github"
    parts: tuple[UpdatePackagePart, ...] = ()
    incremental: incremental_update.Manifest | None = None
    incremental_urls: tuple[tuple[str, str], ...] = ()


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


def parse_gitee_manifest(
    payload: bytes,
) -> tuple[UpdateManifest, tuple[UpdatePackagePart, ...]]:
    data = _read_json_object(payload, "Gitee 分卷更新清单")
    base_fields = {
        "schema", "version", "version_code", "package", "sha256", "bytes",
        "unpacked_bytes", "release_url", "notes",
    }
    expected = base_fields | {"source", "repository", "parts"}
    if set(data) != expected:
        missing = sorted(expected - set(data))
        unknown = sorted(set(data) - expected)
        details = []
        if missing:
            details.append("缺少 " + ", ".join(missing))
        if unknown:
            details.append("未知 " + ", ".join(unknown))
        raise UpdateError("Gitee 分卷更新清单字段不符：" + "；".join(details))
    if data["source"] != "gitee-split" or data["repository"] != GITEE_REPOSITORY:
        raise UpdateError("Gitee 分卷更新清单来源不符")
    manifest = parse_manifest(
        json.dumps({key: data[key] for key in base_fields}).encode("utf-8")
    )
    expected_release_url = (
        f"https://gitee.com/{GITEE_REPOSITORY}/releases/tag/v{manifest.version}"
    )
    if manifest.release_url != expected_release_url:
        raise UpdateError("Gitee Release 页面与版本不一致")
    raw_parts = data["parts"]
    if not isinstance(raw_parts, list) or not 1 <= len(raw_parts) <= MAX_GITEE_PARTS:
        raise UpdateError("Gitee 分卷数量无效")
    parts: list[UpdatePackagePart] = []
    total = 0
    for index, value in enumerate(raw_parts, 1):
        if not isinstance(value, dict) or set(value) != {"name", "sha256", "bytes"}:
            raise UpdateError(f"Gitee 第 {index} 个分卷记录无效")
        expected_name = f"{manifest.package}.{index:03d}"
        name = value["name"]
        digest = value["sha256"]
        size = value["bytes"]
        if name != expected_name:
            raise UpdateError(f"Gitee 分卷名称或顺序无效：{name!r}")
        if not isinstance(digest, str) or not SHA256_PATTERN.fullmatch(digest):
            raise UpdateError(f"Gitee 分卷 SHA-256 无效：{expected_name}")
        if type(size) is not int or not 0 < size <= MAX_GITEE_PART_BYTES:
            raise UpdateError(f"Gitee 分卷大小无效：{expected_name}")
        total += size
        parts.append(UpdatePackagePart(name, digest, size))
    if total != manifest.bytes:
        raise UpdateError("Gitee 分卷总大小与完整更新包不一致")
    return manifest, tuple(parts)


def _asset_map(
    release: dict[str, object], source_name: str = "GitHub",
) -> dict[str, dict[str, object]]:
    assets = release.get("assets")
    if not isinstance(assets, list):
        raise UpdateError(f"{source_name} Release 缺少资产列表")
    result: dict[str, dict[str, object]] = {}
    for item in assets:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            raise UpdateError(f"{source_name} Release 资产信息无效")
        name = item["name"]
        if name in result:
            raise UpdateError(f"{source_name} Release 含重复资产：{name}")
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


def _validated_gitee_asset_url(
    asset: dict[str, object], expected_name: str, tag_name: str,
) -> str:
    if asset.get("name") != expected_name:
        raise UpdateError(f"Gitee Release 资产名称不符：{expected_name}")
    url = _validate_https_url(
        asset.get("browser_download_url"), f"{expected_name} 下载地址",
    )
    parsed = urllib.parse.urlparse(url)
    expected_prefix = f"/{GITEE_REPOSITORY}/releases/download/{tag_name}/"
    if parsed.hostname != "gitee.com" or not parsed.path.startswith(expected_prefix):
        raise UpdateError(f"{expected_name} 不是目标 Gitee 仓库的 Release 资产")
    if urllib.parse.unquote(PurePosixPath(parsed.path).name) != expected_name:
        raise UpdateError(f"{expected_name} 下载地址文件名不符")
    return url


def candidate_from_gitee_release(
    release: dict[str, object],
    manifest: UpdateManifest,
    parts: tuple[UpdatePackagePart, ...],
) -> UpdateCandidate:
    if release.get("prerelease") is not False:
        raise UpdateError("只允许使用正式 Gitee Release")
    tag_name = release.get("tag_name")
    if tag_name != f"v{manifest.version}":
        raise UpdateError("Gitee Release 标签与更新清单版本不一致")
    expected_release_url = (
        f"https://gitee.com/{GITEE_REPOSITORY}/releases/tag/{tag_name}"
    )
    if manifest.release_url != expected_release_url:
        raise UpdateError("Gitee Release 页面与更新清单不一致")
    published_at = release.get("published_at") or release.get("created_at")
    if not isinstance(published_at, str) or not published_at:
        raise UpdateError("Gitee Release 发布时间无效")
    assets = _asset_map(release, "Gitee")
    manifest_asset = assets.get(GITEE_MANIFEST_NAME)
    if manifest_asset is None:
        raise UpdateError(f"Gitee Release 缺少 {GITEE_MANIFEST_NAME}")
    _validated_gitee_asset_url(manifest_asset, GITEE_MANIFEST_NAME, tag_name)
    with_urls: list[UpdatePackagePart] = []
    for part in parts:
        asset = assets.get(part.name)
        if asset is None:
            raise UpdateError(f"Gitee Release 缺少分卷：{part.name}")
        url = _validated_gitee_asset_url(asset, part.name, tag_name)
        with_urls.append(UpdatePackagePart(part.name, part.sha256, part.bytes, url))
    return UpdateCandidate(
        manifest=manifest,
        package_url=None,
        published_at=published_at,
        tag_name=tag_name,
        source="gitee",
        parts=tuple(with_urls),
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
        "source": candidate.source,
        "parts": [asdict(part) for part in candidate.parts],
        "incremental": asdict(candidate.incremental) if candidate.incremental else None,
        "incremental_urls": dict(candidate.incremental_urls),
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
    published_at = value.get("published_at")
    tag_name = value.get("tag_name")
    if not isinstance(published_at, str) or not isinstance(tag_name, str):
        raise UpdateError("更新缓存字段无效")
    source = value.get("source", "github")
    raw_parts = value.get("parts", [])
    if source == "github":
        package_url = _validate_https_url(value.get("package_url"), "缓存下载地址")
        if raw_parts not in (None, []):
            raise UpdateError("GitHub 更新缓存不应包含分卷")
        return _restore_incremental(
            UpdateCandidate(manifest, package_url, published_at, tag_name), value,
        )
    if source != "gitee" or value.get("package_url") is not None:
        raise UpdateError("更新缓存来源无效")
    if not isinstance(raw_parts, list) or not raw_parts:
        raise UpdateError("Gitee 更新缓存缺少分卷")
    parts: list[UpdatePackagePart] = []
    total = 0
    for index, item in enumerate(raw_parts, 1):
        if not isinstance(item, dict) or set(item) != {"name", "sha256", "bytes", "url"}:
            raise UpdateError("Gitee 更新缓存分卷字段无效")
        name = item["name"]
        digest = item["sha256"]
        size = item["bytes"]
        expected_name = f"{manifest.package}.{index:03d}"
        if name != expected_name or not isinstance(digest, str) or not SHA256_PATTERN.fullmatch(digest):
            raise UpdateError("Gitee 更新缓存分卷记录无效")
        if type(size) is not int or not 0 < size <= MAX_GITEE_PART_BYTES:
            raise UpdateError("Gitee 更新缓存分卷大小无效")
        url = _validated_gitee_asset_url(
            {"name": name, "browser_download_url": item["url"]},
            expected_name,
            tag_name,
        )
        total += size
        parts.append(UpdatePackagePart(name, digest, size, url))
    if total != manifest.bytes:
        raise UpdateError("Gitee 更新缓存分卷总大小无效")
    return _restore_incremental(
        UpdateCandidate(manifest, None, published_at, tag_name, "gitee", tuple(parts)), value,
    )


def _incremental_asset_url(candidate: UpdateCandidate, asset: dict, name: str) -> str:
    if candidate.source == "gitee":
        return _validated_gitee_asset_url(asset, name, candidate.tag_name)
    url = _validated_asset_url(asset, name)
    expected = f"/{GITHUB_REPOSITORY}/releases/download/{candidate.tag_name}/{name}"
    if urllib.parse.unquote(urllib.parse.urlparse(url).path) != expected:
        raise UpdateError("增量资产与 Release 版本不一致")
    return url


def _restore_incremental(candidate: UpdateCandidate, value: dict) -> UpdateCandidate:
    from dataclasses import replace

    data = value.get("incremental")
    if data is None:
        return candidate
    try:
        metadata = incremental_update.parse_manifest(data)
    except incremental_update.IncrementalError as exc:
        raise UpdateError(str(exc)) from exc
    if (
        metadata.version != candidate.manifest.version
        or candidate.tag_name != f"v{metadata.version}"
        or metadata.version_code != candidate.manifest.version_code
        or metadata.package_sha256 != candidate.manifest.sha256
        or metadata.unpacked_bytes != candidate.manifest.unpacked_bytes
    ):
        raise UpdateError("增量清单与完整更新清单不一致")
    urls = value.get("incremental_urls")
    if not isinstance(urls, dict) or set(urls) != {bundle.name for bundle in metadata.bundles}:
        raise UpdateError("增量清单缺少数据包下载地址")
    verified = tuple((bundle.name, _incremental_asset_url(
        candidate, {"name": bundle.name, "browser_download_url": urls[bundle.name]}, bundle.name,
    )) for bundle in metadata.bundles)
    return replace(candidate, incremental=metadata, incremental_urls=verified)


def _attach_incremental(candidate: UpdateCandidate, assets: dict, opener: Callable) -> UpdateCandidate:
    name = incremental_update.MANIFEST_NAME
    if name not in assets:
        return candidate  # Releases published before incremental support.
    url = _incremental_asset_url(candidate, assets[name], name)
    request = urllib.request.Request(url, headers={"User-Agent": "FRLG-Auto-RNG-Updater"})
    with _open(opener, request, 15.0) as response:
        payload = _read_response(response, incremental_update.MAX_MANIFEST_BYTES)
    data = _read_json_object(payload, "增量更新清单")
    try:
        metadata = incremental_update.parse_manifest(data)
    except incremental_update.IncrementalError as exc:
        raise UpdateError(str(exc)) from exc
    urls = {}
    for bundle in metadata.bundles:
        asset = assets.get(bundle.name)
        if asset is None:
            raise UpdateError(f"Release 缺少增量数据包：{bundle.name}")
        if "size" in asset and asset["size"] != bundle.bytes:
            raise UpdateError(f"增量数据包大小与 Release 不一致：{bundle.name}")
        urls[bundle.name] = _incremental_asset_url(candidate, asset, bundle.name)
    return _restore_incremental(candidate, {"incremental": data, "incremental_urls": urls})


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


def _system_urlopen(request: urllib.request.Request, *, timeout: float):
    """Open HTTPS with two verified CA sources and never disable TLS checks."""

    system_context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    try:
        return urllib.request.urlopen(
            request, timeout=timeout, context=system_context,
        )
    except Exception as exc:
        if not _is_certificate_error(exc):
            raise
    # Some packaged Windows environments cannot build the complete issuer
    # chain from the machine store.  Retry with Mozilla's bundled CA set while
    # retaining hostname and certificate verification.
    bundled_context = ssl.create_default_context(cafile=certifi.where())
    return urllib.request.urlopen(
        request, timeout=timeout, context=bundled_context,
    )


def _is_certificate_error(error: BaseException) -> bool:
    current: BaseException | object | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, ssl.SSLCertVerificationError):
            return True
        reason = getattr(current, "reason", None)
        cause = getattr(current, "__cause__", None)
        context = getattr(current, "__context__", None)
        current = reason or cause or context
    return False


def _open(opener: Callable, request: urllib.request.Request, timeout: float):
    try:
        try:
            return opener(request, timeout=timeout)
        except TypeError:
            return opener(request)
    except Exception as exc:
        if _is_certificate_error(exc):
            raise UpdateSourceUnavailable(CERTIFICATE_ERROR_MESSAGE) from exc
        raise


def fetch_gitee_candidate(
    *, opener: Callable = _system_urlopen,
) -> UpdateCandidate:
    headers = {
        "Accept": "application/json",
        "User-Agent": "FRLG-Auto-RNG-Updater",
    }
    request = urllib.request.Request(GITEE_API_URL, headers=headers)
    with _open(opener, request, 15.0) as response:
        release_payload = _read_response(response, 2 * 1024 * 1024)
    release = _read_json_object(release_payload, "Gitee Release")
    tag_name = release.get("tag_name")
    if not isinstance(tag_name, str) or not re.fullmatch(
        r"v[0-9]+(?:\.[0-9]+){1,3}", tag_name,
    ):
        raise UpdateError("Gitee Release 标签无效")
    assets = _asset_map(release, "Gitee")
    manifest_asset = assets.get(GITEE_MANIFEST_NAME)
    if manifest_asset is None:
        raise UpdateError(f"Gitee Release 缺少 {GITEE_MANIFEST_NAME}")
    manifest_url = _validated_gitee_asset_url(
        manifest_asset, GITEE_MANIFEST_NAME, tag_name,
    )
    manifest_request = urllib.request.Request(manifest_url, headers=headers)
    with _open(opener, manifest_request, 12.0) as response:
        manifest_payload = _read_response(response, 256 * 1024)
    manifest, parts = parse_gitee_manifest(manifest_payload)
    return _attach_incremental(candidate_from_gitee_release(release, manifest, parts), assets, opener)


def check_for_update(
    *,
    current_version_code: int = APP_VERSION_CODE,
    cache_dir: Path,
    force: bool = False,
    opener: Callable = _system_urlopen,
    now: float | None = None,
    source: str = "auto",
) -> UpdateCheckResult:
    if source not in UPDATE_SOURCE_CHOICES:
        raise ValueError(f"不支持的程序更新源：{source}")
    now_value = time.time() if now is None else now
    cache_path = Path(cache_dir) / "check-cache.json"
    cache: dict[str, object] = {}
    try:
        raw_cache = json.loads(cache_path.read_text(encoding="utf-8"))
        if isinstance(raw_cache, dict):
            cache = raw_cache
    except (OSError, json.JSONDecodeError):
        pass

    if not force and cache.get("selected_source", "auto") == source:
        last_checked = cache.get("last_checked", cache.get("checked_at"))
        if (
            isinstance(last_checked, (int, float))
            and 0 <= now_value - last_checked < AUTO_CHECK_INTERVAL_SECONDS
        ):
            cached = _cached_result(cache, current_version_code=current_version_code)
            if cached is not None:
                return cached

    if source == "gitee":
        try:
            candidate = fetch_gitee_candidate(opener=opener)
            if candidate.manifest.version_code > current_version_code:
                result = UpdateCheckResult(
                    "available",
                    f"已从 Gitee 发现新版本 {candidate.manifest.version}。",
                    candidate,
                )
            elif candidate.manifest.version_code == current_version_code:
                result = UpdateCheckResult("current", "Gitee 确认当前已是最新正式版。")
            else:
                raise UpdateError(
                    f"Gitee 仍停留在 {candidate.manifest.version}，早于当前版本"
                )
        except (OSError, urllib.error.URLError, urllib.error.HTTPError, UpdateError) as exc:
            return UpdateCheckResult("error", f"检查程序更新失败：Gitee：{exc}")
        _atomic_json(
            cache_path,
            {
                "last_checked": now_value,
                "checked_at": now_value,
                "current_version_code": current_version_code,
                "selected_source": source,
                "etag": None,
                "release_url": result.candidate.manifest.release_url if result.candidate else None,
                "status": result.status,
                "message": result.message,
                "candidate": _candidate_to_json(result.candidate),
            },
        )
        return result

    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "FRLG-Auto-RNG-Updater",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if isinstance(cache.get("etag"), str) and cache["etag"]:
        headers["If-None-Match"] = cache["etag"]
    request = urllib.request.Request(GITHUB_API_URL, headers=headers)
    response_etag = None
    github_succeeded = False
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
            candidate = _attach_incremental(candidate_from_release(release, manifest), assets, opener)
            if manifest.version_code > current_version_code:
                result = UpdateCheckResult(
                    "available", f"发现新版本 {manifest.version}。", candidate
                )
            else:
                result = UpdateCheckResult("current", "当前已是最新正式版。")
        github_succeeded = True
    except (OSError, urllib.error.URLError, urllib.error.HTTPError, UpdateError) as github_exc:
        if source == "github":
            return UpdateCheckResult(
                "error", f"检查程序更新失败：GitHub：{github_exc}"
            )
        try:
            candidate = fetch_gitee_candidate(opener=opener)
            if candidate.manifest.version_code > current_version_code:
                result = UpdateCheckResult(
                    "available",
                    f"GitHub 暂时不可用，已从 Gitee 备用源发现新版本 {candidate.manifest.version}。",
                    candidate,
                )
            elif candidate.manifest.version_code == current_version_code:
                result = UpdateCheckResult(
                    "current",
                    "GitHub 暂时不可用；Gitee 备用源确认当前已是最新正式版。",
                )
            else:
                raise UpdateError(
                    f"Gitee 备用源仍停留在 {candidate.manifest.version}，无法确认最新版本"
                )
        except (OSError, urllib.error.URLError, urllib.error.HTTPError, UpdateError) as gitee_exc:
            # Keep the last good cache intact.  A transient failure in both
            # sources must not overwrite the last verified candidate.
            return UpdateCheckResult(
                "error",
                f"检查程序更新失败：GitHub：{github_exc}；Gitee 备用源：{gitee_exc}",
            )

    _atomic_json(
        cache_path,
        {
            "last_checked": now_value,
            "checked_at": now_value,
            "current_version_code": current_version_code,
            "selected_source": source,
            # A Gitee result must never be paired with an older GitHub ETag;
            # otherwise a later GitHub 304 could incorrectly reuse the mirror
            # candidate as if GitHub had verified it.
            "etag": (response_etag or cache.get("etag")) if github_succeeded else None,
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


def _stream_candidate_package(
    candidate: UpdateCandidate,
    partial: Path,
    *,
    opener: Callable,
    progress: Callable[[int, int], None] | None,
    cancelled: Callable[[], bool] | None,
) -> None:
    if candidate.parts:
        if candidate.source != "gitee" or candidate.package_url is not None:
            raise UpdateError("分卷更新候选来源无效")
        sources = tuple((part.url, part) for part in candidate.parts)
    else:
        if candidate.source != "github" or not candidate.package_url:
            raise UpdateError("单文件更新候选来源无效")
        sources = ((candidate.package_url, None),)
    total_digest = hashlib.sha256()
    total_received = 0
    with partial.open("xb") as output:
        for url, part in sources:
            if cancelled is not None and cancelled():
                raise UpdateCancelled("程序更新下载已取消")
            request = urllib.request.Request(
                url,
                headers={"User-Agent": "FRLG-Auto-RNG-Updater"},
            )
            part_digest = hashlib.sha256()
            part_received = 0
            with _open(opener, request, 30.0) as response:
                while True:
                    if cancelled is not None and cancelled():
                        raise UpdateCancelled("程序更新下载已取消")
                    chunk = response.read(DOWNLOAD_CHUNK_BYTES)
                    if not chunk:
                        break
                    part_received += len(chunk)
                    total_received += len(chunk)
                    part_limit = part.bytes if part is not None else candidate.manifest.bytes
                    if part_received > part_limit or total_received > candidate.manifest.bytes:
                        raise UpdateError("下载大小超过更新清单")
                    output.write(chunk)
                    part_digest.update(chunk)
                    total_digest.update(chunk)
                    if progress is not None:
                        progress(total_received, candidate.manifest.bytes)
            if part is not None:
                if part_received != part.bytes:
                    raise UpdateError(
                        f"Gitee 分卷大小不符：{part.name} 应为 {part.bytes}，实际 {part_received}"
                    )
                if part_digest.hexdigest() != part.sha256:
                    raise UpdateError(f"Gitee 分卷 SHA-256 校验失败：{part.name}")
    if total_received != candidate.manifest.bytes:
        raise UpdateError(
            f"更新包大小不符：应为 {candidate.manifest.bytes}，实际 {total_received}"
        )
    if total_digest.hexdigest() != candidate.manifest.sha256:
        raise UpdateError("更新包 SHA-256 校验失败")


def _same_package(left: UpdateManifest, right: UpdateManifest) -> bool:
    fields = (
        "schema", "version", "version_code", "package", "sha256", "bytes",
        "unpacked_bytes",
    )
    return all(getattr(left, field) == getattr(right, field) for field in fields)


def download_package(
    candidate: UpdateCandidate,
    destination: Path,
    *,
    opener: Callable = _system_urlopen,
    progress: Callable[[int, int], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
    allow_gitee_fallback: bool = True,
) -> Path:
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + ".part")
    partial.unlink(missing_ok=True)
    try:
        try:
            _stream_candidate_package(
                candidate,
                partial,
                opener=opener,
                progress=progress,
                cancelled=cancelled,
            )
        except (OSError, urllib.error.URLError, urllib.error.HTTPError, UpdateSourceUnavailable) as primary_exc:
            if candidate.source != "github":
                raise UpdateError(f"Gitee 备用源下载失败：{primary_exc}") from primary_exc
            if not allow_gitee_fallback:
                raise UpdateError(f"GitHub 更新源下载失败：{primary_exc}") from primary_exc
            partial.unlink(missing_ok=True)
            try:
                mirror = fetch_gitee_candidate(opener=opener)
                if not _same_package(candidate.manifest, mirror.manifest):
                    raise UpdateError("Gitee 备用源与 GitHub 更新包版本或校验值不一致")
                if progress is not None:
                    progress(0, candidate.manifest.bytes)
                _stream_candidate_package(
                    mirror,
                    partial,
                    opener=opener,
                    progress=progress,
                    cancelled=cancelled,
                )
            except UpdateCancelled:
                raise
            except (OSError, urllib.error.URLError, urllib.error.HTTPError, UpdateError) as mirror_exc:
                raise UpdateError(
                    f"GitHub 下载失败：{primary_exc}；Gitee 备用源下载失败：{mirror_exc}"
                ) from primary_exc
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


def _check_cancelled(cancelled: Callable[[], bool] | None) -> None:
    if cancelled is not None and cancelled():
        raise UpdateCancelled("程序更新已取消")


def plan_incremental_update(
    candidate: UpdateCandidate, *, install_dir: Path, updates_root: Path,
    cancelled: Callable[[], bool] | None = None,
    status: Callable[[str], None] | None = None,
) -> incremental_update.Plan | None:
    if candidate.incremental is None:
        return None
    try:
        return incremental_update.plan_update(
            candidate.incremental, Path(install_dir), Path(updates_root) / "bundles",
            cancelled=lambda: _check_cancelled(cancelled), status=status or (lambda text: None),
        )
    except incremental_update.IncrementalError as exc:
        raise UpdateError(str(exc)) from exc


def _download_incremental_bundles(
    candidate: UpdateCandidate, plan: incremental_update.Plan, cache: Path, *,
    opener: Callable, progress: Callable[[int, int], None] | None,
    cancelled: Callable[[], bool] | None,
) -> None:
    cache.mkdir(parents=True, exist_ok=True)
    check_cancel = lambda: _check_cancelled(cancelled)
    missing = [bundle for bundle in plan.needed if not incremental_update.matches(
        incremental_update.local_file(cache, bundle.name), bundle.bytes, bundle.sha256, check_cancel,
    )]
    total = sum(bundle.bytes for bundle in missing)
    received = 0
    urls = dict(candidate.incremental_urls)
    if progress:
        progress(0, total)
    for bundle in missing:
        check_cancel()
        destination = cache / bundle.name
        partial = cache / f"{bundle.name}.{uuid.uuid4().hex}.part"
        request = urllib.request.Request(urls[bundle.name], headers={"User-Agent": "FRLG-Auto-RNG-Updater"})
        digest = hashlib.sha256()
        size = 0
        try:
            with _open(opener, request, 30.0) as response, partial.open("xb") as output:
                while chunk := response.read(DOWNLOAD_CHUNK_BYTES):
                    check_cancel()
                    size += len(chunk)
                    if size > bundle.bytes:
                        raise UpdateError(f"增量数据包下载大小超出清单：{bundle.name}")
                    digest.update(chunk)
                    output.write(chunk)
                    received += len(chunk)
                    if progress:
                        progress(received, total)
            if size != bundle.bytes or digest.hexdigest() != bundle.sha256:
                raise UpdateError(f"增量数据包大小或 SHA-256 校验失败：{bundle.name}")
            partial.replace(destination)
        except urllib.error.HTTPError as exc:
            raise UpdateSourceUnavailable(
                f"增量数据包下载失败：{candidate.source} HTTP {exc.code}；{request.full_url}"
            ) from exc
        finally:
            partial.unlink(missing_ok=True)
    if progress:
        progress(total, total)


def _prepare_incremental(
    candidate: UpdateCandidate, plan: incremental_update.Plan, install_dir: Path,
    updates_root: Path, stage_dir: Path, *, opener: Callable,
    progress: Callable[[int, int], None] | None, cancelled: Callable[[], bool] | None,
    status: Callable[[str], None], allow_gitee_fallback: bool,
) -> None:
    cache = updates_root / "bundles"
    try:
        _download_incremental_bundles(candidate, plan, cache, opener=opener, progress=progress, cancelled=cancelled)
    except (OSError, urllib.error.URLError, UpdateSourceUnavailable) as exc:
        if candidate.source != "github" or not allow_gitee_fallback:
            raise UpdateError(f"{candidate.source} 增量更新下载失败：{exc}") from exc
        status("GitHub 下载失败，正在检查 Gitee 增量备用源……")
        _check_cancelled(cancelled)
        mirror = fetch_gitee_candidate(opener=opener)
        if not _same_package(candidate.manifest, mirror.manifest) or mirror.incremental != candidate.incremental:
            raise UpdateError("Gitee 备用源增量清单与 GitHub 不一致") from exc
        _download_incremental_bundles(mirror, plan, cache, opener=opener, progress=progress, cancelled=cancelled)
    try:
        incremental_update.stage_update(
            plan, install_dir, cache, stage_dir,
            cancelled=lambda: _check_cancelled(cancelled), status=status,
        )
    except incremental_update.IncrementalError as exc:
        raise UpdateError(str(exc)) from exc


def prepare_update(
    candidate: UpdateCandidate,
    *,
    install_dir: Path,
    updates_root: Path,
    updater_source: Path | None = None,
    opener: Callable = _system_urlopen,
    progress: Callable[[int, int], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
    probe: Callable[[Path, UpdateManifest], None] = _probe_staged_version,
    cancel_event: object | None = None,
    version_probe: Callable[[Path], dict[str, object]] | None = None,
    allow_gitee_fallback: bool = True,
    incremental_plan: incremental_update.Plan | None = None,
    status: Callable[[str], None] | None = None,
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
    report = status or (lambda text: None)
    if candidate.incremental is not None:
        if incremental_plan is None:
            incremental_plan = plan_incremental_update(
                candidate, install_dir=install_dir, updates_root=updates_root,
                cancelled=cancelled, status=report,
            )
        if incremental_plan.manifest != candidate.incremental:
            raise UpdateError("增量下载计划与当前候选不一致，请重新检查更新")
        needed = candidate.manifest.unpacked_bytes + max(256 * 1024 * 1024, candidate.manifest.unpacked_bytes // 10)
    else:
        needed = required_free_space(candidate.manifest)
    if shutil.disk_usage(install_dir.parent).free < needed:
        raise UpdateError("安装盘剩余空间不足，无法安全保留回滚副本")
    updates_root.mkdir(parents=True, exist_ok=True)
    if candidate.incremental is not None:
        same_volume = updates_root.stat().st_dev == install_dir.parent.stat().st_dev
        cache_needed = incremental_plan.download_bytes + (needed if same_volume else 64 * 1024 * 1024)
        if shutil.disk_usage(updates_root).free < cache_needed:
            raise UpdateError("更新缓存盘剩余空间不足")
    download_dir = updates_root / "downloads" / str(candidate.manifest.version_code)
    package_path = download_dir / candidate.manifest.package
    if candidate.incremental is not None:
        report(
            f"增量更新：复用 {len(incremental_plan.reuse)}/{len(candidate.incremental.files)} 个文件，"
            f"需下载 {incremental_plan.download_bytes / (1024 * 1024):.1f} MiB"
        )
        _prepare_incremental(
            candidate, incremental_plan, install_dir, updates_root, stage_dir,
            opener=opener, progress=progress, cancelled=cancelled,
            status=report, allow_gitee_fallback=allow_gitee_fallback,
        )
    elif package_path.is_file():
        actual_size = package_path.stat().st_size
        digest = incremental_update.digest_file(package_path, lambda: _check_cancelled(cancelled))
        if actual_size != candidate.manifest.bytes or digest != candidate.manifest.sha256:
            package_path.unlink()
    if candidate.incremental is None and not package_path.is_file():
        download_package(
            candidate,
            package_path,
            opener=opener,
            progress=progress,
            cancelled=cancelled,
            allow_gitee_fallback=allow_gitee_fallback,
        )
    if candidate.incremental is None:
        _check_cancelled(cancelled)
        report("正在解压并校验完整更新包……")
        safe_extract(package_path, stage_dir, candidate.manifest)
    try:
        _check_cancelled(cancelled)
        report("正在验证新版程序版本……")
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
