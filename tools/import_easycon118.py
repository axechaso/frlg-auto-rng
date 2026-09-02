"""Import the user-supplied 1.1.8 package into a local, ignored asset cache."""

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from automation.easycon118 import (  # noqa: E402
    EXPECTED_TEMPLATE_NAMES,
    EXPECTED_LABEL_COUNT,
    EXPECTED_LABEL_METHODS,
    EXPECTED_LABEL_SHA256,
    EXPECTED_SCRIPT_FILE_COUNT,
    EXPECTED_TESSDATA_SHA256,
    copy_easycon118_extension_labels,
    inspect_label_corpus,
    inspect_script_corpus,
    is_supported_script_input_sha256,
    is_supported_runtime_script_sha256,
    materialize_easycon118_164a_fixes,
)
from automation.sid_reverse118 import SID_REVERSE_TEMPLATE_NAME  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = Path.home() / "Downloads" / "NS火叶全自动一键乱数1.1.8"
DEFAULT_DESTINATION = ROOT / "local_assets" / "easycon118"
EXTENSION_DIR = ROOT / "assets" / "easycon118_extensions"


def import_package(source: Path, destination: Path) -> Path:
    source = source.resolve()
    destination = destination.resolve()
    if ROOT.resolve() not in destination.parents:
        raise ValueError("导入目标必须位于当前项目目录内")
    label_dir = source / "ImgLabel"
    # The upstream 1.1.8 package may predate either repository extension:
    # the SID shiny-male icon and the egg pond surf-complete marker. Always
    # audit a copy with both canonical labels installed so old and new source
    # folders produce the same deterministic 1150-label corpus.
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".easycon118-label-audit-",
        dir=destination.parent,
    ) as audit_root:
        inspect_dir = Path(audit_root) / "ImgLabel"
        shutil.copytree(label_dir, inspect_dir)
        copy_easycon118_extension_labels(inspect_dir)
        manifest = inspect_label_corpus(inspect_dir)
        if manifest["count"] != EXPECTED_LABEL_COUNT:
            raise ValueError(f"标签数量不是 {EXPECTED_LABEL_COUNT}: {manifest['count']}")
        if manifest["methods"] != EXPECTED_LABEL_METHODS:
            raise ValueError(f"标签方法分布不匹配: {manifest['methods']}")
        if manifest["sha256"] != EXPECTED_LABEL_SHA256:
            raise ValueError(f"标签指纹不匹配: {manifest['sha256']}")

    script_manifest = inspect_script_corpus(source)
    if script_manifest["count"] != EXPECTED_SCRIPT_FILE_COUNT:
        raise ValueError(f"主脚本/lib 文件数不匹配: {script_manifest['count']}")
    if not is_supported_script_input_sha256(script_manifest["sha256"]):
        print(
            "警告：主脚本/lib 指纹未登记，仍继续导入："
            + script_manifest["sha256"],
            file=sys.stderr,
        )

    templates = [source / name for name in EXPECTED_TEMPLATE_NAMES]
    sid_template = EXTENSION_DIR / SID_REVERSE_TEMPLATE_NAME
    if not sid_template.is_file():
        sid_template = source / SID_REVERSE_TEMPLATE_NAME
    templates.append(sid_template)
    if any(not path.is_file() for path in templates) or not (source / "lib").is_dir():
        raise FileNotFoundError("1.1.8 包必须包含正式/孵蛋/SID采集主 ECS、lib 和 ImgLabel")
    destination.mkdir(parents=True, exist_ok=True)
    for name in ("lib", "ImgLabel", "Tessdata"):
        source_path = source / name
        if name == "Tessdata":
            missing_models = [
                model for model in EXPECTED_TESSDATA_SHA256
                if not (source_path / model).is_file()
            ]
            if missing_models:
                raise FileNotFoundError(
                    "1.1.8 包缺少火叶 OCR 模型: " + ", ".join(missing_models)
                )
            mismatched_models = []
            for model, expected_sha256 in EXPECTED_TESSDATA_SHA256.items():
                actual_sha256 = hashlib.sha256((source_path / model).read_bytes()).hexdigest()
                if actual_sha256 != expected_sha256:
                    mismatched_models.append(f"{model}: {actual_sha256}")
            if mismatched_models:
                raise ValueError(
                    "1.1.8 火叶 OCR 模型指纹不一致: " + "; ".join(mismatched_models)
                )
        target = destination / name
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(source_path, target)
        if name == "ImgLabel":
            copy_easycon118_extension_labels(target)
    for old_template in destination.glob("*.ecs"):
        old_template.unlink()
    for template in templates:
        shutil.copy2(template, destination / template.name)
    installed_script_manifest = materialize_easycon118_164a_fixes(destination)
    if not is_supported_runtime_script_sha256(installed_script_manifest["sha256"]):
        print(
            "警告：1.1.8 修正合并后的脚本指纹未登记，仍继续导入："
            + installed_script_manifest["sha256"],
            file=sys.stderr,
        )
    (destination / "asset_manifest.json").write_text(
        json.dumps(
            {
                "source": str(source),
                "templates": [template.name for template in templates],
                "labels": manifest,
                "source_scripts": script_manifest,
                "scripts": installed_script_manifest,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return destination


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path, nargs="?", default=DEFAULT_SOURCE)
    parser.add_argument("--destination", type=Path, default=DEFAULT_DESTINATION)
    args = parser.parse_args()
    try:
        result = import_package(args.source, args.destination)
    except Exception as exc:
        print(f"导入失败: {exc}", file=sys.stderr)
        return 1
    print(f"已导入 2.0 正式/时间轴/SID采集脚本与 {EXPECTED_LABEL_COUNT} 标签: {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
