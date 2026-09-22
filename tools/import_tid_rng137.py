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
    TID_EXTENSION_LABEL_DIR,
    copy_tid_extension_labels,
    referenced_image_labels,
    verify_tid_package,
)
from automation.tid_starter_save import (  # noqa: E402
    TID_STARTER_SAVE_NAME,
    TID_STARTER_SAVE_SHA256,
)


ROOT = Path(__file__).resolve().parents[1]


def import_package(
    source: Path, destination: Path, *, starter_save_source: Path | None = None
) -> Path:
    source = source.resolve()
    destination = destination.resolve()
    if ROOT.resolve() not in destination.parents:
        raise ValueError("TID 1.3.7 导入目标必须位于当前项目目录内")
    # The previous 328-label cache remains a recognizable upgrade input. The
    # generated cache below is rebuilt as the strict 119-label mother corpus.
    # The full 1.1.8 package contains labels for every workflow. Accept the
    # superset here, then materialize only labels referenced by this mother.
    manifest = verify_tid_package(
        source, allow_legacy_labels=True, allow_label_superset=True
    )
    if starter_save_source is not None:
        starter_save_source = starter_save_source.resolve()
        expected_mother = (source / TID_STARTER_SAVE_NAME).resolve()
        if starter_save_source != expected_mother:
            raise ValueError(
                "TID统一母本与ImgLabel必须来自同一个原包目录："
                f"母本={starter_save_source}；标签={source / 'ImgLabel'}"
            )
        if hashlib.sha256(starter_save_source.read_bytes()).hexdigest() != TID_STARTER_SAVE_SHA256:
            raise ValueError("TID球前存档脚本指纹与本次确认版本不一致")
        text = starter_save_source.read_text(encoding="utf-8-sig")
        for name in referenced_image_labels(text):
            original_label = source / "ImgLabel" / f"{name}.IL"
            extension_label = TID_EXTENSION_LABEL_DIR / f"{name}.IL"
            updated_label = starter_save_source.parent / "ImgLabel" / f"{name}.IL"
            canonical_label = original_label if original_label.is_file() else extension_label
            if not canonical_label.is_file():
                raise FileNotFoundError("TID球前存档脚本缺少标签：" + name)
            if (
                updated_label.is_file()
                and canonical_label.read_bytes().rstrip(b"\r\n")
                != updated_label.read_bytes().rstrip(b"\r\n")
            ):
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
        target_labels.mkdir(parents=True)
        mother_text = (source / TID_STARTER_SAVE_NAME).read_text(encoding="utf-8-sig")
        for name in referenced_image_labels(mother_text):
            source_label = source / "ImgLabel" / f"{name}.IL"
            if source_label.is_file():
                shutil.copy2(source_label, target_labels / source_label.name)
                continue
            extension_label = TID_EXTENSION_LABEL_DIR / f"{name}.IL"
            if not extension_label.is_file():
                raise FileNotFoundError("TID统一母本缺少标签：" + name)
            (target_labels / extension_label.name).write_bytes(
                extension_label.read_bytes().rstrip(b"\r\n")
            )
    copy_tid_extension_labels(target_labels)
    # 同步工具实际选中的统一母本；独立英/日脚本只作为原包直跑参考。
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
                "tool_mother": str(source / TID_STARTER_SAVE_NAME),
                "label_source": str(source / "ImgLabel"),
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
        default=None,
        help="同步用户确认的 TID/SID 到御三家球前存档新版",
    )
    args = parser.parse_args()
    starter_save_source = args.starter_save_source
    if starter_save_source is None:
        same_package_mother = args.source / TID_STARTER_SAVE_NAME
        starter_save_source = same_package_mother if same_package_mother.is_file() else None
    try:
        if args.check_only:
            verify_tid_package(args.source, allow_label_superset=True)
            result = args.source.resolve()
        else:
            result = import_package(
                args.source, args.destination, starter_save_source=starter_save_source
            )
    except Exception as exc:
        print(f"TID/SID 1.3.7 导入失败: {exc}", file=sys.stderr)
        return 1
    print(f"TID/SID 1.3.7 英文/日文脚本与标签校验通过: {result}")
    manifest = verify_tid_package(result, allow_label_superset=args.check_only)
    for language, script in manifest["scripts"].items():
        print(f"{language}模板：{script['filename']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
