"""Structured target evidence shared by generated scripts and SID workers."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Any, Mapping


MARKER = "# SIDTRAVERSAL_TARGET_VERIFICATION_V2"
_LEGACY_MARKER = "# SIDTRAVERSAL_TARGET_VERIFICATION_V1"
_ANSI_COLOR = re.compile(r"\x1b\[[0-9;]*m")
_TIMESTAMP = re.compile(r"^\[(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d\.\d{3}\]\s*")
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_PID_RE = re.compile(r"^[0-9A-Fa-f]{8}$")
_SEED_RE = re.compile(r"^[0-9A-Fa-f]{4,8}$")
_EVENT_RE = re.compile(
    r"^SIDTRAVERSAL\|V=1\|RUN=(?P<run>[A-Za-z0-9_-]{1,64})"
    r"\|ATTEMPT=(?P<attempt>[A-Za-z0-9_-]{1,64})"
    r"\|ROUND=(?P<round>\d+)\|EVENT=(?P<event>TARGET|NON_TARGET_SHINY|INCOMPLETE)"
    r"\|SEED_MATCH=(?P<seed>[01])\|ADV_MATCH=(?P<adv>[01])"
    r"\|SPECIES_MATCH=(?P<species>[01])\|SHINY=(?P<shiny>[01])\|END=1$"
)


@dataclass(frozen=True)
class TargetVerificationSpec:
    run_id: str
    attempt_id: str
    target_seed: str
    target_advances: int
    species_id: int
    method: str
    pid_hex: str

    def __post_init__(self) -> None:
        if not isinstance(self.run_id, str) or not _ID_RE.fullmatch(self.run_id):
            raise ValueError("SID 目標證明運行 ID 格式無效")
        if not isinstance(self.attempt_id, str) or not _ID_RE.fullmatch(self.attempt_id):
            raise ValueError("SID 目標證明嘗試 ID 格式無效")
        if not isinstance(self.target_seed, str) or not _SEED_RE.fullmatch(self.target_seed):
            raise ValueError("SID 目標證明 Seed 格式無效")
        if type(self.target_advances) is not int or self.target_advances < 0:
            raise ValueError("SID 目標證明 Advance 必須是非負整數")
        if type(self.species_id) is not int or not 1 <= self.species_id <= 386:
            raise ValueError("SID 目標證明物種編號無效")
        if not isinstance(self.method, str) or not self.method.strip():
            raise ValueError("SID 目標證明演算法不能為空")
        if not isinstance(self.pid_hex, str) or not _PID_RE.fullmatch(self.pid_hex):
            raise ValueError("SID 目標證明 PID 格式無效")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def spec_from_mapping(value: TargetVerificationSpec | Mapping[str, object]) -> TargetVerificationSpec:
    if isinstance(value, TargetVerificationSpec):
        return value
    if not isinstance(value, Mapping):
        raise ValueError("SID 目標證明計劃必須是對象")
    try:
        return TargetVerificationSpec(
            run_id=value["run_id"],
            attempt_id=value["attempt_id"],
            target_seed=value["target_seed"],
            target_advances=value["target_advances"],
            species_id=value["species_id"],
            method=value["method"],
            pid_hex=value["pid_hex"],
        )
    except KeyError as exc:
        raise ValueError(f"SID 目標證明計劃缺少字段: {exc.args[0]}") from exc


def _event_line(spec: TargetVerificationSpec, event: str, *, shiny: str) -> str:
    return (
        '        PRINT "SIDTRAVERSAL|V=1|RUN='
        + spec.run_id
        + "|ATTEMPT="
        + spec.attempt_id
        + '|ROUND=" & $循环计数 & "|EVENT='
        + event
        + '|SEED_MATCH=1|ADV_MATCH=1|SPECIES_MATCH=1|SHINY=" & '
        + shiny
        + ' & "|END=1"'
    )


def inject_target_verification(
    template: str,
    spec: TargetVerificationSpec | Mapping[str, object],
) -> str:
    """Continue past the first star label and emit evidence at exact hit branches."""
    resolved = spec_from_mapping(spec)
    if _LEGACY_MARKER in template:
        raise ValueError("该方案使用旧版结果标记，请重新生成后继续；遍历断点仍保留")
    expected_values = (
        f'$SID遍历运行ID = "{resolved.run_id}"',
        f'$SID遍历尝试ID = "{resolved.attempt_id}"',
    )
    if MARKER in template:
        if all(template.count(value) == 1 for value in expected_values):
            validate_injected_target_verification(template, resolved)
            return template
        raise ValueError("主脚本已有 SID 目标证明，但运行或尝试身份不一致")

    global_anchor = '$脚本版本 = "2.0"\n'
    shiny_anchor = "    IF $道具乱数模式 == 0 and @出闪 >= $识图阈值\n"
    english_block = (
        shiny_anchor
        + '        PRINT ""\n'
        + "        PRINT 已识别到出闪，脚本停止\n"
        + "        RETURN 0\n"
        + "    ENDIF\n"
    )
    japanese_block = (
        shiny_anchor
        + "        PRINT 已识别到出闪，脚本停止\n"
        + "        RETURN 0\n"
        + "    ENDIF\n"
    )
    loop_anchor = "        $本轮流程结果 = 执行RNG启动与目标获取()\n"
    exact_target_anchor = (
        "    IF $道具乱数模式 == 0 and $命中差索引 == 0 and "
        "$本轮消耗帧误差 == 0 and $本轮物种命中 == 1\n"
    )
    non_target_anchor = (
        "    IF $命中差索引 == 0 and $本轮消耗帧误差 == 0 and $本轮物种命中 == 0\n"
    )
    if template.count(global_anchor) != 1:
        raise ValueError("主脚本缺少唯一版本全局锚点，拒绝注入 SID 目标证明")
    if template.count(english_block) != 1 or template.count(japanese_block) != 1:
        raise ValueError("主脚本英/日闪光识别分支结构异常，拒绝注入 SID 目标证明")
    if template.count(loop_anchor) != 1:
        raise ValueError("主脚本缺少唯一目标循环锚点，拒绝注入 SID 目标证明")
    if template.count(exact_target_anchor) != 1 or template.count(non_target_anchor) != 1:
        raise ValueError("主脚本精确目标命中锚点数量异常，拒绝注入 SID 目标证明")

    identity_block = (
        MARKER
        + f'\n$SID遍历运行ID = "{resolved.run_id}"'
        + f'\n$SID遍历尝试ID = "{resolved.attempt_id}"'
        + "\n$SID遍历本轮出闪 = 0\n"
    )
    template = template.replace(global_anchor, global_anchor + identity_block, 1)
    shiny_observation = (
        shiny_anchor + "        $SID遍历本轮出闪 = 1\n    ENDIF\n"
    )
    template = template.replace(english_block, shiny_observation, 1)
    template = template.replace(japanese_block, shiny_observation, 1)
    template = template.replace(
        loop_anchor,
        "        $SID遍历本轮出闪 = 0\n" + loop_anchor,
        1,
    )
    target_event = (
        exact_target_anchor
        + "        IF $SID遍历本轮出闪 == 1\n"
        + _event_line(resolved, "TARGET", shiny="1")
        + "\n        ELSE\n"
        + _event_line(resolved, "TARGET", shiny="0")
        + "\n        ENDIF\n"
    )
    template = template.replace(exact_target_anchor, target_event, 1)
    non_target_event = (
        non_target_anchor
        + "        IF $SID遍历本轮出闪 == 1\n"
        + '            PRINT "SIDTRAVERSAL|V=1|RUN='
        + resolved.run_id
        + "|ATTEMPT="
        + resolved.attempt_id
        + '|ROUND=" & $循环计数 & "|EVENT=NON_TARGET_SHINY|SEED_MATCH=1|ADV_MATCH=1|SPECIES_MATCH=0|SHINY=1|END=1"\n'
        + "            RETURN 0\n"
        + "        ENDIF\n"
    )
    template = template.replace(non_target_anchor, non_target_event, 1)
    incomplete = (
        "    IF $SID遍历本轮出闪 == 1\n"
        + '        PRINT "SIDTRAVERSAL|V=1|RUN='
        + resolved.run_id
        + "|ATTEMPT="
        + resolved.attempt_id
        + '|ROUND=" & $循环计数 & "|EVENT=INCOMPLETE|SEED_MATCH=0|ADV_MATCH=0|SPECIES_MATCH=0|SHINY=1|END=1"\n'
        + "        RETURN 0\n"
        + "    ENDIF\n"
    )
    completion_anchor = "    $循环计数 += 1\n"
    # Other calibration and retry functions also advance the round counter.
    # Restrict the evidence exit to the exact target branch's own function.
    start = template.index(non_target_anchor)
    end = template.find("\nENDFUNC", start)
    if end == -1:
        end = len(template)
    region = template[start:end+1]
    exits = list(re.finditer(r"(?m)^    \$循环计数 \+= 1\n", region))
    if len(exits) != 1:
        raise ValueError("主脚本目标循环缺少唯一收尾锚点")
    offset = start + exits[0].start()
    return template[:offset] + incomplete + template[offset:]


def normalize_protocol_line(line: str) -> str:
    """Remove only EasyCon's known SGR and one valid timestamp wrapper."""
    clean = _ANSI_COLOR.sub("", line).strip()
    return _TIMESTAMP.sub("", clean, count=1)


def parse_target_verification(
    text: str,
    *,
    run_id: str,
    attempt_id: str,
) -> dict[str, Any] | None:
    if not isinstance(text, str):
        return None
    lines = (normalize_protocol_line(line) for line in text.removeprefix("\ufeff").splitlines())
    matching_lines = [line for line in lines if line.startswith("SIDTRAVERSAL|")]
    if len(matching_lines) != 1:
        return None
    match = _EVENT_RE.fullmatch(matching_lines[0])
    if match is None or match["run"] != run_id or match["attempt"] != attempt_id:
        return None
    return {
        "run_id": match["run"],
        "attempt_id": match["attempt"],
        "round": int(match["round"]),
        "event": match["event"],
        "seed_match": match["seed"] == "1",
        "advance_match": match["adv"] == "1",
        "species_match": match["species"] == "1",
        "shiny": match["shiny"] == "1",
        "complete": True,
    }


def validate_injected_target_verification(
    text: str,
    spec: TargetVerificationSpec | Mapping[str, object],
) -> None:
    resolved = spec_from_mapping(spec)
    if _LEGACY_MARKER in text:
        raise ValueError("该方案使用旧版结果标记，请重新生成后继续；遍历断点仍保留")
    if MARKER not in text or text.count(MARKER) != 1:
        raise ValueError("生成工程缺少唯一 SID 目标证明注入标记")
    for value in (
        f'$SID遍历运行ID = "{resolved.run_id}"',
        f'$SID遍历尝试ID = "{resolved.attempt_id}"',
    ):
        if text.count(value) != 1:
            raise ValueError("生成工程 SID 目标证明运行/尝试身份不一致")
    for shiny in ("0", "1"):
        expected = _event_line(resolved, "TARGET", shiny=shiny)
        if sum(line.strip() == expected.strip() for line in text.splitlines()) != 1:
            raise ValueError("生成工程 SID 目标证明事件语句不完整，请重新生成后继续")
    prefix = f'SIDTRAVERSAL|V=1|RUN={resolved.run_id}|ATTEMPT={resolved.attempt_id}|ROUND=" & $循环计数 & "|EVENT='
    for suffix in (
        'NON_TARGET_SHINY|SEED_MATCH=1|ADV_MATCH=1|SPECIES_MATCH=0|SHINY=1|END=1"',
        'INCOMPLETE|SEED_MATCH=0|ADV_MATCH=0|SPECIES_MATCH=0|SHINY=1|END=1"',
    ):
        if sum(line.strip() == 'PRINT "' + prefix + suffix for line in text.splitlines()) != 1:
            raise ValueError("生成工程 SID 非目标/不完整证明事件语句异常")


__all__ = [
    "MARKER",
    "TargetVerificationSpec",
    "inject_target_verification",
    "parse_target_verification",
    "normalize_protocol_line",
    "spec_from_mapping",
    "validate_injected_target_verification",
]
