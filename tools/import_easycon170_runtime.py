"""Import the reviewed local 170 PC-extension package without rebuilding it."""
from __future__ import annotations

import argparse
import shutil
import tempfile
from pathlib import Path

from automation.easycon170 import (
    EASYCON170_MANIFEST_PATH, cli_path, runtime_files, verify_cli,
)


def import_runtime(source: Path, destination: Path | None = None) -> Path:
    source = source.resolve()
    destination = (destination or cli_path().parent).resolve()
    if source == destination or source in destination.parents or destination in source.parents:
        raise ValueError("170 导入源和目标必须是独立目录")
    # Check the compiler DLL and all models before creating or changing output.
    verify_cli(source / "EasyCon2.CLI.exe")
    existing = list(destination.iterdir()) if destination.exists() else []
    if any(path.name != "build-manifest.json" for path in existing):
        # Re-running an already completed import is safe, but a modified or
        # partial installation is never overwritten silently.
        verify_cli(destination / "EasyCon2.CLI.exe")
        return destination / "EasyCon2.CLI.exe"
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="easycon170-import-", dir=destination.parent) as temp:
        staged = Path(temp)
        for relative in runtime_files():
            target = staged / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / relative, target)
        shutil.copy2(EASYCON170_MANIFEST_PATH, staged / "build-manifest.json")
        verify_cli(staged / "EasyCon2.CLI.exe")
        destination.mkdir(exist_ok=True)
        for path in staged.iterdir():
            if path.name == "build-manifest.json" and (destination / path.name).exists():
                continue
            path.rename(destination / path.name)
    return destination / "EasyCon2.CLI.exe"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="包含修复版 CLI 和依赖的本地目录")
    parser.add_argument("--destination", type=Path)
    args = parser.parse_args()
    print(import_runtime(args.source, args.destination))


if __name__ == "__main__":
    main()
