# -*- coding: utf-8 -*-
"""Search, rank and optionally launch a configured EasyCon 1.1.8 project."""

import argparse
import json
import signal
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from automation import (
    AutoSearchRequest,
    DEFAULT_EZCON_PATH,
    EasyCon118Options,
    NoMatchingTargetError,
    NoReachablePlanError,
    SearchWorkLimitError,
    build_run_command,
    prepare_compat_runner,
    probe_easycon_devices,
    search_best_plan,
    validate_runtime,
    write_configured_project,
)


ROOT = Path(__file__).resolve().parent
IMPORTED_SOURCE_118 = ROOT / "local_assets" / "easycon118"
DOWNLOADED_SOURCE_118 = Path.home() / "Downloads" / "NS火叶全自动一键乱数1.1.8"
DEFAULT_SOURCE_118 = IMPORTED_SOURCE_118 if IMPORTED_SOURCE_118.is_dir() else DOWNLOADED_SOURCE_118
DEFAULT_EZCON = DEFAULT_EZCON_PATH


def parse_ivs(value: str) -> tuple[int, int, int, int, int, int]:
    normalized = value.replace("/", ",").replace(" ", ",")
    parts = [part for part in normalized.split(",") if part]
    if len(parts) != 6:
        raise argparse.ArgumentTypeError("IV 必须是 6 个数字，例如 25/0/25/25/25/25")
    try:
        result = tuple(int(part) for part in parts)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("IV 只能包含整数") from exc
    if any(value < 0 or value > 31 for value in result):
        raise argparse.ArgumentTypeError("IV 必须在 0-31 之间")
    return result  # type: ignore[return-value]


def parse_seed_mode(value: str) -> int | None:
    if value.strip().lower() in {"auto", "any", "自动"}:
        return None
    try:
        result = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Seed 模式应为 auto 或 0-9") from exc
    if not 0 <= result <= 9:
        raise argparse.ArgumentTypeError("Seed 模式应为 auto 或 0-9")
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="火红/叶绿自动乱数首版计划器")
    parser.add_argument("--game", choices=("fr_nx", "lg_nx", "fr_nx2", "lg_nx2"), required=True)
    parser.add_argument("--tid", type=int, required=True)
    parser.add_argument("--sid", type=int, required=True)
    parser.add_argument("--method", choices=("Static", "Wild", "Static 1", "All Wild Methods"), required=True)
    parser.add_argument("--category", required=True, help="例如 Gift、Grass、SuperRod")
    parser.add_argument("--location", default="", help="野生地点的 Ten Lines 英文名")
    parser.add_argument("--pokemon", required=True, help="英文名或全国图鉴编号")
    parser.add_argument("--min-advances", type=int, default=3000)
    parser.add_argument("--max-advances", type=int, required=True)
    parser.add_argument("--iv-min", type=parse_ivs, default=(0, 0, 0, 0, 0, 0))
    parser.add_argument("--iv-max", type=parse_ivs, default=(31, 31, 31, 31, 31, 31))
    parser.add_argument("--shiny", choices=("Any", "None", "Star", "Square", "Star/Square"), default="Star/Square")
    parser.add_argument("--nature", default="Any")
    parser.add_argument("--gender", choices=("Any", "M", "F", "-"), default="Any")
    parser.add_argument("--ability", default="Any")
    parser.add_argument("--hidden-type", default="Any")
    parser.add_argument("--seed-mode", type=parse_seed_mode, default=None, metavar="auto|0-9")
    parser.add_argument("--seed-candidates", type=int, default=1)
    parser.add_argument("--search-work-limit", type=int, default=25_000_000)

    parser.add_argument("--source-118", type=Path, default=DEFAULT_SOURCE_118)
    parser.add_argument("--output", type=Path, default=ROOT / "runtime" / "easycon118")
    parser.add_argument("--nx-model", type=int, choices=(1, 2))
    parser.add_argument("--auto-capture", action="store_true")
    parser.add_argument("--paralysis", action="store_true")
    parser.add_argument("--false-swipe", action="store_true")
    parser.add_argument(
        "--item-rng",
        action="store_true",
        help="野生目标启用道具乱数模式",
    )
    parser.add_argument(
        "--party-empty-slots",
        type=int,
        choices=range(1, 6),
        default=1,
        metavar="1-5",
        help="道具乱数模式下队伍预留的空位数量",
    )

    parser.add_argument("--ezcon", type=Path, default=DEFAULT_EZCON)
    parser.add_argument("--port", default="COM22")
    parser.add_argument("--video-device", type=int, default=0)
    parser.add_argument("--video-type", choices=("ANY", "DSHOW", "MSMF"), default="DSHOW")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument(
        "--run",
        action="store_true",
        help="完成生成和预检后立即把控制权交给 ezcon；不写此参数只生成计划",
    )
    return parser


def print_plan(result) -> None:
    plan = result.plan
    ivs = plan.target.ivs
    print("\n已生成方案")
    print(f"  宝可梦: {plan.request.pokemon} / {plan.target.nature} / {plan.target.shiny}")
    print(
        "  IV: "
        f"{ivs.hp}/{ivs.attack}/{ivs.defense}/{ivs.sp_attack}/{ivs.sp_defense}/{ivs.speed} "
        f"(总和 {plan.iv_total}, 平均 {plan.iv_average:.2f})"
    )
    print(f"  目标状态 Seed: {plan.target.target_seed} ({plan.target.method})")
    print(
        f"  初始 Seed: {plan.initial_seed.seed} | Advance: {plan.initial_seed.advances} "
        f"| Seed 模式: {plan.seed_mode}"
    )
    print(f"  路线状态: {plan.route_support.level.value} | 可启动: {plan.route_support.can_start}")
    print(
        f"  扫描到 {result.matching_outcomes} 个候选结果，"
        f"{result.feasible_routes} 条路线符合 Advance 范围。"
    )
    for warning in plan.warnings:
        print(f"  注意: {warning}")


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    method = {
        "Static": "Static 1",
        "Wild": "All Wild Methods",
    }.get(args.method, args.method)
    location = args.location or args.category
    request = AutoSearchRequest(
        game=args.game,
        tid=args.tid,
        sid=args.sid,
        method=method,
        category=args.category,
        location=location,
        pokemon=args.pokemon,
        min_advances=args.min_advances,
        max_advances=args.max_advances,
        iv_min=args.iv_min,
        iv_max=args.iv_max,
        shiny=args.shiny,
        nature=args.nature,
        gender=args.gender,
        ability=args.ability,
        hidden_type=args.hidden_type,
        initial_seed_result_count=args.seed_candidates,
        max_iv_combinations=args.search_work_limit,
        seed_mode=args.seed_mode,
    )

    print("正在按 IV 总和从高到低搜索 Ten Lines 结果……", flush=True)
    try:
        result = search_best_plan(request)
    except (ValueError, NoMatchingTargetError, NoReachablePlanError, SearchWorkLimitError) as exc:
        print(f"无可用方案: {exc}", file=sys.stderr)
        return 2
    print_plan(result)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    plan_dir = ROOT / "rng_logs" / "plans"
    plan_dir.mkdir(parents=True, exist_ok=True)
    plan_path = plan_dir / f"{timestamp}.json"
    plan_path.write_text(
        json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"  计划文件: {plan_path}")

    if not result.plan.route_support.can_start:
        print("该路线仅保存搜索计划；首版不会为它生成或运行 ECS。")
        return 5 if args.run else 0

    options = EasyCon118Options(
        nx_model=args.nx_model,
        paralysis=args.paralysis,
        false_swipe=args.false_swipe,
        continue_capture_after_shiny=args.auto_capture,
        item_rng_mode=args.item_rng,
        party_empty_slots=args.party_empty_slots,
    )
    try:
        main_path = write_configured_project(
            args.source_118,
            args.output,
            result.plan,
            options,
        )
    except (OSError, ValueError) as exc:
        print(f"1.1.8 项目生成失败: {exc}", file=sys.stderr)
        return 3
    print(f"  EasyCon 项目: {main_path}")

    check = validate_runtime(args.ezcon, main_path)
    for warning in check.warnings:
        print(f"  预检提示: {warning}")
    if not check.ok:
        for error in check.errors:
            print(f"  预检失败: {error}", file=sys.stderr)
        return 4

    selected_port = args.port.strip().upper()
    runner_path = args.ezcon
    if args.run:
        try:
            runner_path = prepare_compat_runner(args.ezcon)
        except (OSError, ValueError, RuntimeError) as exc:
            print(f"启动后端检查失败: {exc}", file=sys.stderr)
            return 7
    command = build_run_command(
        runner_path,
        main_path,
        port=selected_port,
        video_device=args.video_device,
        video_type=args.video_type,
        verbose=args.verbose,
    )
    print("  启动命令:", subprocess.list2cmdline(command))
    if not args.run:
        print("未使用 --run；已安全停在计划/脚本生成阶段。")
        return 0
    try:
        ports, videos, _ = probe_easycon_devices(args.ezcon)
    except Exception as exc:
        print(f"设备预检失败: {exc}", file=sys.stderr)
        return 6
    if selected_port not in ports:
        print(f"设备预检失败: 未检测到串口 {selected_port}", file=sys.stderr)
        return 6
    if args.video_device not in videos:
        print(f"设备预检失败: 未检测到采集卡序号 {args.video_device}", file=sys.stderr)
        return 6
    print("开始运行 EasyCon 1.1.8；按 Ctrl+C 可请求停止。", flush=True)
    flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    process = subprocess.Popen(command, cwd=str(main_path.parent), creationflags=flags)
    try:
        return process.wait()
    except KeyboardInterrupt:
        try:
            process.send_signal(signal.CTRL_BREAK_EVENT)
            process.wait(timeout=5)
        except (OSError, AttributeError, subprocess.TimeoutExpired):
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
