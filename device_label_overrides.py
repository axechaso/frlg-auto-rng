"""Per-capture-device EasyCon label overrides and log diagnostics.

The audited source label corpus is never modified.  Overrides are stored in a
separate user profile and are copied into generated runtime projects only
after the base corpus has been verified.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import shutil
import struct
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence


LABEL_OVERRIDE_SCHEMA = 1
PROJECT_OVERRIDE_SCHEMA = 1
PROJECT_OVERRIDE_FILENAME = "label-overrides.json"
SUPPORTED_SEARCH_METHODS = {1, 3, 5, 11, 14}
_DEVICE_INDEX_RE = re.compile(r"^\s*\[\d+\]\s*")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_json_atomic(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(path)


def capture_device_identity(choice: str) -> str:
    """Return a stable capture-device name without EasyCon's volatile index."""
    raw = choice.strip()
    identity = _DEVICE_INDEX_RE.sub("", raw).strip()
    if not identity or raw.isdigit():
        raise ValueError("请先检测并选择采集卡，再管理该设备的标签")
    return identity


def capture_device_key(choice: str) -> str:
    identity = capture_device_identity(choice)
    return hashlib.sha256(identity.casefold().encode("utf-8")).hexdigest()[:16]


def inspect_label_file(path: str | Path) -> dict[str, object]:
    """Validate one EasyCon ``.IL`` JSON file and return safe metadata."""
    path = Path(path)
    if path.suffix.lower() != ".il":
        raise ValueError(f"只接受 .IL 标签文件: {path.name}")
    data = path.read_bytes()
    try:
        payload = json.loads(data.decode("utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{path.name} 不是有效的 EasyCon 标签 JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{path.name} 的标签根结构必须是对象")
    try:
        method = int(payload["searchMethod"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"{path.name} 缺少有效 searchMethod") from exc
    if method not in SUPPORTED_SEARCH_METHODS:
        raise ValueError(f"{path.name} 使用不支持的 searchMethod={method}")
    image_text = payload.get("ImgBase64")
    if not isinstance(image_text, str) or not image_text:
        raise ValueError(f"{path.name} 缺少 ImgBase64")
    try:
        image = base64.b64decode(image_text, validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"{path.name} 的 ImgBase64 无效") from exc
    if len(image) < 16:
        raise ValueError(f"{path.name} 的标签图像为空或损坏")
    for key in (
        "RangeX", "RangeY", "RangeWidth", "RangeHeight",
        "TargetX", "TargetY", "TargetWidth", "TargetHeight",
    ):
        value = payload.get(key)
        if not isinstance(value, int):
            raise ValueError(f"{path.name} 缺少整数坐标 {key}")
        if key.endswith(("Width", "Height")) and value <= 0:
            raise ValueError(f"{path.name} 的 {key} 必须大于0")
    return {
        "name": path.name,
        "sha256": _sha256(data),
        "size": len(data),
        "search_method": method,
    }


def inspect_label_directory(label_dir: str | Path) -> dict[str, object]:
    """Match the deterministic corpus fingerprint used by EasyCon adapters."""
    label_dir = Path(label_dir)
    files = sorted(
        (path for path in label_dir.iterdir() if path.is_file() and path.suffix == ".IL"),
        key=lambda path: path.name,
    )
    digest = hashlib.sha256()
    methods: dict[int, int] = {}
    total_bytes = 0
    for path in files:
        name = path.name.encode("utf-8")
        data = path.read_bytes()
        digest.update(struct.pack(">I", len(name)))
        digest.update(name)
        digest.update(struct.pack(">Q", len(data)))
        digest.update(data)
        total_bytes += len(data)
        payload = json.loads(data.decode("utf-8-sig"))
        method = int(payload.get("searchMethod", 5))
        methods[method] = methods.get(method, 0) + 1
    return {
        "count": len(files),
        "bytes": total_bytes,
        "methods": methods,
        "sha256": digest.hexdigest(),
    }


@dataclass(frozen=True)
class LabelOverrideProfile:
    key: str
    capture_device: str
    directory: Path

    @property
    def label_dir(self) -> Path:
        return self.directory / "ImgLabel"

    @property
    def manifest_path(self) -> Path:
        return self.directory / "manifest.json"


@dataclass(frozen=True)
class LabelImportResult:
    profile: LabelOverrideProfile
    imported: tuple[str, ...]
    total: int


class LabelOverrideStore:
    """Persistent device profiles containing validated replacement labels."""

    def __init__(self, root: str | Path):
        self.root = Path(root)

    def profile(self, capture_device: str) -> LabelOverrideProfile:
        identity = capture_device_identity(capture_device)
        key = capture_device_key(capture_device)
        return LabelOverrideProfile(key, identity, self.root / key)

    @staticmethod
    def _expand_inputs(paths: Iterable[str | Path]) -> tuple[Path, ...]:
        files: list[Path] = []
        for raw in paths:
            path = Path(raw)
            if path.is_dir():
                files.extend(
                    sorted(
                        item for item in path.rglob("*")
                        if item.is_file() and item.suffix.lower() == ".il"
                    )
                )
            elif path.is_file():
                files.append(path)
            else:
                raise FileNotFoundError(f"找不到拖入的标签路径: {path}")
        return tuple(files)

    @staticmethod
    def _known_targets(
        name: str, known_label_dirs: Sequence[str | Path]
    ) -> tuple[Path, ...]:
        targets = []
        for raw in known_label_dirs:
            path = Path(raw) / name
            if path.is_file():
                targets.append(path)
        return tuple(targets)

    def load_manifest(self, profile: LabelOverrideProfile) -> dict[str, object]:
        if not profile.manifest_path.is_file():
            return {
                "schema": LABEL_OVERRIDE_SCHEMA,
                "profile_key": profile.key,
                "capture_device": profile.capture_device,
                "files": {},
            }
        try:
            payload = json.loads(profile.manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"设备标签清单损坏: {profile.manifest_path}: {exc}") from exc
        if not isinstance(payload, dict) or payload.get("schema") != LABEL_OVERRIDE_SCHEMA:
            raise ValueError("设备标签清单版本不支持")
        files = payload.get("files")
        if not isinstance(files, dict):
            raise ValueError("设备标签清单缺少 files")
        return payload

    def list_overrides(self, capture_device: str) -> tuple[dict[str, object], ...]:
        profile = self.profile(capture_device)
        manifest = self.load_manifest(profile)
        result = []
        for name, metadata in sorted(manifest["files"].items()):
            path = profile.label_dir / name
            current = inspect_label_file(path)
            if not isinstance(metadata, dict) or current["sha256"] != metadata.get("sha256"):
                raise ValueError(f"设备标签文件与清单不一致: {name}")
            result.append(current)
        return tuple(result)

    def import_paths(
        self,
        capture_device: str,
        paths: Iterable[str | Path],
        known_label_dirs: Sequence[str | Path],
    ) -> LabelImportResult:
        profile = self.profile(capture_device)
        candidates = self._expand_inputs(paths)
        if not candidates:
            raise ValueError("所选路径中没有 .IL 标签文件")

        prepared: dict[str, tuple[Path, dict[str, object]]] = {}
        for path in candidates:
            metadata = inspect_label_file(path)
            name = str(metadata["name"])
            previous = prepared.get(name)
            if previous is not None:
                if previous[1]["sha256"] != metadata["sha256"]:
                    raise ValueError(f"同一批次存在两个内容不同的同名标签: {name}")
                continue
            targets = self._known_targets(name, known_label_dirs)
            if not targets:
                raise ValueError(
                    f"{name} 在当前1.1.8/TID/SID标签包中没有同名目标；"
                    "设备覆盖层只允许替换现有标签"
                )
            base_methods = {int(inspect_label_file(target)["search_method"]) for target in targets}
            if int(metadata["search_method"]) not in base_methods:
                raise ValueError(
                    f"{name} 的 searchMethod={metadata['search_method']} 与原标签"
                    f" {sorted(base_methods)} 不一致"
                )
            prepared[name] = (path, metadata)

        manifest = self.load_manifest(profile)
        files_payload = dict(manifest["files"])
        profile.label_dir.mkdir(parents=True, exist_ok=True)
        for name, (source, metadata) in prepared.items():
            destination = profile.label_dir / name
            temporary = destination.with_name(destination.name + ".tmp")
            temporary.write_bytes(source.read_bytes())
            temporary.replace(destination)
            files_payload[name] = {
                **metadata,
                "source": str(source.resolve()),
                "imported_at_utc": datetime.now(timezone.utc).isoformat(),
            }
        updated = {
            "schema": LABEL_OVERRIDE_SCHEMA,
            "profile_key": profile.key,
            "capture_device": profile.capture_device,
            "updated_at_utc": datetime.now(timezone.utc).isoformat(),
            "files": files_payload,
        }
        _write_json_atomic(profile.manifest_path, updated)
        return LabelImportResult(profile, tuple(sorted(prepared)), len(files_payload))

    def clear(self, capture_device: str) -> None:
        profile = self.profile(capture_device)
        if profile.directory.is_dir():
            shutil.rmtree(profile.directory)


@dataclass(frozen=True)
class ProjectOverrideResult:
    project_dir: Path
    installed: tuple[str, ...]
    base_sha256: str
    effective_sha256: str


@dataclass(frozen=True)
class OverrideValidation:
    recognized: bool
    ok: bool
    base_sha256: str | None
    errors: tuple[str, ...]
    warnings: tuple[str, ...]


def _load_profile_files(profile: LabelOverrideProfile) -> tuple[dict[str, object], ...]:
    store = LabelOverrideStore(profile.directory.parent)
    return store.list_overrides(profile.capture_device)


def load_label_override_profile(directory: str | Path) -> LabelOverrideProfile:
    """Load and authenticate a persisted profile passed to a worker process."""
    directory = Path(directory).resolve()
    manifest_path = directory / "manifest.json"
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取设备标签清单 {manifest_path}: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema") != LABEL_OVERRIDE_SCHEMA:
        raise ValueError("设备标签清单版本不支持")
    device = payload.get("capture_device")
    profile_key = payload.get("profile_key")
    if not isinstance(device, str) or not isinstance(profile_key, str):
        raise ValueError("设备标签清单缺少采集设备身份")
    if capture_device_key(device) != profile_key or directory.name != profile_key:
        raise ValueError("设备标签清单路径或设备身份与登记值不一致")
    profile = LabelOverrideProfile(profile_key, capture_device_identity(device), directory)
    _load_profile_files(profile)
    return profile


def _normalized_corpus(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise ValueError("标签语料清单不是对象")
    return {
        "count": int(payload.get("count", -1)),
        "bytes": int(payload.get("bytes", -1)),
        "methods": {
            int(key): int(value)
            for key, value in dict(payload.get("methods", {})).items()
        },
        "sha256": str(payload.get("sha256", "")),
    }


def apply_profile_to_projects(
    project_root: str | Path,
    profile: LabelOverrideProfile,
) -> tuple[ProjectOverrideResult, ...]:
    """Overlay matching labels in every generated project below ``project_root``."""
    project_root = Path(project_root)
    files = _load_profile_files(profile)
    if not files:
        return ()
    label_dirs: set[Path] = set()
    if project_root.name == "ImgLabel" and project_root.is_dir():
        label_dirs.add(project_root)
    direct = project_root / "ImgLabel"
    if direct.is_dir():
        label_dirs.add(direct)
    if project_root.is_dir():
        label_dirs.update(path for path in project_root.rglob("ImgLabel") if path.is_dir())

    results = []
    for label_dir in sorted(label_dirs):
        installable = [item for item in files if (label_dir / str(item["name"])).is_file()]
        if not installable:
            continue
        project_dir = label_dir.parent
        sidecar = project_dir / PROJECT_OVERRIDE_FILENAME
        if sidecar.is_file():
            try:
                existing = json.loads(sidecar.read_text(encoding="utf-8"))
                existing_files = {
                    str(item["name"]): str(item["override_sha256"])
                    for item in existing.get("files", [])
                }
                wanted_files = {
                    str(item["name"]): str(item["sha256"])
                    for item in installable
                }
                actual = inspect_label_directory(label_dir)
                effective = _normalized_corpus(existing.get("effective_corpus"))
                recorded_base = _normalized_corpus(existing.get("base_corpus"))
            except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
                raise ValueError(f"运行工程已有损坏的设备标签覆盖清单: {sidecar}: {exc}") from exc
            if (
                existing.get("schema") == PROJECT_OVERRIDE_SCHEMA
                and existing.get("profile_key") == profile.key
                and existing_files == wanted_files
                and actual == effective
            ):
                results.append(
                    ProjectOverrideResult(
                        project_dir,
                        tuple(sorted(existing_files)),
                        str(recorded_base["sha256"]),
                        str(effective["sha256"]),
                    )
                )
                continue
            if actual == recorded_base:
                # Project generators replace ImgLabel but intentionally keep
                # unrelated files in the output directory.  An old sidecar is
                # therefore stale, not an attempt to stack two override layers.
                sidecar.unlink()
                plan_path = project_dir / "plan.json"
                if plan_path.is_file():
                    try:
                        plan = json.loads(plan_path.read_text(encoding="utf-8"))
                        if isinstance(plan, dict):
                            plan.pop("device_label_overrides", None)
                            _write_json_atomic(plan_path, plan)
                    except (OSError, json.JSONDecodeError) as exc:
                        raise ValueError(f"无法清理旧设备标签登记 {plan_path}: {exc}") from exc
            else:
                raise ValueError(
                    f"{project_dir} 已应用另一版设备标签；请重新生成方案，"
                    "不要在覆盖后的工程上叠加覆盖"
                )
        base = inspect_label_directory(label_dir)
        installed_payload = []
        for item in installable:
            name = str(item["name"])
            target = label_dir / name
            original = inspect_label_file(target)
            if original["search_method"] != item["search_method"]:
                raise ValueError(f"运行工程中的 {name} 方法与设备覆盖标签不一致")
            source = profile.label_dir / name
            target.write_bytes(source.read_bytes())
            installed_payload.append(
                {
                    "name": name,
                    "original_sha256": original["sha256"],
                    "override_sha256": item["sha256"],
                    "search_method": item["search_method"],
                }
            )
        effective = inspect_label_directory(label_dir)
        payload = {
            "schema": PROJECT_OVERRIDE_SCHEMA,
            "profile_key": profile.key,
            "capture_device": profile.capture_device,
            "base_corpus": base,
            "effective_corpus": effective,
            "files": installed_payload,
        }
        _write_json_atomic(project_dir / PROJECT_OVERRIDE_FILENAME, payload)
        plan_path = project_dir / "plan.json"
        if plan_path.is_file():
            try:
                plan = json.loads(plan_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ValueError(f"无法登记设备标签到 {plan_path}: {exc}") from exc
            if not isinstance(plan, dict):
                raise ValueError(f"运行计划不是JSON对象: {plan_path}")
            plan["device_label_overrides"] = payload
            _write_json_atomic(plan_path, plan)
        results.append(
            ProjectOverrideResult(
                project_dir,
                tuple(item["name"] for item in installed_payload),
                str(base["sha256"]),
                str(effective["sha256"]),
            )
        )
    return tuple(results)


def validate_project_overrides(
    label_dir: str | Path,
    expected_base_sha256: str,
    *,
    fingerprint_warning_only: bool = False,
) -> OverrideValidation:
    """Validate an installed override sidecar without treating it as base drift."""
    label_dir = Path(label_dir)
    sidecar = label_dir.parent / PROJECT_OVERRIDE_FILENAME
    if not sidecar.is_file():
        return OverrideValidation(False, True, None, (), ())
    errors: list[str] = []
    warnings: list[str] = []
    base_sha256: str | None = None
    fingerprint_mismatch = False

    def record_fingerprint_problem(message: str) -> None:
        nonlocal fingerprint_mismatch
        fingerprint_mismatch = True
        if fingerprint_warning_only:
            warnings.append("高级模式指纹警告：" + message)
        else:
            errors.append(message)

    try:
        payload = json.loads(sidecar.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("schema") != PROJECT_OVERRIDE_SCHEMA:
            raise ValueError("覆盖清单版本不支持")
        base = payload.get("base_corpus")
        effective = payload.get("effective_corpus")
        files = payload.get("files")
        if not isinstance(base, dict) or not isinstance(effective, dict) or not isinstance(files, list):
            raise ValueError("覆盖清单结构不完整")
        base_sha256 = str(base.get("sha256", ""))
        if base_sha256 != expected_base_sha256:
            record_fingerprint_problem(
                "设备标签覆盖所基于的原始标签包指纹不一致: " + base_sha256
            )
        actual = inspect_label_directory(label_dir)
        effective_normalized = _normalized_corpus(effective)
        effective_methods = effective_normalized["methods"]
        if actual != effective_normalized:
            record_fingerprint_problem("设备标签覆盖后的运行标签清单已被再次修改")
        base_methods = _normalized_corpus(base)["methods"]
        if int(base.get("count", -1)) != effective_normalized["count"] or base_methods != effective_methods:
            errors.append("设备标签覆盖改变了标签数量或 searchMethod 分布")
        for item in files:
            if not isinstance(item, dict) or not isinstance(item.get("name"), str):
                errors.append("设备标签覆盖文件记录无效")
                continue
            path = label_dir / item["name"]
            if not path.is_file():
                errors.append(f"设备标签覆盖文件缺失: {item['name']}")
            elif _sha256(path.read_bytes()) != item.get("override_sha256"):
                record_fingerprint_problem(
                    f"设备标签覆盖文件与清单指纹不一致: {item['name']}"
                )
        if not errors and not fingerprint_mismatch:
            warnings.append(
                f"已应用设备标签覆盖：{payload.get('capture_device', '未知采集设备')} / "
                f"{len(files)} 个标签；原始标签包指纹仍已验证"
            )
    except (OSError, ValueError, json.JSONDecodeError, TypeError) as exc:
        errors.append(f"设备标签覆盖清单无效: {exc}")
    return OverrideValidation(True, not errors, base_sha256, tuple(errors), tuple(warnings))


@dataclass(frozen=True)
class LabelIssue:
    labels: tuple[str, ...]
    score: int | None
    threshold: int | None
    occurrences: int
    context: str
    reason: str

    @property
    def gap(self) -> int | None:
        if self.score is None or self.threshold is None:
            return None
        return self.threshold - self.score


def _pipe_values(line: str) -> dict[str, int]:
    values: dict[str, int] = {}
    for key, value in re.findall(r"(?:^|\|)([A-Z0-9_]+)=(-?\d+)", line):
        values[key] = int(value)
    return values


def diagnose_label_log(text: str, near_threshold_margin: int = 10) -> tuple[LabelIssue, ...]:
    """Extract unresolved, near-threshold label failures from an EasyCon log."""
    states: dict[str, LabelIssue] = {}

    def observe(
        context: str,
        candidates: Sequence[tuple[tuple[str, ...], int]],
        threshold: int,
        reason: str,
    ) -> None:
        if not candidates:
            return
        best = max(score for _, score in candidates)
        if best >= threshold:
            states.pop(context, None)
            return
        labels = tuple(
            label for group, score in candidates if score == best for label in group
        )
        previous = states.get(context)
        occurrences = (
            previous.occurrences + 1
            if previous is not None and previous.labels == labels
            else 1
        )
        states[context] = LabelIssue(labels, best, threshold, occurrences, context, reason)

    for line in text.splitlines():
        if "HOME_BUFFER_LABEL|" in line or "TID_HOME_BUFFER_LABEL|" in line:
            values = _pipe_values(line[line.index("HOME_BUFFER_LABEL|"):])
            nx = values.get("NX", 1)
            suffix = "_NS2" if nx == 2 else ""
            observe(
                "HOME_BUFFER",
                (
                    ((f"HOME_BUFFER正确退出{suffix}.IL",), values.get("BUFFER", -1)),
                    ((f"正确退出{suffix}.IL",), values.get("NORMAL", -1)),
                    ((f"错误退出{suffix}.IL",), values.get("ERROR", -1)),
                ),
                values.get("THRESHOLD", 95),
                "HOME_BUFFER 三类状态均未达阈值；最高项最可能需要按当前设备重做",
            )
            continue

        if "孵蛋重启识图|主页=" in line:
            pairs = dict(re.findall(r"([\w_]+)=(-?\d+)", line))
            mapping = {
                "主页": "主页.IL", "主页_NS2": "主页_NS2.IL",
                "正确退出": "正确退出.IL", "正确退出_NS2": "正确退出_NS2.IL",
                "HOME_BUFFER正确退出": "HOME_BUFFER正确退出.IL",
                "错误退出": "错误退出.IL", "错误退出_NS2": "错误退出_NS2.IL",
            }
            observe(
                "孵蛋重启",
                tuple(((mapping[key],), int(value)) for key, value in pairs.items() if key in mapping),
                95,
                "孵蛋关闭/主页状态识别未达阈值",
            )
            continue

        match = re.search(r"设置识别 TEXT 第\d+次: FAST=(\d+) MID=(\d+) SLOW=(\d+)", line)
        if match:
            observe(
                "游戏设置/文字速度",
                (
                    (("TEXT_SPEED_FAST.IL", "日版TEXT_SPEED_FAST.IL"), int(match.group(1))),
                    (("TEXT_SPEED_MID.IL", "日版TEXT_SPEED_MID.IL"), int(match.group(2))),
                    (("TEXT_SPEED_SLOW.IL", "日版TEXT_SPEED_SLOW.IL"), int(match.group(3))),
                ), 95, "文字速度标签连续识别失败",
            )
            continue
        match = re.search(r"设置识别 BATTLE 第\d+次: OFF=(\d+) ON=(\d+)", line)
        if match:
            observe(
                "游戏设置/战斗动画",
                (
                    (("BATTLE_SCENE_OFF.IL", "日版BATTLE_SCENE_OFF.IL"), int(match.group(1))),
                    (("BATTLE_SCENE_ON.IL", "日版BATTLE_SCENE_ON.IL"), int(match.group(2))),
                ), 95, "战斗动画标签连续识别失败",
            )
            continue
        match = re.search(r"设置识别 SOUND 第\d+次: MONO=(\d+) STEREO=(\d+)", line)
        if match:
            observe(
                "游戏设置/声音",
                (
                    (("SOUND_MONO.IL", "日版SOUND_MONO.IL"), int(match.group(1))),
                    (("SOUND_STEREO.IL", "日版SOUND_STEREO.IL"), int(match.group(2))),
                ), 95, "声音标签连续识别失败",
            )
            continue
        match = re.search(r"设置识别 BUTTON 第\d+次: HELP=(\d+) L=A=(\d+) LR=(\d+)", line)
        if match:
            observe(
                "游戏设置/按键模式",
                (
                    (("BUTTON_MODE_HELP.IL", "日版BUTTON_MODE_HELP.IL"), int(match.group(1))),
                    (("BUTTON_MODE_LA.IL", "日版BUTTON_MODE_LA.IL"), int(match.group(2))),
                    (("BUTTON_MODE_LR.IL", "日版BUTTON_MODE_LR.IL"), int(match.group(3))),
                ), 95, "按键模式标签连续识别失败",
            )
            continue

        match = re.search(r"孵蛋池塘冲浪检测\|尝试=.*?\|冲浪=(\d+)", line)
        if match:
            observe("孵蛋池塘冲浪", ((('冲浪.IL',), int(match.group(1))),), 96, "冲浪结束标签未达到脚本的 >95 条件")
            continue
        match = re.search(r"孵蛋池塘战斗检测\|尝试=.*?\|野生出现=(\d+)\|抓捕就绪=(\d+)", line)
        if match:
            observe(
                "孵蛋池塘战斗/野生出现",
                ((("野生出现.IL",), int(match.group(1))),),
                91,
                "甜甜香气后野生出现标签未达到脚本的 >90 条件",
            )
            observe(
                "孵蛋池塘战斗/抓捕就绪",
                ((("抓捕就绪.IL",), int(match.group(2))),),
                96,
                "甜甜香气后抓捕就绪标签未达到脚本的 >95 条件",
            )
            continue
        match = re.search(r"SIDREV\|CANDY_LABEL\|.*?SCORE=(\d+)\|THRESHOLD=(\d+)", line)
        if match:
            observe(
                "SID神奇糖果",
                ((('神奇糖果.IL',), int(match.group(1))),),
                int(match.group(2)) + 1,
                "SID 糖果标签必须严格高于配置阈值",
            )

    general_groups = (
        ("HP识图失败", "能力值/HP", ("HP能力值标签组",)),
        ("ATK识图失败", "能力值/攻击", ("攻击能力值标签组",)),
        ("DEF识图失败", "能力值/防御", ("防御能力值标签组",)),
        ("SPA识图失败", "能力值/特攻", ("特攻能力值标签组",)),
        ("SPD识图失败", "能力值/特防", ("特防能力值标签组",)),
        ("SPE识图失败", "能力值/速度", ("速度能力值标签组",)),
        ("LV识图失败", "等级", ("等级标签组",)),
        ("性格识图失败", "性格", ("性格标签组",)),
        ("性别识图失败", "性别", ("性别标签组",)),
    )
    for marker, context, labels in general_groups:
        if marker in text and context not in states:
            states[context] = LabelIssue(
                labels, None, None, 1, context,
                "日志只定位到标签组，当前脚本没有输出组内每个标签的分数",
            )

    return tuple(
        sorted(
            (
                issue for issue in states.values()
                if issue.score is None
                or issue.gap is not None and issue.gap <= near_threshold_margin
                or issue.occurrences >= 3
            ),
            key=lambda issue: (
                issue.gap is None,
                issue.gap if issue.gap is not None else 999,
                -issue.occurrences,
                issue.context,
            ),
        )
    )
