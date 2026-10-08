"""Few uploadable ZIPs containing the existing independently verified blocks.

ZIP_STORED wraps already compressed blocks without recompressing them. Clients
can fetch a block with HTTP Range, or verify/cache the enclosing ZIP when Range
is unavailable. Legacy releases and the whole-package migration stay supported.
"""

from __future__ import annotations

import json
import shutil
import struct
import tempfile
import uuid
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path

import incremental_update as incremental


MANIFEST_NAME = "incremental-packs.json"
MAX_ARCHIVE_BYTES = 90 * 1024 * 1024


@dataclass(frozen=True)
class Archive:
    name: str
    bytes: int
    sha256: str


@dataclass(frozen=True)
class Location:
    bundle: str
    archive: str
    offset: int


@dataclass(frozen=True)
class Manifest(incremental.Manifest):
    archives: tuple[Archive, ...]
    locations: tuple[Location, ...]


@dataclass(frozen=True)
class Plan(incremental.Plan):
    archive_download_bytes: int
    cache_bytes: int


def parse_manifest(data: object) -> Manifest:
    if (
        not isinstance(data, dict) or type(data.get("schema")) is not int or data["schema"] != 2
        or set(data) != {
            "schema", "version", "version_code", "package_sha256", "unpacked_bytes",
            "files", "bundles", "archives", "locations",
        }
    ):
        raise incremental.IncrementalError("合并增量清单结构或协议版本无效")
    base = incremental.parse_manifest({
        **{key: value for key, value in data.items() if key not in {"archives", "locations"}},
        "schema": 1,
    })
    raw_archives, raw_locations = data["archives"], data["locations"]
    if not isinstance(raw_archives, list) or not 1 <= len(raw_archives) <= incremental.MAX_BUNDLES:
        raise incremental.IncrementalError("增量压缩包数量无效")
    archives: dict[str, Archive] = {}
    for item in raw_archives:
        if not isinstance(item, dict) or set(item) != {"name", "bytes", "sha256"}:
            raise incremental.IncrementalError("增量压缩包字段无效")
        digest = item["sha256"]
        if not isinstance(digest, str) or not incremental.SHA256.fullmatch(digest):
            raise incremental.IncrementalError("增量压缩包摘要无效")
        if item["name"] != f"update-pack-{digest}.zip" or item["name"] in archives:
            raise incremental.IncrementalError("增量压缩包名称无效或重复")
        if type(item["bytes"]) is not int or not 0 < item["bytes"] <= MAX_ARCHIVE_BYTES:
            raise incremental.IncrementalError("增量压缩包大小无效")
        archives[item["name"]] = Archive(**item)
    if not isinstance(raw_locations, list) or len(raw_locations) != len(base.bundles):
        raise incremental.IncrementalError("增量数据块位置数量无效")
    bundles = {bundle.name: bundle for bundle in base.bundles}
    locations: list[Location] = []
    seen: set[str] = set()
    spans = {name: [] for name in archives}
    for item in raw_locations:
        if not isinstance(item, dict) or set(item) != {"bundle", "archive", "offset"}:
            raise incremental.IncrementalError("增量数据块位置字段无效")
        bundle, archive, offset = item["bundle"], item["archive"], item["offset"]
        if not isinstance(bundle, str) or bundle not in bundles or bundle in seen:
            raise incremental.IncrementalError("增量数据块位置引用无效或重复")
        if not isinstance(archive, str) or archive not in archives:
            raise incremental.IncrementalError("增量数据块引用不存在的压缩包")
        if type(offset) is not int or offset < 30 or offset + bundles[bundle].bytes > archives[archive].bytes:
            raise incremental.IncrementalError("增量数据块压缩包位置越界")
        seen.add(bundle)
        spans[archive].append((offset, offset + bundles[bundle].bytes))
        locations.append(Location(**item))
    for archive_name, ranges in spans.items():
        if not ranges:
            raise incremental.IncrementalError("增量压缩包没有引用的数据块")
        end = 0
        for start, stop in sorted(ranges):
            if start < end:
                raise incremental.IncrementalError("增量压缩包数据块重叠")
            end = stop
        size = 22 + sum(
            bundles[item.bundle].bytes + 76 + 2 * len(item.bundle.encode("ascii"))
            for item in locations if item.archive == archive_name
        )
        if size != archives[archive_name].bytes:
            raise incremental.IncrementalError("增量压缩包声明大小与成员结构不符")
    return Manifest(
        2, base.version, base.version_code, base.package_sha256, base.unpacked_bytes,
        base.files, base.bundles, tuple(archives.values()), tuple(locations),
    )


def parse_metadata(data: object) -> incremental.Manifest:
    return parse_manifest(data) if isinstance(data, dict) and data.get("schema") == 2 else incremental.parse_manifest(data)


def asset_names(manifest: incremental.Manifest) -> tuple[str, ...]:
    if isinstance(manifest, Manifest):
        return (MANIFEST_NAME, *(archive.name for archive in manifest.archives))
    return (incremental.MANIFEST_NAME, *(bundle.name for bundle in manifest.bundles))


def archive_cache(cache: Path) -> Path:
    return cache.parent / "archives"


def plan_update(manifest: Manifest, install: Path, cache: Path, *, cancelled=lambda: None, status=lambda text: None) -> Plan:
    base = incremental.plan_update(manifest, install, cache, cancelled=cancelled, status=status)
    missing = [bundle for bundle in base.needed if not incremental.matches(
        incremental.local_file(cache, bundle.name), bundle.bytes, bundle.sha256, cancelled,
    )]
    locations = {item.bundle: item for item in manifest.locations}
    needed_archives = {locations[bundle.name].archive for bundle in missing}
    available = set()
    archive_bytes = 0
    for archive in manifest.archives:
        if archive.name not in needed_archives:
            continue
        cancelled()
        status("正在检查已缓存的增量压缩包……")
        if incremental.matches(incremental.local_file(archive_cache(cache), archive.name), archive.bytes, archive.sha256, cancelled):
            available.add(archive.name)
        else:
            archive_bytes += archive.bytes
    range_bytes = sum(bundle.bytes for bundle in missing if locations[bundle.name].archive not in available)
    # Reserve for the no-Range case, including both ZIPs and materialized blocks.
    return Plan(base.manifest, base.reuse, base.needed, range_bytes, archive_bytes, archive_bytes + sum(b.bytes for b in missing))


def extract_bundles(manifest: Manifest, archive: Archive, source: Path, bundles: list[incremental.Bundle], cache: Path, *, cancelled=lambda: None) -> None:
    locations = {item.bundle: item for item in manifest.locations}
    cache.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as stream:
        for bundle in bundles:
            cancelled()
            location = locations[bundle.name]
            if location.archive != archive.name:
                raise incremental.IncrementalError("数据块与增量压缩包不一致")
            stream.seek(location.offset)
            payload = stream.read(bundle.bytes)
            # Validate decompression too, before making the cached block reusable.
            incremental.unpack_payload(payload, bundle)
            temporary = cache / f"{bundle.name}.{uuid.uuid4().hex}.part"
            try:
                temporary.write_bytes(payload)
                cancelled()
                temporary.replace(cache / bundle.name)
            finally:
                temporary.unlink(missing_ok=True)


def _member_offset(path: Path, info: zipfile.ZipInfo) -> int:
    with path.open("rb") as stream:
        stream.seek(info.header_offset)
        header = stream.read(30)
    if len(header) != 30 or header[:4] != b"PK\x03\x04":
        raise incremental.IncrementalError("增量压缩包成员头无效")
    name_size, extra_size = struct.unpack_from("<HH", header, 26)
    return info.header_offset + 30 + name_size + extra_size


def pack_assets(source: Path, output: Path, *, max_archive_bytes: int = MAX_ARCHIVE_BYTES, split_resources: bool = False) -> Manifest:
    """Compact v1 assets without changing block hashes or touching the source."""
    source, output = source.resolve(), output.resolve()
    if output == source or output.is_relative_to(source) or source.is_relative_to(output):
        raise incremental.IncrementalError("增量压缩包目录不得与源目录重叠")
    if type(max_archive_bytes) is not int or not 0 < max_archive_bytes <= MAX_ARCHIVE_BYTES:
        raise incremental.IncrementalError("增量压缩包上限必须在 1 到 90 MiB 之间")
    manifest_path = source / incremental.MANIFEST_NAME
    if manifest_path.stat().st_size > incremental.MAX_MANIFEST_BYTES:
        raise incremental.IncrementalError("增量清单超过大小限制")
    payload = manifest_path.read_bytes()
    base = incremental.parse_manifest(json.loads(payload))
    large = {
        block.bundle for file in base.files if file.bytes >= 1024 * 1024 for block in file.blocks
    }
    resources = ({bundle.name for bundle in base.bundles} - {
        block.bundle for file in base.files if Path(file.path).suffix.lower() not in incremental.RESOURCE_SUFFIXES
        for block in file.blocks
    } - large) if split_resources else set()
    archives: list[Archive] = []
    locations: list[Location] = []
    output.mkdir(parents=True, exist_ok=False)
    try:
        batches: list[list[incremental.Bundle]] = []
        # Small script/label groups never share an enclosing ZIP with large DLLs.
        for category in ("resources", "runtime-small", "runtime-large"):
            batch: list[incremental.Bundle] = []
            size = 22  # ZIP end-of-central-directory record.
            for bundle in base.bundles:
                actual = "runtime-large" if bundle.name in large else "resources" if bundle.name in resources else "runtime-small"
                if actual != category:
                    continue
                extra = bundle.bytes + 76 + 2 * len(bundle.name.encode("ascii"))
                if extra + 22 > max_archive_bytes:
                    raise incremental.IncrementalError("单个增量数据块超过压缩包上限")
                if size + extra > max_archive_bytes:
                    batches.append(batch)
                    batch, size = [], 22
                batch.append(bundle)
                size += extra
            if batch:
                batches.append(batch)
        for index, batch in enumerate(batches):
            temporary = output / f"pack-{index}.tmp"
            offsets: list[tuple[str, int]] = []
            with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_STORED, allowZip64=False) as archive:
                for bundle in batch:
                    path = incremental.local_file(source, bundle.name)
                    if path is None:
                        raise incremental.IncrementalError(f"缺少增量数据块：{bundle.name}")
                    if path.stat().st_size != bundle.bytes:
                        raise incremental.IncrementalError(f"增量数据块大小不符：{bundle.name}")
                    value = path.read_bytes()
                    incremental.unpack_payload(value, bundle)
                    info = zipfile.ZipInfo(bundle.name, date_time=(1980, 1, 1, 0, 0, 0))
                    info.create_system = 0
                    info.external_attr = 0o600 << 16
                    archive.writestr(info, value)
                    archive.fp.flush()
                    offsets.append((bundle.name, _member_offset(temporary, info)))
            size = temporary.stat().st_size
            if size > max_archive_bytes:
                raise incremental.IncrementalError("生成的增量压缩包超过上限")
            digest = incremental.digest_file(temporary)
            name = f"update-pack-{digest}.zip"
            temporary.replace(output / name)
            archives.append(Archive(name, size, digest))
            locations.extend(Location(bundle, name, offset) for bundle, offset in offsets)
        metadata = parse_manifest({
            **json.loads(json.dumps(asdict(base))), "schema": 2,
            "archives": [asdict(archive) for archive in archives],
            "locations": [asdict(location) for location in locations],
        })
        value = json.dumps(asdict(metadata), ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        if len(value.encode("utf-8")) > incremental.MAX_MANIFEST_BYTES:
            raise incremental.IncrementalError("合并增量清单超过大小限制")
        (output / MANIFEST_NAME).write_text(value, encoding="utf-8", newline="\n")
        return metadata
    except BaseException:
        shutil.rmtree(output, ignore_errors=True)
        raise


def create_assets(root: Path, package_manifest: dict, output: Path) -> Manifest:
    root, output = root.resolve(), output.resolve()
    if output == root or output.is_relative_to(root) or root.is_relative_to(output):
        raise incremental.IncrementalError("增量压缩包目录不得与程序目录重叠")
    with tempfile.TemporaryDirectory(prefix="frlg-incremental-") as temporary:
        source = Path(temporary) / "blocks"
        incremental.create_assets(root, package_manifest, source, separate_resources=True)
        return pack_assets(source, output, split_resources=True)


def verify_release_assets(package: Path, package_manifest: dict, assets: Path) -> incremental.Manifest:
    manifest_path = assets / MANIFEST_NAME
    if not manifest_path.exists():
        return incremental.verify_release_assets(package, package_manifest, assets)
    if manifest_path.stat().st_size > incremental.MAX_MANIFEST_BYTES:
        raise incremental.IncrementalError("合并增量清单超过大小限制")
    metadata = parse_manifest(json.loads(manifest_path.read_text(encoding="utf-8")))
    locations = {item.bundle: item for item in metadata.locations}
    bundles = {bundle.name: bundle for bundle in metadata.bundles}
    for archive in metadata.archives:
        path = incremental.local_file(assets, archive.name)
        if not incremental.matches(path, archive.bytes, archive.sha256, lambda: None):
            raise incremental.IncrementalError(f"增量压缩包大小或摘要不符：{archive.name}")
        expected = {item.bundle for item in metadata.locations if item.archive == archive.name}
        try:
            with zipfile.ZipFile(path) as reader:
                infos = reader.infolist()
                if len(infos) != len(expected) or {info.filename for info in infos} != expected:
                    raise incremental.IncrementalError("增量压缩包成员不符")
                for info in infos:
                    if (
                        info.compress_type != zipfile.ZIP_STORED or info.flag_bits & 9
                        or info.file_size != bundles[info.filename].bytes
                        or info.compress_size != info.file_size
                        or _member_offset(path, info) != locations[info.filename].offset
                    ):
                        raise incremental.IncrementalError("增量压缩包成员位置或格式不符")
        except zipfile.BadZipFile as exc:
            raise incremental.IncrementalError("增量压缩包不是有效 ZIP") from exc

    def read_bundle(bundle):
        location = locations[bundle.name]
        with (assets / location.archive).open("rb") as stream:
            stream.seek(location.offset)
            return stream.read(bundle.bytes)

    return incremental.verify_release_assets(
        package, package_manifest, assets, manifest=metadata, read_bundle=read_bundle,
    )
