"""Search-only extensions for the audited 164a combined TID template.

The original timing formulas, OCR, input helpers and bridge remain the source
of truth. All injected work executes between attempts, outside timed inputs.
"""
from __future__ import annotations

import re

from .tid_starter_save import split_tid_modules

SEARCH_MARKER = "# TID_SEARCH_V3"
AXES = ("OP", "F1", "F2")


def parse_target_tids(text: str) -> tuple[int, ...]:
    parts = re.split(r"[,，、;；\s]+", text.strip()) if text.strip() else []
    if any(not re.fullmatch(r"[0-9]{1,5}", part) or int(part) > 65535 for part in parts):
        raise ValueError("额外目标TID用空格或逗号分隔，每项填写0-65535（可保留前导零）")
    values = tuple(dict.fromkeys(map(int, parts)))
    if len(values) > 31:
        raise ValueError("额外目标TID最多填写31个")
    return values


def progress_supported(request) -> bool:
    return not request.calibration_check and (request.mode == 0 or any(
        value != 0 for value in (request.op_rng_range, request.f1_rng_range, request.f2_rng_range)
    ))


def replace_once(text: str, old: str, new: str) -> str:
    if text.count(old) != 1:
        raise ValueError("TID搜索模板与已审计结构不一致：" + old[:80])
    return text.replace(old, new, 1)


def function(text: str, name: str) -> str:
    found = re.search(rf"(?ms)^FUNC {re.escape(name)}[^\n]*\n.*?^ENDFUNC", text)
    if found is None:
        raise ValueError("TID搜索模板缺少函数：" + name)
    return found[0]


def normalization_function(prefix: str) -> str:
    lines = [f"FUNC {prefix}_规范搜索范围"]
    for axis in AXES:
        for suffix in ("_Max_Range", "_RNG_Max_Range"):
            field = f"${axis}{suffix}"
            lines += [f"    $TID旧半径 = {field}", f"    IF {field} < 0", f"        {field} = 0", "    ENDIF"]
            if suffix == "_RNG_Max_Range":
                lines += ["    IF $ID_RNG == 1",
                          f"        IF ${axis}目标帧 < ${axis}脚本固定帧",
                          f"            PRINT {axis}中心低于可执行下限，自动提升到： & ${axis}脚本固定帧",
                          f"            ${axis}目标帧 = ${axis}脚本固定帧", "        ENDIF",
                          f"        $TID最大半径 = ${axis}目标帧 - ${axis}脚本固定帧",
                          f"        IF {field} > $TID最大半径", f"            {field} = $TID最大半径",
                          "        ENDIF", "    ENDIF"]
            lines += [f"    {field} -= {field} % 2",
                      f"    IF {field} != $TID旧半径",
                      f"        PRINT {axis}{suffix}自动调整： & $TID旧半径 & \" -> \" & {field}", "    ENDIF"]
    lines += ["ENDFUNC"]
    return "\n".join(lines)


def initialize_function(prefix: str) -> str:
    lines = [f"FUNC {prefix}_初始化乱数搜索", f"    CALL {prefix}_规范搜索范围",
             "    $RNGRadius = 0", "    $RNGCurrentRadius = 0", "    $RNGMaxRadius = 0"]
    for axis in AXES:
        lines += [f"    ${axis}SearchPos = 0", f"    ${axis} = ${axis}_RNG_Max_Range",
                  f"    ${axis}_Max_Range = ${axis}_RNG_Max_Range",
                  f"    IF ${axis}_RNG_Max_Range > $RNGMaxRadius",
                  f"        $RNGMaxRadius = ${axis}_RNG_Max_Range", "    ENDIF"]
    lines += [f"    CALL {prefix}_清空窗口", "    $denoise_hit_count = 0", "ENDFUNC"]
    return "\n".join(lines)


def extend_tid_search(text: str, request) -> str:
    if request.calibration_check:
        return text
    if SEARCH_MARKER in text:
        raise ValueError("TID搜索扩展不能重复注入")
    head, english, japanese, tail = split_tid_modules(text)
    prefix = "EN" if request.language == "英文" else "JP"
    module = english if prefix == "EN" else japanese
    # Legacy synthetic/old templates lack the corrected fixed-frame model.
    if f"${prefix}_F1帧基准毫秒" not in text:
        if request.auto_rng or request.additional_target_tids:
            raise ValueError("自动搜索需要包含精确帧换算的新TID模板")
        return text
    auto = request.auto_rng and request.mode == 0
    targets = request.exhaustive_targets
    globals_ = [SEARCH_MARKER, "$TID自动切换 = 0", "$TID区域目标 = 0", "$TID区域次数 = 0",
                "$TID区域差 = 32769", "$TID区域观察 = 0", "$TID区域命中 = 0",
                "$TID区域临时差 = 0", "$TID区域距离 = 0", "$TID区域检测目标 = 0",
                "$TID旧半径 = 0", "$TID最大半径 = 0", "$TID本轮已切换 = 0"]
    head = replace_once(head, "# 唤醒设备\n", "\n".join(globals_) + "\n\n# 唤醒设备\n")
    extra = [normalization_function(prefix), initialize_function(prefix)]
    # Clamp before offsets/search indices are initialized, never after a WAIT.
    anchor = f"    CALL {prefix}_计算脚本固定帧\n    IF $ID_RNG == 0"
    module = replace_once(module, anchor,
                          f"    CALL {prefix}_计算脚本固定帧\n    CALL {prefix}_规范搜索范围\n    IF $ID_RNG == 0")
    old_validation = function(module, f"{prefix}_乱数模式操作延迟校验")
    validation = old_validation[:old_validation.index("    $OP中心差值")]
    validation += old_validation[old_validation.index("    IF $ID_RNG == 1"):]
    module = replace_once(module, old_validation, validation)

    if request.mode == 0 and len(targets) > 1:
        old = function(module, f"{prefix}_计算穷举候选距离")
        start = old.index(f"    $候选ID = ${prefix}_TARGET_TID")
        end = old.index("    IF $65535开关")
        intro = ["    $最佳候选AbsDelta = 32769"]
        for tid in targets:
            intro += [f"    $候选ID = {tid}", f"    CALL {prefix}_用当前候选ID更新最佳距离"]
        intro += ["    IF $最佳候选AbsDelta <= $F2candidate_range",
                  "        $targetID = $最佳候选ID", "        $Delta = $最佳候选Delta",
                  "        $AbsDelta = $最佳候选AbsDelta", "        RETURN", "    ENDIF", ""]
        module = replace_once(module, old, old[:start] + "\n".join(intro) + old[end:])
        match = function(module, f"{prefix}_匹配")
        multi = ["    IF $ID_RNG == 0"]
        for tid in targets:
            multi += [f"        IF $ID == {tid}", "            $is_match = 1", "        ENDIF"]
        multi += ["    ENDIF", ""]
        updated = match.replace("    IF $65535开关 == 1", "\n".join(multi) + "    IF $65535开关 == 1", 1)
        module = replace_once(module, match, updated)

    if auto:
        # Count each target against the same window, including distinct nearby
        # TIDs. Invalid OCR never enters the window and never contributes a vote.
        scan = [f"FUNC {prefix}_统计接近目标", "    $TID区域命中 = 0"]
        for i in range(1, 11):
            scan += [f"    IF $Slot{i} >= 0 and $Slot{i} <= 65535",
                     f"        $TID区域临时差 = $Slot{i} - $TID区域检测目标",
                     "        IF $TID区域临时差 > 32767", "            $TID区域临时差 -= 65536", "        ENDIF",
                     "        IF $TID区域临时差 < -32768", "            $TID区域临时差 += 65536", "        ENDIF",
                     "        IF $TID区域临时差 < 0", "            $TID区域临时差 = 0 - $TID区域临时差", "        ENDIF",
                     f"        IF $TID区域临时差 <= {request.near_tid_distance}", "            $TID区域命中 += 1",
                     "        ENDIF", "    ENDIF"]
        scan += ["ENDFUNC"]
        extra.append("\n".join(scan))
        detect = [f"FUNC {prefix}_检测目标区域", "    $TID区域次数 = 0", "    $TID区域差 = 32769",
                  "    $TID区域观察 = 0", "    IF $ID_RNG != 0", "        RETURN", "    ENDIF"]
        for tid in targets:
            detect += [f"    $TID区域检测目标 = {tid}", f"    CALL {prefix}_统计接近目标",
                       f"    $候选ID = {tid}", f"    CALL {prefix}_用当前候选ID计算距离",
                       "    IF $TID区域命中 > $TID区域次数 or $TID区域命中 == $TID区域次数 and $候选AbsDelta < $TID区域差",
                       f"        $TID区域目标 = {tid}", "        $TID区域次数 = $TID区域命中",
                       "        $TID区域差 = $候选AbsDelta", "    ENDIF"]
        detect += ["    IF $TID区域次数 > 0", "        $TID区域观察 = 1", "    ENDIF",
                   f"    IF $TID区域次数 >= {request.near_tid_hits}", f"        CALL {prefix}_打印参数",
                   f"        CALL {prefix}_自动转乱数", "    ENDIF", "ENDFUNC"]
        extra.append("\n".join(detect))
        switch = [f"FUNC {prefix}_自动转乱数", "    $TID自动切换 = 1", "    $TID本轮已切换 = 1",
                  f"    ${prefix}_TARGET_TID = $TID区域目标"]
        for axis in AXES:
            switch += [f"    ${axis}目标帧 = ${axis}总帧",
                       f"    ${axis}_RNG_Max_Range = {getattr(request, 'auto_' + axis.lower() + '_rng_range')}"]
        # Exhaustive padding has already increased the stored fixed delay.
        # Restore natural calibration before using the RNG formula, so the
        # omitted padding WAIT is transferred into the computed WAIT exactly.
        for axis in ("F1", "F2"):
            switch += [f"    ${axis}脚本固定延迟 -= ${axis}脚本固定延迟补偿", f"    ${axis}脚本固定延迟补偿 = 0"]
        switch += ["    $ID_RNG = 1", f"    CALL {prefix}_计算脚本固定帧",
                   "    $same_id_switch = 0", "    $continue_id_switch = 0",
                   "    $65535开关 = 0", "    $个位检测开关 = 0",
                   "    $same_condition_match = 0", "    $continue_condition_match = 0",
                   "    $65535_match = 0", "    $个位检测结果 = 0", "    $is_match = 0",
                   "    $Name_GREEN = 0", "    IF $SID_RAND == 0", f"        CALL {prefix}_SID计算_奇",
                   "        IF $Name_GREEN == 1", f"            $F3脚本固定延迟 += {3750 if prefix == 'EN' else 3210}",
                   f"            CALL {prefix}_SID计算_偶", "        ENDIF", f"        CALL {prefix}_SID计算结果打印", "    ENDIF"]
        # Update digit match state and seed-derived SID inputs with the selected
        # target; the nearby observed TID is never substituted as the target.
        for i, div in enumerate((10000, 1000, 100, 10, 1), 1):
            switch += [f"    $target{i} = ${prefix}_TARGET_TID / {div}", f"    $target{i} %= 10"]
        switch += [f"    CALL {prefix}_计算脚本固定帧", f"    CALL {prefix}_初始化乱数搜索", f"    CALL {prefix}_计算操作延迟",
                   f"    CALL {prefix}_乱数模式操作延迟校验",
                   "    PRINT >>> 穷举已自动转为乱数模式 <<<",
                   f"    PRINT 锁定目标TID： & ${prefix}_TARGET_TID & \"；窗口内接近次数：\" & $TID区域次数",
                   "    PRINT 乱数中心OP/F1/F2： & $OP目标帧 & \"/\" & $F1目标帧 & \"/\" & $F2目标帧",
                   "    PRINT 乱数半径OP/F1/F2： & $OP_RNG_Max_Range & \"/\" & $F1_RNG_Max_Range & \"/\" & $F2_RNG_Max_Range",
                   "ENDFUNC"]
        extra.append("\n".join(switch))
        anchor = f"            CALL {prefix}_去噪\n"
        # Restart the game before judging a result under the new mode/SID.
        hook = (f"            $TID本轮已切换 = 0\n            CALL {prefix}_检测目标区域\n"
                "            IF $TID本轮已切换 == 1\n                $CISHU += 1\n                BREAK\n            ENDIF\n")
        module = replace_once(module, anchor, anchor + hook)
        old = function(module, f"{prefix}_穷举模式偏移运算")
        guard = (f"    IF $TID区域观察 == 1 and $denoise_try_count < $denoise_try_window\n"
                 "        PRINT 已接近目标，继续观察当前参数以确认区域\n        RETURN\n    ENDIF\n")
        module = replace_once(module, old, old.replace(f"FUNC {prefix}_穷举模式偏移运算\n",
                                                       f"FUNC {prefix}_穷举模式偏移运算\n" + guard, 1))

    # Invalid but complete five-digit OCR must not influence proximity evidence.
    guard = "            IF $digits_ok == 0\n"
    module = replace_once(module, guard, "            IF $digits_ok == 0 or $curr1 * 10000 + $curr2 * 1000 + $curr3 * 100 + $curr4 * 10 + $curr5 > 65535\n")
    # The generic flow's any-TID guard expects the original digit guard as an
    # anchor. Keep it and perform the range rejection immediately before it.
    module = module.replace("            IF $digits_ok == 0 or $curr1 * 10000 + $curr2 * 1000 + $curr3 * 100 + $curr4 * 10 + $curr5 > 65535\n",
                            "            IF $curr1 * 10000 + $curr2 * 1000 + $curr3 * 100 + $curr4 * 10 + $curr5 > 65535\n                $digits_ok = 0\n            ENDIF\n" + guard, 1)
    module += "\n" + "\n\n".join(extra) + "\n\n"
    from .tid_search_policy import optimize_tid_search
    from .tid_logging import restore_tid_logging
    configured = optimize_tid_search(head + (module if prefix == "EN" else english) + (module if prefix == "JP" else japanese) + tail, request)
    return restore_tid_logging(configured, request)
