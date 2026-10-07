"""Unique-PID evidence for SID traversal, independent of target timing hits.

This extension is applied only to generated traversal projects.  All matching
PIDs in a completed scan must agree; a path/vote-selected result is not proof.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import re

from .target_verification import (
    MARKER as TARGET_MARKER, TargetVerificationSpec, normalize_protocol_line,
    spec_from_mapping,
)


MARKER = "# SIDTRAVERSAL_PID_OBSERVATION_V1"
EXTENSION_PATH = Path(__file__).resolve().parent.parent / "assets/easycon118_extensions/sid_pid_observation.ecs"
_WIRE = re.compile(
    r"^SIDTRAVERSAL_OBS\|V=1\|RUN=(?P<run>[A-Za-z0-9_-]{1,64})"
    r"\|ATTEMPT=(?P<attempt>[A-Za-z0-9_-]{1,64})\|ROUND=(?P<round>\d+)"
    r"\|SPECIES=(?P<species>\d+)\|PIDHI=(?P<hi>\d+)\|PIDLO=(?P<lo>\d+)"
    r"\|UNIQUE_PID=1\|CANDIDATES=(?P<count>\d+)\|SHINY=(?P<shiny>[01])"
    r"\|STAR_MIN=(?P<star_min>\d+)\|STAR_MAX=(?P<star_max>\d+)"
    r"\|PAGE_MIN=(?P<page_min>\d+)\|THRESHOLD=(?P<threshold>\d+)\|END=1$"
)


@dataclass(frozen=True)
class PIDObservation:
    run_id: str
    attempt_id: str
    round: int
    species_id: int
    pid: int
    shiny: bool
    candidate_count: int
    star_min: int
    star_max: int
    page_min: int
    threshold: int

    def to_dict(self) -> dict:
        result = asdict(self)
        result["pid"] = f"{self.pid:08X}"
        result["unique_pid"] = True
        result["source"] = "unique-reverse-pid"
        return result


def validate_observation(value: dict) -> PIDObservation:
    """Validate durable evidence too, rather than trusting loaded TSV lists."""
    if not isinstance(value, dict) or value.get("source") != "unique-reverse-pid" or value.get("unique_pid") is not True:
        raise ValueError("SID 遍历缺少唯一 PID 证据")
    for key in ("run_id", "attempt_id"):
        if not isinstance(value.get(key), str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value[key]):
            raise ValueError("SID 反查证据身份无效")
    for key in ("round", "species_id", "candidate_count", "star_min", "star_max", "page_min", "threshold"):
        if type(value.get(key)) is not int:
            raise ValueError("SID 反查证据字段必须是整数")
    if value["round"] < 0 or not 1 <= value["species_id"] <= 386 or value["candidate_count"] < 1:
        raise ValueError("SID 反查证据轮次/物种/候选数量无效")
    pid_hex = value.get("pid")
    if not isinstance(pid_hex, str) or not re.fullmatch(r"[0-9A-Fa-f]{8}", pid_hex):
        raise ValueError("SID 反查证据 PID 无效")
    if type(value.get("shiny")) is not bool:
        raise ValueError("SID 反查证据闪光状态无效")
    lo, hi, page, threshold = (value[k] for k in ("star_min", "star_max", "page_min", "threshold"))
    if not 0 <= lo <= hi <= 100 or not 0 <= page <= 100 or not 95 <= threshold <= 100 or page < threshold:
        raise ValueError("SID 反查证据识图置信度不足")
    if (value["shiny"] and lo < threshold) or (not value["shiny"] and hi > threshold - 5):
        raise ValueError("SID 反查证据闪光状态未确认")
    return PIDObservation(value["run_id"], value["attempt_id"], value["round"], value["species_id"],
                          int(pid_hex, 16), value["shiny"], value["candidate_count"], lo, hi, page, threshold)


def parse_pid_observations(text: str, *, run_id: str, attempt_id: str) -> list[dict]:
    observations = []
    seen_rounds = set()
    for raw in text.removeprefix("\ufeff").splitlines():
        line = normalize_protocol_line(raw)
        if not line.startswith("SIDTRAVERSAL_OBS|"):
            continue
        match = _WIRE.fullmatch(line)
        if match is None or match["run"] != run_id or match["attempt"] != attempt_id:
            raise ValueError("SID 唯一 PID 证据格式或运行身份不一致；不据此排除 TSV")
        hi, lo = int(match["hi"]), int(match["lo"])
        if hi > 65535 or lo > 65535:
            raise ValueError("SID 反查证据 PID 半字超出范围")
        value = {
            "run_id": run_id, "attempt_id": attempt_id, "round": int(match["round"]),
            "species_id": int(match["species"]), "pid": f"{(hi << 16) | lo:08X}",
            "unique_pid": True, "source": "unique-reverse-pid", "shiny": match["shiny"] == "1",
            "candidate_count": int(match["count"]), "star_min": int(match["star_min"]),
            "star_max": int(match["star_max"]), "page_min": int(match["page_min"]),
            "threshold": int(match["threshold"]),
        }
        validate_observation(value)
        if value["round"] in seen_rounds or (observations and value["round"] <= observations[-1]["round"]):
            raise ValueError("SID 唯一 PID 证据轮次重复或倒退")
        seen_rounds.add(value["round"])
        observations.append(value)
    return observations


def _insert_in_function(text: str, name: str, anchor: str, replacement: str) -> str:
    match = re.search(r"(?m)^FUNC " + re.escape(name) + r"(?:\(.*)?\n", text)
    if match is None:
        raise ValueError(f"SID PID 证据缺少函数：{name}")
    end = text.find("\nENDFUNC", match.end())
    if end < 0:
        raise ValueError(f"SID PID 证据函数未结束：{name}")
    region = text[match.start():end + 1]
    if region.count(anchor) != 1:
        raise ValueError(f"SID PID 证据函数锚点异常：{name}；请重新生成")
    return text[:match.start()] + region.replace(anchor, replacement, 1) + text[end + 1:]


def inject_pid_observation(template: str, spec: TargetVerificationSpec, *, tid: int, sid: int) -> str:
    spec = spec_from_mapping(spec)
    if type(tid) is not int or not 0 <= tid <= 65535 or type(sid) is not int or not 0 <= sid <= 65535:
        raise ValueError("SID PID 证据 TID/SID 无效")
    if MARKER in template:
        raise ValueError("SID PID 证据已经注入；请从母本重新生成")
    if TARGET_MARKER not in template or f'$SID遍历尝试ID = "{spec.attempt_id}"' not in template:
        raise ValueError("SID PID 证据必须绑定当前目标证明身份")
    global_anchor = '$SID遍历本轮出闪 = 0\n'
    if len(re.findall(r"(?m)^" + re.escape(global_anchor), template)) != 1:
        raise ValueError("SID PID 证据全局锚点异常")
    extension = EXTENSION_PATH.read_text(encoding="utf-8")
    pid_prefix = f'SIDTRAVERSAL_OBS|V=1|RUN={spec.run_id}|ATTEMPT={spec.attempt_id}'
    extension = extension.replace('"__PID_OBSERVATION_PREFIX__"', f'"{pid_prefix}"')
    extension = extension.replace("__CANDIDATE_TID__", str(tid)).replace("__CANDIDATE_SID__", str(sid))
    template = template.replace(global_anchor, global_anchor + extension + "\n", 1)

    capture_anchor = '$普通闪光策略结果 = 设置普通闪光策略('
    if template.count(capture_anchor) != 1:
        raise ValueError("SID PID 证据闪光抓捕策略锚点异常")
    template = template.replace(capture_anchor,
        "$实际出闪后继续抓捕 = 1\n$普通闪光停止策略 = 0\n" + capture_anchor, 1)
    loop_anchor = '        $SID遍历本轮出闪 = 0\n'
    if template.count(loop_anchor) != 1:
        raise ValueError("SID PID 证据轮次重置锚点异常")
    template = template.replace(loop_anchor, loop_anchor +
        "        $SID遍历闪光状态 = -1\n        CALL 清空最近出闪检测\n", 1)
    reverse_anchor = '        $反查细分成功 = 执行识图反查直到候选唯一()\n'
    if template.count(reverse_anchor) != 1:
        raise ValueError("SID PID 证据完整反查锚点异常")
    template = template.replace(reverse_anchor, reverse_anchor +
        "        $SID遍历证据动作 = SID遍历处理反查证据($反查细分成功)\n"
        "        IF $SID遍历证据动作 != 0\n            RETURN\n        ENDIF\n", 1)
    obtain_anchor = '        $本轮流程结果 = 执行RNG启动与目标获取()\n'
    template = template.replace(obtain_anchor, obtain_anchor +
        "        $SID遍历最近闪光 = 读取最近出闪检测结果()\n"
        "        IF $SID遍历最近闪光 == 1 and $本轮流程结果 != 1 and $本轮流程结果 != 2 and $本轮流程结果 != 3\n"
        "            PRINT SID遍历检测到闪光但获取未完成，保留现场停止，不重启游戏\n            RETURN\n        ENDIF\n", 1)
    template = _insert_in_function(template, "重置本轮候选状态",
        "    $本轮候选命中计数 = 0\n", "    $本轮候选命中计数 = 0\n"
        "    $SID遍历PID一致 = 0\n    $SID遍历PID高 = -1\n    $SID遍历PID低 = -1\n")
    template = _insert_in_function(template, "处理匹配候选",
        "    $本轮候选命中计数 += 1\n", "    $本轮候选命中计数 += 1\n"
        "    CALL SID遍历收集匹配PID\n")
    for name in ("读取并输出识图结果", "读取并输出日版御三家识图结果"):
        # The generator's EN/JP recognition branches both contain this star
        # observation. Sample before the original RIGHT; never send another key.
        anchor = "    IF $道具乱数模式 == 0 and @出闪 >= $识图阈值\n        $SID遍历本轮出闪 = 1\n    ENDIF\n"
        template = _insert_in_function(template, name, anchor,
            anchor + "    CALL SID遍历采样闪光状态\n")
    target_anchor = (
        "    IF $道具乱数模式 == 0 and $命中差索引 == 0 and "
        "$本轮消耗帧误差 == 0 and $本轮物种命中 == 1\n"
    )
    target_pid = int(spec.pid_hex, 16)
    if template.count(target_anchor) != 1:
        raise ValueError("SID PID 证据目标终态锚点异常")
    template = template.replace(target_anchor, target_anchor +
        "        IF $SID遍历PID一致 != 1 or $SID遍历闪光状态 < 0 or "
        f"$SID遍历PID高 != {target_pid >> 16} or $SID遍历PID低 != {target_pid & 65535}\n"
        "            PRINT SID遍历精确目标缺少一致的唯一PID/闪光状态，保留现场停止\n"
        "            RETURN 0\n        ENDIF\n", 1)
    return template


def validate_injected_pid_observation(text: str, spec: TargetVerificationSpec, *, tid: int, sid: int) -> None:
    spec = spec_from_mapping(spec)
    if text.count(MARKER) != 1:
        raise ValueError("生成工程缺少唯一 PID 反查证据扩展，请重新生成")
    expected = EXTENSION_PATH.read_text(encoding="utf-8")
    prefix = f'SIDTRAVERSAL_OBS|V=1|RUN={spec.run_id}|ATTEMPT={spec.attempt_id}'
    expected = expected.replace('"__PID_OBSERVATION_PREFIX__"', f'"{prefix}"')
    expected = expected.replace("__CANDIDATE_TID__", str(tid)).replace("__CANDIDATE_SID__", str(sid))
    if expected not in text:
        raise ValueError("生成工程 PID 反查证据实现不一致，请重新生成")
    for hook, count in (
        ("    CALL SID遍历收集匹配PID\n", 1),
        ("    CALL SID遍历采样闪光状态\n", 2),
        ("        $SID遍历证据动作 = SID遍历处理反查证据($反查细分成功)\n", 1),
        ("$实际出闪后继续抓捕 = 1\n$普通闪光停止策略 = 0\n", 1),
        ("        CALL 清空最近出闪检测\n", 1),
    ):
        if text.count(hook) != count:
            raise ValueError("生成工程 PID 反查证据接线不完整，请重新生成")
