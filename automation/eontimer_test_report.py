"""Incremental, session-local reader for the temporary EonTimer test protocol."""
from __future__ import annotations

from dataclasses import asdict
import re

from .eontimer_core import Countergroup, GBA_FRAME_MS, GBA_FPS, to_milliseconds

_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_PREFIX = re.compile(r"^(?:\[\d{2}:\d{2}:\d{2}(?:\.\d+)?\]\s*)?EONTEST\|")
_INIT_KEYS = set("V TYPE SEED_TARGET ADV_TARGET F1_TARGET F2_TARGET SEED_CAL F2_CAL MULTIPLIER END".split())
_ROUND_KEYS = set("V TYPE ROUND CANDIDATES TRUTH UPDATED HIT_SEED HIT_ADV USED_SEED USED_F1 USED_F2 BASE_SEED BASE_F1 BASE_F2 NEXT_SEED NEXT_F1 NEXT_F2 SEED_CAL F2_CAL APPLIED END".split())


class EonTestReport:
    def __init__(self, run_id=""):
        self.run_id = run_id
        self.initial = None
        self.settings = None
        self.rows = []
        self.last_round = 0
        self.updated = 0
        self.skipped = 0
        self.error = ""
        self.finished = False

    def consume(self, line: str) -> bool:
        clean = _ANSI.sub("", line).strip()
        prefix = _PREFIX.match(clean)
        if not prefix:
            return False
        if self.error or self.finished:
            return False
        try:
            pairs = [part.split("=", 1) for part in clean[prefix.end():].split("|")]
            if any(len(pair) != 2 for pair in pairs) or len({key for key, _ in pairs}) != len(pairs):
                raise ValueError("字段重复或残缺")
            data = dict(pairs)
            kind = data.get("TYPE")
            expected = _INIT_KEYS if kind == "INIT" else _ROUND_KEYS if kind == "ROUND" else set()
            if set(data) != expected or data.get("V") != "1" or data.get("END") != "1":
                raise ValueError("未知版本或字段不完整")
            numeric = {key: int(value) for key, value in data.items() if key != "TYPE"}
            if any(not re.fullmatch(r"-?\d{1,10}", value) for key, value in data.items() if key != "TYPE"):
                raise ValueError("非法数值")
            if any(abs(value) > 2**31 - 1 for value in numeric.values()):
                raise ValueError("数值越界")
            if kind == "INIT":
                self._init(numeric)
            else:
                self._round(numeric)
            return True
        except (ValueError, TypeError, KeyError) as exc:
            self.error = f"EonTimer 对照记录无效：{exc}；原始运行日志保留，不影响脚本停止按钮。"
            return True

    def _init(self, data):
        if self.settings is not None or data["MULTIPLIER"] != 2 or data["F2_CAL"] != 0:
            raise ValueError("初始化冲突")
        if not 0 <= data["ADV_TARGET"] < 14400:
            raise ValueError("TV 范围不受支持")
        settings = Countergroup(data["SEED_TARGET"], data["F1_TARGET"], data["F2_TARGET"],
                                data["ADV_TARGET"], data["SEED_CAL"], 0, data["F2_CAL"])
        settings.validate()
        self.initial = self.settings = settings

    def _round(self, data):
        if self.settings is None:
            raise ValueError("缺少本次运行的初始化")
        if data["ROUND"] <= self.last_round:
            raise ValueError("轮次重复或倒退")
        if any(data[key] not in (0, 1) for key in ("TRUTH", "UPDATED", "APPLIED")):
            raise ValueError("判定标志非法")
        if data["CANDIDATES"] < 1 or data["HIT_SEED"] < 0 or data["HIT_ADV"] < 0:
            raise ValueError("反查观测越界")
        expected_update = int(data["CANDIDATES"] == 1 and data["TRUTH"] == 1)
        if data["UPDATED"] != expected_update:
            raise ValueError("非唯一结果不能更新 Calibration")
        old = self.settings
        old_points = [row["from_start_ms"] for row in old.settings()]
        used = (data["USED_SEED"], data["USED_SEED"] + data["USED_F1"], data["USED_SEED"] + data["USED_F2"])
        if tuple(old_points) != used:
            raise ValueError("已执行时间轴与本次测试参数不一致")
        seed_cal = old.seed_calibration_ms + expected_update * (old.seed_ms - data["HIT_SEED"])
        # Final FRLG F2 ADV observations use two RNG advances per GBA frame.
        # The Custom target is already normalized; apply Update in that unit.
        frame_cal = old.f2_calibration_ms + expected_update * round((old.target_advances - data["HIT_ADV"]) * GBA_FRAME_MS / 2)
        if data["SEED_CAL"] != seed_cal or data["F2_CAL"] != frame_cal:
            raise ValueError("Calibration 不符合本次 GBA / Custom 更新规则")
        next_settings = Countergroup(old.seed_ms, old.f1_frames, old.f2_frames, old.target_advances,
                                     seed_cal, 0, frame_cal)
        baseline = (data["BASE_SEED"], data["BASE_SEED"] + data["BASE_F1"], data["BASE_SEED"] + data["BASE_F2"])
        if min(baseline) < 0 or data["BASE_F2"] < data["BASE_F1"]:
            raise ValueError("伊机控对照截止无效")
        points = None
        if data["APPLIED"]:
            next_settings.validate()
            points = [row["from_start_ms"] for row in next_settings.settings()]
            reported = (data["NEXT_SEED"], data["NEXT_SEED"] + data["NEXT_F1"], data["NEXT_SEED"] + data["NEXT_F2"])
            if tuple(points) != reported:
                raise ValueError("下轮截止与 Calibration 不一致")
            self.settings = next_settings
        row = {"round": data["ROUND"], "candidates": data["CANDIDATES"], "truth": data["TRUTH"],
               "updated": bool(expected_update), "hit_seed_ms": data["HIT_SEED"], "hit_advances": data["HIT_ADV"],
               "seed_calibration_ms": seed_cal, "f2_calibration_ms": frame_cal,
               "executed_points_ms": list(used), "easycon_same_observation_points_ms": list(baseline),
               "next_eontimer_points_ms": points, "applied": bool(data["APPLIED"])}
        row["next_minus_easycon_ms"] = None if points is None else [left - right for left, right in zip(points, baseline)]
        self.rows.append(row)
        # Keep the UI bounded during long runs; the original log is complete.
        self.rows = self.rows[-500:]
        self.last_round = data["ROUND"]
        self.updated += expected_update
        self.skipped += 1 - expected_update
        if not data["APPLIED"]:
            self.finished = True

    def payload(self):
        return {"schema": "FRLG_EONTIMER_GBA_TEST_REPORT_V1", "run_id": self.run_id,
                "console": "GBA", "fps": GBA_FPS, "initial": asdict(self.initial) if self.initial else None,
                "current": asdict(self.settings) if self.settings else None, "updated_rounds": self.updated,
                "skipped_rounds": self.skipped, "rows": self.rows, "error": self.error,
                "timeline_kind": "requested_deadlines_not_measured_keypress_timestamps",
                "comparison_kind": "same_observation_easycon_calculation_not_executed"}

    def render(self):
        lines = ["EonTimer 临时计时测试 · GBA / Custom", "",
                 "工具自动换算目标并根据独立唯一反查更新；无需手填或启动外部 EonTimer。",
                 "F1 保持初始化目标；F2 观测先统一成 GBA 帧，再按 Custom 规则累加校准。",
                 "本次不运行菜单调整或 TV，不读取/写回普通预校准。",
                 "时间轴列为本轮采用/下轮计算的请求截止点，不是实测按键时间戳。",
                 "伊机控列是按同一批观测计算的对照值，并非另一组已执行的实机结果。", ""]
        if self.settings is None:
            lines.append("等待第0轮固定延迟检测完成，随后自动生成 Seed / F1 / F2 目标。")
        else:
            lines += ["阶段       单位         目标       Calibration(ms)       本段(ms)"]
            for row in self.settings.settings():
                lines.append(f"{row['phase']:<10} {row['unit']:<12} {row['target']:<10} {row['calibration_ms']:<20g} {row['duration_ms']:g}")
            lines += ["", f"已更新 {self.updated} 轮 · 非唯一跳过 {self.skipped} 轮", ""]
        for row in self.rows[-50:]:
            lines += [f"第 {row['round']} 轮：命中 Seed {row['hit_seed_ms']} ms / ADV {row['hit_advances']}；"
                      + ("已校准" if row['updated'] else "非唯一，保持原校准")]
            for index, phase in enumerate(("Seed", "F1", "F2")):
                next_ = row['next_eontimer_points_ms']
                baseline = row['easycon_same_observation_points_ms'][index]
                lines.append(f"  {phase}: 本轮请求截止 {row['executed_points_ms'][index]:g} ms；"
                             + (f"下轮 EonTimer {next_[index]:g} ms；伊机控对照 {baseline:g} ms；差 {next_[index] - baseline:+g} ms"
                                if next_ else "校准后截止不可执行，已停止测试"))
        if self.error:
            lines += ["", self.error]
        if self.finished:
            lines += ["", "本次运行已结束；完整证据保留在原日志。"]
        return "\n".join(lines)
