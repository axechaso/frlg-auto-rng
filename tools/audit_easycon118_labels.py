"""Verify the 2.0 label corpus and optionally self-match every label."""

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from automation.easycon118 import (  # noqa: E402
    EXPECTED_LABEL_COUNT,
    EXPECTED_LABEL_METHODS,
    EXPECTED_LABEL_SHA256,
    EXPECTED_SCRIPT_FILE_COUNT,
    inspect_label_corpus,
    inspect_script_corpus,
    is_supported_script_input_sha256,
)
from easycon.label_matcher import match_prepared_label, prepare_label  # noqa: E402


DEFAULT_LABELS = Path.home() / "Downloads" / "NS火叶全自动一键乱数1.1.8" / "ImgLabel"


def audit_self_match(label_dir: Path, minimum_degree: int = 99) -> tuple[int, float]:
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    failures = []
    minimum_seen = float("inf")
    files = sorted(label_dir.glob("*.IL"), key=lambda path: path.name)
    for index, path in enumerate(files, 1):
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        prepared = prepare_label(payload)
        template = prepared["template"]
        rx, ry = prepared["rx"], prepared["ry"]
        height, width = template.shape[:2]
        frame[ry:ry + height, rx:rx + width] = template
        match = match_prepared_label(frame, prepared)
        minimum_seen = min(minimum_seen, match.degree)
        if match.easycon_degree < minimum_degree:
            failures.append((path.name, match.degree, prepared["search_method"]))
        frame[ry:ry + height, rx:rx + width] = 0
        if index % 100 == 0:
            print(f"已自匹配 {index}/{len(files)}", flush=True)
    if failures:
        sample = ", ".join(
            f"{name}:{degree:.2f}%/m{method}"
            for name, degree, method in failures[:10]
        )
        raise RuntimeError(f"{len(failures)} 个标签低于 {minimum_degree}%: {sample}")
    return len(files), minimum_seen


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("label_dir", type=Path, nargs="?", default=DEFAULT_LABELS)
    parser.add_argument("--self-match", action="store_true")
    args = parser.parse_args()

    manifest = inspect_label_corpus(args.label_dir)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    expected = (
        manifest["count"] == EXPECTED_LABEL_COUNT
        and manifest["methods"] == EXPECTED_LABEL_METHODS
        and manifest["sha256"] == EXPECTED_LABEL_SHA256
    )
    if not expected:
        print("标签清单与已审计的 2.0 资产不一致。", file=sys.stderr)
        return 2
    scripts = inspect_script_corpus(args.label_dir.parent)
    print(json.dumps({"scripts": scripts}, ensure_ascii=False, indent=2))
    if scripts["count"] != EXPECTED_SCRIPT_FILE_COUNT:
        print("主 ECS/lib 文件数与已审计的 2.0 资产不一致。", file=sys.stderr)
        return 3
    if not is_supported_script_input_sha256(scripts["sha256"]):
        print(
            "警告：主 ECS/lib 指纹未登记，继续完成标签审计："
            + scripts["sha256"],
            file=sys.stderr,
        )
    if args.self_match:
        count, minimum = audit_self_match(args.label_dir)
        print(f"全部 {count} 个标签自匹配通过；最低浮点匹配度 {minimum:.4f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
