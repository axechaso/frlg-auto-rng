"""Read-only comparison of manual EonTimer settings and EasyCon log plans."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import re

from .eontimer_core import Countergroup, GBA_FPS, UPSTREAM_COMMIT

_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_SEED = re.compile(r"Seed绝对时间轴:\s*(?:请求|目标)\s*(\d+)\s*ms")
_F1 = re.compile(r"F1绝对时间轴:\s*目标\s*(\d+)\s*ms")
_F2 = re.compile(r"F2绝对时间轴计划:\s*自Seed确认起\s*(\d+)\s*ms")


@dataclass(frozen=True)
class EasyConPlan:
    """All three fields are planned offsets, not hardware receipt timestamps.

    Seed is from the shared timer origin. F1 and F2 are from Seed confirmation. F2 is NOT
    a duration to add after F1; keep the existing ECS absolute-anchor semantics.
    """
    seed_ms: int
    f1_from_seed_ms: int
    f2_from_seed_ms: int
    seed_line: int = 0

    def validate(self) -> None:
        for value in (self.seed_ms, self.f1_from_seed_ms, self.f2_from_seed_ms):
            if type(value) is not int or value < 0:
                raise ValueError("伊机控时间轴必须为非负整数毫秒")
        if self.f2_from_seed_ms < self.f1_from_seed_ms:
            raise ValueError("伊机控 F2 绝对截止不能早于 F1")


def read_easycon_plans(text: str) -> list[EasyConPlan]:
    """Read complete same-attempt triples; never splice incomplete attempts."""
    result = []
    pending = None
    for number, line in enumerate(_ANSI.sub("", text).splitlines(), 1):
        if any(boundary in line for boundary in ("脚本运行完成", "-- 运行终止 --", "-- 开始运行 --", "==>开始执行脚本")):
            pending = None
            continue
        seed = _SEED.search(line)
        if seed:
            pending = {"seed_ms": int(seed[1]), "seed_line": number}
            continue
        if pending is None:
            continue
        f1, f2 = _F1.search(line), _F2.search(line)
        if f1:
            if "f1_from_seed_ms" in pending:
                pending = None  # conflicting / repeated marker
            else:
                pending["f1_from_seed_ms"] = int(f1[1])
        elif f2:
            if "f1_from_seed_ms" in pending:
                plan = EasyConPlan(**pending, f2_from_seed_ms=int(f2[1]))
                plan.validate()
                result.append(plan)
            pending = None
    return result


def report(settings: Countergroup, easycon: EasyConPlan | None = None) -> dict:
    rows = settings.settings()
    payload = {
        "schema": "FRLG_EONTIMER_MANUAL_COUNTERGROUP_V1",
        "upstream_commit": UPSTREAM_COMMIT, "console": "GBA", "fps": GBA_FPS,
        "config": asdict(settings), "eontimer_custom": rows,
        "limitations": ["只计算填入 EonTimer 的数值，不启动计时器或执行游戏按键。",
                        "F1 保持手工配置；最终反查的帧误差加到 F2，不假定可以独立反查 F1。",
                        "本次不考虑菜单调整和 TV；伊机控数据必须来自同一目标、同一原点的无菜单/TV样本。",
                        "比较的是计划时间轴，不代表 Switch 收键时刻，也不证明命中率改善。"],
    }
    if easycon is not None:
        easycon.validate()
        planned = (easycon.seed_ms, easycon.seed_ms + easycon.f1_from_seed_ms,
                   easycon.seed_ms + easycon.f2_from_seed_ms)
        payload["easycon_plan"] = asdict(easycon)
        payload["comparison"] = [{"point": row["phase"], "eontimer_from_start_ms": row["from_start_ms"],
                                  "easycon_from_start_ms": deadline,
                                  "eontimer_minus_easycon_ms": row["from_start_ms"] - deadline}
                                 for row, deadline in zip(rows, planned)]
    return payload


def render_report(payload: dict) -> str:
    lines = ["EonTimer 独立对照 · GBA / Custom（只计算，不运行游戏）",
             "Seed 使用查表得到的毫秒；F1/F2 直接按输入目标帧计算。",
             "阶段 | Unit | Target | Calibration(ms) | 本段时长(ms) | 起点累计(ms)",
             "--- | --- | ---: | ---: | ---: | ---:"]
    for row in payload["eontimer_custom"]:
        lines.append(f"{row['phase']} | {row['unit']} | {row['target']} | {row['calibration_ms']:g} | "
                     f"{row['duration_ms']:g} | {row['from_start_ms']:g}")
    if "comparison" in payload:
        lines += ["", "与伊机控已校准计划对照（差值 = EonTimer − 伊机控）：",
                  "截止点 | EonTimer起点累计(ms) | 伊机控起点累计(ms) | 差值(ms)",
                  "--- | ---: | ---: | ---:"]
        for row in payload["comparison"]:
            lines.append(f"{row['point']} | {row['eontimer_from_start_ms']:g} | {row['easycon_from_start_ms']} | "
                         f"{row['eontimer_minus_easycon_ms']:+g}")
    lines += ["", *payload["limitations"]]
    return "\n".join(lines) + "\n"
