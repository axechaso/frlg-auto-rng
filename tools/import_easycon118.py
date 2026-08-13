"""Import the user-supplied 1.1.8 package into a local, ignored asset cache."""

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from automation.easycon118 import (  # noqa: E402
    EXPECTED_TEMPLATE_NAMES,
    EXPECTED_LABEL_COUNT,
    EXPECTED_LABEL_METHODS,
    EXPECTED_LABEL_SHA256,
    EXPECTED_SCRIPT_FILE_COUNT,
    EXPECTED_SCRIPT_SHA256,
    EXPECTED_TESSDATA_SHA256,
    inspect_label_corpus,
    inspect_script_corpus,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = Path.home() / "Downloads" / "NS火叶全自动一键乱数1.1.8"
DEFAULT_DESTINATION = ROOT / "local_assets" / "easycon118"


def import_package(source: Path, destination: Path) -> Path:
    source = source.resolve()
    destination = destination.resolve()
    if ROOT.resolve() not in destination.parents:
        raise ValueError("导入目标必须位于当前项目目录内")
    label_dir = source / "ImgLabel"
    manifest = inspect_label_corpus(label_dir)
    if manifest["count"] != EXPECTED_LABEL_COUNT:
        raise ValueError(f"标签数量不是 {EXPECTED_LABEL_COUNT}: {manifest['count']}")
    if manifest["methods"] != EXPECTED_LABEL_METHODS:
        raise ValueError(f"标签方法分布不匹配: {manifest['methods']}")
    if manifest["sha256"] != EXPECTED_LABEL_SHA256:
        raise ValueError(f"标签指纹不匹配: {manifest['sha256']}")

    script_manifest = inspect_script_corpus(source)
    if script_manifest["count"] != EXPECTED_SCRIPT_FILE_COUNT:
        raise ValueError(f"主脚本/lib 文件数不匹配: {script_manifest['count']}")
    if script_manifest["sha256"] != EXPECTED_SCRIPT_SHA256:
        raise ValueError(f"主脚本/lib 指纹不匹配: {script_manifest['sha256']}")

    templates = [source / name for name in EXPECTED_TEMPLATE_NAMES]
    if any(not path.is_file() for path in templates) or not (source / "lib").is_dir():
        raise FileNotFoundError("1.1.8 包必须包含正式/孵蛋主 ECS、lib 和 ImgLabel")
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
    for old_template in destination.glob("*.ecs"):
        old_template.unlink()
    for template in templates:
        shutil.copy2(template, destination / template.name)
    (destination / "asset_manifest.json").write_text(
        json.dumps(
            {
                "source": str(source),
                "templates": [template.name for template in templates],
                "labels": manifest,
                "scripts": script_manifest,
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
    print(f"已导入 1.1.8 正式/孵蛋脚本与 {EXPECTED_LABEL_COUNT} 标签: {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
