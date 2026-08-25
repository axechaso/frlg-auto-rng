"""Download and atomically activate Ten Lines NX seed tables.

The packaged GUI uses this module directly, so updating seed tables never
depends on a separately installed Python interpreter or an external script.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import struct
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Sequence

from app_paths import DATA_ROOT, RESOURCE_ROOT


SEED_BASE_URL = "https://lincoln-lm.github.io/ten-lines/generated"
UPDATER_VERSION = "1.0.0"
FORMAT_VERSION = 1
USER_AGENT = f"frlg-auto-rng-seed-updater/{UPDATER_VERSION}"
EXPECTED_EZCON_VERSION = "1.6.4-a+9c86137c7e63bff842175470895727a5fa9bab52"
EXPECTED_EZCON_SHA256 = "559b81c234d2548c439926a88f5355ccac0958b8a191c1ecca48b2c7c71c1260"
NX_RAW_TIME_OFFSET = 5737
NX_MS_NUMERATOR = 548625
NX_MS_DENOMINATOR = 524288

FR_BINARY_NAME = "fr_eng_nx.bin"
LG_BINARY_NAME = "lg_eng_nx.bin"
FR_ECS_NAME = "02_Seed表_火红_NX.ecs"
LG_ECS_NAME = "03_Seed表_叶绿_NX.ecs"
MANIFEST_NAME = "manifest.json"
STANDARD_TEMPLATE_NAME = "NS火叶全自动一键乱数1.1.8.ecs"
EGG_TEMPLATE_NAME = "NS火叶全自动一键乱数1.1.8-TV时间轴测试.ecs"

CANONICAL_NX_ENGLISH_MODES = (
    "mono_h_a",
    "stereo_h_a",
    "mono_h_start",
    "stereo_r_a",
    "mono_h_a_blackout_r",
    "mono_h_a_blackout_l",
    "stereo_h_a_blackout_r",
    "stereo_h_a_blackout_l",
    "mono_h_start_blackout_r",
    "mono_h_start_blackout_l",
)
REQUIRED_BASE_MODES = {
    "fr": ("mono_h_a", "stereo_h_a", "mono_h_start"),
    "lg": ("mono_h_a", "stereo_h_a", "mono_h_start", "stereo_r_a"),
}

ProgressCallback = Callable[[str], None]


class SeedTableUpdateError(RuntimeError):
    """Raised when a downloaded or installed seed table is invalid."""


@dataclass(frozen=True)
class NxSeedTable:
    raw_times: tuple[int, ...]
    modes: Mapping[str, tuple[int | None, ...]]


@dataclass(frozen=True)
class SeedTableUpdateResult:
    updated: bool
    active_directory: Path
    fire_red_count: int
    leaf_green_count: int
    source_fingerprint: str
    message: str


def _notify(progress: ProgressCallback | None, message: str) -> None:
    if progress is not None:
        progress(message)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _utc_now_text() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def seed_table_store_root(data_root: str | Path = DATA_ROOT) -> Path:
    return Path(data_root) / "seed_tables"


def active_seed_table_directory(data_root: str | Path = DATA_ROOT) -> Path | None:
    current = seed_table_store_root(data_root) / "current"
    if not current.exists():
        return None
    verify_seed_table_directory(current)
    return current


def active_seed_binary_path(
    filename: str, data_root: str | Path = DATA_ROOT
) -> Path | None:
    current = active_seed_table_directory(data_root)
    if current is None:
        return None
    path = current / filename
    if not path.is_file():
        raise SeedTableUpdateError(f"已启用的 Seed 表缺少 {filename}")
    return path


def decode_nx_seed_binary(data: bytes) -> NxSeedTable:
    """Decode the official Ten Lines NX binary without discarding blank rows."""
    if len(data) < 4:
        raise SeedTableUpdateError("Ten Lines NX Seed 二进制过短")
    count = struct.unpack_from("<I", data, 0)[0]
    if count <= 0 or count > 100_000:
        raise SeedTableUpdateError(f"Ten Lines NX Seed 记录数异常：{count}")
    raw_end = 4 + count * 2
    if raw_end > len(data):
        raise SeedTableUpdateError("Ten Lines NX Seed raw time 区域不完整")
    raw_times = struct.unpack_from(f"<{count}H", data, 4)
    position = raw_end
    modes: dict[str, tuple[int | None, ...]] = {}
    while position < len(data):
        try:
            key_end = data.index(0, position)
        except ValueError as exc:
            raise SeedTableUpdateError("Ten Lines NX Seed 模式名称未终止") from exc
        try:
            key = data[position:key_end].decode("ascii")
        except UnicodeDecodeError as exc:
            raise SeedTableUpdateError("Ten Lines NX Seed 模式名称不是 ASCII") from exc
        if not key or key in modes:
            raise SeedTableUpdateError(f"Ten Lines NX Seed 模式名称无效或重复：{key!r}")
        position = key_end + 1
        if position + 4 > len(data):
            raise SeedTableUpdateError(f"Ten Lines NX Seed 模式 {key} 缺少记录数")
        entries_count = struct.unpack_from("<I", data, position)[0]
        position += 4
        if entries_count != count:
            raise SeedTableUpdateError(
                f"Ten Lines NX Seed 模式 {key} 有 {entries_count} 条，预期 {count} 条"
            )
        entries_end = position + entries_count * 3
        if entries_end > len(data):
            raise SeedTableUpdateError(f"Ten Lines NX Seed 模式 {key} 数据不完整")
        values: list[int | None] = []
        for _ in range(entries_count):
            seed = struct.unpack_from("<H", data, position)[0]
            invalid = data[position + 2]
            position += 3
            if invalid not in (0, 1):
                raise SeedTableUpdateError(
                    f"Ten Lines NX Seed 模式 {key} 含未知无效标志 {invalid}"
                )
            values.append(None if invalid else seed)
        modes[key] = tuple(values)
    if not modes:
        raise SeedTableUpdateError("Ten Lines NX Seed 二进制不含任何模式")
    return NxSeedTable(raw_times=tuple(raw_times), modes=modes)


def encode_nx_seed_binary(table: NxSeedTable) -> bytes:
    """Encode NX data in the same compact format, primarily for validation/tests."""
    count = len(table.raw_times)
    if count <= 0:
        raise SeedTableUpdateError("不能编码空的 Ten Lines NX Seed 表")
    output = bytearray(struct.pack("<I", count))
    for raw_time in table.raw_times:
        if not 0 <= raw_time <= 0xFFFF:
            raise SeedTableUpdateError(f"raw time 超出 16 位范围：{raw_time}")
        output.extend(struct.pack("<H", raw_time))
    for key, values in table.modes.items():
        if len(values) != count:
            raise SeedTableUpdateError(f"模式 {key} 长度与 raw time 不一致")
        output.extend(key.encode("ascii"))
        output.append(0)
        output.extend(struct.pack("<I", count))
        for seed in values:
            if seed is None:
                output.extend(b"\x00\x00\x01")
            elif 0 <= seed <= 0xFFFF:
                output.extend(struct.pack("<HB", seed, 0))
            else:
                raise SeedTableUpdateError(f"Seed 超出 16 位范围：{seed}")
    return bytes(output)


def _validate_base_modes(game: str, table: NxSeedTable) -> None:
    missing = [mode for mode in REQUIRED_BASE_MODES[game] if mode not in table.modes]
    if missing:
        raise SeedTableUpdateError(
            f"Ten Lines {game.upper()} NX 表缺少模式：{', '.join(missing)}"
        )


def _offset(values: Sequence[int | None], amount: int) -> tuple[int | None, ...]:
    return tuple(None if value is None else (value + amount) & 0xFFFF for value in values)


def canonical_seed_modes(table: NxSeedTable) -> tuple[tuple[int | None, ...], ...]:
    blank = tuple(None for _ in table.raw_times)
    mono_h_a = table.modes.get("mono_h_a", blank)
    stereo_h_a = table.modes.get("stereo_h_a", blank)
    mono_h_start = table.modes.get("mono_h_start", blank)
    return (
        mono_h_a,
        stereo_h_a,
        mono_h_start,
        table.modes.get("stereo_r_a", blank),
        _offset(mono_h_a, -36),
        _offset(mono_h_a, -36),
        _offset(stereo_h_a, -36),
        _offset(stereo_h_a, -36),
        _offset(mono_h_start, -36),
        _offset(mono_h_start, -36),
    )


def _format_ms(raw_time: int) -> int:
    return ((raw_time + NX_RAW_TIME_OFFSET) * NX_MS_NUMERATOR) // NX_MS_DENOMINATOR


def _add_int_lookup(
    lines: list[str], function_name: str, variable_name: str, values: Sequence[int]
) -> None:
    lines.append(f"{variable_name} = [{','.join(str(value) for value in values)}]")
    lines.append("")
    lines.append(f"FUNC {function_name}($idx: INT): INT")
    lines.append(f"    IF $idx < 0 or $idx > {len(values) - 1}")
    lines.append("        RETURN -1")
    lines.append("    ENDIF")
    lines.append(f"    RETURN {variable_name}[$idx]")
    lines.append("ENDFUNC")
    lines.append("")


def render_easycon_seed_table(
    game: str,
    table: NxSeedTable,
    *,
    source_sha256: str,
    generated_at: str,
) -> str:
    """Render the canonical EasyCon modes from one official NX binary."""
    if game not in ("fr", "lg"):
        raise ValueError(game)
    _validate_base_modes(game, table)
    game_cn = "火红" if game == "fr" else "叶绿"
    game_name = "FireRed" if game == "fr" else "LeafGreen"
    output_filename = FR_ECS_NAME if game == "fr" else LG_ECS_NAME
    modes = canonical_seed_modes(table)
    max_index = len(table.raw_times) - 1
    lines = [
        "# ==================================================",
        f"# lib/{output_filename}",
        "# 由火叶全自动乱数工具根据 Ten Lines 官方 NX 二进制表生成",
        f"# 转换时间：{generated_at}",
        f"# Ten Lines 二进制 SHA-256：{source_sha256}",
        "#",
        f"# 适用：{game_cn} / {game}_nx / NX",
        "#",
        "# Seed模式：",
    ]
    for index, mode_name in enumerate(CANONICAL_NX_ENGLISH_MODES):
        lines.append(f"#   {index} = {mode_name}")
    lines.extend(
        [
            "#",
            "# Ten Lines / NX 显示MS换算：",
            f"#   seedTime = rawTime + {NX_RAW_TIME_OFFSET}",
            f"#   MS = floor(seedTime * {NX_MS_NUMERATOR} / {NX_MS_DENOMINATOR})",
            "#   NX2 = NX - 750ms",
            "#",
            f"# 数据来源：{SEED_BASE_URL}/{game}_eng_nx.bin ({game_name})",
            "# ==================================================",
            "",
            f"FUNC 取Seed最大索引_{game_cn}(): INT",
            f"    RETURN {max_index}",
            "ENDFUNC",
            "",
        ]
    )
    _add_int_lookup(
        lines,
        f"取MS_{game_cn}",
        f"$Seed_MS_{game_cn}",
        [_format_ms(value) for value in table.raw_times],
    )
    _add_int_lookup(
        lines,
        f"取RawTime_{game_cn}",
        f"$Seed_Raw_{game_cn}",
        table.raw_times,
    )
    for mode_index, (mode_name, values) in enumerate(
        zip(CANONICAL_NX_ENGLISH_MODES, modes)
    ):
        rendered = ",".join(
            '""' if value is None else f'"{value:04X}"' for value in values
        )
        lines.append(f"# mode {mode_index} = {mode_name}")
        lines.append(f"$Seed_HEX_{game_cn}_m{mode_index} = [{rendered}]")
    lines.extend(
        [
            "",
            f"FUNC 取SeedHEX_{game_cn}($idx: INT, $mode: INT): STRING",
            f"    IF $idx < 0 or $idx > {max_index}",
            '        RETURN ""',
            "    ENDIF",
        ]
    )
    for mode_index in range(len(modes)):
        keyword = "IF" if mode_index == 0 else "ELIF"
        lines.append(f"    {keyword} $mode == {mode_index}")
        lines.append(f"        RETURN $Seed_HEX_{game_cn}_m{mode_index}[$idx]")
    lines.extend(["    ENDIF", '    RETURN ""', "ENDFUNC", ""])
    return "\n".join(lines)


def _encode_ecs(text: str) -> bytes:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return b"\xef\xbb\xbf" + normalized.replace("\n", "\r\n").encode("utf-8")


def _fetch_bytes(url: str, timeout: float = 25.0, retries: int = 3) -> bytes:
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                data = response.read()
            if not data:
                raise SeedTableUpdateError(f"下载结果为空：{url}")
            return data
        except (OSError, urllib.error.URLError, urllib.error.HTTPError) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(float(attempt))
    raise SeedTableUpdateError(f"下载 Ten Lines Seed 表失败：{url}：{last_error}")


def _write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def _manifest_for_files(
    files: Mapping[str, bytes],
    fr_table: NxSeedTable,
    lg_table: NxSeedTable,
    source_fingerprint: str,
) -> dict[str, object]:
    return {
        "format_version": FORMAT_VERSION,
        "updater_version": UPDATER_VERSION,
        "generated_at_utc": _utc_now_text(),
        "source_base_url": SEED_BASE_URL,
        "source_fingerprint": source_fingerprint,
        "files": {
            name: {"sha256": _sha256(data), "size": len(data)}
            for name, data in sorted(files.items())
        },
        "games": {
            "fr": {"record_count": len(fr_table.raw_times), "max_index": len(fr_table.raw_times) - 1},
            "lg": {"record_count": len(lg_table.raw_times), "max_index": len(lg_table.raw_times) - 1},
        },
    }


def verify_seed_table_directory(directory: str | Path) -> dict[str, object]:
    directory = Path(directory)
    manifest_path = directory / MANIFEST_NAME
    if not manifest_path.is_file():
        raise SeedTableUpdateError(f"Seed 表目录缺少 {MANIFEST_NAME}：{directory}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SeedTableUpdateError(f"Seed 表清单无法读取：{exc}") from exc
    if manifest.get("format_version") != FORMAT_VERSION:
        raise SeedTableUpdateError("Seed 表清单格式版本不受支持")
    file_manifest = manifest.get("files")
    if not isinstance(file_manifest, dict):
        raise SeedTableUpdateError("Seed 表清单缺少文件指纹")
    expected = (FR_BINARY_NAME, LG_BINARY_NAME, FR_ECS_NAME, LG_ECS_NAME)
    for filename in expected:
        metadata = file_manifest.get(filename)
        path = directory / filename
        if not isinstance(metadata, dict) or not path.is_file():
            raise SeedTableUpdateError(f"Seed 表清单或目录缺少 {filename}")
        data = path.read_bytes()
        if metadata.get("sha256") != _sha256(data) or metadata.get("size") != len(data):
            raise SeedTableUpdateError(f"Seed 表文件校验失败：{filename}")
    fr_table = decode_nx_seed_binary((directory / FR_BINARY_NAME).read_bytes())
    lg_table = decode_nx_seed_binary((directory / LG_BINARY_NAME).read_bytes())
    _validate_base_modes("fr", fr_table)
    _validate_base_modes("lg", lg_table)
    games = manifest.get("games")
    if not isinstance(games, dict):
        raise SeedTableUpdateError("Seed 表清单缺少游戏记录数")
    fr_game = games.get("fr")
    lg_game = games.get("lg")
    if not isinstance(fr_game, dict) or not isinstance(lg_game, dict):
        raise SeedTableUpdateError("Seed 表清单游戏记录格式无效")
    if fr_game.get("record_count") != len(fr_table.raw_times):
        raise SeedTableUpdateError("火红 Seed 表记录数与清单不一致")
    if lg_game.get("record_count") != len(lg_table.raw_times):
        raise SeedTableUpdateError("叶绿 Seed 表记录数与清单不一致")
    return manifest


def apply_easycon_seed_table_overrides(
    lib_directory: str | Path, data_root: str | Path = DATA_ROOT
) -> dict[str, object] | None:
    """Overlay both validated ECS tables onto a generated 1.1.8 project."""
    active = active_seed_table_directory(data_root)
    if active is None:
        return None
    lib_directory = Path(lib_directory)
    if not lib_directory.is_dir():
        raise SeedTableUpdateError(f"EasyCon 工程缺少 lib 目录：{lib_directory}")
    for filename in (FR_ECS_NAME, LG_ECS_NAME):
        shutil.copy2(active / filename, lib_directory / filename)
    manifest = verify_seed_table_directory(active)
    return {
        "directory": str(active),
        "source_fingerprint": manifest["source_fingerprint"],
        "files": {
            filename: manifest["files"][filename]
            for filename in (FR_ECS_NAME, LG_ECS_NAME)
        },
    }


def _validate_easycon_candidate(
    candidate: Path,
    source_directory: Path,
    ezcon_path: Path,
    progress: ProgressCallback | None,
) -> None:
    if not ezcon_path.is_file():
        raise FileNotFoundError(f"找不到 ezcon.exe：{ezcon_path}")
    actual_sha256 = _sha256(ezcon_path.read_bytes())
    if actual_sha256 != EXPECTED_EZCON_SHA256:
        raise SeedTableUpdateError(
            "Seed 表校验只允许已审计的 EasyCon 1.6.4-a；ezcon.exe 指纹为 "
            + actual_sha256
        )
    try:
        version = subprocess.run(
            [str(ezcon_path), "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise SeedTableUpdateError(f"无法读取 EasyCon 版本：{exc}") from exc
    version_text = (version.stdout + "\n" + version.stderr).strip()
    version_line = version_text.splitlines()[-1] if version_text else ""
    if version.returncode != 0 or version_line != EXPECTED_EZCON_VERSION:
        raise SeedTableUpdateError(
            f"Seed 表校验要求 EasyCon {EXPECTED_EZCON_VERSION}，检测到 {version_line or '无输出'}"
        )
    if not source_directory.is_dir():
        raise FileNotFoundError(f"找不到 1.1.8 包：{source_directory}")
    lib_source = source_directory / "lib"
    label_source = source_directory / "ImgLabel"
    if not lib_source.is_dir():
        raise FileNotFoundError(f"1.1.8 包缺少 lib：{lib_source}")
    if not label_source.is_dir():
        raise FileNotFoundError(f"1.1.8 包缺少 ImgLabel：{label_source}")
    validation_root = candidate.parent / f".validation-{uuid.uuid4().hex}"
    try:
        for label, template_name in (
            ("正式脚本", STANDARD_TEMPLATE_NAME),
            ("孵蛋时间轴脚本", EGG_TEMPLATE_NAME),
        ):
            template = source_directory / template_name
            if not template.is_file():
                raise FileNotFoundError(f"1.1.8 包缺少 {template_name}")
            project = validation_root / ("standard" if label == "正式脚本" else "egg")
            project.mkdir(parents=True, exist_ok=True)
            shutil.copy2(template, project / "main.ecs")
            shutil.copytree(lib_source, project / "lib")
            shutil.copytree(label_source, project / "ImgLabel")
            for filename in (FR_ECS_NAME, LG_ECS_NAME):
                shutil.copy2(candidate / filename, project / "lib" / filename)
            _notify(progress, f"使用 EasyCon 1.6.4-a format 校验{label}……")
            try:
                checked = subprocess.run(
                    [str(ezcon_path), "format", str(project / "main.ecs")],
                    cwd=str(project),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=90,
                )
            except (OSError, subprocess.SubprocessError) as exc:
                raise SeedTableUpdateError(f"EasyCon format 无法执行：{exc}") from exc
            if checked.returncode != 0:
                detail = (checked.stderr or checked.stdout).strip()
                raise SeedTableUpdateError(
                    f"{label}未通过 EasyCon 1.6.4-a format：{detail[-1500:]}"
                )
    finally:
        if validation_root.exists():
            shutil.rmtree(validation_root, ignore_errors=True)


def _activate_candidate(candidate: Path, store_root: Path) -> Path:
    current = store_root / "current"
    previous = store_root / "previous"
    if previous.exists():
        shutil.rmtree(previous)
    moved_current = False
    try:
        if current.exists():
            current.replace(previous)
            moved_current = True
        candidate.replace(current)
    except Exception:
        if not current.exists() and moved_current and previous.exists():
            previous.replace(current)
        raise
    return current


def update_seed_tables(
    *,
    source_directory: str | Path,
    ezcon_path: str | Path,
    data_root: str | Path = DATA_ROOT,
    progress: ProgressCallback | None = None,
    timeout: float = 25.0,
) -> SeedTableUpdateResult:
    """Check official binaries, validate both ECS entries, then activate together."""
    store_root = seed_table_store_root(data_root)
    store_root.mkdir(parents=True, exist_ok=True)
    _notify(progress, "正在下载 Ten Lines 官方火红 NX Seed 表……")
    fr_data = _fetch_bytes(f"{SEED_BASE_URL}/{FR_BINARY_NAME}", timeout=timeout)
    _notify(progress, "正在下载 Ten Lines 官方叶绿 NX Seed 表……")
    lg_data = _fetch_bytes(f"{SEED_BASE_URL}/{LG_BINARY_NAME}", timeout=timeout)
    fr_table = decode_nx_seed_binary(fr_data)
    lg_table = decode_nx_seed_binary(lg_data)
    _validate_base_modes("fr", fr_table)
    _validate_base_modes("lg", lg_table)
    fingerprint = _sha256(fr_data + b"\0" + lg_data)
    current = store_root / "current"
    if current.exists():
        try:
            manifest = verify_seed_table_directory(current)
        except SeedTableUpdateError as exc:
            _notify(progress, f"现有更新表校验失败，将用官方数据重建：{exc}")
        else:
            if (
                manifest.get("source_fingerprint") == fingerprint
                and manifest.get("updater_version") == UPDATER_VERSION
            ):
                message = (
                    f"Seed 表已经是最新：火红 {len(fr_table.raw_times)} 条，"
                    f"叶绿 {len(lg_table.raw_times)} 条。"
                )
                _notify(progress, message)
                return SeedTableUpdateResult(
                    False,
                    current,
                    len(fr_table.raw_times),
                    len(lg_table.raw_times),
                    fingerprint,
                    message,
                )
    generated_at = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %z")
    _notify(progress, "正在从同一份官方数据生成 EasyCon 火红/叶绿表……")
    files = {
        FR_BINARY_NAME: fr_data,
        LG_BINARY_NAME: lg_data,
        FR_ECS_NAME: _encode_ecs(
            render_easycon_seed_table(
                "fr", fr_table, source_sha256=_sha256(fr_data), generated_at=generated_at
            )
        ),
        LG_ECS_NAME: _encode_ecs(
            render_easycon_seed_table(
                "lg", lg_table, source_sha256=_sha256(lg_data), generated_at=generated_at
            )
        ),
    }
    candidate = store_root / f".staging-{uuid.uuid4().hex}"
    candidate.mkdir(parents=False, exist_ok=False)
    try:
        for filename, data in files.items():
            _write_bytes(candidate / filename, data)
        manifest = _manifest_for_files(files, fr_table, lg_table, fingerprint)
        _write_bytes(
            candidate / MANIFEST_NAME,
            (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
                "utf-8"
            ),
        )
        verify_seed_table_directory(candidate)
        _validate_easycon_candidate(
            candidate,
            Path(source_directory).resolve(),
            Path(ezcon_path).resolve(),
            progress,
        )
        _notify(progress, "两份主脚本校验通过，正在同时切换新 Seed 表……")
        active = _activate_candidate(candidate, store_root)
    except Exception:
        if candidate.exists():
            shutil.rmtree(candidate, ignore_errors=True)
        raise
    message = (
        f"Seed 表更新完成：火红 {len(fr_table.raw_times)} 条，"
        f"叶绿 {len(lg_table.raw_times)} 条；新生成方案会自动使用。"
    )
    _notify(progress, message)
    return SeedTableUpdateResult(
        True,
        active,
        len(fr_table.raw_times),
        len(lg_table.raw_times),
        fingerprint,
        message,
    )


def bundled_seed_binary_path(filename: str) -> Path:
    return RESOURCE_ROOT / "rng" / "resources" / filename
