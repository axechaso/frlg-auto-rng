"""Import the pinned TID/SID 1.3.7 scripts and labels into local assets."""

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from automation.tid_rng137 import (  # noqa: E402
    DOWNLOADED_TID_SOURCE,
    IMPORTED_TID_SOURCE,
    TID_LEGACY_SCRIPT_NAMES,
    TID_REFERENCE_SCRIPT_NAMES,
    referenced_image_labels,
    verify_tid_package,
)
from automation.easycon118 import (  # noqa: E402
    EXPECTED_LABEL_COUNT,
    EXPECTED_LABEL_METHODS,
    EXPECTED_LABEL_SHA256,
    copy_easycon118_extension_labels,
    inspect_label_corpus,
)
from automation.tid_starter_save import (  # noqa: E402
    TID_STARTER_SAVE_NAME,
    TID_STARTER_SAVE_SHA256,
)


ROOT = Path(__file__).resolve().parents[1]

# The unified mother is the only TID script used by the application.  Older
# standalone references and hashed .bak.ecs copies can be left behind when a
# cache is refreshed in place, so remove those stale root files explicitly.
_STALE_TID_ROOT_FILENAMES = {
    *TID_REFERENCE_SCRIPT_NAMES.values(),
    *TID_LEGACY_SCRIPT_NAMES.values(),
    "【TID+SID乱数&穷举】英文版-火红叶绿1.3.7-164a重写版_v2_全局变量修正版.txt",
}


def remove_stale_tid_root_files(destination: Path) -> tuple[str, ...]:
    removed: list[str] = []
    if not destination.is_dir():
        return ()
    for path in destination.iterdir():
        if not path.is_file():
            continue
        if path.name in _STALE_TID_ROOT_FILENAMES or path.name.endswith(".bak.ecs"):
            path.unlink()
            removed.append(path.name)
    return tuple(sorted(removed))


def audit_common_label_mother(source: Path, audit_parent: Path) -> dict:
    """Verify the source package after installing canonical shared labels."""
    source_labels = source / "ImgLabel"
    audit_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".tid-label-audit-", dir=audit_parent
    ) as audit_root:
        audit_labels = Path(audit_root) / "ImgLabel"
        shutil.copytree(source_labels, audit_labels)
        copy_easycon118_extension_labels(audit_labels)
        label_manifest = inspect_label_corpus(audit_labels)
    if label_manifest["count"] != EXPECTED_LABEL_COUNT:
        raise ValueError(
            f"全流程母本标签数量应为 {EXPECTED_LABEL_COUNT}，"
            f"当前为 {label_manifest['count']}"
        )
    if label_manifest["methods"] != EXPECTED_LABEL_METHODS:
        raise ValueError(
            f"全流程母本标签方法分布不一致: {label_manifest['methods']}"
        )
    if label_manifest["sha256"] != EXPECTED_LABEL_SHA256:
        raise ValueError(
            f"全流程母本标签指纹不一致: {label_manifest['sha256']}"
        )
    return label_manifest


def import_package(
    source: Path, destination: Path, *, starter_save_source: Path | None = None
) -> Path:
    source = source.resolve()
    destination = destination.resolve()
    if ROOT.resolve() not in destination.parents:
        raise ValueError("TID 1.3.7 导入目标必须位于当前项目目录内")
    # ImgLabel is the common mother for every workflow, not a TID-only subset.
    # Audit the canonicalized full corpus before replacing the local cache.
    source_labels = source / "ImgLabel"
    audit_common_label_mother(source, destination.parent)

    # Script and label fingerprints are verified together after the staged
    # full corpus has been copied and normalized below.
    mother_path = source / TID_STARTER_SAVE_NAME
    if not mother_path.is_file():
        raise FileNotFoundError(f"TID统一母本不存在：{mother_path}")
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
            if not original_label.is_file():
                raise FileNotFoundError("TID球前存档脚本缺少标签：" + name)
    if source == destination and starter_save_source is None:
        return destination
    destination.mkdir(parents=True, exist_ok=True)
    remove_stale_tid_root_files(destination)
    target_labels = destination / "ImgLabel"
    if target_labels.resolve().parent != destination:
        raise ValueError("TID 标签导入目标不能指向项目外部")
    if source != destination:
        if target_labels.exists():
            shutil.rmtree(target_labels)
        shutil.copytree(source_labels, target_labels)
    copy_easycon118_extension_labels(target_labels)
    # 同步工具实际选中的统一母本；独立英/日脚本只作为原包直跑参考。
    if source != destination:
        shutil.copy2(mother_path, destination / TID_STARTER_SAVE_NAME)
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
            source = args.source.resolve()
            audit_common_label_mother(source, IMPORTED_TID_SOURCE.parent)
            mother = source / TID_STARTER_SAVE_NAME
            if hashlib.sha256(mother.read_bytes()).hexdigest() != TID_STARTER_SAVE_SHA256:
                raise ValueError("TID球前存档脚本指纹与本次确认版本不一致")
            result = args.source.resolve()
        else:
            result = import_package(
                args.source, args.destination, starter_save_source=starter_save_source
            )
    except Exception as exc:
        print(f"TID/SID 1.3.7 导入失败: {exc}", file=sys.stderr)
        return 1
    print(f"TID/SID 1.3.7 英文/日文脚本与标签校验通过: {result}")
    manifest = (
        {"scripts": {language: {"filename": TID_STARTER_SAVE_NAME}
                     for language in ("英文", "日文")}}
        if args.check_only
        else verify_tid_package(result)
    )
    for language, script in manifest["scripts"].items():
        print(f"{language}模板：{script['filename']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
