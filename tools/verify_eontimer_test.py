"""Generate deterministic binding fixtures and run the pinned offline ECS checks.

These targets are compile-test fixtures, not searched/verified shiny outcomes.
Never starts the EasyCon execution runner, capture card, or MCU.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from automation import AutoSearchRequest, EasyCon118Options, EGG_TEMPLATE_NAME, write_configured_project, validate_generated_project_consistency
from automation.eontimer_test import RUNTIME_PATH, apply_test_project, test_options, validate_test_project
from automation.eontimer_test_report import EonTestReport
from automation.fixed_timeline_test import FixedTimeline, FixedTestReport, request_context
from automation.planner import RunPlan
from automation.seed_modes import seed_mode_to_settings
from automation.support import get_route_support
from rng.tenlines_utils import InitialSeedResult, SearcherResult, IVs


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "local_assets/easycon118")
    parser.add_argument("--output", type=Path, required=True, help="New evidence directory; existing directory refused")
    args = parser.parse_args(argv)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    projects = []
    for kind, game, pokemon, category, method, location in (
        ("wild-en", "fr_nx", "Pikachu", "Grass", "Wild 1", "Viridian Forest"),
        ("static-en", "lg_nx", "Articuno", "Legend", "Static 1", ""),
        ("starter-jp", "fr_jpn_nx", "Squirtle", "Starter", "Static 1", ""),
    ):
        for nx in (1, 2):
            request_game = game + ("2" if nx == 2 else "")
            request = AutoSearchRequest(game=request_game, tid=12345, sid=54321, method=method,
                                        category=category, location=location, pokemon=pokemon, max_advances=9000)
            target = SearcherResult("1234", method, pokemon, 5, "00000001", "Star", "Timid", "Any",
                                    IVs(*(31,) * 6), "Dark", 70, "M")
            initial = InitialSeedResult("75D1", 8021, 8021, "00:00:00", 40000, seed_mode_to_settings(0))
            plan = RunPlan(request, target, initial, 186, get_route_support(method, category, location, game=game, pokemon=pokemon))
            options = test_options(EasyCon118Options(nx_model=nx, japanese_starter="jpn" in game))
            project = write_configured_project(args.source, output / f"{kind}-ns{nx}", plan, options,
                                                template_name=EGG_TEMPLATE_NAME)
            validate_generated_project_consistency(project, plan, options, template_name=EGG_TEMPLATE_NAME)
            apply_test_project(project, plan, options, advanced=True)
            validate_generated_project_consistency(project, plan, options, template_name=EGG_TEMPLATE_NAME)
            validate_test_project(project, expected=True)
            projects.append(project)
            fixed = FixedTimeline(40000, 5000, 70000, "offline-fixture.log", "0" * 32,
                                  request_context(request, options), initial.seed, initial.advances,
                                  10 if "jpn" in game else 0, 5)
            fixed_project = write_configured_project(args.source, output / f"{kind}-ns{nx}-fixed", plan, options,
                                                     template_name=EGG_TEMPLATE_NAME)
            apply_test_project(fixed_project, plan, options, advanced=True, fixed=fixed)
            validate_generated_project_consistency(fixed_project, plan, options, template_name=EGG_TEMPLATE_NAME)
            validate_test_project(fixed_project, expected=True, fixed=fixed)
            projects.append(fixed_project)
    checker = ROOT / "tools/EasyCon164aEonTimerCheck/EasyCon164aEonTimerCheck.csproj"
    subprocess.run(["dotnet", "build", str(checker), "-c", "Release", "--nologo", "--verbosity", "quiet"], check=True)
    result = subprocess.run(["dotnet", str(checker.parent / "bin/Release/net9.0/EasyCon164aEonTimerCheck.dll"),
                             str(RUNTIME_PATH), *(str(path) for path in projects)],
                            capture_output=True, text=True, encoding="utf-8", errors="replace")
    print(result.stdout)
    print(result.stderr, file=sys.stderr)
    (output / "native-output.log").write_text(result.stdout + result.stderr, encoding="utf-8")
    if result.returncode:
        return result.returncode
    # Parse the actual production ECS PRINT markers emitted in native tests.
    report = EonTestReport("offline-native-check")
    fixed_report = FixedTestReport("offline-native-fixed-check")
    for line in result.stdout.splitlines():
        report.consume(line)
        fixed_report.consume(line)
    if report.error or report.updated != 2 or report.skipped != 2:
        raise ValueError(f"Native ECS / Python protocol mismatch: {report.error}, updated={report.updated}, skipped={report.skipped}")
    (output / "protocol-report.json").write_text(json.dumps(report.payload(), ensure_ascii=False, indent=2), encoding="utf-8")
    if fixed_report.error or fixed_report.attempts != 2 or len(fixed_report.rows) != 2 or not fixed_report.limit_reached:
        raise ValueError(f"Native fixed / Python protocol mismatch: {fixed_report.error}")
    (output / "fixed-protocol-report.json").write_text(json.dumps(fixed_report.payload(), ensure_ascii=False, indent=2), encoding="utf-8")
    (output / "acceptance.json").write_text(json.dumps({
        "hardware_access": False, "outcomes_are_binding_fixtures_not_shiny_evidence": True,
        "projects": [{"main": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for path in projects],
        "native_markers_parsed": True,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"EonTimer offline integration passed: {len(projects)} real generated projects, hardware=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
