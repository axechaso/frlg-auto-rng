"""Calculate manual EonTimer inputs and compare an existing EasyCon timeline.

No ECS generation, runner launch, serial connection or precalibration write.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from automation.eontimer_core import Countergroup
from automation.eontimer_comparison import read_easycon_plans, render_report, report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed-ms", required=True, type=int, help="目标 Seed 查表得到的毫秒，不是 Seed 十六进制数")
    parser.add_argument("--f1", required=True, type=int, help="手工分配的 F1 Custom 目标帧；0 表示不单列这一段")
    parser.add_argument("--f2", required=True, type=int, help="手工分配的 F2 Custom 目标帧")
    parser.add_argument("--target-advances", required=True, type=int, help="最终目标消耗帧；不自动猜测 F1/F2 的帧分配")
    parser.add_argument("--seed-cal", type=float, default=0, help="EonTimer 当前 Seed Calibration 毫秒")
    parser.add_argument("--f1-cal", type=float, default=0)
    parser.add_argument("--f2-cal", type=float, default=0)
    parser.add_argument("--hit-seed-ms", type=int)
    parser.add_argument("--hit-advances", type=int)
    parser.add_argument("--candidates", type=int, help="本轮反查候选数；只有 1 才计算新的校准值")
    parser.add_argument("--easycon-log", type=Path, help="只读已校准的时间轴日志")
    parser.add_argument("--round", type=int, help="日志中第几个完整时间轴样本，从 1 开始；多样本时必须指定")
    parser.add_argument("--output", type=Path, help="可选：另存 JSON 对照记录；已有文件不覆盖")
    args = parser.parse_args(argv)
    try:
        config = Countergroup(args.seed_ms, args.f1, args.f2, args.target_advances,
                              args.seed_cal, args.f1_cal, args.f2_cal)
        config.validate()
        hit = (args.hit_seed_ms, args.hit_advances, args.candidates)
        if any(value is not None for value in hit):
            if any(value is None for value in hit):
                raise ValueError("反查校准须同时提供 --hit-seed-ms、--hit-advances、--candidates")
            config = config.calibrated(args.hit_seed_ms, args.hit_advances, candidates=args.candidates)
        plan = None
        if args.easycon_log is not None:
            plans = read_easycon_plans(args.easycon_log.read_text(encoding="utf-8-sig", errors="replace"))
            if not plans:
                raise ValueError("日志没有完整的 Seed/F1/F2 时间轴记录；不会拼接不同轮次或猜测旧日志")
            if len(plans) != 1 and args.round is None:
                raise ValueError(f"日志有 {len(plans)} 个完整样本；请用 --round 选择校准完成后的样本")
            index = 1 if args.round is None else args.round
            if not 1 <= index <= len(plans):
                raise ValueError("--round 超出完整样本范围")
            plan = plans[index - 1]
        elif args.round is not None:
            raise ValueError("--round 必须与 --easycon-log 一起使用")
        payload = report(config, plan)
        if args.output is not None:
            # Exclusive creation also prevents accidentally replacing a log/ECS
            # or someone else's saved test; do not alter normal user settings.
            with args.output.open("x", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
        print(render_report(payload), end="")
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
