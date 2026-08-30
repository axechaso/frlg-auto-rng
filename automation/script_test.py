"""Advanced direct-ECS test support for pinned EasyCon 1.6.4-a."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from app_paths import RESOURCE_ROOT
from fingerprint_policy import record_fingerprint_mismatch

from .easycon118 import (
    EASYCON118_EXTENSION_LABEL_DIR,
    EGG_TEMPLATE_NAME,
    EXPECTED_EZCON_SHA256,
    EXPECTED_EZCON_VERSION,
    EXPECTED_TESSDATA_SHA256,
    EasyConRuntimeCheck,
    STANDARD_TEMPLATE_NAME,
    prepare_compat_runner,
)


SCRIPT_TEST_BACKEND_COMPAT = "工具兼容运行器（正式工具）"
SCRIPT_TEST_BACKEND_ORIGINAL = "原始 EasyCon 1.6.4-a CLI（A/B 对照）"
SCRIPT_TEST_BACKENDS = (
    SCRIPT_TEST_BACKEND_COMPAT,
    SCRIPT_TEST_BACKEND_ORIGINAL,
)

SCRIPT_TEST_ENTRY_FORMAL = "正式版脚本"
SCRIPT_TEST_ENTRY_TIMELINE = "时间轴版脚本"
SCRIPT_TEST_ENTRY_CUSTOM = "自选 ECS"
SCRIPT_TEST_ENTRIES = (
    SCRIPT_TEST_ENTRY_FORMAL,
    SCRIPT_TEST_ENTRY_TIMELINE,
    SCRIPT_TEST_ENTRY_CUSTOM,
)
# Descriptive alias kept for callers that treat these as immutable choices.
SCRIPT_TEST_ENTRY_CHOICES = SCRIPT_TEST_ENTRIES
_SCRIPT_TEST_ENTRY_FILENAMES = {
    SCRIPT_TEST_ENTRY_FORMAL: STANDARD_TEMPLATE_NAME,
    SCRIPT_TEST_ENTRY_TIMELINE: EGG_TEMPLATE_NAME,
}

BUILTIN_EGG_SURF_MENU_PROBE = (
    RESOURCE_ROOT
    / "assets"
    / "easycon118_extensions"
    / "egg_surf_menu_probe.ecs"
)
BUILTIN_EGG_SURF_MENU_LABELS = ("冲浪",)

_LABEL_REFERENCE_RE = re.compile(r"@([\w]+)", re.UNICODE)


def resolve_script_test_entry(
    source_dir: str | Path,
    selection: str,
    *,
    require_exists: bool = True,
) -> Path:
    """Resolve one of the two audited 1.1.8 entry scripts."""
    try:
        filename = _SCRIPT_TEST_ENTRY_FILENAMES[selection]
    except KeyError as exc:
        if selection == SCRIPT_TEST_ENTRY_CUSTOM:
            raise ValueError("自选 ECS 需要在下方指定脚本文件") from exc
        raise ValueError(f"未知 1.1.8 脚本入口: {selection}") from exc
    path = (Path(source_dir).expanduser().resolve() / filename).resolve()
    if require_exists and not path.is_file():
        raise FileNotFoundError(f"找不到{selection}入口: {path}")
    return path


def identify_script_test_entry(
    source_dir: str | Path,
    script_path: str | Path,
) -> str:
    """Identify a selected path as formal, timeline, or a custom ECS."""
    selected = Path(script_path).expanduser().resolve()
    for entry in (SCRIPT_TEST_ENTRY_FORMAL, SCRIPT_TEST_ENTRY_TIMELINE):
        if selected == resolve_script_test_entry(
            source_dir,
            entry,
            require_exists=False,
        ):
            return entry
    return SCRIPT_TEST_ENTRY_CUSTOM


@dataclass(frozen=True)
class ScriptTestPreparation:
    """Validated direct-run selection and the executable chosen for it."""

    script_path: Path
    project_dir: Path
    backend: str
    runner_path: Path | None
    label_references: tuple[str, ...]
    check: EasyConRuntimeCheck


def inspect_script_label_references(script_path: str | Path) -> tuple[str, ...]:
    """Return literal ``@Label`` references from a main ECS and sibling libs."""
    script_path = Path(script_path).resolve()
    candidates = [script_path]
    lib_dir = script_path.parent / "lib"
    if lib_dir.is_dir():
        candidates.extend(sorted(lib_dir.rglob("*.ecs")))

    labels: set[str] = set()
    for candidate in candidates:
        text = candidate.read_text(encoding="utf-8-sig")
        code_only = "\n".join(line.split("#", 1)[0] for line in text.splitlines())
        labels.update(_LABEL_REFERENCE_RE.findall(code_only))
    return tuple(sorted(labels))


def prepare_script_test_runtime(
    ezcon_path: str | Path,
    script_path: str | Path,
    backend: str,
    *,
    fingerprint_warning_only: bool = False,
) -> ScriptTestPreparation:
    """Validate an arbitrary ECS project without applying 1.1.8 rewrites.

    The selected script stays in place.  The original pinned CLI is always
    used for version and ``format`` checks.  At run time the caller uses either
    that executable or the same compatibility runner used by normal GUI runs.
    """
    ezcon_path = Path(ezcon_path).resolve()
    script_path = Path(script_path).resolve()
    errors: list[str] = []
    warnings: list[str] = []
    label_references: tuple[str, ...] = ()
    runner_path: Path | None = None

    if backend not in SCRIPT_TEST_BACKENDS:
        errors.append(f"未知脚本测试后端: {backend}")

    ezcon_is_pinned = False
    if not ezcon_path.is_file():
        errors.append(f"找不到 ezcon.exe: {ezcon_path}")
    else:
        try:
            actual_sha256 = hashlib.sha256(ezcon_path.read_bytes()).hexdigest()
        except OSError as exc:
            errors.append(f"无法读取 ezcon.exe: {exc}")
        else:
            if actual_sha256 != EXPECTED_EZCON_SHA256:
                record_fingerprint_mismatch(
                    "EasyCon 1.6.4-a ezcon.exe 指纹不一致: " + actual_sha256,
                    warning_only=fingerprint_warning_only,
                    errors=errors,
                    warnings=warnings,
                )
            ezcon_is_pinned = (
                actual_sha256 == EXPECTED_EZCON_SHA256
                or fingerprint_warning_only
            )

    if not script_path.is_file():
        errors.append(f"找不到所选 ECS 脚本: {script_path}")
    elif script_path.suffix.lower() != ".ecs":
        errors.append(f"直接脚本测试只接受 .ecs 文件: {script_path.name}")
    else:
        try:
            label_references = inspect_script_label_references(script_path)
        except (OSError, UnicodeError) as exc:
            errors.append(f"无法读取所选 ECS 或其 lib: {exc}")
        if label_references:
            label_dir = script_path.parent / "ImgLabel"
            if not label_dir.is_dir():
                errors.append(
                    f"脚本引用了 {len(label_references)} 个标签，但同目录缺少 ImgLabel: "
                    f"{label_dir}"
                )
            else:
                missing = [
                    name for name in label_references
                    if not (label_dir / f"{name}.IL").is_file()
                ]
                if missing:
                    preview = "、".join(missing[:12])
                    suffix = "……" if len(missing) > 12 else ""
                    errors.append(f"ImgLabel 缺少脚本引用的标签: {preview}{suffix}")

    if ezcon_is_pinned:
        tessdata_dir = ezcon_path.parent / "Tessdata"
        for model, expected_sha256 in EXPECTED_TESSDATA_SHA256.items():
            model_path = tessdata_dir / model
            if not model_path.is_file():
                errors.append(f"EasyCon Tessdata 缺少 {model}")
                continue
            try:
                actual_sha256 = hashlib.sha256(model_path.read_bytes()).hexdigest()
            except OSError as exc:
                errors.append(f"无法读取 EasyCon Tessdata/{model}: {exc}")
                continue
            if actual_sha256 != expected_sha256:
                record_fingerprint_mismatch(
                    f"EasyCon Tessdata/{model} 指纹不一致: {actual_sha256}",
                    warning_only=fingerprint_warning_only,
                    errors=errors,
                    warnings=warnings,
                )

    run_options = dict(
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if ezcon_is_pinned:
        try:
            version = subprocess.run(
                [str(ezcon_path), "--version"], timeout=15, **run_options
            )
        except (OSError, subprocess.SubprocessError) as exc:
            errors.append(f"无法读取 EasyCon 版本: {exc}")
        else:
            version_text = (version.stdout + "\n" + version.stderr).strip()
            version_line = version_text.splitlines()[-1] if version_text else ""
            if version.returncode != 0 or version_line != EXPECTED_EZCON_VERSION:
                errors.append(
                    f"脚本测试只允许 EasyCon {EXPECTED_EZCON_VERSION}；"
                    f"检测结果为: {version_line or '(无版本输出)'}"
                )
            else:
                warnings.append("EasyCon 版本: " + version_line)

    if ezcon_is_pinned and script_path.is_file() and script_path.suffix.lower() == ".ecs":
        try:
            formatted = subprocess.run(
                [str(ezcon_path), "format", str(script_path)],
                cwd=str(script_path.parent),
                timeout=60,
                **run_options,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            errors.append(f"EasyCon 1.6.4-a ECS 语法预检无法执行: {exc}")
        else:
            if formatted.returncode != 0:
                details = (formatted.stderr or formatted.stdout).strip()
                errors.append(
                    "EasyCon 1.6.4-a ECS 语法预检失败，退出码 "
                    f"{formatted.returncode}: {details[-1000:]}"
                )

    if backend == SCRIPT_TEST_BACKEND_ORIGINAL and ezcon_is_pinned:
        runner_path = ezcon_path
        warnings.append("运行后端：原始 1.6.4-a CLI（不含工具兼容补丁）")
    elif backend == SCRIPT_TEST_BACKEND_COMPAT and ezcon_is_pinned and not errors:
        try:
            runner_path = prepare_compat_runner(
                ezcon_path,
                fingerprint_warning_only=fingerprint_warning_only,
                fingerprint_warnings=warnings,
            )
        except (OSError, ValueError, RuntimeError) as exc:
            errors.append(f"工具兼容运行器预检失败: {exc}")
        else:
            warnings.append("运行后端：与正式工具相同的持续采帧/向上取整兼容运行器")

    if label_references:
        warnings.append(f"已核对脚本及 lib 的 {len(label_references)} 个直接标签引用")
    else:
        warnings.append("脚本及 lib 未发现直接 @标签 引用")
    warnings.extend(
        (
            "高级测试直接运行所选文件：不改参数、不复制脚本、不套用 1.1.8 完整语料指纹。",
            "所选 ECS 拥有完整手柄控制权限，运行前必须人工确认游戏与存档状态。",
        )
    )
    check = EasyConRuntimeCheck(not errors, tuple(errors), tuple(warnings))
    return ScriptTestPreparation(
        script_path=script_path,
        project_dir=script_path.parent,
        backend=backend,
        runner_path=runner_path,
        label_references=label_references,
        check=check,
    )


def write_builtin_egg_surf_menu_probe(
    source_dir: str | Path,
    output_dir: str | Path,
) -> Path:
    """Create the standalone surf-complete probe with its audited label."""
    source_dir = Path(source_dir).resolve()
    output_dir = Path(output_dir).resolve()
    if not BUILTIN_EGG_SURF_MENU_PROBE.is_file():
        raise FileNotFoundError(f"缺少内置冲浪结束测试脚本: {BUILTIN_EGG_SURF_MENU_PROBE}")

    label_sources = []
    for name in BUILTIN_EGG_SURF_MENU_LABELS:
        label_path = EASYCON118_EXTENSION_LABEL_DIR / f"{name}.IL"
        if not label_path.is_file():
            raise FileNotFoundError(f"仓库缺少内置测试标签: {label_path.name}")
        label_sources.append(label_path)

    output_dir.mkdir(parents=True, exist_ok=True)
    output_label_dir = output_dir / "ImgLabel"
    output_label_dir.mkdir(parents=True, exist_ok=True)
    main_path = output_dir / "main.ecs"
    shutil.copy2(BUILTIN_EGG_SURF_MENU_PROBE, main_path)
    for label_path in label_sources:
        (output_label_dir / label_path.name).write_bytes(
            label_path.read_bytes().rstrip(b"\r\n")
        )

    manifest = {
        "kind": "builtin_egg_surf_menu_probe",
        "source_script": str(BUILTIN_EGG_SURF_MENU_PROBE),
        "source_118": str(source_dir),
        "main_sha256": hashlib.sha256(main_path.read_bytes()).hexdigest(),
        "labels": {
            label_path.name: hashlib.sha256(label_path.read_bytes()).hexdigest()
            for label_path in label_sources
        },
    }
    (output_dir / "script-test.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return main_path
