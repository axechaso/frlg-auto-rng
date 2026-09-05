"""Restore the original per-attempt report in generated 164a copies only.

All added arithmetic uses display-only globals. The original ADV and SELECT
assignments remain in the print helper because flow markers depend on them.
"""
from __future__ import annotations

from .tid_search import AXES, function, replace_once
from .tid_starter_save import split_tid_modules


def choice_lines(variable: str, label: str, choices: tuple[str, ...]) -> list[str]:
    lines = []
    for index, choice in enumerate(choices):
        lines += [f"{'IF' if index == 0 else 'ELIF'} ${variable} == {index}",
                  f"    PRINT {label}：{choice}"]
    return lines + ["ENDIF"]


def restore_tid_logging(text: str, request) -> str:
    head, english, japanese, tail = split_tid_modules(text)
    p = "EN" if request.language == "英文" else "JP"
    module = english if p == "EN" else japanese
    globals_ = ["# TID_LOG_V1"] + [f"$TID日志{name} = 0" for name in (
        "轮次", "目标", "位1", "位2", "位3", "位4", "位5", "OP", "F1", "F2")]
    head = replace_once(head, "# 唤醒设备\n", "\n".join(globals_) + "\n\n# 唤醒设备\n")
    digits = " & ".join(f"$TID日志位{i}" for i in range(1, 6))
    formatter = [f"FUNC {p}_日志目标位数"]
    for i, divisor in enumerate((10000, 1000, 100, 10, 1), 1):
        formatter += [f"$TID日志位{i} = $TID日志目标 / {divisor}", f"$TID日志位{i} %= 10"]
    formatter += ["ENDFUNC"]
    old = function(module, p + "_打印参数")
    # Preserve the two non-display calculations verbatim.
    intro = old[:old.index("    PRINT 当前TID：")].rstrip()
    lines = [intro, "PRINT =========== 目标信息 ===========", "IF $ID_RNG == 0",
             "    PRINT 当前模式：穷举",
             "    PRINT 目标TID：" + "、".join(f"{tid:05d}" for tid in request.exhaustive_targets)]
    values = request.to_user_values()
    special = [label for key, label in (("$same_id_switch", "豹子"), ("$个位检测开关", "个位"),
               ("$continue_id_switch", "连号"), ("$65535开关", "65535")) if values[key]]
    lines += ["    PRINT 特殊号码筛选：" + ("、".join(special) if special else "关闭")]
    if request.auto_rng and request.mode == 0:
        lines += [f"    PRINT 自动转乱数：同一目标环形距离≤{request.near_tid_distance}，窗口内累计{request.near_tid_hits}次触发",
                  "    PRINT 当前接近次数： & $TID区域次数 & \" / " + str(request.near_tid_hits) + "\""]
    lines += ["ELSE", "    IF $TID自动切换 == 1", "        PRINT 当前模式：乱数（穷举自动切换）",
              "    ELSE", "        PRINT 当前模式：乱数", "    ENDIF",
              f"    $TID日志目标 = ${p}_TARGET_TID", f"    CALL {p}_日志目标位数",
              "    PRINT 目标TID： & " + digits, "ENDIF",
              "IF $ID_RNG == 1 and $SID_RAND == 0", f"    $TID日志目标 = ${p}_TARGET_SID",
              f"    CALL {p}_日志目标位数", "    PRINT 目标SID： & " + digits,
              "ELSE", "    PRINT 目标SID：随机（未指定）", "ENDIF",
              "PRINT SID ADV： & $adv & \"（时序推算）\""]
    lines += choice_lines("Name_GREEN", "劲敌自定义名称", ("否", "是"))
    lines += ["PRINT =========== TID数据 ===========",
              "PRINT 脚本版本： & $TID脚本版本", "PRINT 游戏语言：" + request.language,
              "PRINT NS机型：Switch & $NS机型",
              "PRINT 当前TID： & $curr1 & $curr2 & $curr3 & $curr4 & $curr5",
              "PRINT 当前TID命中次数： & $denoise_hit_count & \" / \" & $denoise_need_hit & \"（同参数窗口）\"",
              "PRINT 本参数观察次数： & $denoise_try_count & \" / \" & $denoise_try_window",
              "PRINT 【OP】 & $OP总帧 & 【F1】 & $F1总帧 & 【F2】 & $F2总帧",
              "PRINT 主角名称： & $name",
              "PRINT select执行次数： & $select执行次数 & \"；HOME_BUFFER(ms)：\" & $HOME_BUFFER延迟",
              "PRINT OP修正(ms)： & $OP修正"]
    lines += choice_lines("Sound", "Sound", ("MONO", "STEREO"))
    lines += choice_lines("Button_Mode", "Button Mode", ("HELP", "LR", "L=A"))
    lines += choice_lines("Seed_Button", "Seed Button", ("A", "START", "L(L=A)"))
    lines += choice_lines("取名进入键", "取名进入键", ("A", "B"))
    lines += ["PRINT ========== 当前搜索进度 =========", "$TID日志目标 = $targetID",
              f"CALL {p}_日志目标位数", "PRINT 本轮参考目标TID： & " + digits,
              "PRINT 本轮环形差值： & $Delta", "IF $ID_RNG == 0"]
    lines += ["    " + line for line in choice_lines("SearchStage", "当前阶段", (
        "F2外层筛查", "固定F2遍历F1", "固定F2/F1遍历OP"))]
    lines += ["    PRINT 当前偏移/搜索上限（帧）：",
              "    PRINT 【OP】 & $OP & \" / \" & $OP_Max_Range & \"【F1】\" & $F1 & \" / \" & $F1_Max_Range & \"【F2】\" & $F2 & \" / \" & $F2_Max_Range",
              "ELSE", "    PRINT 乱数中心：OP= & $OP目标帧 & \" / F1=\" & $F1目标帧 & \" / F2=\" & $F2目标帧"]
    for axis in AXES:
        lines += [f"    $TID日志{axis} = ${axis} - ${axis}_RNG_Max_Range",
                  f"    PRINT {axis}当前偏移： & $TID日志{axis} & \"；有效范围：-\" & ${axis}_RNG_Min_Range & \" / +\" & ${axis}_RNG_Max_Range"]
    lines += ["    PRINT 当前壳层半径： & $RNGRadius & \" / \" & $RNGMaxRadius", "ENDIF",
              "ENDFUNC"]
    module = replace_once(module, old, "\n".join(lines))

    # A repeated unrelated TID is a useful observation, not a successful target.
    # Emit the full reusable settings only in one of the five confirmed exits.
    success = "                IF $denoise_hit_count >= $denoise_need_hit\n"
    if module.count(success) != 5:
        raise ValueError("TID日志缺少五种已确认命中出口")
    module = module.replace(success, success + "                    PRINT ✅ 目标已通过去噪确认\n"
                            + f"                    CALL {p}_打印回填参数\n")
    for label in ("豹子TID", "个位TID", "连号TID", "65535", "5位TID全"):
        module = replace_once(module, f"PRINT ✅ {label}匹配成功！", f"PRINT 发现候选：{label.replace('5位TID全', '指定TID')}")

    # The auto-switch path reports the completed observation before resetting
    # its window, but increments the actual round counter later in the caller.
    if request.auto_rng and request.mode == 0:
        old = function(module, p + "_检测目标区域")
        report = ("$TID日志轮次 = $CISHU + 1\nPRINT ========================\n"
                  "PRINT 📋 第 & $TID日志轮次 & 轮\n" + f"CALL {p}_打印参数")
        module = replace_once(module, old, replace_once(old, f"CALL {p}_打印参数", report))
        module = replace_once(module,
            f'    PRINT 锁定目标TID： & ${p}_TARGET_TID & "；窗口内接近次数：" & $TID区域次数',
            f'    $TID日志目标 = ${p}_TARGET_TID\n    CALL {p}_日志目标位数\n'
            + '    PRINT 锁定目标TID： & ' + digits + ' & "；窗口内接近次数：" & $TID区域次数')
    # The policy selects a target using the entire window, not just this round.
    module = module.replace("PRINT 当前距离最近目标TID:", "PRINT 窗口优先目标TID:")
    module = module.replace("PRINT 当前TID与最近目标差值:", "PRINT 窗口最近环形差值:")
    module += "\n" + "\n".join(formatter) + "\n"
    return head + (module if p == "EN" else english) + (module if p == "JP" else japanese) + tail
