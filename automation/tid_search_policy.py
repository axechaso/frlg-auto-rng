"""Bounded local searches and whole-window decisions for the 164a template."""
from __future__ import annotations

from .tid_search import AXES, function, replace_once

HISTORY_SIZE = 16
POLICY_STATE_VARIABLES = {
    **{f"{a}_NEG": f"${a}_RNG_Min_Range" for a in AXES},
    **{f"RETURN_{a}": f"$TID返回{a}" for a in AXES},
    "RETURN_STAGE": "$TID返回层级", "RETURN_DISTANCE": "$TID返回距离",
    "LOCAL_CORRECTION": "$TID局部起始修正",
    "COMPLETED_REGIONS": "$TID完成区域数", "HISTORY_SLOT": "$TID历史写位",
    **{f"H{i}_{field}": f"$TID历史{i}_{field}"
       for i in range(1, HISTORY_SIZE + 1) for field in ("TARGET", "OP", "F1", "F2", "CORRECTION")},
}


def scan_function(p, request):
    lines = [f"FUNC {p}_统计接近目标", "$TID区域命中 = 0", "$TID区域距离 = 0",
             "$TID窗口小次数 = 0", "$TID窗口大次数 = 0", "$TID窗口最短 = 32769", "$TID窗口差 = 0"]
    for i in range(1, 11):
        lines += [f"IF $Slot{i} >= 0 and $Slot{i} <= 65535",
                  f"    $TID区域临时差 = $Slot{i} - $TID区域检测目标",
                  "    IF $TID区域临时差 > 32767", "        $TID区域临时差 -= 65536", "    ENDIF",
                  "    IF $TID区域临时差 < -32768", "        $TID区域临时差 += 65536", "    ENDIF",
                  "    $TID窗口临时差 = $TID区域临时差",
                  "    IF $TID区域临时差 < 0", "        $TID区域临时差 = 0 - $TID区域临时差", "    ENDIF",
                  f"    IF $TID区域临时差 <= {request.near_tid_distance}",
                  "        $TID区域命中 += 1", "        $TID区域距离 += $TID区域临时差", "    ENDIF",
                  "    IF $TID区域临时差 <= $F2candidate_range", "        $TID窗口大次数 += 1",
                  "        IF $TID区域临时差 <= $F1candidate_range", "            $TID窗口小次数 += 1", "        ENDIF", "    ENDIF",
                  "    IF $TID区域临时差 < $TID窗口最短", "        $TID窗口最短 = $TID区域临时差",
                  "        $TID窗口差 = $TID窗口临时差", "    ENDIF", "ENDIF"]
    return "\n".join(lines + ["ENDFUNC"])


def window_functions(p, request):
    targets = list(request.exhaustive_targets if request.mode == 0 else (request.target_tid,))
    values = request.to_user_values()
    if request.mode == 0:
        for enabled, extra in (
            ("$65535开关", (65535,)), ("$same_id_switch", range(0, 55556, 11111)),
            ("$个位检测开关", range(1, 10)),
            ("$continue_id_switch", (1234, 12345, 23456, 34567, 45678, 56789, 43210, 54321, 65432)),
        ):
            if values[enabled]: targets.extend(extra)
    lines = [f"FUNC {p}_采用窗口候选", "$TID窗口最佳小次数 = -1", "$TID窗口最佳大次数 = -1",
             "$TID窗口最佳距离 = 32769", "$TID窗口需观察 = 0"]
    for tid in dict.fromkeys(targets):
        lines += [f"$TID区域检测目标 = {tid}", f"CALL {p}_统计接近目标",
                  "IF $TID窗口小次数 > 0 or $TID区域命中 > 0", "    $TID窗口需观察 = 1", "ENDIF",
                  "IF $TID窗口小次数 > $TID窗口最佳小次数 or $TID窗口小次数 == $TID窗口最佳小次数 and $TID窗口大次数 > $TID窗口最佳大次数 or $TID窗口小次数 == $TID窗口最佳小次数 and $TID窗口大次数 == $TID窗口最佳大次数 and $TID窗口最短 < $TID窗口最佳距离",
                  "    $TID窗口最佳小次数 = $TID窗口小次数", "    $TID窗口最佳大次数 = $TID窗口大次数",
                  "    $TID窗口最佳距离 = $TID窗口最短", f"    $TID窗口最佳目标 = {tid}",
                  "    $TID窗口最佳差 = $TID窗口差", "ENDIF"]
    lines += ["IF $TID窗口最佳距离 <= 32768", "$targetID = $TID窗口最佳目标",
              "$AbsDelta = $TID窗口最佳距离", "$Delta = $TID窗口最佳差", "ENDIF", "ENDFUNC"]
    # The locked RNG target can differ from the primary exhaustive target.
    hold = [f"FUNC {p}_乱数窗口需观察", f"$TID区域检测目标 = ${p}_TARGET_TID",
            f"CALL {p}_统计接近目标", "$TID窗口需观察 = 0",
            "IF $TID区域命中 > 0", "$TID窗口需观察 = 1", "ENDIF", "ENDFUNC"]
    return "\n".join(lines) + "\n\n" + "\n".join(hold)


def history_functions(p, request):
    lines = [f"FUNC {p}_当前区域已经搜索", "$TID区域已搜索 = 0"]
    for i in range(1, HISTORY_SIZE + 1):
        conditions = [f"$TID历史{i}_TARGET == $TID区域检测目标", f"$TID历史{i}_CORRECTION == $OP修正"]
        for a in AXES:
            radius = max(0, getattr(request, f"auto_{a.lower()}_rng_range")) // 2 * 2
            conditions += [f"${a}总帧 >= $TID历史{i}_{a} - {radius}",
                           f"${a}总帧 <= $TID历史{i}_{a} + {radius}",
                           f"(${a}总帧 - $TID历史{i}_{a}) % 2 == 0"]
        lines += ["IF " + " and ".join(conditions), "$TID区域已搜索 = 1", "RETURN", "ENDIF"]
    lines += ["ENDFUNC", "", f"FUNC {p}_记录完成区域",
              "IF $TID局部起始修正 != $OP修正", "PRINT 局部搜索期间OP修正改变，不将混合时序记为已完成区域", "RETURN", "ENDIF",
              "$TID完成区域数 += 1", "$TID历史写位 += 1",
              f"IF $TID历史写位 > {HISTORY_SIZE}", "$TID历史写位 = 1", "ENDIF"]
    for i in range(1, HISTORY_SIZE + 1):
        lines += [f"IF $TID历史写位 == {i}", f"$TID历史{i}_TARGET = ${p}_TARGET_TID",
                  f"$TID历史{i}_CORRECTION = $OP修正"]
        lines += [f"$TID历史{i}_{a} = ${a}目标帧" for a in AXES]
        lines += ["ENDIF"]
    return "\n".join(lines + ["ENDFUNC"])


def return_functions(p, request):
    lines = [f"FUNC {p}_返回穷举", f"CALL {p}_记录完成区域", "$ID_RNG = 0", "$TID自动切换 = 0",
             f"${p}_TARGET_TID = {request.target_tid}", "$Name_GREEN = 0",
             f"$F3脚本固定延迟 = {request.f3_fixed_delay}"]
    values = request.to_user_values()
    for field in ("$same_id_switch", "$continue_id_switch", "$65535开关", "$个位检测开关"):
        lines.append(f"{field} = {values[field]}")
    lines += [f"${field} = 0" for field in ("same_condition_match", "continue_condition_match", "65535_match", "个位检测结果", "is_match")]
    for a in AXES:
        low = a.lower()
        delay = getattr(request, low + "_fixed_delay") + (request.select_correction * 600 if a == "F2" else 0)
        pad = max(0, {"OP": delay, "F1": 22050, "F2": 16750}[a] - delay)
        lines += [f"${a}脚本固定延迟 = {delay + pad}", f"${a}_Max_Range = {max(0, getattr(request, low + '_max_range')) // 2 * 2}",
                  f"${a}目标帧 = {getattr(request, low + '_target_frame')}",
                  f"${a}_RNG_Max_Range = {max(0, getattr(request, low + '_rng_range')) // 2 * 2}",
                  f"${a}_RNG_Min_Range = 0", f"${a}SearchPos = 0", f"${a} = $TID返回{a}"]
        if a != "OP": lines.append(f"${a}脚本固定延迟补偿 = {pad}")
    for i, div in enumerate((10000, 1000, 100, 10, 1), 1):
        lines += [f"$target{i} = {request.target_tid} / {div}", f"$target{i} %= 10"]
    lines += ["$RNGRadius = 0", "$RNGCurrentRadius = 0", "$RNGMaxRadius = 0",
              "$SearchStage = $TID返回层级", "$AbsDelta = $TID返回距离", "$Delta = $TID返回距离",
              f"$targetID = {request.target_tid}", f"CALL {p}_计算脚本固定帧",
              f"CALL {p}_穷举推进核心", "$denoise_hit_count = 0", "$TID区域观察 = 0", "$TID窗口需观察 = 0"]
    lines += [f"$TID返回{a} = 0" for a in AXES]
    lines += ["$TID返回层级 = 0", "$TID返回距离 = 0", "$TID局部起始修正 = 0", f"CALL {p}_计算操作延迟",
              "PRINT 局部乱数已完整搜索一遍，恢复穷举并推进下一个点", "ENDFUNC"]
    return "\n".join(lines)


def optimize_tid_search(text, request):
    p = "EN" if request.language == "英文" else "JP"
    auto = request.mode == 0 and request.auto_rng
    temporary = ("TID窗口小次数", "TID窗口大次数", "TID窗口最短", "TID窗口差", "TID窗口临时差",
                 "TID窗口最佳小次数", "TID窗口最佳大次数", "TID窗口最佳距离", "TID窗口最佳目标",
                 "TID窗口最佳差", "TID窗口需观察", "TID区域已搜索")
    globals_ = [f"{value} = {-1 if key.startswith('H') and key.endswith('_TARGET') else 0}"
                for key, value in POLICY_STATE_VARIABLES.items()]
    globals_ += [f"${name} = 0" for name in temporary]
    text = replace_once(text, "# TID_SEARCH_V3\n", "# TID_SEARCH_V3\n" + "\n".join(globals_) + "\n")
    extra = []
    scan = scan_function(p, request)
    if auto:
        text = replace_once(text, function(text, p + "_统计接近目标"), scan)
    else:
        extra.append(scan)
    extra.append(window_functions(p, request))
    old = function(text, p + "_穷举推进到下一个搜索点")
    extra.append(old.replace(p + "_穷举推进到下一个搜索点", p + "_穷举推进核心", 1))
    text = replace_once(text, old, f"FUNC {p}_穷举推进到下一个搜索点\n    CALL {p}_采用窗口候选\n    CALL {p}_穷举推进核心\nENDFUNC")
    for name, evaluate in (("穷举模式偏移运算", "采用窗口候选"), ("乱数模式偏移运算", "乱数窗口需观察")):
        old = function(text, p + "_" + name)
        head, body = old.split("\n", 1)
        hold = (f"    CALL {p}_{evaluate}\n    IF $TID窗口需观察 == 1 and $denoise_try_count < $denoise_try_window\n"
                "        PRINT 窗口曾接近目标，继续当前参数观察\n        RETURN\n    ENDIF\n")
        text = replace_once(text, old, head + "\n" + hold + body)

    # Keep the positive extent. Reject only unexecutable negative combinations,
    # before any timed round; the original frame-to-millisecond functions stay.
    old = function(text, p + "_规范搜索范围")
    for a in AXES:
        old_clip = (f"        IF ${a}_RNG_Max_Range > $TID最大半径\n"
                    f"            ${a}_RNG_Max_Range = $TID最大半径\n        ENDIF")
        new_clip = (f"        ${a}_RNG_Max_Range -= ${a}_RNG_Max_Range % 2\n"
                    f"        ${a}_RNG_Min_Range = ${a}_RNG_Max_Range\n"
                    f"        IF ${a}_RNG_Min_Range > $TID最大半径\n"
                    f"            ${a}_RNG_Min_Range = $TID最大半径\n        ENDIF\n"
                    f"        ${a}_RNG_Min_Range -= ${a}_RNG_Min_Range % 2\n"
                    f"        PRINT {a}有效偏移范围：- & ${a}_RNG_Min_Range & \" / +\" & ${a}_RNG_Max_Range")
        old = replace_once(old, old_clip, new_clip)
    text = replace_once(text, function(text, p + "_规范搜索范围"), old)
    valid = " and ".join(f"${a} >= ${a}_RNG_Max_Range - ${a}_RNG_Min_Range" for a in AXES)
    old = function(text, p + "_乱数定位到当前壳层下一个有效组合")
    text = replace_once(text, old, replace_once(old, "        IF $RNGCurrentRadius == $RNGRadius\n",
                                              "        IF $RNGCurrentRadius == $RNGRadius and " + valid + "\n"))
    if auto:
        extra += [history_functions(p, request), return_functions(p, request)]
        detect = [f"FUNC {p}_检测目标区域", "$TID区域次数 = 0", "$TID区域差 = 327681", "$TID区域观察 = 0",
                  "IF $ID_RNG != 0", "RETURN", "ENDIF"]
        for tid in request.exhaustive_targets:
            detect += [f"$TID区域检测目标 = {tid}", f"CALL {p}_当前区域已经搜索", "IF $TID区域已搜索 == 0",
                       f"CALL {p}_统计接近目标",
                       "IF $TID区域命中 > $TID区域次数 or $TID区域命中 == $TID区域次数 and $TID区域距离 < $TID区域差",
                       f"$TID区域目标 = {tid}", "$TID区域次数 = $TID区域命中", "$TID区域差 = $TID区域距离", "ENDIF", "ENDIF"]
        detect += ["IF $TID区域次数 > 0", "$TID区域观察 = 1", "ENDIF",
                   f"IF $TID区域次数 >= {request.near_tid_hits}", f"CALL {p}_打印参数", f"CALL {p}_自动转乱数", "ENDIF", "ENDFUNC"]
        text = replace_once(text, function(text, p + "_检测目标区域"), "\n".join(detect))
        backup = [f"CALL {p}_采用窗口候选", "$TID返回层级 = $SearchStage", "$TID返回距离 = $AbsDelta",
                  "$TID局部起始修正 = $OP修正"]
        backup += [f"$TID返回{a} = ${a}" for a in AXES]
        text = replace_once(text, f"FUNC {p}_自动转乱数\n", f"FUNC {p}_自动转乱数\n" + "\n".join(backup) + "\n")
        for name in ("乱数推进到下一个壳层组合", "乱数定位到当前壳层下一个有效组合"):
            old = function(text, p + "_" + name)
            anchor = "IF $RNGRadius > $RNGMaxRadius\n"
            hook = f"    IF $TID自动切换 == 1\n        CALL {p}_返回穷举\n        RETURN\n    ENDIF\n"
            text = replace_once(text, old, replace_once(old, anchor, anchor + hook))
    return text + "\n\n" + "\n\n".join(extra) + "\n"
