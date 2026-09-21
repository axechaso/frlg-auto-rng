"""Generate and compile TID search variants with the native ECS engine."""
from dataclasses import replace
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from easycon.native import EasyConScriptEngine, ScriptCompileError
from automation.tid_checkpoint import instrument_tid_checkpoint
from automation.tid_rng137 import TidRngRequest, configure_tid_template_text
from automation.tid_starter_flow import enable_any_tid_handoff
from automation.tid_starter_save import DEFAULT_TID_STARTER_SAVE_SOURCE


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    shutil.copytree(DEFAULT_TID_STARTER_SAVE_SOURCE.parent / "ImgLabel", args.output / "ImgLabel", dirs_exist_ok=True)
    source = DEFAULT_TID_STARTER_SAVE_SOURCE.read_text(encoding="utf-8-sig")
    results = []
    for language in ("英文", "日文"):
        base = TidRngRequest(language=language, player_name="Alxe" if language == "英文" else "レット゛")
        cases = {
            "rng": replace(base, op_rng_range=20, f1_rng_range=20, f2_rng_range=10),
            "clamp": replace(base, op_target_frame=0, f1_rng_range=99999, f2_rng_range=-1),
            "auto": replace(base, mode=0, auto_rng=True, additional_target_tids=(0,33333,65535), sid_random=True),
            "auto_sid": replace(base, mode=0, auto_rng=True, additional_target_tids=(0,33333)),
            "multi": replace(base, mode=0, additional_target_tids=(0,33333,65535), sid_random=True),
            "calibration": replace(base, mode=0, auto_rng=True, calibration_check=True),
            "any": replace(base, mode=0, sid_random=True),
        }
        for name, request in cases.items():
            configured = configure_tid_template_text(source, request, include_flow_marker=True)
            if name == "any": configured = enable_any_tid_handoff(configured)
            if name not in ("calibration", "any"):
                configured = instrument_tid_checkpoint(configured, request)
            path = args.output / (("en" if language == "英文" else "jp") + "_" + name + ".ecs")
            path.write_text(configured, encoding="utf-8")
            try:
                EasyConScriptEngine().load_file(path)
                code, output = 0, "原生 ECS 编译通过"
            except ScriptCompileError as exc:
                code, output = 2, str(exc)
            path.with_suffix(".compile.log").write_text(output, encoding="utf-8")
            results.append({"case": path.name, "exit_code": code, "output": output})
            print(path.name, code, flush=True)
    (args.output / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    if any(item["exit_code"] != 0 for item in results):
        raise SystemExit(1)


if __name__ == "__main__": main()
