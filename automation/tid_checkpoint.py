"""Round-boundary checkpoints for the audited combined TID script.

No timing/search function is rewritten. Resume repeats the interrupted point
with a fresh denoise window; it never assumes an unfinished observation passed.
"""
from __future__ import annotations

import re

from .tid_rng137 import TidRngRequest
from .tid_starter_save import is_starter_save_template, split_tid_modules


STATE_VARIABLES = {
    "OP": "$OP", "F1": "$F1", "F2": "$F2", "STAGE": "$SearchStage",
    "COUNT": "$CISHU", "OP_CORRECTION": "$OP修正", "OP_FIXED": "$OP固定",
    "OP_RETRIES": "$OP自动修正次数", "HOME": "$HOME_BUFFER延迟",
    "CLOSE": "$关闭游戏延迟",
}
CHECKPOINT_PREFIX = "TIDPROGRESS|V=1|"
DONE_MARKER = "TIDPROGRESS|DONE=1"
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def validate_checkpoint(state: dict, request: TidRngRequest) -> dict[str, int]:
    if not isinstance(state, dict) or set(state) != set(STATE_VARIABLES):
        raise ValueError("TID进度字段不完整，请勿手动编辑进度文件")
    if any(type(value) is not int or not -(2**31) < value < 2**31 for value in state.values()):
        raise ValueError("TID进度包含非法整数")
    if request.mode != 0 or request.calibration_check:
        raise ValueError("进度仅适用于正式穷举模式")
    for name, limit in (("OP", request.op_max_range), ("F1", request.f1_max_range), ("F2", request.f2_max_range)):
        if not 0 <= state[name] <= limit or state[name] % 2:
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


def parse_checkpoint(line: str, request: TidRngRequest) -> dict[str, int] | None:
    text = ANSI.sub("", line).strip()
    if CHECKPOINT_PREFIX not in text:
        return None
    payload = text.split(CHECKPOINT_PREFIX, 1)[1]
    if not payload.endswith("|END=1"):
        return None
    parts = payload[:-6].split("|")
    state = {}
    for part in parts:
        match = re.fullmatch(r"([A-Z_0-9]+)=(-?\d+)", part)
        if not match or match[1] in state:
            raise ValueError("TID进度日志格式无效")
        state[match[1]] = int(match[2])
    return validate_checkpoint(state, request)


def instrument_tid_checkpoint(text: str, request: TidRngRequest, state: dict | None = None) -> str:
    """Insert only before the outer round and after its successful exit."""
    if not is_starter_save_template(text):
        raise ValueError("穷举续跑需要新版TID球前存档脚本，请更新TID缓存")
    if request.mode != 0 or request.calibration_check:
        raise ValueError("进度仅适用于正式穷举模式")
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
    if state is not None:
        restore += "# 只恢复搜索位置和实际运行修正；去噪窗口重新观察。\n"
        restore += "\n".join(f"{variable} = {state[name]}" for name, variable in STATE_VARIABLES.items()) + "\n"
        restore += "PRINT TIDPROGRESS|RESUMED=1\n"
    restore += "# TID_CHECKPOINT_END\n"
    parts = [f'"{name}=" & {variable}' for name, variable in STATE_VARIABLES.items()]
    output = '    PRINT ' + CHECKPOINT_PREFIX + ' & ' + ' & "|" & '.join(parts) + ' & "|END=1"\n'
    module = module.replace(anchor, restore + anchor + "    # TID_CHECKPOINT_BEGIN\n" + output + "    # TID_CHECKPOINT_END\n", 1)
    end = f"    NEXT\nNEXT\n\nENDIF\n\nFUNC {prefix}_识图"
    if module.count(end) != 1:
        raise ValueError("TID穷举成功出口与已审计结构不一致")
    module = module.replace(end, f"    NEXT\nNEXT\n\n# TID_CHECKPOINT_BEGIN\nPRINT {DONE_MARKER}\n# TID_CHECKPOINT_END\nENDIF\n\nFUNC {prefix}_识图", 1)
    return head + (module if prefix == "EN" else english) + (module if prefix == "JP" else japanese) + tail
