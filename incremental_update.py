"""File-verified updates transported as bounded, reusable compressed bundles.

This protocol is independent of HTTP Range support and of the installed version.
Only bundles needed by changed/missing files are downloaded. Installation still
uses a complete, separately staged directory and the existing rollback protocol.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import zipfile
import zlib
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path, PureWindowsPath
from typing import Callable


MANIFEST_NAME = "incremental-manifest.json"
MAX_MANIFEST_BYTES = 32 * 1024 * 1024
BUNDLE_BYTES = 16 * 1024 * 1024
MAX_BUNDLE_BYTES = BUNDLE_BYTES + 64 * 1024
MAX_FILES = 100_000
MAX_BUNDLES = 4096
MAX_UNPACKED_BYTES = 12 * 1024 * 1024 * 1024
SHA256 = re.compile(r"^[0-9a-f]{64}$")


class IncrementalError(ValueError):
    pass


@dataclass(frozen=True)
class Block:
    bundle: str
    offset: int
    bytes: int


@dataclass(frozen=True)
class File:
    path: str
    bytes: int
    sha256: str
    blocks: tuple[Block, ...]


@dataclass(frozen=True)
class Bundle:
    name: str
    bytes: int
    sha256: str
    unpacked_bytes: int


@dataclass(frozen=True)
class Manifest:
    schema: int
    version: str
    version_code: int
    package_sha256: str
    unpacked_bytes: int
    files: tuple[File, ...]
    bundles: tuple[Bundle, ...]


@dataclass(frozen=True)
class Plan:
    manifest: Manifest
    reuse: frozenset[str]
    needed: tuple[Bundle, ...]
    download_bytes: int


def digest_file(path: Path, cancelled: Callable[[], None] = lambda: None) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            cancelled()
            digest.update(chunk)
    return digest.hexdigest()


def safe_path(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise IncrementalError("增量清单文件路径无效")
    parts = value.split("/")
    if any(
        not part or part in {".", ".."} or part.endswith((".", " "))
        or any(ord(c) < 32 or c in '<>:"|?*' for c in part)
        or PureWindowsPath(part).is_reserved()
        for part in parts
    ) or parts[0].casefold().startswith(".frlg-"):
        raise IncrementalError(f"增量清单含不安全路径：{value!r}")
    return value


def _integer(value: object, maximum: int, *, zero: bool = False) -> bool:
    return type(value) is int and (0 if zero else 1) <= value <= maximum


def parse_manifest(data: object) -> Manifest:
    keys = {"schema", "version", "version_code", "package_sha256", "unpacked_bytes", "files", "bundles"}
    if not isinstance(data, dict) or set(data) != keys or type(data["schema"]) is not int or data["schema"] != 1:
        raise IncrementalError("增量清单结构或协议版本无效")
    if (
        not isinstance(data["version"], str)
        or not re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,3}", data["version"])
        or not _integer(data["version_code"], 10**15)
        or not isinstance(data["package_sha256"], str) or not SHA256.fullmatch(data["package_sha256"])
        or not _integer(data["unpacked_bytes"], MAX_UNPACKED_BYTES)
    ):
        raise IncrementalError("增量清单版本、大小或摘要无效")
    raw_files, raw_bundles = data["files"], data["bundles"]
    if not isinstance(raw_files, list) or not 1 <= len(raw_files) <= MAX_FILES:
        raise IncrementalError("增量清单文件数量无效")
    if not isinstance(raw_bundles, list) or not 1 <= len(raw_bundles) <= MAX_BUNDLES:
        raise IncrementalError("增量清单数据包数量无效")
    bundles: dict[str, Bundle] = {}
    spans: dict[str, list[tuple[int, int]]] = {}
    for item in raw_bundles:
        if not isinstance(item, dict) or set(item) != {"name", "bytes", "sha256", "unpacked_bytes"}:
            raise IncrementalError("增量数据包字段无效")
        digest = item["sha256"]
        if not isinstance(digest, str) or not SHA256.fullmatch(digest):
            raise IncrementalError("增量数据包摘要无效")
        name = item["name"]
        if name != f"update-data-{digest}.bin" or name in bundles:
            raise IncrementalError("增量数据包名称无效或重复")
        if not _integer(item["bytes"], MAX_BUNDLE_BYTES) or not _integer(item["unpacked_bytes"], BUNDLE_BYTES):
            raise IncrementalError("增量数据包大小无效")
        bundles[name] = Bundle(**item)
        spans[name] = []
    files: list[File] = []
    names: set[str] = set()
    total_blocks = 0
    for item in raw_files:
        if not isinstance(item, dict) or set(item) != {"path", "bytes", "sha256", "blocks"}:
            raise IncrementalError("增量文件字段无效")
        path = safe_path(item["path"])
        normalized = path.casefold()
        if normalized in names:
            raise IncrementalError(f"增量清单含重复路径：{path}")
        names.add(normalized)
        if not _integer(item["bytes"], MAX_UNPACKED_BYTES, zero=True):
            raise IncrementalError("增量文件大小无效")
        if not isinstance(item["sha256"], str) or not SHA256.fullmatch(item["sha256"]):
            raise IncrementalError("增量文件摘要无效")
        raw_blocks = item["blocks"]
        if not isinstance(raw_blocks, list):
            raise IncrementalError("增量文件数据块无效")
        total_blocks += len(raw_blocks)
        if total_blocks > MAX_FILES + MAX_UNPACKED_BYTES // BUNDLE_BYTES:
            raise IncrementalError("增量文件数据块过多")
        blocks: list[Block] = []
        for block in raw_blocks:
            if not isinstance(block, dict) or set(block) != {"bundle", "offset", "bytes"}:
                raise IncrementalError("增量数据块字段无效")
            name = block["bundle"]
            if not isinstance(name, str) or name not in bundles:
                raise IncrementalError("增量文件引用不存在的数据包")
            if (
                not _integer(block["offset"], BUNDLE_BYTES, zero=True)
                or not _integer(block["bytes"], BUNDLE_BYTES)
                or block["offset"] + block["bytes"] > bundles[name].unpacked_bytes
            ):
                raise IncrementalError("增量文件数据块越界")
            blocks.append(Block(**block))
            spans[name].append((block["offset"], block["bytes"]))
        if sum(block.bytes for block in blocks) != item["bytes"]:
            raise IncrementalError("增量文件数据块总大小不符")
        files.append(File(path, item["bytes"], item["sha256"], tuple(blocks)))
    for name in names:
        parts = name.split("/")
        if any("/".join(parts[:index]) in names for index in range(1, len(parts))):
            raise IncrementalError("增量文件路径与目录冲突")
    if not {"frlg-auto-rng.exe", "frlg-auto-rng-updater.exe"}.issubset(names) or not any(
        name.startswith("_internal/") for name in names
    ):
        raise IncrementalError("增量清单缺少主程序、更新器或运行库")
    if sum(file.bytes for file in files) != data["unpacked_bytes"]:
        raise IncrementalError("增量清单解压总大小不符")
    # Identical bundle content can be shared by files with different block
    # boundaries. Check coverage, allowing overlap but never unreferenced bytes.
    for name, ranges in spans.items():
        cursor = 0
        for offset, size in sorted(set(ranges)):
            if offset > cursor:
                raise IncrementalError("增量数据包含未登记内容")
            cursor = max(cursor, offset + size)
        if cursor != bundles[name].unpacked_bytes:
            raise IncrementalError("增量数据包内容不完整")
    return Manifest(
        1, data["version"], data["version_code"], data["package_sha256"],
        data["unpacked_bytes"], tuple(files), tuple(bundles.values()),
    )


def local_file(root: Path, name: str) -> Path | None:
    path = root
    for part in name.split("/"):
        path = path / part
        if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
            return None
    return path if path.is_file() else None


def matches(path: Path | None, size: int, digest: str, cancelled: Callable[[], None]) -> bool:
    try:
        return path is not None and path.stat().st_size == size and digest_file(path, cancelled) == digest
    except OSError:
        return False


def plan_update(manifest: Manifest, install: Path, cache: Path, *, cancelled=lambda: None, status=lambda text: None) -> Plan:
    reuse: set[str] = set()
    needed: set[str] = set()
    for index, file in enumerate(manifest.files, 1):
        cancelled()
        if index == 1 or index % 100 == 0 or index == len(manifest.files):
            status(f"正在比对本地文件：{index}/{len(manifest.files)}")
        if matches(local_file(install, file.path), file.bytes, file.sha256, cancelled):
            reuse.add(file.path)
        else:
            needed.update(block.bundle for block in file.blocks)
    bundles = tuple(bundle for bundle in manifest.bundles if bundle.name in needed)
    missing = sum(bundle.bytes for bundle in bundles if not matches(
        local_file(cache, bundle.name), bundle.bytes, bundle.sha256, cancelled,
    ))
    return Plan(manifest, frozenset(reuse), bundles, missing)


def unpack_bundle(path: Path, bundle: Bundle) -> bytes:
    with path.open("rb") as stream:
        payload = stream.read(bundle.bytes + 1)
    if len(payload) != bundle.bytes or hashlib.sha256(payload).hexdigest() != bundle.sha256:
        raise IncrementalError(f"增量数据包校验失败：{bundle.name}")
    decoder = zlib.decompressobj()
    try:
        content = decoder.decompress(payload, bundle.unpacked_bytes + 1)
    except zlib.error as exc:
        raise IncrementalError(f"增量数据包解压失败：{bundle.name}") from exc
    if len(content) != bundle.unpacked_bytes or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
        raise IncrementalError(f"增量数据包解压大小或格式不符：{bundle.name}")
    return content


def stage_update(plan: Plan, install: Path, cache: Path, stage: Path, *, cancelled=lambda: None, status=lambda text: None) -> None:
    stage.mkdir(parents=False, exist_ok=False)
    bundles = {bundle.name: bundle for bundle in plan.needed}

    @lru_cache(maxsize=2)
    def content(name):
        return unpack_bundle(cache / name, bundles[name])

    try:
        for index, file in enumerate(plan.manifest.files, 1):
            cancelled()
            if index == 1 or index % 100 == 0 or index == len(plan.manifest.files):
                status(f"正在组装并校验新版文件：{index}/{len(plan.manifest.files)}")
            target = stage.joinpath(*file.path.split("/"))
            target.parent.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256()
            written = 0
            with target.open("xb") as output:
                if file.path in plan.reuse:
                    source = local_file(install, file.path)
                    if source is None:
                        raise IncrementalError(f"本地文件已变化，请重新检查更新：{file.path}")
                    with source.open("rb") as stream:
                        while chunk := stream.read(1024 * 1024):
                            cancelled()
                            written += len(chunk)
                            if written > file.bytes:
                                raise IncrementalError(f"本地文件已变化：{file.path}")
                            output.write(chunk)
                            digest.update(chunk)
                else:
                    for block in file.blocks:
                        cancelled()
                        chunk = content(block.bundle)[block.offset:block.offset + block.bytes]
                        output.write(chunk)
                        digest.update(chunk)
                        written += len(chunk)
            if written != file.bytes or digest.hexdigest() != file.sha256:
                raise IncrementalError(f"新版文件校验失败，请重新检查更新：{file.path}")
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    finally:
        content.cache_clear()


def create_assets(root: Path, package_manifest: dict, output: Path) -> Manifest:
    """Build deterministic bundles; no previous release or Range server needed.

    Large files have their own bundles. Small files are grouped into 16 stable
    path buckets, so a small edit never pulls unchanged large runtime files.
    """
    output.mkdir(parents=True, exist_ok=False)
    files: list[dict] = []
    bundles: dict[str, Bundle] = {}
    pending = bytearray()
    references: list[tuple[list, int, int]] = []

    def flush():
        if not pending:
            return
        payload = zlib.compress(pending, level=6)
        digest = hashlib.sha256(payload).hexdigest()
        name = f"update-data-{digest}.bin"
        if name not in bundles:
            (output / name).write_bytes(payload)
            bundles[name] = Bundle(name, len(payload), digest, len(pending))
        for blocks, offset, size in references:
            blocks.append({"bundle": name, "offset": offset, "bytes": size})
        pending.clear()
        references.clear()

    try:
        groups: dict[str, list[Path]] = {}
        for path in sorted(root.rglob("*")):
            if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
                raise IncrementalError(f"发布目录不允许链接：{path}")
            if not path.is_file():
                continue
            name = safe_path(path.relative_to(root).as_posix())
            group = ("file:" + name) if path.stat().st_size >= 1024 * 1024 else (
                "small:" + hashlib.sha256(name.encode("utf-8")).hexdigest()[0]
            )
            groups.setdefault(group, []).append(path)
        for group in sorted(groups):
            for path in groups[group]:
                file = {"path": path.relative_to(root).as_posix(), "bytes": 0, "sha256": "", "blocks": []}
                digest = hashlib.sha256()
                with path.open("rb") as stream:
                    while chunk := stream.read(BUNDLE_BYTES - len(pending)):
                        offset = len(pending)
                        pending.extend(chunk)
                        references.append((file["blocks"], offset, len(chunk)))
                        digest.update(chunk)
                        file["bytes"] += len(chunk)
                        if len(pending) == BUNDLE_BYTES:
                            flush()
                file["sha256"] = digest.hexdigest()
                files.append(file)
            flush()
        data = {
            "schema": 1, "version": package_manifest["version"],
            "version_code": package_manifest["version_code"],
            "package_sha256": package_manifest["sha256"],
            "unpacked_bytes": package_manifest["unpacked_bytes"],
            "files": files, "bundles": [asdict(bundle) for bundle in bundles.values()],
        }
        manifest = parse_manifest(data)
        payload = json.dumps(asdict(manifest), ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        if len(payload.encode("utf-8")) > MAX_MANIFEST_BYTES:
            raise IncrementalError("增量清单超过大小限制")
        (output / MANIFEST_NAME).write_text(payload, encoding="utf-8", newline="\n")
        return manifest
    except BaseException:
        shutil.rmtree(output, ignore_errors=True)
        raise


def verify_release_assets(package: Path, package_manifest: dict, assets: Path) -> Manifest:
    """Check every published byte and bind the incremental tree to the full ZIP."""
    manifest_path = assets / MANIFEST_NAME
    if manifest_path.stat().st_size > MAX_MANIFEST_BYTES:
        raise IncrementalError("增量清单超过大小限制")
    manifest = parse_manifest(json.loads(manifest_path.read_text(encoding="utf-8")))
    if any(getattr(manifest, key) != package_manifest[key] for key in ("version", "version_code", "unpacked_bytes")):
        raise IncrementalError("增量清单版本或大小与整包不一致")
    if (
        manifest.package_sha256 != package_manifest["sha256"]
        or package.stat().st_size != package_manifest["bytes"]
        or digest_file(package) != manifest.package_sha256
    ):
        raise IncrementalError("增量清单与整包摘要不一致")
    bundles = {bundle.name: bundle for bundle in manifest.bundles}

    @lru_cache(maxsize=2)
    def content(name):
        path = assets / name
        if path.stat().st_size != bundles[name].bytes:
            raise IncrementalError(f"增量数据包大小不符：{name}")
        return unpack_bundle(path, bundles[name])

    try:
        with zipfile.ZipFile(package) as archive:
            entries = [info for info in archive.infolist() if not info.is_dir()]
            if len(entries) != len(manifest.files) or {info.filename for info in entries} != {file.path for file in manifest.files}:
                raise IncrementalError("增量文件列表与完整 ZIP 不一致")
            for file in manifest.files:
                if archive.getinfo(file.path).file_size != file.bytes:
                    raise IncrementalError(f"增量文件与完整 ZIP 大小不一致：{file.path}")
                digest = hashlib.sha256()
                for block in file.blocks:
                    digest.update(content(block.bundle)[block.offset:block.offset + block.bytes])
                if digest.hexdigest() != file.sha256:
                    raise IncrementalError(f"增量文件内容校验失败：{file.path}")
                digest = hashlib.sha256()
                with archive.open(file.path) as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(chunk)
                if digest.hexdigest() != file.sha256:
                    raise IncrementalError(f"增量文件与完整 ZIP 内容不一致：{file.path}")
    finally:
        content.cache_clear()
    return manifest
