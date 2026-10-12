"""Strict QPC wait observations plus independent fixed reverse observations."""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
import re
import statistics

from .clock_test import DRIVER_LABELS, DRIVERS
from .fixed_timeline_test import FixedTestReport, _ANSI, _STAMP


class ClockTestReport(FixedTestReport):
    def __init__(self, run_id, config, driver, *, capture_name="", labels_sha256="", native_sha256=""):
        super().__init__(run_id, config)
        if driver not in DRIVERS or config is None:
            raise ValueError("底层计时报告缺少计时器或固定参数")
        self.driver = driver
        self.capture_name = capture_name
        self.labels_sha256 = labels_sha256
        self.native_sha256 = native_sha256
        self.clock_initial = None
        self.clock_rows = []
        self.reference = None

    def consume(self, line):
        clean = _STAMP.sub("", _ANSI.sub("", line).strip())
        if not clean.startswith("CLOCKTEST|"):
            return super().consume(line)
        if self.finished or self.error:
            return False
        try:
            pairs = [part.split("=", 1) for part in clean.removeprefix("CLOCKTEST|").split("|")]
            if any(len(pair) != 2 for pair in pairs) or len({key for key, _ in pairs}) != len(pairs):
                raise ValueError("字段残缺或重复")
            data = dict(pairs)
            kind = data.get("TYPE")
            fields = {"INIT": "DRIVER SEED F1 F2 FREQ_KHZ FREQ_REMAINDER",
                      "STAGE": "ATTEMPT DRIVER STAGE STATUS TARGET_MS ELAPSED_US ERROR_US WALL_ELAPSED_MS"}.get(kind)
            if (fields is None or set(data) != set(fields.split()) | {"V", "TYPE", "END"}
                    or data["V"] != "1" or data["END"] != "1"):
                raise ValueError("未知版本或字段不完整")
            if any(not re.fullmatch(r"-?\d{1,10}", value) for key, value in data.items() if key != "TYPE"):
                raise ValueError("非法数值")
            values = {key: int(value) for key, value in data.items() if key != "TYPE"}
            if any(abs(value) > 2**31 - 1 for value in values.values()) or values["DRIVER"] != DRIVERS[self.driver]:
                raise ValueError("数值越界或计时器不一致")
            self._clock_record(kind, values)
        except (ValueError, KeyError, TypeError) as exc:
            self.error = f"底层计时记录无效：{exc}；原始日志保留。"
        return True

    def _clock_record(self, kind, data):
        expected = (self.config.seed_ms, self.config.f1_ms, self.config.f2_total_ms)
        if kind == "INIT":
            if (self.clock_initial or not self.initial or self.attempts != 1
                    or tuple(data[key] for key in ("SEED", "F1", "F2")) != expected
                    or not 1 <= data["FREQ_KHZ"] <= 10000000 or not 0 <= data["FREQ_REMAINDER"] < 1000):
                raise ValueError("初始化冲突、截止不一致或缺少固定测试初始化")
            self.clock_initial = data
            return
        stage = data["STAGE"]
        if not self.clock_initial or data["ATTEMPT"] != self.attempts or not self.attempts or stage not in (0, 1, 2):
            raise ValueError("阶段轮次不匹配或缺少初始化")
        rows = [row for row in self.clock_rows if row["attempt"] == self.attempts]
        if stage != len(rows) or data["TARGET_MS"] != expected[stage] or data["STATUS"] not in (0, 1, 2):
            raise ValueError("阶段重复、顺序错误或固定目标变化")
        complete = data["STATUS"] == 2
        if complete:
            if (data["ELAPSED_US"] < 0 or data["ERROR_US"] != data["ELAPSED_US"] - expected[stage] * 1000
                    or (stage and not rows[stage - 1]["complete"])):
                raise ValueError("时长/误差矛盾或前置阶段未完成")
            if self.driver == "eontimer" and data["ERROR_US"] < -1:
                raise ValueError("高精度等待提前结束")
        elif any(data[key] for key in ("ELAPSED_US", "ERROR_US", "WALL_ELAPSED_MS")):
            raise ValueError("未完成阶段伪造测量值")
        self.clock_rows.append({"attempt": self.attempts, "stage": stage, "status": data["STATUS"],
                               "complete": complete, "target_ms": expected[stage],
                               "elapsed_us": data["ELAPSED_US"] if complete else None,
                               "deadline_error_us": data["ERROR_US"] if complete else None,
                               "wall_elapsed_ms": data["WALL_ELAPSED_MS"] if complete else None,
                               "wall_minus_qpc_us": data["WALL_ELAPSED_MS"] * 1000 - data["ELAPSED_US"] if complete else None})

    def statistics(self):
        stats = {}
        for stage, name in enumerate(("Seed", "F1", "F2")):
            errors = [row["deadline_error_us"] for row in self.clock_rows if row["stage"] == stage and row["complete"]]
            stats[name] = {"count": len(errors), "mean_error_us": statistics.mean(errors) if errors else None,
                           "min_error_us": min(errors) if errors else None, "max_error_us": max(errors) if errors else None,
                           "stddev_us": statistics.pstdev(errors) if errors else None}
        return stats

    def comparison_key(self):
        fixed = asdict(self.config)
        fixed.pop("source_log")
        fixed.pop("repeat_limit")
        return hashlib.sha256(json.dumps({"fixed": fixed, "capture": self.capture_name,
                                          "labels": self.labels_sha256, "native": self.native_sha256}, sort_keys=True).encode()).hexdigest()

    def payload(self):
        payload = super().payload()
        payload.update(schema="FRLG_CLOCK_AB_REPORT_V1", driver=self.driver,
                       clock_initial=self.clock_initial, clock_rows=self.clock_rows, clock_statistics=self.statistics(),
                       capture_name=self.capture_name, labels_sha256=self.labels_sha256,
                       native_sha256=self.native_sha256,
                       comparison_key=self.comparison_key(), reference_run_id=(self.reference or {}).get("run_id"),
                       measurement_kind="qpc_at_wait_return_not_electrical_keypress",
                       timer_implementation="easycon_wall_clock" if self.driver == "easycon" else "eontimer_style_qpc_waitable_timer_2ms_spin")
        return payload

    def render(self):
        lines = ["底层计时 A/B · " + DRIVER_LABELS[self.driver], "",
                 "两组使用相同固定截止、不校准；Seed 用启动原点，F1/F2 共用 Seed 确认原点。",
                 "QPC 记录等待结束处的软件时间，含观测调用开销；不是单片机/游戏收到按键的时间。",
                 "B 移植 EonTimer 的单调时钟及 2 ms 不休眠尾段设计；不是原 Qt 程序的完整移植。", ""]
        if not self.clock_initial:
            lines.append("尚未取得本次完整的高精度计时初始化，不能进行计时器比较。")
        for name, stats in self.statistics().items():
            if stats["count"]:
                lines.append(f"{name}：{stats['count']} 个完整等待；误差均值 {stats['mean_error_us'] / 1000:+.3f} ms，"
                             f"范围 {stats['min_error_us'] / 1000:+.3f}～{stats['max_error_us'] / 1000:+.3f} ms，"
                             f"标准差 {stats['stddev_us'] / 1000:.3f} ms")
        for row in self.clock_rows:
            name = ("Seed", "F1", "F2")[row["stage"]]
            lines.append(f"第 {row['attempt']} 轮 {name}：" + (
                f"QPC {row['elapsed_us'] / 1000:.3f} ms / 截止误差 {row['deadline_error_us'] / 1000:+.3f} ms / "
                f"TIME 与 QPC 差 {row['wall_minus_qpc_us'] / 1000:+.3f} ms" if row["complete"] else
                "未完成，不作为零误差样本"))
        if self.reference:
            lines += ["", "同参数另一组：" + DRIVER_LABELS[self.reference["driver"]] + " · 运行 " + self.reference["run_id"]]
            for name, stats in self.reference["clock_statistics"].items():
                if stats["count"]:
                    lines.append(f"{name}：{stats['count']} 样本 / 均值 {stats['mean_error_us'] / 1000:+.3f} ms / "
                                 f"标准差 {stats['stddev_us'] / 1000:.3f} ms")
            lines.append("样本少或出闪提前结束时，不能仅凭两组平均值断言命中率改善。")
        lines += ["", super().render()]
        return "\n".join(lines)
