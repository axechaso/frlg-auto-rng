"""Validate synchronized release scripts offline; never send controller input."""

import argparse
from dataclasses import replace
import hashlib
from itertools import product
import json
from pathlib import Path
import subprocess
import sys
import shutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from automation import easycon118 as ecs
from automation.sid_reverse118 import SIDReverseRunRequest, write_sid_reverse_project
from automation.tid_starter_save import TID_STARTER_SAVE_NAME, TID_STARTER_SAVE_SHA256
from automation.tid_starter_flow import enable_starter_success_markers
from tests.test_easycon118_egg import egg_request
from tools.verify_sid_observation import generate_matrix as sid_evidence_matrix
from tools.verify_tid_bootstrap_integration import generate_matrix as tid_matrix


def verify(source: Path, tid_source: Path, output: Path, ezcon: Path) -> dict:
    source, tid_source, output, ezcon = (
        path.resolve() for path in (source, tid_source, output, ezcon)
    )
    if output.exists():
        raise ValueError("验收目录已存在；请选择新目录，避免覆盖旧证据")
    if source == output or source in output.parents or tid_source in output.parents:
        raise ValueError("验收输出不能写入母本资源目录")
    version = subprocess.run([str(ezcon), "--version"], capture_output=True,
                             text=True, encoding="utf-8", timeout=20, check=True)
    if ecs.EXPECTED_EZCON_VERSION not in version.stdout:
        raise ValueError("验收必须使用固定的 EasyCon 1.6.4-a")
    scripts, labels = ecs.inspect_script_corpus(source), ecs.inspect_label_corpus(source / "ImgLabel")
    if scripts["count"] != 34 or not ecs.is_supported_runtime_script_sha256(scripts["sha256"]):
        raise ValueError("2.0 母本、31个运行库及Seed表状态文件不属于本次已审计语料")
    if labels["count"] != ecs.EXPECTED_LABEL_COUNT or labels["sha256"] != ecs.EXPECTED_LABEL_SHA256:
        raise ValueError("共同标签语料不一致")
    tid_sha = hashlib.sha256((tid_source / TID_STARTER_SAVE_NAME).read_bytes()).hexdigest()
    if tid_sha != TID_STARTER_SAVE_SHA256:
        raise ValueError("必须保留用户确认的 TID r5，不接受下载包恢复的 r4")
    output.mkdir(parents=True)
    paths = []
    for template in ecs.EXPECTED_TEMPLATE_NAMES:
        main = source / template
        text = main.read_text(encoding="utf-8")
        if not ecs._uses_upstream_unified_seed_controller(text) or text.count("# EGG_MODULE_DELEGATE:") != 12:
            raise ValueError("新版统一控制器或孵蛋模块委托缺失")
        paths.append(("mother", main))
    paths.extend(("sid-evidence", path) for path in sid_evidence_matrix(source, output / "sid-evidence"))
    paths.extend(("tid-r5", path) for path in tid_matrix(tid_source, output / "tid-r5"))
    marker_root = output / "tid-starter-markers"
    shutil.copytree(source, marker_root)
    for template in ecs.EXPECTED_TEMPLATE_NAMES:
        path = marker_root / template
        path.write_text(enable_starter_success_markers(path.read_text(encoding="utf-8")), encoding="utf-8")
        paths.append(("tid-starter-marker", path))
    for template, startup, prepared, calibration in product(
        ecs.EXPECTED_TEMPLATE_NAMES, (0, 1), (False, True), (0, 1, 2)
    ):
        directory = output / "egg" / f"{Path(template).stem}-start{startup}-prepared{int(prepared)}-cal{calibration}"
        request = replace(egg_request(), seed_startup_scheme=startup,
                          start_from_prepared_254=prepared,
                          seed_calibration_scheme=calibration,
                          update_precalibration=False)
        main = ecs.write_configured_egg_project(source, directory, request,
                    template_name=template, precalibration_store_path=output / "unused-precalibration.json")
        text = main.read_text(encoding="utf-8")
        if text.count("# EGG_MODULE_DELEGATE:") != 12:
            raise ValueError("生成孵蛋工程丢失模块委托")
        if not (main.parent / "lib/29_孵蛋校准.ecs").is_file():
            raise ValueError("生成孵蛋工程未复制校准库")
        paths.append(("egg", main))
    for template in ecs.EXPECTED_TEMPLATE_NAMES:
        request = replace(egg_request(), egg_seed_reverse_seed_tolerance=7,
                          egg_seed_reverse_min_advances=700,
                          egg_seed_reverse_max_advances=8700,
                          update_precalibration=False)
        main = ecs.write_configured_egg_project(source, output / "egg-advanced" / Path(template).stem,
                    request, template_name=template, precalibration_store_path=output / "unused-precalibration.json")
        ecs.validate_generated_egg_project_consistency(main, request, template_name=template)
        paths.append(("egg-advanced", main))
    for game, model, adaptive in product(("fr_nx", "lg_nx"), (1, 2), (False, True)):
        directory = output / "sid-capture" / f"{game}-ns{model}-adaptive{int(adaptive)}"
        request = SIDReverseRunRequest(tid=12345, party_count=1, game=game, nx_model=model,
                    dex_overrides=(18, 0, 0, 0, 0, 0), initial_levels=(36, 1, 1, 1, 1, 1),
                    home_buffer_adaptive_threshold=adaptive)
        paths.append(("sid-capture", write_sid_reverse_project(source, directory, request)))
    rows = []
    for index, (kind, main) in enumerate(paths):
        result = subprocess.run([str(ezcon), "format", str(main), "-o", str(output / f"formatted-{index:03}.ecs")],
                    cwd=main.parent, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
        (output / f"format-{index:03}.log").write_text(result.stdout + result.stderr, encoding="utf-8")
        rows.append({"kind": kind, "path": str(main), "sha256": hashlib.sha256(main.read_bytes()).hexdigest(),
                     "format_exit": result.returncode})
        if result.returncode != 0:
            raise RuntimeError(f"{kind} 格式验收失败：{main}\n{result.stdout}{result.stderr}")
        print(f"PASS {index + 1}/{len(paths)}: {kind} {main.name}", flush=True)
    report = {"hardware_access": False, "runtime": version.stdout.strip(), "scripts": scripts,
              "labels": labels, "tid_mother_version": "2026-09-25-r5", "tid_mother_sha256": tid_sha,
              "count": len(rows), "matrix": rows}
    (output / "verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "local_assets/easycon118")
    parser.add_argument("--tid-source", type=Path, default=ROOT / "local_assets/tid_rng137")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ezcon", type=Path, required=True)
    args = parser.parse_args()
    report = verify(args.source, args.tid_source, args.output, args.ezcon)
    print(f"Offline acceptance: {report['count']}/{report['count']} format checks passed; no hardware input.")


if __name__ == "__main__":
    main()
