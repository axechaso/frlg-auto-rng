"""Prepare and verify the native EasyCon OCR runtime.

The historical filename is kept so existing setup scripts remain usable. It
no longer reads, launches, or validates ``ezcon.exe``.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from automation.easycon118 import EXPECTED_TESSDATA_SHA256, EXPECTED_COMPAT_OCR_NATIVE_SHA256


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_NATIVE_ROOT = ROOT / "assets" / "easycon_native"
DEFAULT_SOURCES = (ROOT / "local_assets" / "easycon118", Path.home() / "Downloads" / "NS火叶全自动一键乱数1.1.8")
NATIVE_DLLS = ("x64/tesseract50.dll", "x64/leptonica-1.82.0.dll")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _find_models(source: Path) -> Path | None:
    for candidate in (source / "Tessdata", source):
        if all((candidate / name).is_file() for name in EXPECTED_TESSDATA_SHA256):
            return candidate
    return None


def prepare_backend(native_root: str | Path = DEFAULT_NATIVE_ROOT, source: str | Path | None = None, *, check_only: bool = False) -> Path:
    root = Path(native_root).resolve()
    missing = [root / relative for relative in NATIVE_DLLS if not (root / relative).is_file()]
    if missing:
        raise FileNotFoundError("原生 OCR DLL 缺失：" + ", ".join(str(path) for path in missing))

    for relative, expected in EXPECTED_COMPAT_OCR_NATIVE_SHA256.items():
        if _sha256(root / relative) != expected:
            raise RuntimeError(f"原生 OCR DLL 指纹不一致: {relative}")

    destination = root / "Tessdata"
    candidates = (Path(source),) if source is not None else DEFAULT_SOURCES
    model_root = next((found for item in candidates if item.exists()
                       if (found := _find_models(item.resolve())) is not None), None)
    if model_root is not None and not check_only:
        destination.mkdir(parents=True, exist_ok=True)
        for name, expected in EXPECTED_TESSDATA_SHA256.items():
            source_path = model_root / name
            if _sha256(source_path) != expected:
                raise RuntimeError(f"OCR 模型指纹不一致: {source_path}")
            if source_path.resolve() != (destination / name).resolve():
                shutil.copy2(source_path, destination / name)
    missing_models = [name for name in EXPECTED_TESSDATA_SHA256 if not (destination / name).is_file()]
    if missing_models:
        raise FileNotFoundError("原生 OCR 模型缺失：" + ", ".join(missing_models))
    for name, expected in EXPECTED_TESSDATA_SHA256.items():
        if _sha256(destination / name) != expected:
            raise RuntimeError(f"OCR 模型指纹不一致: {destination / name}")
    return root


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="准备 Python 原生 EasyCon OCR 运行环境")
    parser.add_argument("--native-root", type=Path, default=DEFAULT_NATIVE_ROOT)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        root = prepare_backend(args.native_root, args.source, check_only=args.check_only)
    except Exception as exc:
        print(f"原生 EasyCon 准备失败: {exc}")
        return 1
    print(f"Python 原生 EasyCon OCR 运行时校验通过: {root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
