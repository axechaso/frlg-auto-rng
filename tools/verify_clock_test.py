"""Clock A/B binding/FFI/cancellation evidence, with no capture or MCU calls."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from automation import AutoSearchRequest, EasyCon118Options, EGG_TEMPLATE_NAME, write_configured_project, validate_generated_project_consistency
from automation.clock_test import ASSETS
from automation.clock_test_report import ClockTestReport
from automation.eontimer_test import apply_test_project, test_options, validate_test_project
from automation.fixed_timeline_test import FixedTimeline, request_context
from automation.planner import RunPlan
from automation.seed_modes import seed_mode_to_settings
from automation.support import get_route_support
from rng.tenlines_utils import InitialSeedResult, SearcherResult, IVs


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "local_assets/easycon118")
    parser.add_argument("--output", type=Path, required=True)
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
            request = AutoSearchRequest(game=game + ("2" if nx == 2 else ""), tid=12345, sid=54321,
                                        method=method, category=category, location=location, pokemon=pokemon, max_advances=9000)
            target = SearcherResult("1234", method, pokemon, 5, "00000001", "Star", "Timid", "Any", IVs(*(31,) * 6), "Dark", 70, "M")
            initial = InitialSeedResult("75D1", 8021, 8021, "00:00:00", 40000, seed_mode_to_settings(0))
            plan = RunPlan(request, target, initial, 186, get_route_support(method, category, location, game=game, pokemon=pokemon))
            options = test_options(EasyCon118Options(nx_model=nx, japanese_starter="jpn" in game))
            fixed = FixedTimeline(40000, 5000, 70000, "offline-binding-fixture.log", "0" * 32,
                                  request_context(request, options), initial.seed, initial.advances, 10 if "jpn" in game else 0)
            for driver in ("easycon", "eontimer"):
                project = write_configured_project(args.source, output / f"{kind}-ns{nx}-{driver}", plan, options,
                                                    template_name=EGG_TEMPLATE_NAME)
                apply_test_project(project, plan, options, advanced=True, fixed=fixed, clock_driver=driver)
                validate_generated_project_consistency(project, plan, options, template_name=EGG_TEMPLATE_NAME)
                validate_test_project(project, expected=True, fixed=fixed, clock_driver=driver)
                projects.append(project)
    checker = ROOT / "tools/EasyCon164aClockTestCheck/EasyCon164aClockTestCheck.csproj"
    subprocess.run(["dotnet", "build", str(checker), "-c", "Release", "--nologo", "--verbosity", "quiet"], check=True)
    result = subprocess.run(["dotnet", str(checker.parent / "bin/Release/net9.0/EasyCon164aClockTestCheck.dll"),
                             str(output), str(ASSETS), *(str(path) for path in projects)],
                            capture_output=True, text=True, encoding="utf-8", errors="replace")
    (output / "native-output.log").write_text(result.stdout + result.stderr, encoding="utf-8")
    print(result.stdout)
    print(result.stderr, file=sys.stderr)
    if result.returncode:
        return result.returncode
    fixed = FixedTimeline(25, 35, 100, "offline-native-fixture.log", "0" * 32, "{}", "75D1", 10, 0, 2)
    reports = {number: ClockTestReport(f"offline-driver-{number}", fixed, driver)
               for number, driver in enumerate(("easycon", "eontimer"))}
    active = None
    for line in result.stdout.splitlines():
        if line.startswith("BEGIN_DRIVER="):
            active = int(line.split("=")[1])
        elif line.startswith("END_DRIVER="):
            active = None
        elif active is not None:
            reports[active].consume(line)
    for number, report in reports.items():
        if report.error or not report.limit_reached or len(report.clock_rows) != 6 or not all(row["complete"] for row in report.clock_rows):
            raise ValueError(f"Native clock / Python protocol mismatch: {report.error}")
        (output / f"driver-{number}.clock-timing.json").write_text(json.dumps(report.payload(), ensure_ascii=False, indent=2), encoding="utf-8")
    (output / "acceptance.json").write_text(json.dumps({"hardware_access": False, "full_projects": len(projects),
        "ffi_real_execution": True, "native_cancellation": True, "protocol_parsed": True,
        "fixtures_not_shiny_performance_evidence": True}, indent=2), encoding="utf-8")
    print(f"Clock A/B offline integration passed: {len(projects)} projects, real FFI, hardware=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
