"""Import the pinned TID/SID 1.3.7 scripts and labels into local assets."""

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from automation.tid_rng137 import (  # noqa: E402
    DOWNLOADED_TID_SOURCE,
    IMPORTED_TID_SOURCE,
    referenced_image_labels,
    verify_tid_package,
)
from automation.tid_starter_save import (  # noqa: E402
    DEFAULT_TID_STARTER_SAVE_SOURCE,
    TID_STARTER_SAVE_NAME,
    TID_STARTER_SAVE_SUPPORTED_SHA256,
)


ROOT = Path(__file__).resolve().parents[1]


def import_package(
    source: Path, destination: Path, *, starter_save_source: Path | None = None
) -> Path:
    source = source.resolve()
    destination = destination.resolve()
    if ROOT.resolve() not in destination.parents:
        raise ValueError("TID 1.3.7 导入目标必须位于当前项目目录内")
    manifest = verify_tid_package(source)
    if starter_save_source is not None:
        starter_save_source = starter_save_source.resolve()
        if hashlib.sha256(starter_save_source.read_bytes()).hexdigest() not in TID_STARTER_SAVE_SUPPORTED_SHA256:
            raise ValueError("TID球前存档脚本指纹与本次确认版本不一致")
        text = starter_save_source.read_text(encoding="utf-8-sig")
        for name in referenced_image_labels(text):
            original_label = source / "ImgLabel" / f"{name}.IL"
            updated_label = starter_save_source.parent / "ImgLabel" / f"{name}.IL"
            if not original_label.is_file():
                raise FileNotFoundError("TID球前存档脚本缺少标签：" + name)
            if updated_label.is_file() and original_label.read_bytes() != updated_label.read_bytes():
                raise ValueError("TID新脚本与导入标签内容不一致：" + name)
    if source == destination and starter_save_source is None:
        return destination
    destination.mkdir(parents=True, exist_ok=True)
    target_labels = destination / "ImgLabel"
    if target_labels.resolve().parent != destination:
        raise ValueError("TID 标签导入目标不能指向项目外部")
    if source != destination:
        if target_labels.exists():
            shutil.rmtree(target_labels)
        shutil.copytree(source / "ImgLabel", target_labels)
    # 只同步实际选中的版本，保留旧版和用户放在缓存中的其他文本。
    if source != destination:
        for filename in {script["filename"] for script in manifest["scripts"].values()}:
            shutil.copy2(source / filename, destination / filename)
    if starter_save_source is not None:
        target = destination / TID_STARTER_SAVE_NAME
        if starter_save_source != target:
            shutil.copy2(starter_save_source, target)
    manifest = verify_tid_package(destination)
    (destination / "asset_manifest.json").write_text(
        json.dumps(
            {
                "source": str(source), **manifest,
                "starter_save_source": str(starter_save_source) if starter_save_source else None,
            },
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
    parser.add_argument(
        "--starter-save-source", type=Path,
        default=DEFAULT_TID_STARTER_SAVE_SOURCE if DEFAULT_TID_STARTER_SAVE_SOURCE.is_file() else None,
        help="同步用户确认的 TID/SID 到御三家球前存档新版",
    )
    args = parser.parse_args()
    try:
        if args.check_only:
            verify_tid_package(args.source)
            result = args.source.resolve()
        else:
            result = import_package(
                args.source, args.destination, starter_save_source=args.starter_save_source
            )
    except Exception as exc:
        print(f"TID/SID 1.3.7 导入失败: {exc}", file=sys.stderr)
        return 1
    print(f"TID/SID 1.3.7 英文/日文脚本与标签校验通过: {result}")
    manifest = verify_tid_package(result)
    for language, script in manifest["scripts"].items():
        print(f"{language}模板：{script['filename']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
