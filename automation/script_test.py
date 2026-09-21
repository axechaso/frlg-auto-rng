"""Advanced direct-ECS tests with the native EasyCon engine."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


from .easycon118 import (
    EGG_TEMPLATE_NAME,
    EasyConRuntimeCheck,
    STANDARD_TEMPLATE_NAME,
    prepare_compat_runner,
)


SCRIPT_TEST_BACKEND_NATIVE = "Python 原生 EasyCon"
SCRIPT_TEST_BACKEND_COMPAT = SCRIPT_TEST_BACKEND_NATIVE
# Kept only to identify old saved choices, never exposed as an execution option.
SCRIPT_TEST_BACKEND_ORIGINAL = "原始 EasyCon 1.6.4-a CLI（A/B 对照）"
SCRIPT_TEST_BACKENDS = (SCRIPT_TEST_BACKEND_NATIVE,)

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

_LABEL_REFERENCE_RE = re.compile(r"@([\w]+)", re.UNICODE)


def resolve_script_test_entry(
    source_dir: str | Path,
    selection: str,
    *,
    require_exists: bool = True,
) -> Path:
    """Resolve one of the two audited 2.0 entry scripts."""
    try:
        filename = _SCRIPT_TEST_ENTRY_FILENAMES[selection]
    except KeyError as exc:
        if selection == SCRIPT_TEST_ENTRY_CUSTOM:
            raise ValueError("自选 ECS 需要在下方指定脚本文件") from exc
        raise ValueError(f"未知 2.0 脚本入口: {selection}") from exc
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
    """Compile a selected ECS project in place with the native backend."""
    from .native_runtime import validate_native_runtime
    path = Path(script_path).resolve()
    check = validate_native_runtime(path, fingerprint_warning_only=fingerprint_warning_only)
    if backend not in SCRIPT_TEST_BACKENDS:
        check = EasyConRuntimeCheck(False, (*check.errors, f"未知脚本测试后端: {backend}"), check.warnings)
    try:
        references = inspect_script_label_references(path) if path.is_file() else ()
    except (OSError, UnicodeError):
        references = ()
    return ScriptTestPreparation(path, path.parent, SCRIPT_TEST_BACKEND_NATIVE,
                                 prepare_compat_runner(ezcon_path) if check.ok else None,
                                 references, check)
