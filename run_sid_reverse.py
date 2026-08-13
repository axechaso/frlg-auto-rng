"""Analyze EasyCon SIDREV observations or a saved SID reverse log."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from rng.sid_reverse_workflow import analyze_shiny_team, parse_sid_reverse_log
from rng.sid_reverse import DEFAULT_SID_SEARCH_ADVANCES, canonical_sid_for_psv
from rng.tenlines_utils import NATURES


def _format_ivs(values: tuple[int, ...]) -> str:
    return "/".join(str(value) for value in values)


def build_report(text: str, *, tid_override: int | None = None, game: str = "fr_nx") -> str:
    logged_tid, observations = parse_sid_reverse_log(text)
    tid = tid_override if tid_override is not None else logged_tid
    if tid is None:
        raise ValueError("log has no SIDREV META TID; pass --tid")
    if not observations:
        raise ValueError("log has no SIDREV observation")
    team = analyze_shiny_team(tid, observations, game=game)

    lines = [f"TID: {tid:05d}", ""]
    for item in team.pokemon:
        source = "定点" if item.source_type == "STATIC" else "野生"
        lines.append(
            f"#{item.pokemon_index} {item.species_name} / {NATURES[item.nature]}: "
            f"{item.observations}组观测；来源: {source}"
        )
        if item.location:
            categories = "/".join(item.encounter_categories)
            lines.append(f"  相遇地点: {item.location}；匹配方式: {categories}")
        lines.append(f"  努力值: {_format_ivs(item.effort_values)}")
        lines.append(f"  IV范围: {_format_ivs(item.iv_min)} - {_format_ivs(item.iv_max)}")
        lines.append(f"  PID候选: {len(item.candidates)}；PSV候选: {len(item.psvs)}")
        if len(item.candidates) <= 12:
            candidates = ", ".join(
                f"{candidate.pid:08X}({candidate.method_name},PSV {candidate.psv})"
                for candidate in item.candidates
            )
            lines.append("  " + candidates)
        lines.append("")

    result = team.result
    if not result.common_psvs:
        lines.append("结果: 没有共同PSV。")
        lines.append("请检查OCR、努力值、Method 1/2/4来源，以及每只宝可梦是否都在此存档中为闪光。")
    elif len(result.common_psvs) > 1:
        values = ", ".join(str(value) for value in result.common_psvs)
        lines.append(f"结果: 仍有{len(result.common_psvs)}个共同PSV: {values}")
        lines.append("需要继续反查下一只闪光宝可梦。")
    else:
        psv = result.common_psvs[0]
        sid_values = ", ".join(f"{sid:05d}" for sid in result.sid_candidates)
        lines.append(f"结果: PSV已经唯一: {psv}")
        lines.append(
            f"工具兼容反查SID（低3位清零）: "
            f"{canonical_sid_for_psv(tid, psv):05d}"
        )
        lines.append(f"真实SID候选（8个）: {sid_values}")
        lines.append(
            f"按TID作为初始Seed搜索前{DEFAULT_SID_SEARCH_ADVANCES} ADV，"
            "窗口内首次出现如下："
        )
        if result.sid_advances:
            lines.extend(
                f"  SID {item.sid:05d}: ADV {item.advance}"
                for item in result.sid_advances
            )
            lines.append(
                f"最终SID（窗口内最早ADV）: {result.selected_sid:05d}；"
                f"ADV: {result.selected_advance}"
            )
        else:
            lines.append(
                f"  前{DEFAULT_SID_SEARCH_ADVANCES} ADV没有出现任何SID候选，"
                "本次不确定最终SID。"
            )
        lines.append(
            "说明: 8个SID都满足闪光公式；最终值仅按TID/SID 1.3.7生成链"
            f"前{DEFAULT_SID_SEARCH_ADVANCES} ADV内的最早命中选取。"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reverse Gen 3 shiny PSV/SID candidates")
    parser.add_argument("log", type=Path, help="EasyCon log containing SIDREV records")
    parser.add_argument("--tid", type=int, help="override the TID recorded in the log")
    parser.add_argument("--game", choices=("fr_nx", "lg_nx"), default="fr_nx")
    args = parser.parse_args(argv)
    try:
        text = args.log.read_text(encoding="utf-8-sig", errors="replace")
        print(build_report(text, tid_override=args.tid, game=args.game))
    except (OSError, ValueError) as exc:
        print(f"SID反查失败: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
