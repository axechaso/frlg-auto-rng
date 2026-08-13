"""Verify the pinned EasyCon 1.6.4a backend and install FRLG OCR models."""

import argparse
import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from automation import (  # noqa: E402
    DEFAULT_EZCON_PATH,
    EXPECTED_EZCON_SHA256,
    EXPECTED_EZCON_VERSION,
    EXPECTED_TESSDATA_SHA256,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PACKAGE = Path.home() / "Downloads" / "NS火叶全自动一键乱数1.1.8"
DEFAULT_SOURCES = (
    DEFAULT_PACKAGE / "Tessdata",
    ROOT / "local_assets" / "easycon118" / "Tessdata",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_ezcon_version(ezcon_path: Path) -> str:
    result = subprocess.run(
        [str(ezcon_path), "--version"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15,
    )
    if result.returncode != 0:
        raise RuntimeError(f"EasyCon 版本检查失败，退出码 {result.returncode}")
    lines = [line.strip() for line in (result.stdout + "\n" + result.stderr).splitlines() if line.strip()]
    if not lines:
        raise RuntimeError("EasyCon 没有返回版本信息")
    return lines[-1]


def verify_ezcon(ezcon_path: Path) -> None:
    if not ezcon_path.is_file():
        raise FileNotFoundError(f"找不到 EasyCon 1.6.4a CLI: {ezcon_path}")
    actual_sha256 = sha256_file(ezcon_path)
    if actual_sha256 != EXPECTED_EZCON_SHA256:
        raise RuntimeError(f"ezcon.exe 指纹不一致: {actual_sha256}")
    actual_version = read_ezcon_version(ezcon_path)
    if actual_version != EXPECTED_EZCON_VERSION:
        raise RuntimeError(
            f"需要 EasyCon {EXPECTED_EZCON_VERSION}，检测到 {actual_version}"
        )


def verify_tessdata(tessdata_dir: Path) -> tuple[str, ...]:
    errors = []
    for name, expected_sha256 in EXPECTED_TESSDATA_SHA256.items():
        path = tessdata_dir / name
        if not path.is_file():
            errors.append(f"缺少 {name}")
            continue
        actual_sha256 = sha256_file(path)
        if actual_sha256 != expected_sha256:
            errors.append(f"{name} 指纹不一致: {actual_sha256}")
    return tuple(errors)


def find_source(explicit_source: Path | None) -> Path:
    candidates = (explicit_source,) if explicit_source is not None else DEFAULT_SOURCES
    diagnostics = []
    for candidate in candidates:
        if candidate is None:
            continue
        candidate = candidate.resolve()
        if (candidate / "Tessdata").is_dir():
            candidate = candidate / "Tessdata"
        errors = verify_tessdata(candidate)
        if not errors:
            return candidate
        diagnostics.append(f"{candidate}: {', '.join(errors)}")
    raise FileNotFoundError("找不到已审计的火叶 OCR 模型；" + "；".join(diagnostics))


def prepare_backend(
    ezcon_path: Path,
    source: Path | None = None,
    *,
    check_only: bool = False,
) -> Path:
    ezcon_path = ezcon_path.resolve()
    verify_ezcon(ezcon_path)
    target = ezcon_path.parent / "Tessdata"
    current_errors = verify_tessdata(target)
    if not current_errors:
        return target
    if check_only:
        raise RuntimeError("EasyCon Tessdata 校验失败：" + "；".join(current_errors))

    source_dir = find_source(source)
    target.mkdir(parents=True, exist_ok=True)
    for name in EXPECTED_TESSDATA_SHA256:
        shutil.copy2(source_dir / name, target / name)
    final_errors = verify_tessdata(target)
    if final_errors:
        raise RuntimeError("复制后 Tessdata 校验仍失败：" + "；".join(final_errors))
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description="准备 EasyCon 1.6.4a 火叶 OCR 运行环境")
    parser.add_argument("--ezcon", type=Path, default=DEFAULT_EZCON_PATH)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    try:
        target = prepare_backend(args.ezcon, args.source, check_only=args.check_only)
    except Exception as exc:
        print(f"EasyCon 1.6.4a 准备失败: {exc}", file=sys.stderr)
        return 1
    print(f"EasyCon 1.6.4a 与火叶 OCR 模型校验通过: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
