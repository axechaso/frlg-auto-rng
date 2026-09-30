"""Profile the FRLG search without changing its algorithm or result."""

import argparse
import cProfile
import json
from pathlib import Path
import platform
import pstats
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--source-root", type=Path, default=ROOT)
parser.add_argument("--request", type=Path, default=ROOT / "tests/fixtures/frlg-golbat-plan.json")
parser.add_argument("--min-advances", type=int)
parser.add_argument("--max-advances", type=int)
parser.add_argument("--repeat", type=int, default=2, help="Cold and warm searches share a process")
parser.add_argument("--timing-only", action="store_true", help="Measure latency without cProfile overhead")
parser.add_argument("--stats-dir", type=Path, help="Optional local pstats output for deeper inspection")
args = parser.parse_args()
if args.repeat < 1:
    parser.error("--repeat must be positive")
sys.path.insert(0, str(args.source_root.resolve()))
started = perf_counter()
from automation.planner import AutoSearchRequest, search_best_plan  # noqa: E402
print(json.dumps({"import_seconds": perf_counter() - started,
                  "python": platform.python_version(), "platform": platform.platform()}), flush=True)
payload = json.loads(args.request.read_text(encoding="utf-8"))
payload = payload.get("request", payload)
for field in ("min_advances", "max_advances"):
    value = getattr(args, field)
    if value is not None:
        payload[field] = value
request = AutoSearchRequest(**payload)
if args.stats_dir:
    args.stats_dir.mkdir(parents=True, exist_ok=True)
for iteration in range(args.repeat):
    profiler = cProfile.Profile()
    started = perf_counter()
    result = (search_best_plan(request) if args.timing_only else profiler.runcall(search_best_plan, request)).to_dict()
    elapsed = perf_counter() - started
    rows = []
    stats = None if args.timing_only else pstats.Stats(profiler)
    hotspots = sorted(stats.stats.items(), key=lambda item: item[1][3], reverse=True)[:20] if stats else []
    for (file, line, function), (_, calls, own_seconds, cumulative_seconds, _) in hotspots:
        try:
            file = str(Path(file).relative_to(ROOT))
        except ValueError:
            file = Path(file).name
        rows.append({"function": function, "file": file, "line": line, "calls": calls,
                     "own_seconds": round(own_seconds, 4), "cumulative_seconds": round(cumulative_seconds, 4)})
    report = {"request": payload, "result": result, "iteration": iteration + 1, "profiled": not args.timing_only, "search_seconds": elapsed,
              "total_calls": stats.total_calls if stats else None,
              "range": [request.min_advances, request.max_advances], "target": result["target"],
              "initial_seed": result["initial_seed"], "summary": result["search_summary"], "hotspots": rows}
    print(json.dumps(report, ensure_ascii=False), flush=True)
    if args.stats_dir:
        if stats:
            profiler.dump_stats(str(args.stats_dir / f"search-{iteration + 1}.pstats"))
        (args.stats_dir / f"search-{iteration + 1}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
