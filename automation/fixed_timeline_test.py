"""Immutable fixed-deadline experiments; never read/write pre-calibration."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re

_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_STAMP = re.compile(r"^\[\d{2}:\d{2}:\d{2}(?:\.\d+)?\]\s*")
_SEED = re.compile(r"^Seed绝对时间轴: 请求(\d+) ms，实际\s*(\d+) ms，超时\s*0 ms$")
_F1 = re.compile(r"^F1绝对时间轴: 目标(\d+) ms，实际\s*(\d+) ms，超时\s*0 ms$")
_F2 = re.compile(r"^F2绝对时间轴计划: 自Seed确认起(\d+) ms$")
_END = re.compile(r"FRLG_INPUT_SESSION\|V=1\|RUN=([0-9a-f]{32})\|SESSION=[0-9a-f]{32}\|STAGE=wild\|STATE=ENDED\|END=1$")


def request_context(request, options) -> str:
    """Exclude search filters, but bind identity, route and startup semantics."""
    return json.dumps({key: getattr(request, key) for key in
                       ("game", "tid", "sid", "method", "category", "location", "pokemon")}
                      | {key: getattr(options, key) for key in
                         ("nx_model", "seed_startup_scheme", "mystery_gift_enabled")},
                      ensure_ascii=False, sort_keys=True)


@dataclass(frozen=True)
class FixedTimeline:
    seed_ms: int
    f1_ms: int
    f2_total_ms: int
    source_log: str
    source_run_id: str
    context: str
    initial_seed: str
    advances: int
    seed_mode: int
    repeat_limit: int = 5

    def validate(self):
        if any(type(value) is not int for value in
               (self.seed_ms, self.f1_ms, self.f2_total_ms, self.advances, self.seed_mode, self.repeat_limit)):
            raise ValueError("固定时长测试的参数必须是整数")
        if not (0 < self.seed_ms <= 1000000 and 0 < self.f1_ms < self.f2_total_ms <= 1000000
                and 0 <= self.advances < 14400 and 0 <= self.seed_mode <= 10
                and 1 <= self.repeat_limit <= 20):
            raise ValueError("固定时长测试的时间轴或轮数范围无效")
        if not re.fullmatch(r"[0-9A-F]{4}", self.initial_seed) or not re.fullmatch(r"[0-9a-f]{32}", self.source_run_id):
            raise ValueError("固定时长测试缺少有效的源目标或运行标识")
        if not isinstance(json.loads(self.context), dict) or not self.source_log:
            raise ValueError("固定时长测试缺少源运行信息")

    def validate_request(self, request, options):
        self.validate()
        if self.context != request_context(request, options):
            raise ValueError("固定时长来自另一目标、存档、机型或启动方式；请重新读取最近成功时长")
        if request.direct_mode and (str(request.direct_seed).upper().removeprefix("0X") != self.initial_seed
                                    or request.direct_advances != self.advances):
            raise ValueError("指定的 Seed / 消耗帧与固定时长源目标不同，请重新读取或恢复源目标")
        requested_mode = 10 if "_jpn_" in request.game else request.seed_mode
        if requested_mode is not None and requested_mode != self.seed_mode:
            raise ValueError("Seed 模式与固定时长源目标不同，请重新读取或恢复源模式")

    def validate_plan(self, plan, options):
        self.validate_request(plan.request, options)
        from .seed_modes import settings_to_seed_mode
        mode = 10 if "_jpn_" in plan.request.game else settings_to_seed_mode(plan.initial_seed.settings)
        if (plan.initial_seed.seed.upper(), plan.initial_seed.advances, mode) != (
                self.initial_seed, self.advances, self.seed_mode):
            raise ValueError(f"本次搜索换了目标，不能复用固定时长；请指定 Seed {self.initial_seed} / "
                             f"消耗帧 {self.advances} / Seed 模式 {self.seed_mode} 后重新生成")


def read_successful_timeline(log: Path, request, options) -> FixedTimeline | None:
    """Accept complete, same-context timeline logs, not truncated previews/reports.

    Entry detection is only a logged shiny classification. This does NOT invent
    a PID/ADV confirmation for a terminal round that skipped reverse lookup.
    """
    log = Path(log)
    manifest = log.parent / "plan.json"
    if log.is_symlink() or manifest.is_symlink() or not manifest.is_file():
        return None
    try:
        if log.stat().st_size > 16 * 1024 * 1024 or manifest.stat().st_size > 1024 * 1024:
            return None
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        plan, saved_options = payload["plan"], payload["easycon118_options"]
        wanted = json.loads(request_context(request, options))
        saved = {key: plan["request"][key] for key in
                 ("game", "tid", "sid", "method", "category", "location", "pokemon")}
        saved.update({key: saved_options[key] for key in
                      ("nx_model", "seed_startup_scheme", "mystery_gift_enabled")})
        if wanted != saved or saved_options.get("frame_parity_scheme") != 0:
            return None
        if payload.get("template") != "NS火叶全自动一键乱数2.0-时间轴.ecs":
            return None
        # A fixed test cannot manufacture a new success source for itself.
        if payload.get("eontimer_test", {}).get("mode") == "fixed":
            return None
        text = _ANSI.sub("", log.read_text(encoding="utf-8"))
        lines = [_STAMP.sub("", line).strip() for line in text.splitlines()]
        end = _END.search(lines[-1]) if lines else None
        if not end or log.stem != "easycon-" + end[1] or "脚本运行完成" not in lines[-1]:
            return None
        # Parse one uninterrupted final attempt. A newer partial/failed run
        # cannot donate the successful deadlines from an earlier attempt.
        seed = f1 = f2 = None
        f2_reached = shiny = stopped = False
        for line in lines[:-1]:
            if line.startswith("第") and re.fullmatch(r"第\d+轮(?:开始)?", line):
                seed = f1 = f2 = None
                f2_reached = shiny = stopped = False
            if match := _SEED.fullmatch(line):
                seed, f1, f2 = int(match[1]), None, None
                f2_reached = shiny = stopped = False
                if int(match[2]) != seed:
                    seed = None
            elif match := _F1.fullmatch(line):
                f1 = int(match[1]) if int(match[2]) == int(match[1]) and seed else None
            elif match := _F2.fullmatch(line):
                f2 = int(match[1]) if f1 else None
            elif re.fullmatch(r"F2绝对时间轴\([^)]*\): 超时\s*0 ms", line):
                f2_reached = f2 is not None
            elif line.startswith("时差检测到出闪:"):
                shiny = f2_reached
            elif line == "目标获取流程结束，停止脚本":
                stopped = shiny
        if not (seed and f1 and f2 and shiny and stopped):
            return None
        initial = plan["initial_seed"]
        result = FixedTimeline(seed, f1, f2, str(log.resolve()), end[1], request_context(request, options),
                               initial["seed"].upper(), initial["advances"], plan["execution"]["seed_mode"])
        result.validate_request(request, options)
        return result
    except (OSError, UnicodeError, KeyError, TypeError, ValueError, AttributeError):
        return None


def find_successful_timeline(entries, request, options, *, cancelled=lambda: False):
    for entry in entries:
        if cancelled():
            return None
        if result := read_successful_timeline(entry.path, request, options):
            return result
    raise ValueError("没有找到同一目标、存档、机型和启动方式的完整成功时间轴日志。"
                     "先完成一次普通时间轴或 EonTimer 自动校准运行，再读取；不会借用其他目标的时长。")


class FixedTestReport:
    """Strict run-local diagnostic; fixed observations never imply calibration."""
    def __init__(self, run_id="", config: FixedTimeline | None = None):
        self.run_id, self.config = run_id, config
        self.initial = None
        self.rows = []
        self.attempts = self.updated = self.skipped = 0
        self.error = ""
        self.finished = False
        self.limit_reached = False

    def consume(self, line):
        clean = _STAMP.sub("", _ANSI.sub("", line).strip())
        if not clean.startswith("FIXEDTEST|") or self.finished or self.error:
            return False
        try:
            pairs = [part.split("=", 1) for part in clean.removeprefix("FIXEDTEST|").split("|")]
            if any(len(pair) != 2 for pair in pairs) or len({key for key, _ in pairs}) != len(pairs):
                raise ValueError("字段残缺或重复")
            data = dict(pairs)
            kind = data.get("TYPE")
            keys = {
                "INIT": "SEED_TARGET ADV_TARGET USED_SEED USED_F1 USED_F2 LIMIT",
                "ATTEMPT": "ATTEMPT", "STOP": "ATTEMPTS",
                "ROUND": "ATTEMPT CANDIDATES TRUTH HIT_SEED HIT_ADV USED_SEED USED_F1 USED_F2 APPLIED",
            }.get(kind)
            if keys is None or set(data) != set(keys.split()) | {"V", "TYPE", "END"} or data["V"] != "1" or data["END"] != "1":
                raise ValueError("未知版本或字段不完整")
            if any(not re.fullmatch(r"-?\d{1,10}", value) for key, value in data.items() if key != "TYPE"):
                raise ValueError("非法数值")
            numbers = {key: int(value) for key, value in data.items() if key != "TYPE"}
            if any(abs(value) > 2**31 - 1 for value in numbers.values()):
                raise ValueError("数值越界")
            self._record(kind, numbers)
        except (ValueError, TypeError, KeyError) as exc:
            self.error = f"固定时长测试记录无效：{exc}；原始日志保留。"
        return True

    def _record(self, kind, data):
        if kind == "INIT":
            if self.initial or not (0 < data["SEED_TARGET"] <= 1000000 and 0 <= data["ADV_TARGET"] < 14400
                                    and 0 < data["USED_SEED"] <= 1000000
                                    and 0 < data["USED_F1"] < data["USED_F2"] <= 1000000
                                    and 1 <= data["LIMIT"] <= 20):
                raise ValueError("初始化无效或冲突")
            if self.config and (data["USED_SEED"], data["USED_F1"], data["USED_F2"], data["LIMIT"], data["ADV_TARGET"]) != (
                    self.config.seed_ms, self.config.f1_ms, self.config.f2_total_ms, self.config.repeat_limit, self.config.advances):
                raise ValueError("初始化与生成时固定的参数不一致")
            self.initial = data
            return
        if not self.initial:
            raise ValueError("缺少本次初始化")
        if kind == "ATTEMPT":
            if data["ATTEMPT"] != self.attempts + 1 or data["ATTEMPT"] > self.initial["LIMIT"]:
                raise ValueError("轮次不连续或超过上限")
            self.attempts += 1
        elif kind == "STOP":
            if data["ATTEMPTS"] != self.attempts or self.attempts != self.initial["LIMIT"]:
                raise ValueError("轮数上限记录不一致")
            self.finished = self.limit_reached = True
        else:
            if data["ATTEMPT"] != self.attempts or not self.attempts or any(row["attempt"] == self.attempts for row in self.rows):
                raise ValueError("反查轮次重复或不匹配")
            if any(data[key] != self.initial[key] for key in ("USED_SEED", "USED_F1", "USED_F2")):
                raise ValueError("固定时间轴发生变化")
            if data["TRUTH"] not in (0, 1) or data["APPLIED"] not in (0, 1) or data["CANDIDATES"] < 0:
                raise ValueError("反查状态无效")
            unique = data["CANDIDATES"] == 1 and data["TRUTH"] == 1
            if unique and min(data["HIT_SEED"], data["HIT_ADV"]) < 0:
                raise ValueError("唯一反查观测无效")
            self.rows.append({"attempt": self.attempts, "candidates": data["CANDIDATES"], "unique": unique,
                              "hit_seed_ms": data["HIT_SEED"] if unique else None,
                              "hit_advances": data["HIT_ADV"] if unique else None,
                              "seed_error_ms": data["HIT_SEED"] - self.initial["SEED_TARGET"] if unique else None,
                              "adv_error": data["HIT_ADV"] - self.initial["ADV_TARGET"] if unique else None})
            self.skipped += int(not unique)
            if not data["APPLIED"]:
                self.finished = True

    def payload(self):
        return {"schema": "FRLG_FIXED_TIMELINE_TEST_REPORT_V1", "run_id": self.run_id,
                "source": asdict(self.config) if self.config else None, "initial": self.initial,
                "attempts": self.attempts, "rows": self.rows, "calibration_enabled": False,
                "limit_reached": self.limit_reached, "error": self.error,
                "timeline_kind": "requested_deadlines_not_measured_keypress_timestamps",
                "source_success_kind": "logged_entry_shiny_not_final_reverse_confirmation"}

    def render(self):
        lines = ["固定时长重复测试 · 不校准", "",
                 "Seed、F1、F2 请求截止保持不变；不计算或写回任何 Seed / 帧数校准。",
                 "F2 是自 Seed 确认起的总时长，已经包含 F1；不是单独的 F2 阶段时长。",
                 "仅独立唯一反查才展示误差；出闪提前停止的轮次没有反查，不能当作零误差。"]
        if self.config:
            lines += [f"来源：{self.config.source_log}", f"源运行：{self.config.source_run_id}"]
        if self.initial:
            lines += [f"固定请求：Seed {self.initial['USED_SEED']} ms / F1 {self.initial['USED_F1']} ms / "
                      f"F2 总 {self.initial['USED_F2']} ms", f"已启动 {self.attempts}/{self.initial['LIMIT']} 轮"]
        for row in self.rows:
            lines.append(f"第 {row['attempt']} 轮：" + (
                f"唯一反查 Seed {row['hit_seed_ms']} ms（{row['seed_error_ms']:+d} ms） / "
                f"ADV {row['hit_advances']}（{row['adv_error']:+d} 帧）" if row["unique"] else
                f"候选 {row['candidates']}，无独立唯一结果，不作为误差样本"))
        missing = self.attempts - len(self.rows)
        if missing:
            lines.append(f"{missing} 轮尚无反查记录（可能出闪提前停止或流程失败，以原日志为准）。")
        if self.limit_reached:
            lines.append("已达到轮数上限，直接停止，保留最后画面。")
        elif self.finished:
            lines.append("本次已结束；出闪或其他提前结束原因见原日志。")
        if self.error:
            lines.append(self.error)
        return "\n".join(lines)
