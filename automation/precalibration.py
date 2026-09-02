"""Persistent, context-scoped pre-calibration values for 1.1.8 runs.

The ECS scripts only emit a small, ASCII marker after a complete target hit.
This module owns the durable side of that handshake.  TID/SID code does not
import it, so identity calibration remains independent from 1.1.8 values.
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


SCHEMA_VERSION = 1
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
}
_RECORD_FIELDS = {
    "seed_ns1",
    "seed_ns2",
    "frame_ns1",
    "frame_ns2",
    "held_pre",
    "pickup_pre",
}


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


def load_store(path: str | Path) -> dict[str, Any]:
    """Load a store without ever replacing a malformed existing file."""
    path = Path(path)
    if not path.is_file():
        return _empty_store()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"预校准记录读取失败，原文件保留: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA_VERSION:
        raise ValueError("预校准记录格式或版本不支持，原文件保留")
    records = payload.get("records")
    if not isinstance(records, dict):
        raise ValueError("预校准记录缺少records对象，原文件保留")
    return {"schema": SCHEMA_VERSION, "records": records}


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


def _validate_record(record: Mapping[str, Any], context: PrecalibrationContext) -> dict[str, Any]:
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
        "seed_ns1": None,
        "seed_ns2": None,
        "frame_ns1": None,
        "frame_ns2": None,
        "held_pre": None,
        "pickup_pre": None,
    }
    for name in _RECORD_FIELDS:
        value = record.get(name)
        if value is None:
            continue
        if type(value) is not int:
            raise ValueError(f"预校准记录字段{name}必须是整数")
        _validate_value(name, value)
        result[name] = value
    if "updated_at" in record and not isinstance(record["updated_at"], str):
        raise ValueError("预校准记录更新时间格式无效")
    if isinstance(record.get("updated_at"), str):
        result["updated_at"] = record["updated_at"]
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
    return _validate_record(raw, normalized)


def update_record(
    path: str | Path,
    context: PrecalibrationContext | Mapping[str, object],
    updates: Mapping[str, object],
) -> dict[str, Any]:
    """Merge validated values and atomically persist the context record."""
    normalized = normalize_context(context)
    unknown = set(updates) - _RECORD_FIELDS
    if unknown:
        raise ValueError("预校准更新包含未知字段: " + ", ".join(sorted(unknown)))
    payload = load_store(path)
    key = context_key(normalized)
    old = payload["records"].get(key)
    legacy_key = None
    if old is None and normalized.seed_startup_scheme == 0:
        legacy_key = _legacy_context_key(normalized)
        old = payload["records"].get(legacy_key)
    record = _validate_record(old, normalized) if old is not None else {
        "context": normalized.to_dict(),
        **{name: None for name in _RECORD_FIELDS},
    }
    for name, value in updates.items():
        if value is None:
            continue
        _validate_value(name, value)
        record[name] = int(value)
    record["updated_at"] = datetime.now(timezone.utc).isoformat()
    payload["records"][key] = record
    if legacy_key is not None and legacy_key != key:
        payload["records"].pop(legacy_key, None)
    _write_json_atomic(Path(path), payload)
    return dict(record)


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
    if marker.get("V") != SCHEMA_VERSION:
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
    if marker.get("KIND") == "EGG":
        if "HELD_PRE" not in marker or "PICKUP_PRE" not in marker:
            return None
    elif "FRAME_PRE" not in marker:
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
            marker.get("V") == SCHEMA_VERSION
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
            return {seed_field: seed_index, "held_pre": held, "pickup_pre": pickup}
        frame = int(marker["FRAME_PRE"])
        frame_field = "frame_ns1" if normalized.nx_model == 1 else "frame_ns2"
        _validate_value(frame_field, frame)
        if int(marker["FRAME_ENABLED"]) == 0:
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
    return update_record(path, context, updates)


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
    return update_from_log(path, config["context"], text)


def build_marker(
    context: PrecalibrationContext | Mapping[str, object],
    *,
    seed_index: int,
    frame_enabled: bool,
    frame_pre: int = 0,
    held_pre: int | None = None,
    pickup_pre: int | None = None,
) -> str:
    """Build the ASCII marker used by tests and diagnostic tooling."""
    normalized = normalize_context(context)
    fields = [
        MARKER_PREFIX,
        "V=1",
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
    if normalized.kind == "EGG":
        if held_pre is None or pickup_pre is None:
            raise ValueError("孵蛋预校准marker必须包含Held和Pickup")
        fields.extend((f"HELD_PRE={int(held_pre)}", f"PICKUP_PRE={int(pickup_pre)}"))
    return "|".join(fields)


__all__ = [
    "DEFAULT_STORE_PATH",
    "MARKER_PREFIX",
    "PrecalibrationContext",
    "build_marker",
    "context_key",
    "load_store",
    "marker_matches_context",
    "marker_updates",
    "normalize_context",
    "parse_marker",
    "read_record",
    "update_record",
    "update_from_log",
    "update_from_manifest",
]
