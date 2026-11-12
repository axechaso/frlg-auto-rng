"""Generate and Desktop-compile all 170 workflows without opening devices.

Search results here are deterministic compiler fixtures, not RNG-hit evidence.
Native `format` uses the Desktop/Interactive profile of the pinned runtime;
`compile` targets Portable and legitimately retains the 255-slot limit.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import replace
from pathlib import Path

from automation.easycon170 import cli_path, copy_adapted_script, enabled, verify_cli
from automation.easycon118 import (
    DEFAULT_SOURCE_PATH, STANDARD_TEMPLATE_NAME, EGG_TEMPLATE_NAME,
    EasyCon118Options, EggRunRequest, write_configured_project,
    write_configured_egg_project, validate_generated_project_consistency,
    validate_generated_egg_project_consistency, validate_runtime,
)
from automation.planner import AutoSearchRequest, search_best_plan
from automation.seed_modes import seed_mode_to_settings
from automation.sid_reverse118 import SIDReverseRunRequest, write_sid_reverse_project
from automation.tid_rng137 import DEFAULT_TID_SOURCE_PATH, TidRngRequest, write_configured_tid_project, validate_tid_runtime
from automation.tid_starter_flow import (
    TidStarterFlowRequest, build_tid_starter_flow_plan, write_tid_starter_flow_bundle,
    ResolvedTidStarterPlan, build_starter_run_plan, write_resolved_exhaustive_starter_project,
    validate_tid_starter_flow_runtime,
)
from rng.starter_sid_verification import StarterTarget
from rng.tenlines_utils import IVs, InitialSeedResult, SearcherResult


def fixture_plan(nx: int, *, static: bool = False):
    req = AutoSearchRequest(
        game="fr_nx2" if nx == 2 else "fr_nx", tid=12345, sid=54321,
        method="Static 1" if static else "Wild", category="Starter" if static else "Grass",
        location="" if static else "Viridian Forest", pokemon="Bulbasaur" if static else "Pikachu",
        min_advances=3000, max_advances=10000,
    )
    target = SearcherResult(
        target_seed="1234", method="Static 1" if static else "Wild 1", pokemon=req.pokemon,
        level=5 if static else 3, pid="00000001", shiny="Star", nature="Timid",
        ability="Overgrow" if static else "Static", ivs=IVs(*(31,) * 6),
        hidden_type="Dark", hidden_power=70, gender="M",
    )
    initial = InitialSeedResult(seed="75D1", advances=8021, total_frames=8021,
                                total_time="00:00:00", seed_time=40000, settings=seed_mode_to_settings(0))
    return search_best_plan(req, target_search=lambda **_: [target],
                            seed_search=lambda *_, **__: [initial]).plan


def verify(output: Path, source: Path, tid_source: Path) -> dict:
    if not enabled():
        raise ValueError("请使用默认170后端运行此验收")
    version, digest = verify_cli(cli_path())
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    results = []
    pending = []

    def check(name: str, main: Path, validation=None):
        pending.append((name, main, validation))

    def compile_case(name, main, validate):
        validation = validate() if validate else None
        if validation is not None and not validation.ok:
            raise ValueError(f"{name}: " + "\n".join(validation.errors))
        result = subprocess.run([str(cli_path()), "format", str(main)], cwd=main.parent,
                                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90)
        (output / f"{name}.format.log").write_text(result.stdout + "\n" + result.stderr, encoding="utf-8")
        if result.returncode:
            raise ValueError(f"{name}: Desktop编译失败，见 {output / (name + '.format.log')}")
        results.append({"name": name, "project": str(main), "desktop_format": result.returncode})
        print(f"PASS {name}", flush=True)

    for nx in (1, 2):
        for template in (STANDARD_TEMPLATE_NAME, EGG_TEMPLATE_NAME):
            suffix = f"{'formal' if template == STANDARD_TEMPLATE_NAME else 'timeline'}-ns{nx}"
            for static in (False, True):
                name = f"{'static' if static else 'wild'}-{suffix}"
                plan = fixture_plan(nx, static=static)
                main = write_configured_project(source, output / name, plan,
                    EasyCon118Options(nx_model=nx), template_name=template)
                validate_generated_project_consistency(main, plan, template_name=template)
                check(name, main, lambda path=main: validate_runtime(cli_path(), path))
            name = f"egg-{suffix}"
            req = EggRunRequest(game="fr_nx2" if nx == 2 else "fr_nx",
                seed_mode=1, target_seed="75D1", held_advances=8021, pickup_advances=10021,
                species_id=148, compatibility=70, parent_a_gender="雌", parent_a_ivs=(31, 30, 29, 28, 27, 26),
                parent_b_gender="雄", parent_b_ivs=(0, 1, 2, 3, 4, 5))
            main = write_configured_egg_project(source, output / name, req, template_name=template)
            validate_generated_egg_project_consistency(main, req, template_name=template)
            check(name, main, lambda path=main: validate_runtime(cli_path(), path))

        name = f"sid-ns{nx}"
        main = write_sid_reverse_project(source, output / name,
            SIDReverseRunRequest(12345, 1, nx_model=nx, dex_overrides=(1, 0, 0, 0, 0, 0)))
        check(name, main, lambda path=main: validate_runtime(cli_path(), path))
        for language in ("英文", "日文"):
            lang = "jp" if language == "日文" else "en"
            req = TidRngRequest(language=language, nx_model=nx)
            for calibrate in (False, True):
                name = f"tid-{lang}-ns{nx}-{'calibration' if calibrate else 'normal'}"
                main = write_configured_tid_project(tid_source, output / name, replace(req, calibration_check=calibrate))
                check(name, main, lambda path=main: validate_tid_runtime(cli_path(), path))
            flow_req = TidStarterFlowRequest(tid_request=replace(req, mode=0, sid_random=True),
                                             version="火红", starter="妙蛙种子", accept_any_tid=True)
            name = f"flow-{lang}-ns{nx}"
            flow_dir = output / name
            write_tid_starter_flow_bundle(tid_source, flow_dir, build_tid_starter_flow_plan(flow_req),
                                          starter_source_dir=source)
            # Resolve a deterministic identity/target fixture through the same
            # writer used after live TID recognition, without launching a game.
            target = StarterTarget("fr", language, 1, "妙蛙种子", "Bulbasaur", 12345, 54321,
                                   flow_req.starter_settings.setting_key, 0x75D1, 40000, 8021, 1,
                                   (31,) * 6, 0, 0, 0, 1)
            resolved = ResolvedTidStarterPlan(12345, 2295, 54321, flow_req, target,
                                             build_starter_run_plan(flow_req, target))
            starter = write_resolved_exhaustive_starter_project(source, flow_dir / "03_starter_118", resolved)
            id_main = flow_dir / "01_id/main.ecs"
            bridge = flow_dir / "02_lab_bridge/main.ecs"
            check(name + "-id", id_main, lambda id_path=id_main, bridge_path=bridge, starter_path=starter:
                  validate_tid_starter_flow_runtime(cli_path(), id_path, bridge_path, starter_path))
            check(name + "-bridge", bridge)
            check(name + "-starter", starter, lambda path=starter: validate_runtime(cli_path(), path))

    for template in (STANDARD_TEMPLATE_NAME, EGG_TEMPLATE_NAME):
        name = "direct-" + ("formal" if template == STANDARD_TEMPLATE_NAME else "timeline")
        main = copy_adapted_script(source / template, output / name)
        check(name, main)
    print(f"Generated {len(pending)} workflow compiler fixtures.", flush=True)
    for name, project, validation in pending:
        compile_case(name, project, validation)
    report = {"runtime_version": version, "cli_sha256": digest,
              "profile": "Desktop/Interactive", "device_operations": False, "cases": results}
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path, help="不存在的验收输出目录")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE_PATH)
    parser.add_argument("--tid-source", type=Path, default=DEFAULT_TID_SOURCE_PATH)
    args = parser.parse_args()
    report = verify(args.output, args.source, args.tid_source)
    print(f"{len(report['cases'])} Desktop compile checks passed; no devices opened.")


if __name__ == "__main__":
    main()
