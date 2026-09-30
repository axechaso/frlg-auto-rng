"""Compare complete plans and serial timings against an explicit baseline checkout."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def search(source, fixture, slow, repeat):
    command = [sys.executable, str(ROOT / "tools/profile-frlg-planner.py"),
               "--source-root", str(source), "--request", str(fixture),
               "--timing-only", "--repeat", str(repeat)]
    if slow:
        command += ["--min-advances", "0", "--max-advances", "10000"]
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1"}
    run = subprocess.run(command, cwd=source, env=env, capture_output=True,
                         text=True, encoding="utf-8", timeout=300, check=True)
    return [json.loads(line) for line in run.stdout.splitlines()]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference", type=Path)
    parser.add_argument("--include-slow", action="store_true")
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    if args.output_dir:
        args.output_dir.mkdir(parents=True, exist_ok=True)
    cases = [("wild", "golbat", False), ("static", "starter", False)]
    if args.include_slow:
        cases.append(("restricted-range", "golbat", True))
    for name, target, slow in cases:
        fixture = ROOT / f"tests/fixtures/frlg-{target}-plan.json"
        baseline = search(args.reference.resolve(), fixture, slow, 1 if slow else 3)
        current = search(ROOT, fixture, slow, 1 if slow else 3)
        expected = baseline[1]["result"]
        for report in baseline[1:] + current[1:]:
            if report["result"] != expected:
                raise AssertionError(f"{name}: complete serialized plans differ")
        if not slow and expected != json.loads(fixture.read_text(encoding="utf-8")):
            raise AssertionError(f"{name}: baseline differs from pinned fixture")
        if args.output_dir:
            for label, reports in (("before", baseline), ("after", current)):
                (args.output_dir / f"{name}-{label}.json").write_text(
                    json.dumps(reports, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"case": name, "full_result_equal": True,
                          "before_seconds": [r["search_seconds"] for r in baseline[1:]],
                          "after_seconds": [r["search_seconds"] for r in current[1:]],
                          "seed": expected["initial_seed"]["seed"],
                          "advances": expected["initial_seed"]["advances"],
                          "iv_total": expected["selection"]["iv_total"]}), flush=True)


if __name__ == "__main__":
    main()
