"""Persistent, context-scoped pre-calibration values for 2.0 runs.

The ECS scripts emit a small ASCII marker after an exact target hit or a
confirmed configured-target shiny, to save the offsets used by that round.
This module owns the durable side of that handshake.  TID/SID code does not
import it, so identity calibration remains independent from 2.0 values.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import uuid
from typing import Any, Mapping

from app_paths import USER_DATA_ROOT


SCHEMA_VERSION = 2
LEGACY_SCHEMA_VERSION = 1
MARKER_PREFIX = "PRECALIBRATION_UPDATE"
DEFAULT_STORE_PATH = USER_DATA_ROOT / "precalibration.json"
_ANSI_RE = re.compile(r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
_MARKER_RE = re.compile(
    rf"(?m){re.escape(MARKER_PREFIX)}\|[^\r\n]+"
)
_INT_FIELDS = {
    "V",
    "NX",
    "MODE",
    "STARTUP",
    "SEED_INDEX",
    "FRAME_PRE",
    "FRAME_ENABLED",
    "HELD_PRE",
    "PICKUP_PRE",
    "PARITY",
    "GIFT",
    "TARGET_DEX",
    "ROUND",
    "SHINY_STAGE",
    "SHINY_END",
}
_SEED_FIELDS = {"seed_ns1", "seed_ns2"}
_FRAME_FIELDS = {
    "frame_ns1",
    "frame_ns2",
    "held_pre",
    "pickup_pre",
}
_RECORD_FIELDS = _SEED_FIELDS | _FRAME_FIELDS


@dataclass(frozen=True)
class PrecalibrationFrameScope:
    effective_parity_scheme: int
    mystery_gift_enabled: bool

    def __post_init__(self) -> None:
        if type(self.effective_parity_scheme) is not int or self.effective_parity_scheme not in (0, 1):
            raise ValueError("预校准帧作用域奇偶方案必须是0或1")
        if type(self.mystery_gift_enabled) is not bool:
            raise ValueError("预校准帧作用域神秘礼物状态必须是布尔值")

    def to_dict(self) -> dict[str, Any]:
        return {
            "effective_parity_scheme": self.effective_parity_scheme,
            "mystery_gift_enabled": self.mystery_gift_enabled,
        }


def normalize_frame_scope(
    value: PrecalibrationFrameScope | Mapping[str, object],
) -> PrecalibrationFrameScope:
    if isinstance(value, PrecalibrationFrameScope):
        return value
    if not isinstance(value, Mapping):
        raise ValueError("预校准帧作用域必须是对象")
    try:
        return PrecalibrationFrameScope(
            effective_parity_scheme=value["effective_parity_scheme"],
            mystery_gift_enabled=value["mystery_gift_enabled"],
        )
    except KeyError as exc:
        raise ValueError(f"预校准帧作用域缺少字段: {exc.args[0]}") from exc


def frame_scope_key(value: PrecalibrationFrameScope | Mapping[str, object]) -> str:
    scope = normalize_frame_scope(value)
    return (
        f"parity={scope.effective_parity_scheme};"
        f"gift={int(scope.mystery_gift_enabled)}"
    )


@dataclass(frozen=True)
class PrecalibrationContext:
    """The dimensions that must match before a value can be reused."""

    game: str
    nx_model: int
    seed_mode: int
    entry: str
    kind: str
    # Seed startup paths have different menu/input timing and therefore must
    # never share a learned Seed offset.  Keep the default for old positional
    # callers and legacy records; new context keys always include it.
    seed_startup_scheme: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "game", normalize_game(self.game))
        try:
            nx_model = int(self.nx_model)
            seed_mode = int(self.seed_mode)
            seed_startup_scheme = int(self.seed_startup_scheme)
        except (TypeError, ValueError) as exc:
            raise ValueError("预校准上下文的NX机型、Seed模式和启动方案必须是整数") from exc
        if nx_model not in (1, 2):
            raise ValueError("预校准上下文的NX机型必须是1或2")
        if not 0 <= seed_mode <= 10:
            raise ValueError("预校准上下文的Seed模式必须在0-10之间")
        if seed_startup_scheme not in (0, 1):
            raise ValueError("预校准上下文的Seed启动方案必须是0或1")
        object.__setattr__(self, "nx_model", nx_model)
        object.__setattr__(self, "seed_mode", seed_mode)
        object.__setattr__(self, "seed_startup_scheme", seed_startup_scheme)
        object.__setattr__(self, "entry", normalize_entry(self.entry))
        object.__setattr__(self, "kind", normalize_kind(self.kind))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_game(value: object) -> str:
    text = str(value).strip().lower()
    if text in {"fr", "火红", "firered", "fire red", "fire_red"} or text.startswith("fr_"):
        return "fr"
    if text in {"lg", "叶绿", "leafgreen", "leaf green", "leaf_green"} or text.startswith("lg_"):
        return "lg"
    raise ValueError(f"预校准上下文的游戏无效: {value!r}")


def normalize_entry(value: object) -> str:
    text = str(value).strip().upper()
    if text in {"FORMAL", "正式", "正式版", "WAIT"}:
        return "FORMAL"
    if text in {"TIMELINE", "时间轴", "时间轴版", "TV"}:
        return "TIMELINE"
    raise ValueError(f"预校准上下文的脚本入口无效: {value!r}")


def normalize_kind(value: object) -> str:
    text = str(value).strip().upper()
    aliases = {
        "STATIC": "STATIC",
        "定点": "STATIC",
        "WILD": "WILD",
        "野生": "WILD",
        "EGG": "EGG",
        "孵蛋": "EGG",
        "STARTER": "STARTER",
        "御三家": "STARTER",
    }
    try:
        return aliases[text]
    except KeyError as exc:
        raise ValueError(f"预校准上下文的流程类型无效: {value!r}") from exc


def normalize_context(value: PrecalibrationContext | Mapping[str, object]) -> PrecalibrationContext:
    if isinstance(value, PrecalibrationContext):
        return value
    if not isinstance(value, Mapping):
        raise ValueError("预校准上下文必须是对象")
    try:
        return PrecalibrationContext(
            game=value["game"],
            nx_model=value["nx_model"],
            seed_mode=value["seed_mode"],
            entry=value["entry"],
            kind=value["kind"],
            # Records written before startup-path separation are treated as
            # the original HOME_BUFFER path only.  They are never used by
            # scheme 1 because that key contains STARTUP=1.
            seed_startup_scheme=value.get("seed_startup_scheme", 0),
        )
    except KeyError as exc:
        raise ValueError(f"预校准上下文缺少字段: {exc.args[0]}") from exc


def context_key(context: PrecalibrationContext | Mapping[str, object]) -> str:
    normalized = normalize_context(context)
    payload = json.dumps(
        normalized.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _legacy_context_key(context: PrecalibrationContext) -> str:
    """Return the pre-startup-separation key used by the first store format."""
    payload = context.to_dict()
    payload.pop("seed_startup_scheme", None)
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _empty_store() -> dict[str, Any]:
    return {"schema": SCHEMA_VERSION, "records": {}}


def _normalize_storage_record(record: Mapping[str, Any], schema: int) -> dict[str, Any]:
    if not isinstance(record, Mapping):
        raise ValueError("预校准记录不是对象，原文件保留")
    if schema == LEGACY_SCHEMA_VERSION:
        legacy_frames = {
            name: record[name] for name in _FRAME_FIELDS if name in record
        }
        frames = {}
    else:
        frames = record.get("frames", {})
        legacy_frames = record.get("legacy_frames", {})
        if not isinstance(frames, dict) or not isinstance(legacy_frames, dict):
            raise ValueError("预校准记录帧作用域格式无效，原文件保留")
    normalized = {
        "context": record.get("context"),
        **{name: record.get(name) for name in _SEED_FIELDS},
        "frames": frames,
        "legacy_frames": legacy_frames,
    }
    if "updated_at" in record:
        normalized["updated_at"] = record["updated_at"]
    return normalized


def load_store(path: str | Path) -> dict[str, Any]:
    """Load schema 1/2 without rewriting the user's file."""
    path = Path(path)
    if not path.is_file():
        return _empty_store()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"预校准记录读取失败，原文件保留: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema") not in {
        LEGACY_SCHEMA_VERSION, SCHEMA_VERSION,
    }:
        raise ValueError("预校准记录格式或版本不支持，原文件保留")
    records = payload.get("records")
    if not isinstance(records, dict):
        raise ValueError("预校准记录缺少records对象，原文件保留")
    schema = payload["schema"]
    normalized_records = {}
    try:
        for key, record in records.items():
            normalized = _normalize_storage_record(record, schema)
            record_context = normalize_context(normalized["context"])
            normalized_records[str(key)] = _validate_storage_record(
                normalized, record_context,
            )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"预校准记录格式无效，原文件保留: {exc}") from exc
    return {"schema": SCHEMA_VERSION, "records": normalized_records}


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _validate_storage_record(
    record: Mapping[str, Any], context: PrecalibrationContext,
) -> dict[str, Any]:
    if not isinstance(record, Mapping):
        raise ValueError("预校准记录与当前上下文不一致")
    raw_context = record.get("context")
    try:
        record_context = normalize_context(raw_context)
    except (TypeError, ValueError):
        record_context = None
    if record_context is None or record_context.to_dict() != context.to_dict():
        raise ValueError("预校准记录与当前上下文不一致")
    result: dict[str, Any] = {
        "context": context.to_dict(),
        **{name: None for name in _SEED_FIELDS},
        "frames": {},
        "legacy_frames": {},
    }
    for name in _SEED_FIELDS:
        value = record.get(name)
        if value is None:
            continue
        if type(value) is not int:
            raise ValueError(f"预校准记录字段{name}必须是整数")
        _validate_value(name, value)
        result[name] = value
    frames = record.get("frames", {})
    if not isinstance(frames, Mapping):
        raise ValueError("预校准帧作用域必须是对象")
    for scope_key, scoped_values in frames.items():
        if not isinstance(scope_key, str) or not isinstance(scoped_values, Mapping):
            raise ValueError("预校准帧作用域记录格式无效")
        for name, value in scoped_values.items():
            if name not in _FRAME_FIELDS:
                raise ValueError(f"预校准帧作用域包含未知字段{name}")
            if value is not None:
                _validate_value(name, value)
        result["frames"][scope_key] = {
            name: value for name, value in scoped_values.items()
        }
    legacy_frames = record.get("legacy_frames", {})
    if not isinstance(legacy_frames, Mapping):
        raise ValueError("预校准历史帧字段必须是对象")
    for name, value in legacy_frames.items():
        if name not in _FRAME_FIELDS:
            raise ValueError(f"预校准历史帧字段包含未知字段{name}")
        if value is not None:
            _validate_value(name, value)
        result["legacy_frames"][name] = value
    if "updated_at" in record and not isinstance(record["updated_at"], str):
        raise ValueError("预校准记录更新时间格式无效")
    if isinstance(record.get("updated_at"), str):
        result["updated_at"] = record["updated_at"]
    return result


def _validate_record(
    record: Mapping[str, Any],
    context: PrecalibrationContext,
    frame_scope: PrecalibrationFrameScope | Mapping[str, object] | None = None,
) -> dict[str, Any]:
    stored = _validate_storage_record(record, context)
    result = {
        "context": context.to_dict(),
        **{name: stored.get(name) for name in _SEED_FIELDS},
        **{name: None for name in _FRAME_FIELDS},
        "legacy_frames": dict(stored["legacy_frames"]),
    }
    if frame_scope is not None:
        scope_values = stored["frames"].get(frame_scope_key(frame_scope), {})
        for name in _FRAME_FIELDS:
            value = scope_values.get(name)
            if value is not None:
                result[name] = value
    if "updated_at" in stored:
        result["updated_at"] = stored["updated_at"]
    return result


def _validate_value(name: str, value: object) -> None:
    if type(value) is not int:
        raise ValueError(f"预校准值{name}必须是整数")
    if name.startswith("seed_") and not -10000 <= value <= 10000:
        raise ValueError(f"预校准值{name}超出允许范围")
    if name.startswith("frame_") and not -1_000_000 <= value <= 1_000_000:
        raise ValueError(f"预校准值{name}超出允许范围")
    if name in {"held_pre", "pickup_pre"} and not -1_000_000 <= value <= 1_000_000:
        raise ValueError(f"预校准值{name}超出允许范围")


def read_record(
    path: str | Path,
    context: PrecalibrationContext | Mapping[str, object],
    *,
    frame_scope: PrecalibrationFrameScope | Mapping[str, object] | None = None,
) -> dict[str, Any] | None:
    normalized = normalize_context(context)
    payload = load_store(path)
    raw = payload["records"].get(context_key(normalized))
    if raw is None and normalized.seed_startup_scheme == 0:
        # A record written before STARTUP existed is safe to interpret only as
        # scheme 0.  Scheme 1 deliberately never consults this fallback.
        raw = payload["records"].get(_legacy_context_key(normalized))
    if raw is None:
        return None
    return _validate_record(raw, normalized, frame_scope)


def update_record(
    path: str | Path,
    context: PrecalibrationContext | Mapping[str, object],
    updates: Mapping[str, object],
    *,
    frame_scope: PrecalibrationFrameScope | Mapping[str, object] | None = None,
) -> dict[str, Any]:
    """Merge Seed values and one explicitly scoped frame record."""
    normalized = normalize_context(context)
    unknown = set(updates) - _RECORD_FIELDS
    if unknown:
        raise ValueError("预校准更新包含未知字段: " + ", ".join(sorted(unknown)))
    frame_updates = set(updates) & _FRAME_FIELDS
    if frame_updates and frame_scope is None:
        raise ValueError("写入预校准帧值必须明确提供奇偶/礼物作用域")
    normalized_scope = normalize_frame_scope(frame_scope) if frame_scope is not None else None
    path = Path(path)
    legacy_schema = False
    if path.is_file():
        try:
            raw_payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"预校准记录读取失败，原文件保留: {exc}") from exc
        legacy_schema = (
            isinstance(raw_payload, dict)
            and raw_payload.get("schema") == LEGACY_SCHEMA_VERSION
        )
    payload = load_store(path)
    key = context_key(normalized)
    old = payload["records"].get(key)
    legacy_key = None
    if old is None and normalized.seed_startup_scheme == 0:
        legacy_key = _legacy_context_key(normalized)
        old = payload["records"].get(legacy_key)
    record = _validate_storage_record(old, normalized) if old is not None else {
        "context": normalized.to_dict(),
        **{name: None for name in _SEED_FIELDS},
        "frames": {},
        "legacy_frames": {},
    }
    for name in _SEED_FIELDS:
        value = updates.get(name)
        if value is None:
            continue
        _validate_value(name, value)
        record[name] = int(value)
    if frame_updates:
        scope_key = frame_scope_key(normalized_scope)
        scoped = record["frames"].setdefault(scope_key, {})
        for name in frame_updates:
            value = updates[name]
            if value is None:
                continue
            _validate_value(name, value)
            scoped[name] = int(value)
    record["updated_at"] = datetime.now(timezone.utc).isoformat()
    payload["records"][key] = record
    if legacy_key is not None and legacy_key != key:
        payload["records"].pop(legacy_key, None)
    if legacy_schema:
        _backup_legacy_store(path)
    _write_json_atomic(path, payload)
    return _validate_record(record, normalized, normalized_scope)


def _backup_legacy_store(path: Path) -> Path:
    """Save the exact schema 1 bytes under a unique, non-overwriting name."""
    raw = path.read_bytes()
    backup = path.with_name(f"{path.name}.schema1-{uuid.uuid4().hex}.bak")
    with backup.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return backup


def parse_marker(text: str) -> dict[str, Any] | None:
    """Parse the first complete marker from an EasyCon log."""
    if not isinstance(text, str):
        return None
    clean = _ANSI_RE.sub("", text)
    match = _MARKER_RE.search(clean)
    if match is None:
        return None
    parts = match.group(0).split("|")
    if not parts or parts[0] != MARKER_PREFIX:
        return None
    marker: dict[str, Any] = {}
    for part in parts[1:]:
        if "=" not in part:
            return None
        key, value = part.split("=", 1)
        if not key or key in marker:
            return None
        if key in _INT_FIELDS:
            try:
                marker[key] = int(value)
            except ValueError:
                return None
        else:
            marker[key] = value.strip()
    if marker.get("V") not in {LEGACY_SCHEMA_VERSION, SCHEMA_VERSION}:
        return None
    required = {"GAME", "NX", "MODE", "ENTRY", "KIND", "SEED_INDEX", "FRAME_ENABLED"}
    if not required.issubset(marker):
        return None
    if marker["NX"] not in (1, 2) or not 0 <= marker["MODE"] <= 10:
        return None
    # STARTUP was added after the first marker format.  Missing means the
    # original HOME_BUFFER path for backward compatibility; an explicit value
    # is mandatory for the newly selectable fixed-user-HOME path.
    if "STARTUP" not in marker:
        marker["STARTUP"] = 0
    if marker["STARTUP"] not in (0, 1):
        return None
    if marker["FRAME_ENABLED"] not in (0, 1):
        return None
    if marker["V"] == SCHEMA_VERSION:
        if marker.get("PARITY") not in (0, 1) or marker.get("GIFT") not in (0, 1):
            return None
    if marker.get("KIND") == "EGG":
        if "HELD_PRE" not in marker or "PICKUP_PRE" not in marker:
            return None
    elif "FRAME_PRE" not in marker:
        return None
    if "EVIDENCE" in marker:
        if (
            marker["EVIDENCE"] != "TARGET_SHINY"
            or marker["V"] != SCHEMA_VERSION
            or marker["KIND"] not in {"WILD", "STATIC"}
            or not 1 <= marker.get("TARGET_DEX", 0) <= 386
            or marker.get("ROUND", 0) <= 0
            or marker.get("SHINY_STAGE") not in (0, 1)
            or marker.get("SHINY_END") != 1
        ):
            return None
    return marker


def marker_matches_context(
    marker: Mapping[str, Any],
    context: PrecalibrationContext | Mapping[str, object],
) -> bool:
    normalized = normalize_context(context)
    try:
        game = normalize_game(marker["GAME"])
        entry = normalize_entry(marker["ENTRY"])
        kind = normalize_kind(marker["KIND"])
        return (
            marker.get("V") in {LEGACY_SCHEMA_VERSION, SCHEMA_VERSION}
            and game == normalized.game
            and int(marker["NX"]) == normalized.nx_model
            and int(marker["MODE"]) == normalized.seed_mode
            and int(marker.get("STARTUP", 0)) == normalized.seed_startup_scheme
            and entry == normalized.entry
            and kind == normalized.kind
        )
    except (KeyError, TypeError, ValueError):
        return False


def marker_updates(
    marker: Mapping[str, Any],
    context: PrecalibrationContext | Mapping[str, object],
) -> dict[str, int] | None:
    """Return only the durable fields when a marker fully matches context."""
    normalized = normalize_context(context)
    if not marker_matches_context(marker, normalized):
        return None
    try:
        seed_index = int(marker["SEED_INDEX"])
        seed_field = "seed_ns1" if normalized.nx_model == 1 else "seed_ns2"
        _validate_value(seed_field, seed_index)
        if marker["KIND"] == "EGG":
            held = int(marker["HELD_PRE"])
            pickup = int(marker["PICKUP_PRE"])
            _validate_value("held_pre", held)
            _validate_value("pickup_pre", pickup)
            if marker.get("V") == LEGACY_SCHEMA_VERSION:
                return {seed_field: seed_index}
            return {seed_field: seed_index, "held_pre": held, "pickup_pre": pickup}
        frame = int(marker["FRAME_PRE"])
        frame_field = "frame_ns1" if normalized.nx_model == 1 else "frame_ns2"
        _validate_value(frame_field, frame)
        if marker.get("V") == LEGACY_SCHEMA_VERSION or int(marker["FRAME_ENABLED"]) == 0:
            return {seed_field: seed_index}
        return {seed_field: seed_index, frame_field: frame}
    except (KeyError, TypeError, ValueError):
        return None


def update_from_log(
    path: str | Path,
    context: PrecalibrationContext | Mapping[str, object],
    text: str,
) -> dict[str, Any] | None:
    """Persist one complete, context-matched EasyCon success marker."""
    if MARKER_PREFIX not in text:
        return None
    marker = parse_marker(text)
    if marker is None:
        raise ValueError("预校准成功标记不完整或格式无效，未更新记录")
    updates = marker_updates(marker, context)
    if updates is None:
        raise ValueError("预校准成功标记与本次生成上下文不一致，未更新记录")
    frame_scope = None
    if marker.get("V") == SCHEMA_VERSION:
        frame_scope = PrecalibrationFrameScope(
            effective_parity_scheme=marker["PARITY"],
            mystery_gift_enabled=bool(marker["GIFT"]),
        )
    return update_record(path, context, updates, frame_scope=frame_scope)


def update_from_manifest(
    path: str | Path,
    manifest_path: str | Path,
    text: str,
) -> dict[str, Any] | None:
    """Load an immutable generated-project context and persist its marker."""
    manifest_path = Path(manifest_path)
    if not manifest_path.is_file():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"预校准生成清单读取失败，未更新记录: {exc}") from exc
    if not isinstance(manifest, dict):
        raise ValueError("预校准生成清单格式无效，未更新记录")
    config = manifest.get("precalibration")
    if not isinstance(config, dict) or config.get("enabled") is not True:
        return None
    if "context" not in config:
        raise ValueError("预校准生成清单缺少上下文，未更新记录")
    # Old projects and non-success stops may have no marker. That is a no-op,
    # not a malformed marker; present but invalid markers still reject writes.
    if MARKER_PREFIX not in text:
        return None
    marker = parse_marker(text)
    if marker is None:
        raise ValueError("预校准成功标记不完整或格式无效，未更新记录")
    if marker.get("EVIDENCE") == "TARGET_SHINY":
        shiny_success = config.get("target_shiny_success")
        if (
            not isinstance(shiny_success, dict)
            or shiny_success.get("enabled") is not True
            or type(shiny_success.get("species_id")) is not int
            or shiny_success["species_id"] != marker["TARGET_DEX"]
            or type(config.get("frame_enabled")) is not bool
            or int(config["frame_enabled"]) != marker["FRAME_ENABLED"]
        ):
            raise ValueError("目标出闪预校准标记与本次配置目标或保存范围不一致，未更新记录")
    if marker.get("V") == SCHEMA_VERSION:
        expected_scope = config.get("frame_scope")
        if expected_scope is None or normalize_frame_scope(expected_scope).to_dict() != PrecalibrationFrameScope(
            marker["PARITY"], bool(marker["GIFT"]),
        ).to_dict():
            raise ValueError("预校准成功标记的帧作用域与生成清单不一致，未更新记录")
    elif config.get("frame_scope") is not None:
        # A V1 manifest/marker pair may still contribute its independently
        # validated Seed index, but never a frame value in the new schema.
        pass
    return update_from_log(path, config["context"], text)


def build_marker(
    context: PrecalibrationContext | Mapping[str, object],
    *,
    seed_index: int,
    frame_enabled: bool,
    frame_scope: PrecalibrationFrameScope | Mapping[str, object] | None = None,
    frame_pre: int = 0,
    held_pre: int | None = None,
    pickup_pre: int | None = None,
) -> str:
    """Build the ASCII marker used by tests and diagnostic tooling."""
    normalized = normalize_context(context)
    scope = normalize_frame_scope(frame_scope) if frame_scope is not None else None
    fields = [
        MARKER_PREFIX,
        f"V={SCHEMA_VERSION if scope is not None else LEGACY_SCHEMA_VERSION}",
        f"GAME={normalized.game.upper()}",
        f"NX={normalized.nx_model}",
        f"MODE={normalized.seed_mode}",
        f"STARTUP={normalized.seed_startup_scheme}",
        f"ENTRY={normalized.entry}",
        f"KIND={normalized.kind}",
        f"SEED_INDEX={int(seed_index)}",
        f"FRAME_PRE={int(frame_pre)}",
        f"FRAME_ENABLED={1 if frame_enabled else 0}",
    ]
    if scope is not None:
        fields.extend((
            f"PARITY={scope.effective_parity_scheme}",
            f"GIFT={int(scope.mystery_gift_enabled)}",
        ))
    if normalized.kind == "EGG":
        if held_pre is None or pickup_pre is None:
            raise ValueError("孵蛋预校准marker必须包含Held和Pickup")
        fields.extend((f"HELD_PRE={int(held_pre)}", f"PICKUP_PRE={int(pickup_pre)}"))
    return "|".join(fields)


__all__ = [
    "DEFAULT_STORE_PATH",
    "MARKER_PREFIX",
    "PrecalibrationContext",
    "PrecalibrationFrameScope",
    "build_marker",
    "context_key",
    "frame_scope_key",
    "load_store",
    "marker_matches_context",
    "marker_updates",
    "normalize_context",
    "normalize_frame_scope",
    "parse_marker",
    "read_record",
    "update_record",
    "update_from_log",
    "update_from_manifest",
]
