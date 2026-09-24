"""Durable fault records shared by the EasyCon runner and the Qt UI."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Iterable, Mapping

INCIDENT_SCHEMA = "frlg-label-incident/v1"
REPAIR_REQUIRED_EXIT_CODE = 20
FAILURE_KINDS = {
    "label_invalid",
    "capture_unavailable",
    "stage_timeout",
    "state_stalled",
}
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
_STORE_LOCK = threading.RLock()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _atomic_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    try:
        with temporary.open("wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _atomic_json(path: Path, payload: object) -> None:
    encoded = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    _atomic_bytes(path, encoded + b"\n")


def _safe_relative(name: str) -> Path:
    value = PurePosixPath(name.replace("\\", "/"))
    if value.is_absolute() or not value.parts or any(part in ("", ".", "..") for part in value.parts):
        raise ValueError(f"故障资料路径无效: {name!r}")
    if any("\x00" in part for part in value.parts):
        raise ValueError("故障资料路径包含无效字符")
    return Path(*value.parts)


def _decode_png(content: bytes, name: str) -> tuple[int, int]:
    try:
        import cv2
        import numpy as np
    except ImportError as exc:  # pragma: no cover - production bundle includes OpenCV
        raise RuntimeError("当前工具环境缺少 OpenCV，无法验证故障原图") from exc
    decoded = cv2.imdecode(np.frombuffer(content, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    if decoded is None or decoded.size == 0 or decoded.ndim not in (2, 3):
        raise ValueError(f"{name} 不是可解码的 PNG 图像")
    if name.lower().endswith(".png") and not content.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError(f"{name} 扩展名与 PNG 数据不一致")
    return int(decoded.shape[1]), int(decoded.shape[0])


def _incident_id(value: object) -> str:
    text = str(value or "")
    if not _ID_RE.fullmatch(text):
        raise ValueError("incident_id 必须是 1–80 位字母、数字、下划线或连字符")
    return text


def validate_incident(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise ValueError("故障记录必须是 JSON 对象")
    record = dict(payload)
    if record.get("schema") != INCIDENT_SCHEMA:
        raise ValueError("故障记录 schema 不受支持")
    record["incident_id"] = _incident_id(record.get("incident_id"))
    for field in ("run_id", "workflow", "stage_id", "stage_instance_id", "failure_kind"):
        if not isinstance(record.get(field), str) or not record[field].strip():
            raise ValueError(f"故障记录缺少 {field}")
    if record["failure_kind"] not in FAILURE_KINDS:
        raise ValueError(f"未知故障类型: {record['failure_kind']}")
    labels = record.get("labels", [])
    if not isinstance(labels, list):
        raise ValueError("labels 必须是数组")
    normalized_labels = []
    for item in labels:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            raise ValueError("labels 中存在无效项")
        normalized = dict(item)
        score = normalized.get("score")
        if score is not None and (isinstance(score, bool) or not isinstance(score, int)):
            raise ValueError(f"{normalized['name']} 的 score 必须是整数或 null")
        normalized_labels.append(normalized)
    record["labels"] = normalized_labels
    return record


class LabelIncidentStore:
    """Read, write, resolve and retain complete incident bundles.

    The native runner writes a bundle before publishing its event. The Python
    side uses the same schema and atomic-file rules for recovery metadata and
    tests. Pending records and explicitly protected drafts are never pruned.
    """

    def __init__(self, root: str | Path, *, keep_resolved: int = 30):
        self.root = Path(root).expanduser().resolve()
        self.keep_resolved = max(0, int(keep_resolved))
        self.root.mkdir(parents=True, exist_ok=True)

    def _bundle_path(self, incident_id: str) -> Path:
        incident_id = _incident_id(incident_id)
        matches = sorted(self.root.glob(f"*-{incident_id}"))
        for candidate in matches:
            if candidate.is_dir() and (candidate / "incident.json").is_file():
                return candidate
        raise FileNotFoundError(f"找不到故障事件 {incident_id}")

    def write_completed(
        self,
        payload: Mapping[str, object],
        *,
        assets: Mapping[str, bytes] | None = None,
        original_labels: Mapping[str, bytes] | None = None,
        append_event: bool = True,
    ) -> Path:
        record = validate_incident(dict(payload))
        incident_id = str(record["incident_id"])
        safe_assets = {str(name): bytes(data) for name, data in (assets or {}).items()}
        for name, data in safe_assets.items():
            rel = _safe_relative(name)
            if rel.name in {"incident.json", "status.json"}:
                raise ValueError(f"不允许覆盖保留故障资料名: {name}")
            if rel.suffix.lower() == ".png":
                _decode_png(data, rel.name)
        safe_labels: dict[str, bytes] = {}
        for name, data in (original_labels or {}).items():
            leaf = Path(name).name
            if leaf != name or Path(leaf).suffix.lower() != ".il":
                raise ValueError(f"原标签必须是 .IL 文件名: {name}")
            from device_label_overrides import inspect_label_file
            import tempfile

            with tempfile.TemporaryDirectory(prefix="frlg-label-incident-") as temp:
                candidate = Path(temp) / leaf
                candidate.write_bytes(bytes(data))
                inspect_label_file(candidate)
            safe_labels[leaf] = bytes(data)

        created = datetime.now(timezone.utc)
        folder = created.strftime("%Y%m%dT%H%M%S%fZ") + "-" + incident_id
        bundle = self.root / folder
        with _STORE_LOCK:
            if bundle.exists() or any(self.root.glob(f"*-{incident_id}")):
                raise FileExistsError(f"故障事件 ID 重复: {incident_id}")
            bundle.mkdir(parents=False)
            try:
                for name, data in safe_assets.items():
                    _atomic_bytes(bundle / _safe_relative(name), data)
                for name, data in safe_labels.items():
                    _atomic_bytes(bundle / "original-labels" / name, data)
                record["created_at_utc"] = record.get("created_at_utc") or created.isoformat()
                record["complete"] = True
                record["assets"] = {
                    name: {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
                    for name, data in sorted(safe_assets.items())
                }
                record["original_labels"] = {
                    name: hashlib.sha256(data).hexdigest() for name, data in sorted(safe_labels.items())
                }
                _atomic_json(bundle / "incident.json", record)
                _atomic_json(bundle / "status.json", {"status": "pending", "updated_at_utc": utc_now()})
                if append_event:
                    event_path = self.root / "events.jsonl"
                    line = json.dumps(
                        {"event": "incident_complete", "incident_id": incident_id,
                         "run_id": record["run_id"], "path": folder,
                         "published_at_utc": utc_now()},
                        ensure_ascii=False,
                    ).encode("utf-8") + b"\n"
                    with event_path.open("ab") as stream:
                        stream.write(line)
                        stream.flush()
                        os.fsync(stream.fileno())
            except BaseException:
                shutil.rmtree(bundle, ignore_errors=True)
                raise
        return bundle

    def read(self, incident_id: str) -> dict[str, object]:
        bundle = self._bundle_path(incident_id)
        try:
            payload = json.loads((bundle / "incident.json").read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"故障记录无法读取: {exc}") from exc
        record = validate_incident(payload)
        if record.get("complete") is not True:
            raise ValueError("故障资料尚未完成写入")
        status_path = bundle / "status.json"
        if status_path.is_file():
            status = json.loads(status_path.read_text(encoding="utf-8"))
            record["resolution"] = status
        record["bundle_path"] = str(bundle)
        return record

    def list(self, *, include_resolved: bool = True) -> tuple[dict[str, object], ...]:
        result = []
        for path in sorted(self.root.glob("*-*"), reverse=True):
            if not path.is_dir() or not (path / "incident.json").is_file():
                continue
            try:
                payload = json.loads((path / "incident.json").read_text(encoding="utf-8"))
                record = validate_incident(payload)
                if record.get("complete") is not True:
                    continue
                status_path = path / "status.json"
                status = json.loads(status_path.read_text(encoding="utf-8")) if status_path.is_file() else {"status": "pending"}
                if not include_resolved and status.get("status") == "resolved":
                    continue
                record["resolution"] = status
                record["bundle_path"] = str(path)
                result.append(record)
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                continue
        return tuple(result)

    def set_status(self, incident_id: str, status: str, *, note: str = "") -> None:
        if status not in {"pending", "editing", "override_saved", "applied", "loaded", "resolved", "failed"}:
            raise ValueError(f"无效故障事件状态: {status}")
        bundle = self._bundle_path(incident_id)
        _atomic_json(bundle / "status.json", {
            "status": status, "note": note, "updated_at_utc": utc_now(),
        })

    def write_draft(self, incident_id: str, filename: str, data: bytes) -> Path:
        if Path(filename).name != filename or Path(filename).suffix.lower() != ".il":
            raise ValueError("标签草稿必须使用单一 .IL 文件名")
        from device_label_overrides import inspect_label_file
        import tempfile

        with tempfile.TemporaryDirectory(prefix="frlg-label-draft-") as temp:
            candidate = Path(temp) / filename
            candidate.write_bytes(data)
            inspect_label_file(candidate)
        path = self._bundle_path(incident_id) / "repair-draft" / filename
        _atomic_bytes(path, bytes(data))
        self.set_status(incident_id, "editing")
        return path

    def write_verification(self, incident_id: str, payload: Mapping[str, object]) -> Path:
        record = dict(payload)
        if record.get("incident_id") != incident_id:
            raise ValueError("验证记录与故障事件 ID 不一致")
        if record.get("schema") != "frlg-label-verification/v1":
            raise ValueError("验证记录 schema 不受支持")
        bundle = self._bundle_path(incident_id)
        record["updated_at_utc"] = utc_now()
        path = bundle / "verification.json"
        _atomic_json(path, record)
        return path

    def prune(self, *, protected_incidents: Iterable[str] = ()) -> tuple[Path, ...]:
        protected = {_incident_id(item) for item in protected_incidents}
        resolved = []
        for item in self.list(include_resolved=True):
            resolution = item.get("resolution", {})
            if isinstance(resolution, dict) and resolution.get("status") == "resolved":
                resolved.append(item)
        removed = []
        for item in resolved[self.keep_resolved:]:
            incident_id = str(item["incident_id"])
            if incident_id in protected:
                continue
            bundle = Path(str(item["bundle_path"]))
            if (bundle / "repair-draft").is_dir():
                continue
            shutil.rmtree(bundle)
            removed.append(bundle)
        return tuple(removed)
