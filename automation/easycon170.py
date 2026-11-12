"""Pinned EasyCon 170 PC-extension runtime and generated-script compatibility.

The PC interpreter supports wide function frames; Portable/MCU compilation
keeps its 255-slot budget. Only runtime array literals need lowering here.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path, PurePosixPath

from app_paths import RESOURCE_ROOT
from fingerprint_policy import record_fingerprint_mismatch


EASYCON_BACKEND_ENV = "FRLG_EASYCON_BACKEND"
EASYCON170_ROOT_ENV = "FRLG_EASYCON170_ROOT"
EASYCON170_SOURCE_ENV = "FRLG_EASYCON170_SOURCE"
EASYCON170_CLI_ENV = "FRLG_EASYCON170_CLI"
EASYCON170_MODE = "easycon170-pc-extension"
EASYCON170_COMMIT = "1cd17729fff3d0c91feef012c562473704792f78"
EASYCON170_VERSION = "1.7.0-rc1+" + EASYCON170_COMMIT
EASYCON170_CLI_SHA256 = "4cc6fa6bd341ec0dc8f26a1f9af0ffd80a498630f209b584ded0c1d42b7a8f0a"
EASYCON170_SCRIPT_SHA256 = "fca8fe20e8b99aaccd9a636b1722444303f215b66e66148c47856221a9a3ba0f"
EASYCON170_MANIFEST_PATH = (
    RESOURCE_ROOT / "runtime_backend" / EASYCON170_MODE / "build-manifest.json"
)


def enabled() -> bool:
    """170 is this branch's default; 164a remains an explicit rollback."""
    value = os.environ.get(EASYCON_BACKEND_ENV, "").strip().lower()
    if not value and getattr(sys, "frozen", False):
        selection = RESOURCE_ROOT / "runtime_backend" / "runtime-selection.json"
        if selection.is_file():
            value = str(json.loads(selection.read_text(encoding="utf-8-sig"))["backend"]).lower()
    if value in {"164", "164a", "1.6.4-a", "easycon164a"}:
        return False
    if value in {"", "170", "1.7", "1.7.0", EASYCON170_MODE, "easycon170-test"}:
        return True
    raise ValueError(f"未知 EasyCon 后端: {value}")


def runtime_root() -> Path:
    configured = os.environ.get(EASYCON170_ROOT_ENV, "").strip()
    return Path(configured).expanduser().resolve() if configured else EASYCON170_MANIFEST_PATH.parent


def cli_path() -> Path:
    configured = os.environ.get(EASYCON170_CLI_ENV, "").strip()
    return Path(configured).expanduser().resolve() if configured else runtime_root() / "EasyCon2.CLI.exe"


def source_path() -> Path:
    configured = os.environ.get(EASYCON170_SOURCE_ENV, "").strip()
    return Path(configured).expanduser().resolve() if configured else RESOURCE_ROOT / "local_assets" / "easycon118"


def runtime_files() -> dict[str, str]:
    """Load the reviewed package manifest, excluding GUI/debug-only files."""
    manifest = json.loads(EASYCON170_MANIFEST_PATH.read_text(encoding="utf-8-sig"))
    if (manifest.get("commit") != EASYCON170_COMMIT
            or manifest.get("files", {}).get("EasyCon.Script.dll") != EASYCON170_SCRIPT_SHA256
            or manifest["files"].get("EasyCon2.CLI.exe") != EASYCON170_CLI_SHA256):
        raise ValueError("EasyCon 170 PC 扩展运行包清单与固定版本不一致")
    result = {}
    for raw, digest in manifest["files"].items():
        path = PurePosixPath(raw.replace("\\", "/"))
        if path.is_absolute() or ".." in path.parts or ":" in raw:
            raise ValueError(f"EasyCon 170 运行包清单含非法路径: {raw}")
        if not re.fullmatch(r"[a-f0-9]{64}", digest):
            raise ValueError(f"EasyCon 170 运行包清单含非法摘要: {raw}")
        if path.suffix.lower() not in {".dll", ".json", ".traineddata", ".exe"}:
            continue
        if path.name.startswith("EasyCon2.Avalonia"):
            continue
        result[str(path)] = digest
    return result


def verify_runtime_files(path: str | Path, *, warning_only: bool = False,
                         warnings: list[str] | None = None) -> None:
    """Validate the compiler, native libraries and all seven OCR models too.

    The apphost EXE alone cannot identify a framework-dependent .NET build.
    """
    root = Path(path).resolve().parent
    for relative, expected in runtime_files().items():
        asset = root / relative
        if not asset.is_file():
            raise FileNotFoundError(f"EasyCon 170 PC 扩展运行包缺少 {relative}: {root}")
        actual = hashlib.sha256(asset.read_bytes()).hexdigest()
        if actual != expected:
            record_fingerprint_mismatch(
                f"EasyCon 170 {relative} 指纹不一致: {actual}",
                warning_only=warning_only, warnings=warnings,
            )


def verify_cli(path: str | Path, *, warning_only: bool = False,
               warnings: list[str] | None = None) -> tuple[str, str]:
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"找不到 EasyCon 170 PC 扩展 CLI: {path}；请先导入修复运行包")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != EASYCON170_CLI_SHA256:
        record_fingerprint_mismatch(
            f"EasyCon 170 CLI 指纹不一致: {digest}",
            warning_only=warning_only, warnings=warnings,
        )
    verify_runtime_files(path, warning_only=warning_only, warnings=warnings)
    try:
        result = subprocess.run(
            [str(path), "--version"], capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"EasyCon 170 启动失败（需要 .NET 10 x64）: {exc}") from exc
    output = ((result.stdout or "") + "\n" + (result.stderr or "")).strip()
    version = output.splitlines()[-1] if output else ""
    if result.returncode != 0 or version != EASYCON170_VERSION:
        raise ValueError(
            f"EasyCon 170 PC 扩展版本检查失败，退出码 {result.returncode}；"
            f"期望 {EASYCON170_VERSION}，实际 {output[-1000:] or '(无输出)'}。"
            "该运行包需要 .NET 10 x64，不能使用未修复的原版 170。"
        )
    return version, digest


_CONTEXT_CALL = re.compile(
    r"(?m)^(?P<indent>[ \t]*)RETURN 孵蛋校准_输入上下文"
    r"\(\[(?P<scalar>[^\]]*)\], \[(?P<text>[^\]]*)\], "
    r"(?P<arrays>[^\)]*)\)$"
)
_VARIABLE_RETURN = re.compile(r"(?m)^(?P<indent>[ \t]*)RETURN \[(?P<items>[^\r\n]*)\]$")


def _variables(raw: str) -> list[str]:
    values = [value.strip() for value in raw.split(",")]
    if not values or not all(re.fullmatch(r"\$\w+", value) for value in values):
        raise ValueError("170 数组兼容转换仅接受无副作用的变量快照，请检查上下文字段")
    return values


def _snapshot(indent: str, name: str, values: list[str], initial: str = "0") -> list[str]:
    return [f"{indent}{name} = [{', '.join([initial] * len(values))}]"] + [
        f"{indent}{name}[{index}] = {value}" for index, value in enumerate(values)
    ]


def adapt_nonconstant_array_literals(text: str) -> tuple[str, int]:
    """Lower variable snapshots without splitting functions or changing RNG."""
    changed = 0

    def replace_context(match: re.Match[str]) -> str:
        nonlocal changed
        scalars = _variables(match.group("scalar"))
        texts = _variables(match.group("text"))
        arrays = _variables(match.group("arrays"))
        indent = match.group("indent")
        lines = _snapshot(indent, "$EC170输入标量", scalars)
        lines += _snapshot(indent, "$EC170输入文本", texts, '\"\"')
        lines.append(f"{indent}RETURN 孵蛋校准_输入上下文($EC170输入标量, $EC170输入文本, "
                     + ", ".join(arrays) + ")")
        changed += 1
        return "\n".join(lines)

    text = _CONTEXT_CALL.sub(replace_context, text)

    def replace_return(match: re.Match[str]) -> str:
        nonlocal changed
        if "$" not in match.group("items"):
            return match.group(0)
        values = _variables(match.group("items"))
        indent = match.group("indent")
        changed += 1
        return "\n".join(_snapshot(indent, "$EC170输出状态", values)
                         + [f"{indent}RETURN $EC170输出状态"])

    return _VARIABLE_RETURN.sub(replace_return, text), changed


def adapt_project_tree(project_dir: str | Path) -> int:
    """Adapt only a generated project, retaining original function bodies."""
    changed_files = 0
    for path in Path(project_dir).resolve().rglob("*.ecs"):
        original = path.read_text(encoding="utf-8-sig")
        adapted, count = adapt_nonconstant_array_literals(original)
        if count and adapted != original:
            path.write_text(adapted, encoding="utf-8")
            changed_files += 1
    return changed_files


def copy_adapted_source(source: str | Path, destination: str | Path) -> int:
    """Make a disposable 170-compatible copy without overwriting user files."""
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if destination == source or source in destination.parents:
        raise ValueError("170 兼容副本必须位于源工程之外")
    if destination.exists():
        raise FileExistsError(f"拒绝覆盖已有 170 工程: {destination}")
    shutil.copytree(source, destination, ignore=shutil.ignore_patterns("obj", "*.ecx"))
    return adapt_project_tree(destination)


def copy_adapted_script(script: str | Path, destination: str | Path) -> Path:
    """Copy a selected entry and its standard runtime resources, not its repo.

    EasyCon loads sibling lib/*.ecs automatically. Retain their names and the
    ImgLabel/data/Tessdata layout; native DLLs and root data files travel too.
    Never rewrite an advanced user's source or copy build/log directories.
    """
    script, destination = Path(script).resolve(), Path(destination).resolve()
    if not script.is_file() or script.suffix.lower() != ".ecs":
        raise ValueError(f"找不到所选 ECS 脚本: {script}")
    if destination == script.parent or destination.exists():
        raise FileExistsError(f"拒绝覆盖已有 170 工程: {destination}")
    destination.mkdir(parents=True)
    shutil.copy2(script, destination / script.name)
    for name in ("lib", "ImgLabel", "data", "Tessdata"):
        source = script.parent / name
        if source.is_dir():
            shutil.copytree(source, destination / name,
                            ignore=shutil.ignore_patterns("obj", "*.ecx"))
    for path in script.parent.iterdir():
        if path.is_file() and path.suffix.lower() in {".dll", ".json", ".csv", ".traineddata"}:
            shutil.copy2(path, destination / path.name)
    adapt_project_tree(destination)
    return destination / script.name
