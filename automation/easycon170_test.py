"""Helpers for the opt-in EasyCon 1.7.0 Actions test backend.

The production backend remains pinned to EasyCon 1.6.4-a.  This module keeps
the 1.7.0 test path isolated behind an environment flag so a test build cannot
silently change the normal release runtime.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path


EASYCON170_TEST_ENV = "FRLG_EASYCON_BACKEND"
EASYCON170_ROOT_ENV = "FRLG_EASYCON170_ROOT"
EASYCON170_SOURCE_ENV = "FRLG_EASYCON170_SOURCE"
EASYCON170_CLI_ENV = "FRLG_EASYCON170_CLI"
EASYCON170_TEST_MODE = "easycon170-test"
EASYCON170_VERSION = "1.7.0-rc1+8787f0bda441f85848ad0f978f780d6ebd82c93e"
EASYCON170_COMMIT = "8787f0bda441f85848ad0f978f780d6ebd82c93e"
EASYCON170_CLI_SHA256 = (
    "979d8b58eb5c50085d3ef4c94f9622aef2fc0106160b70b1f3cd5a5d435ece88"
)


def enabled() -> bool:
    """Return whether the opt-in 1.7.0 test backend is active."""

    value = os.environ.get(EASYCON170_TEST_ENV, "").strip().lower()
    return value in {"170", "1.7", "1.7.0", EASYCON170_TEST_MODE}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_root() -> Path:
    configured = os.environ.get(EASYCON170_ROOT_ENV, "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return _repo_root() / "runtime_backend" / EASYCON170_TEST_MODE


def cli_path() -> Path:
    configured = os.environ.get(EASYCON170_CLI_ENV, "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return test_root() / "EasyCon2.CLI.exe"


def source_path() -> Path:
    configured = os.environ.get(EASYCON170_SOURCE_ENV, "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return test_root() / "assets"


def verify_cli(path: str | Path) -> tuple[str, str]:
    """Return ``(version, sha256)`` for a test CLI or raise a clear error."""

    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"找不到 EasyCon 170 测试 CLI: {path}")
    import hashlib

    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != EASYCON170_CLI_SHA256:
        raise ValueError(
            "EasyCon 170 测试 CLI 指纹不一致: "
            f"期望 {EASYCON170_CLI_SHA256}，实际 {digest}"
        )
    try:
        result = subprocess.run(
            [str(path), "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"EasyCon 170 测试 CLI 版本检查失败: {exc}") from exc
    output = (result.stdout + "\n" + result.stderr).strip()
    version = output.splitlines()[-1] if output else ""
    if result.returncode != 0 or version != EASYCON170_VERSION:
        raise ValueError(
            "EasyCon 170 测试 CLI 版本不一致: "
            f"期望 {EASYCON170_VERSION}，实际 {version or '(无输出)'}"
        )
    return version, digest


_CONTEXT_CALL = re.compile(
    r"(?m)^(?P<indent>[ \t]*)RETURN 孵蛋校准_输入上下文"
    r"\(\[(?P<scalar>[^\]]*)\], \[(?P<text>[^\]]*)\], "
    r"(?P<arrays>[^\)]*)\)$"
)
_VARIABLE_RETURN = re.compile(
    r"(?m)^(?P<indent>[ \t]*)RETURN \[(?P<items>[^\]]*)\]$"
)
_BINGO_FUNCTION = re.compile(
    r"(?ms)^FUNC 增加BINGO次数\n.*?^ENDFUNC$"
)
_BINGO_READ_FUNCTION = re.compile(
    r"(?ms)^FUNC 读取BINGO次数\n.*?^ENDFUNC$"
)
_CALIBRATION_FUNCTION = re.compile(
    r"(?ms)^FUNC 执行自动校准与等待更新\(\): INT\n(?P<body>.*?)^ENDFUNC$"
)


def _adapt_bingo_counter_function(text: str) -> tuple[str, bool]:
    """Split the 9x9 BINGO dispatch table into small PC stack frames."""

    match = _BINGO_FUNCTION.search(text)
    if match is None or "FUNC 增加BINGO次数_负4" in text:
        return text, False
    seed_values = (-4, -3, -2, -1, 0, 1, 2, 3, 4)
    labels = {
        -4: "负4",
        -3: "负3",
        -2: "负2",
        -1: "负1",
        0: "零",
        1: "正1",
        2: "正2",
        3: "正3",
        4: "正4",
    }
    frame_lines = (-4, -3, -2, -1, 0, 1, 2, 3, 4)
    helpers: list[str] = []
    for seed in seed_values:
        seed_label = labels[seed]
        helpers.append(f"FUNC 增加BINGO次数_{seed_label}")
        for index, frame in enumerate(frame_lines):
            prefix = "    IF" if index == 0 else "    ELIF"
            helpers.append(
                f"{prefix} $BINGO帧差 == {frame}"
            )
            helpers.append(
                f"        $BINGO{seed_label}{labels[frame]} += 1"
            )
        helpers.extend(("    ENDIF", "ENDFUNC", ""))
    dispatcher = [
        "FUNC 增加BINGO次数",
        "    IF $BINGOSeed差 == -4",
        "        CALL 增加BINGO次数_负4",
        "    ELIF $BINGOSeed差 == -3",
        "        CALL 增加BINGO次数_负3",
        "    ELIF $BINGOSeed差 == -2",
        "        CALL 增加BINGO次数_负2",
        "    ELIF $BINGOSeed差 == -1",
        "        CALL 增加BINGO次数_负1",
        "    ELIF $BINGOSeed差 == 0",
        "        CALL 增加BINGO次数_零",
        "    ELIF $BINGOSeed差 == 1",
        "        CALL 增加BINGO次数_正1",
        "    ELIF $BINGOSeed差 == 2",
        "        CALL 增加BINGO次数_正2",
        "    ELIF $BINGOSeed差 == 3",
        "        CALL 增加BINGO次数_正3",
        "    ELIF $BINGOSeed差 == 4",
        "        CALL 增加BINGO次数_正4",
        "    ENDIF",
        "ENDFUNC",
    ]
    replacement = "\n".join(helpers + dispatcher)
    return text[: match.start()] + replacement + text[match.end() :], True


def _adapt_bingo_read_function(text: str) -> tuple[str, bool]:
    """Split the matching 9x9 BINGO lookup table into small stack frames."""

    match = _BINGO_READ_FUNCTION.search(text)
    if match is None or "FUNC 读取BINGO次数_负4" in text:
        return text, False
    seed_values = (-4, -3, -2, -1, 0, 1, 2, 3, 4)
    labels = {
        -4: "负4",
        -3: "负3",
        -2: "负2",
        -1: "负1",
        0: "零",
        1: "正1",
        2: "正2",
        3: "正3",
        4: "正4",
    }
    frame_values = (-4, -3, -2, -1, 0, 1, 2, 3, 4)
    helpers: list[str] = []
    for seed in seed_values:
        seed_label = labels[seed]
        helpers.append(f"FUNC 读取BINGO次数_{seed_label}")
        for index, frame in enumerate(frame_values):
            prefix = "    IF" if index == 0 else "    ELIF"
            helpers.append(f"{prefix} $BINGO帧差 == {frame}")
            helpers.append(
                f"        $BINGO次数 = $BINGO{seed_label}{labels[frame]}"
            )
        helpers.extend(("    ENDIF", "ENDFUNC", ""))
    dispatcher = [
        "FUNC 读取BINGO次数",
        "    IF $BINGOSeed差 == -4",
        "        CALL 读取BINGO次数_负4",
        "    ELIF $BINGOSeed差 == -3",
        "        CALL 读取BINGO次数_负3",
        "    ELIF $BINGOSeed差 == -2",
        "        CALL 读取BINGO次数_负2",
        "    ELIF $BINGOSeed差 == -1",
        "        CALL 读取BINGO次数_负1",
        "    ELIF $BINGOSeed差 == 0",
        "        CALL 读取BINGO次数_零",
        "    ELIF $BINGOSeed差 == 1",
        "        CALL 读取BINGO次数_正1",
        "    ELIF $BINGOSeed差 == 2",
        "        CALL 读取BINGO次数_正2",
        "    ELIF $BINGOSeed差 == 3",
        "        CALL 读取BINGO次数_正3",
        "    ELIF $BINGOSeed差 == 4",
        "        CALL 读取BINGO次数_正4",
        "    ENDIF",
        "ENDFUNC",
    ]
    replacement = "\n".join(helpers + dispatcher)
    return text[: match.start()] + replacement + text[match.end() :], True


def _adapt_calibration_function(text: str) -> tuple[str, bool]:
    """Split the large calibration routine at its observation/repair boundary."""

    match = _CALIBRATION_FUNCTION.search(text)
    if match is None or "FUNC 执行自动校准与等待更新_观测门控" in text:
        return text, False
    body = match.group("body")
    marker = "    # Seed 路径中心 = 最聚集簇均值"
    boundary = body.find(marker)
    if boundary < 0:
        return text, False
    prefix = body[:boundary].rstrip()
    suffix = body[boundary:].rstrip()
    replacement = "\n".join(
        (
            "FUNC 执行自动校准与等待更新_观测门控(): INT",
            prefix,
            "    RETURN 0",
            "ENDFUNC",
            "",
            "FUNC 执行自动校准与等待更新_修正执行(): INT",
            suffix,
            "ENDFUNC",
            "",
            "FUNC 执行自动校准与等待更新(): INT",
            "    $EC170自动校准门控结果 = 执行自动校准与等待更新_观测门控()",
            "    IF $EC170自动校准门控结果 == 1",
            "        RETURN 1",
            "    ENDIF",
            "    RETURN 执行自动校准与等待更新_修正执行()",
            "ENDFUNC",
        )
    )
    return text[: match.start()] + replacement + text[match.end() :], True


def _split_values(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def adapt_nonconstant_array_literals(text: str) -> tuple[str, int]:
    """Adapt the two 1.6.4-a array idioms rejected by the 1.7 compiler.

    EasyCon 1.7 keeps array variables and ``APPEND`` compatible, but no longer
    accepts runtime expressions inside an array literal.  We construct the
    same arrays before the call/return.  The transformation is deliberately
    narrow and leaves all algorithmic expressions untouched.
    """

    changed = 0
    text, bingo_changed = _adapt_bingo_counter_function(text)
    if bingo_changed:
        changed += 1
    text, bingo_read_changed = _adapt_bingo_read_function(text)
    if bingo_read_changed:
        changed += 1
    text, calibration_changed = _adapt_calibration_function(text)
    if calibration_changed:
        changed += 1

    def replace_context(match: re.Match[str]) -> str:
        nonlocal changed
        scalars = _split_values(match.group("scalar"))
        texts = _split_values(match.group("text"))
        arrays = _split_values(match.group("arrays"))
        if not scalars or not texts or not arrays:
            return match.group(0)
        indent = match.group("indent")
        scalar_name = "$EC170输入标量"
        text_name = "$EC170输入文本"
        lines = [f"{indent}{scalar_name} = []"]
        lines.extend(
            f"{indent}{scalar_name} = APPEND({scalar_name}, {value})"
            for value in scalars
        )
        # An empty literal defaults to INT[] in the 1.7 binder.  Seed values
        # are strings, so seed the array with a constant string and overwrite
        # that slot before appending the second value.
        lines.append(f'{indent}{text_name} = [""]')
        lines.append(f"{indent}{text_name}[0] = {texts[0]}")
        lines.extend(
            f"{indent}{text_name} = APPEND({text_name}, {value})"
            for value in texts[1:]
        )
        lines.append(
            f"{indent}RETURN 孵蛋校准_输入上下文({scalar_name}, {text_name}, "
            + ", ".join(arrays)
            + ")"
        )
        changed += 1
        return "\n".join(lines)

    text = _CONTEXT_CALL.sub(replace_context, text)

    def replace_return(match: re.Match[str]) -> str:
        nonlocal changed
        items = _split_values(match.group("items"))
        if not items or not any(item.startswith("$") for item in items):
            return match.group(0)
        indent = match.group("indent")
        result_name = "$EC170输出状态"
        lines = [f"{indent}{result_name} = []"]
        lines.extend(
            f"{indent}{result_name} = APPEND({result_name}, {value})"
            for value in items
        )
        lines.append(f"{indent}RETURN {result_name}")
        changed += 1
        return "\n".join(lines)

    text = _VARIABLE_RETURN.sub(replace_return, text)
    return text, changed


def adapt_project_tree(project_dir: str | Path) -> int:
    """Apply the narrow 1.7 script compatibility pass to an ECS project."""

    project_dir = Path(project_dir).resolve()
    changed_files = 0
    for path in project_dir.rglob("*.ecs"):
        original = path.read_text(encoding="utf-8")
        adapted, changed = adapt_nonconstant_array_literals(original)
        if changed and adapted != original:
            path.write_text(adapted, encoding="utf-8")
            changed_files += 1
    return changed_files


def copy_adapted_source(source: str | Path, destination: str | Path) -> int:
    """Copy a project source tree and adapt its ECS files for 1.7."""

    source = Path(source).resolve()
    destination = Path(destination).resolve()
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination)
    return adapt_project_tree(destination)


__all__ = [
    "EASYCON170_CLI_ENV",
    "EASYCON170_CLI_SHA256",
    "EASYCON170_COMMIT",
    "EASYCON170_ROOT_ENV",
    "EASYCON170_SOURCE_ENV",
    "EASYCON170_TEST_ENV",
    "EASYCON170_TEST_MODE",
    "EASYCON170_VERSION",
    "adapt_nonconstant_array_literals",
    "adapt_project_tree",
    "cli_path",
    "copy_adapted_source",
    "enabled",
    "source_path",
    "test_root",
    "verify_cli",
]
