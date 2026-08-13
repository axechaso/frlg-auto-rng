"""Import the pinned TID/SID 1.3.7 scripts and labels into local assets."""

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from automation.tid_rng137 import (  # noqa: E402
    DOWNLOADED_TID_SOURCE,
    IMPORTED_TID_SOURCE,
    TID_SCRIPT_NAMES,
    verify_tid_package,
)


ROOT = Path(__file__).resolve().parents[1]


def import_package(source: Path, destination: Path) -> Path:
    source = source.resolve()
    destination = destination.resolve()
    if ROOT.resolve() not in destination.parents:
        raise ValueError("TID 1.3.7 导入目标必须位于当前项目目录内")
    manifest = verify_tid_package(source)
    destination.mkdir(parents=True, exist_ok=True)
    target_labels = destination / "ImgLabel"
    if target_labels.exists():
        shutil.rmtree(target_labels)
    shutil.copytree(source / "ImgLabel", target_labels)
    for old_script in destination.glob("*.txt"):
        old_script.unlink()
    for filename in TID_SCRIPT_NAMES.values():
        shutil.copy2(source / filename, destination / filename)
    (destination / "asset_manifest.json").write_text(
        json.dumps(
            {"source": str(source), **manifest},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description="导入已审计的 TID/SID 1.3.7 包")
    parser.add_argument("source", type=Path, nargs="?", default=DOWNLOADED_TID_SOURCE)
    parser.add_argument("--destination", type=Path, default=IMPORTED_TID_SOURCE)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    try:
        if args.check_only:
            verify_tid_package(args.source)
            result = args.source.resolve()
        else:
            result = import_package(args.source, args.destination)
    except Exception as exc:
        print(f"TID/SID 1.3.7 导入失败: {exc}", file=sys.stderr)
        return 1
    print(f"TID/SID 1.3.7 英文/日文脚本与标签校验通过: {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
