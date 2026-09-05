"""Round-boundary checkpoints for the audited combined TID script.

No timing/search function is rewritten. Resume repeats the interrupted point
with a fresh denoise window; it never assumes an unfinished observation passed.
"""
from __future__ import annotations

import re

from .tid_rng137 import TidRngRequest
from .tid_starter_save import is_starter_save_template, split_tid_modules
from .tid_search import SEARCH_MARKER, progress_supported


STATE_VARIABLES = {
    "OP": "$OP", "F1": "$F1", "F2": "$F2", "STAGE": "$SearchStage",
    "COUNT": "$CISHU", "OP_CORRECTION": "$OP修正", "OP_FIXED": "$OP固定",
    "OP_RETRIES": "$OP自动修正次数", "HOME": "$HOME_BUFFER延迟",
    "CLOSE": "$关闭游戏延迟",
}
CHECKPOINT_PREFIX = "TIDPROGRESS|V=1|"
CHECKPOINT_V2_PREFIX = "TIDPROGRESS|V=2|"
SEARCH_STATE_VARIABLES = {
    **STATE_VARIABLES, "MODE": "$ID_RNG", "SWITCHED": "$TID自动切换",
    "TARGET": "$targetID", "RADIUS": "$RNGRadius",
    **{f"{axis}_CENTER": f"${axis}目标帧" for axis in ("OP", "F1", "F2")},
    **{f"{axis}_RANGE": f"${axis}_RNG_Max_Range" for axis in ("OP", "F1", "F2")},
    **{f"{axis}_POS": f"${axis}SearchPos" for axis in ("OP", "F1", "F2")},
}
DONE_MARKER = "TIDPROGRESS|DONE=1"
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def validate_checkpoint(state: dict, request: TidRngRequest) -> dict[str, int]:
    v2 = isinstance(state, dict) and set(state) == set(SEARCH_STATE_VARIABLES)
    if not isinstance(state, dict) or (not v2 and set(state) != set(STATE_VARIABLES)):
        raise ValueError("TID进度字段不完整，请勿手动编辑进度文件")
    if any(type(value) is not int or not -(2**31) < value < 2**31 for value in state.values()):
        raise ValueError("TID进度包含非法整数")
    if request.calibration_check or (not v2 and request.mode != 0):
        raise ValueError("进度仅适用于正式穷举模式")
    if v2:
        _validate_search_state(state, request)
    else:
        for name, limit in (("OP", request.op_max_range), ("F1", request.f1_max_range), ("F2", request.f2_max_range)):
            if not 0 <= state[name] <= max(0, limit) // 2 * 2 or state[name] % 2:
                raise ValueError(f"TID进度{name}超出当前穷举范围")
    if state["STAGE"] not in (0, 1, 2) or state["COUNT"] < 0 or not 0 <= state["OP_RETRIES"] <= 10:
        raise ValueError("TID进度搜索层级或计数无效")
    base = 30550 if request.language == "英文" else 30600
    model = 0 if request.nx_model == 1 else -750
    if state["OP_FIXED"] != base + state["OP_CORRECTION"] + model or state["OP_FIXED"] < 0:
        raise ValueError("TID进度OP等待与机型/修正不一致")
    if state["OP_CORRECTION"] != request.op_correction + state["OP_RETRIES"] * 50:
        raise ValueError("TID进度OP修正与本次参数不一致")
    if not 0 <= state["HOME"] <= 60000 or not 0 <= state["CLOSE"] <= 60000:
        raise ValueError("TID进度重启等待值无效")
    return dict(state)


def fixed_frame(ms: int, axis: str) -> int:
    frame = (ms * 750009 + 6250000 - 1) // 6250000
    if axis != "OP":
        base = 22050 if axis == "F1" else 16750
        reference = ((base * 750009 + 6250000 - 1) // 6250000) * 6250000 - base * 750009
        if frame * 6250000 - ms * 750009 < reference:
            frame += 1
    return frame


def _validate_search_state(state, request):
    if not progress_supported(request) or state["MODE"] not in (0, 1) or state["SWITCHED"] not in (0, 1):
        raise ValueError("TID进度运行模式无效")
    switched = state["SWITCHED"] == 1
    if switched:
        if request.mode != 0 or not request.auto_rng or state["MODE"] != 1 or state["TARGET"] not in request.exhaustive_targets:
            raise ValueError("TID进度自动切换目标与配置不一致")
    elif state["MODE"] != request.mode or state["TARGET"] != request.target_tid:
        raise ValueError("TID进度目标或模式与配置不一致")
    offsets = []
    for axis in ("OP", "F1", "F2"):
        lower = axis.lower()
        delay = getattr(request, lower + "_fixed_delay") + (request.select_correction * 600 if axis == "F2" else 0)
        floor = fixed_frame(delay, axis)
        if state["MODE"] == 0:
            limit = max(0, getattr(request, lower + "_max_range")) // 2 * 2
            if not 0 <= state[axis] <= limit or state[axis] % 2:
                raise ValueError("TID穷举进度超出范围")
            if state[axis + "_POS"] != 0:
                raise ValueError("穷举检查点不能包含乱数搜索位置")
            if (state[axis + "_CENTER"] != getattr(request, lower + "_target_frame")
                or state[axis + "_RANGE"] != max(0, getattr(request, lower + "_rng_range")) // 2 * 2):
                raise ValueError("穷举检查点的乱数配置与原请求不一致")
        else:
            center = state[axis + "_CENTER"]
            if switched:
                padded = max(delay, {"OP": delay, "F1": 22050, "F2": 16750}[axis])
                start = max(fixed_frame(padded, axis), getattr(request, lower + "_start"))
                limit = max(0, getattr(request, lower + "_max_range")) // 2 * 2
                if not start <= center <= start + limit or (center - start) % 2:
                    raise ValueError("自动转乱数中心不属于原穷举范围")
            elif center != max(floor, getattr(request, lower + "_target_frame")):
                raise ValueError("乱数中心与当前配置不一致")
            range_field = ("auto_" if switched else "") + lower + "_rng_range"
            radius = max(0, min(getattr(request, range_field), center - floor)) // 2 * 2
            if state[axis + "_RANGE"] != radius:
                raise ValueError("乱数半径与自动修正结果不一致")
            pos = state[axis + "_POS"]
            if not 0 <= pos <= radius:
                raise ValueError("乱数搜索位置越界")
            offset = ((pos + 1) // 2 * 2) * (1 if pos % 2 else -1)
            if state[axis] != radius + offset:
                raise ValueError("乱数搜索位置与偏移不一致")
            offsets.append(abs(offset))
    if state["RADIUS"] != (max(offsets) if offsets else 0):
        raise ValueError("乱数壳层与搜索位置不一致")


def parse_checkpoint(line: str, request: TidRngRequest) -> dict[str, int] | None:
    text = ANSI.sub("", line).strip()
    prefix = CHECKPOINT_V2_PREFIX if CHECKPOINT_V2_PREFIX in text else CHECKPOINT_PREFIX
    if prefix not in text:
        return None
    payload = text.split(prefix, 1)[1]
    if not payload.endswith("|END=1"):
        return None
    parts = payload[:-6].split("|")
    state = {}
    for part in parts:
        match = re.fullmatch(r"([A-Z_0-9]+)=(-?\d+)", part)
        if not match or match[1] in state:
            raise ValueError("TID进度日志格式无效")
        state[match[1]] = int(match[2])
    expected = SEARCH_STATE_VARIABLES if prefix == CHECKPOINT_V2_PREFIX else STATE_VARIABLES
    if set(state) != set(expected):
        raise ValueError("TID进度版本与字段不一致")
    return validate_checkpoint(state, request)


def instrument_tid_checkpoint(text: str, request: TidRngRequest, state: dict | None = None) -> str:
    """Insert only before the outer round and after its successful exit."""
    if not is_starter_save_template(text):
        raise ValueError("穷举续跑需要新版TID球前存档脚本，请更新TID缓存")
    v2 = SEARCH_MARKER in text
    if not progress_supported(request) or (request.mode != 0 and not v2):
        raise ValueError("进度需要新版模板的穷举或非零半径乱数模式")
    if "# TID_CHECKPOINT_BEGIN" in text:
        raise ValueError("TID进度钩子已存在，不能重复注入")
    if state is not None:
        state = validate_checkpoint(state, request)
    head, english, japanese, tail = split_tid_modules(text)
    prefix = "EN" if request.language == "英文" else "JP"
    module = english if prefix == "EN" else japanese
    anchor = f"FOR\n    $select基础次数 = 0\n    CALL {prefix}_计算操作延迟\n"
    if module.count(anchor) != 1:
        raise ValueError("TID穷举主循环与已审计结构不一致")
    restore = "# TID_CHECKPOINT_BEGIN\n"
    variables = dict(SEARCH_STATE_VARIABLES if v2 else STATE_VARIABLES)
    if v2:
        variables["TARGET"] = f"${prefix}_TARGET_TID"
    if state is not None:
        restore += "# 只恢复搜索位置和实际运行修正；去噪窗口重新观察。\n"
        if v2 and "MODE" not in state:
            raise ValueError("旧穷举检查点不能恢复到新版搜索模板")
        if v2 and state["SWITCHED"]:
            restore += f"$TID区域目标 = {state['TARGET']}\n"
            restore += "\n".join(f"${axis}总帧 = {state[axis + '_CENTER']}" for axis in ("OP", "F1", "F2")) + "\n"
            restore += f"CALL {prefix}_自动转乱数\n"
        restore += "\n".join(f"{variable} = {state[name]}" for name, variable in variables.items()) + "\n"
        if v2:
            restore += "$RNGMaxRadius = 0\n"
            for axis in ("OP", "F1", "F2"):
                restore += f"IF ${axis}_RNG_Max_Range > $RNGMaxRadius\n    $RNGMaxRadius = ${axis}_RNG_Max_Range\nENDIF\n"
        restore += "PRINT TIDPROGRESS|RESUMED=1\n"
    restore += "# TID_CHECKPOINT_END\n"
    parts = [f'"{name}=" & {variable}' for name, variable in variables.items()]
    output = '    PRINT ' + (CHECKPOINT_V2_PREFIX if v2 else CHECKPOINT_PREFIX) + ' & ' + ' & "|" & '.join(parts) + ' & "|END=1"\n'
    module = module.replace(anchor, restore + anchor + "    # TID_CHECKPOINT_BEGIN\n" + output + "    # TID_CHECKPOINT_END\n", 1)
    end = f"    NEXT\nNEXT\n\nENDIF\n\nFUNC {prefix}_识图"
    if module.count(end) != 1:
        raise ValueError("TID穷举成功出口与已审计结构不一致")
    module = module.replace(end, f"    NEXT\nNEXT\n\n# TID_CHECKPOINT_BEGIN\nPRINT {DONE_MARKER}\n# TID_CHECKPOINT_END\nENDIF\n\nFUNC {prefix}_识图", 1)
    return head + (module if prefix == "EN" else english) + (module if prefix == "JP" else japanese) + tail
