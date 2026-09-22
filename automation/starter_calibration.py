"""Install starter-only paired selection and measured menu timing fixes."""

import re

from app_paths import RESOURCE_ROOT

ASSET = RESOURCE_ROOT / "assets/easycon118_extensions/starter_calibration.ecs"
MARKER = "# STARTER_CALIBRATION_V1"
MENU_ADVANCE_MARKER = "# NORMAL_MENU_ADVANCE_128_V1"


def _replace(text: str, old: str, new: str, count: int = 1) -> str:
    if text.count(old) != count:
        raise ValueError(f"御三家校准升级入口不匹配: {old[:90]}")
    return text.replace(old, new)


def _upgrade_normal_menu_advance(text: str) -> str:
    if MENU_ADVANCE_MARKER in text or "FUNC 重新计算等待参数" not in text:
        return text
    if "$普通帧轴菜单额外推进帧 = 128" in text:
        # Direct-run packages may already contain the reviewed change without
        # an automation marker.  The configuration itself is the idempotency
        # marker; do not rewrite the source corpus merely to add a comment.
        return text
    text, count = re.subn(
        r"(?m)^(\$帧奇偶修正方案 = [01])$",
        r"\1\n$普通帧轴菜单额外推进帧 = 128",
        text,
        count=1,
    )
    if count != 1:
        raise ValueError("无法写入普通帧轴菜单128帧补偿")
    old = """        # 菜单方案沿用孵蛋生成帧模型：不修改F1，也不预扣菜单固定帧。
        $F1等待帧 = $临时F1等待帧
        $F2等待帧 = $临时F2等待帧
        IF $临时F2等待帧 % 2 != 0
            $帧轴菜单奇偶开关 = 1
        ENDIF
"""
    new = """        # 普通目标实测开关菜单额外推进128帧；御三家使用独立计时模型，不套此补偿。
        $F1等待帧 = $临时F1等待帧
        $F2等待帧 = $临时F2等待帧
        IF $临时F2等待帧 % 2 != 0
            $帧轴菜单奇偶开关 = 1
            IF $静态或野生 != "孵蛋" and 是否御三家目标() == 0
                $F2等待帧 = $F2等待帧 - $普通帧轴菜单额外推进帧
                # TV余帧不足时从上一圈借回314帧，保持总推进不变。
                IF $F2等待帧 < 0 and $进入TV == 1 and $TV等待帧 > 0
                    $TV等待帧 = $TV等待帧 - 1
                    $F2等待帧 = $F2等待帧 + $TV单次消耗帧
                ENDIF
            ENDIF
        ENDIF
"""
    text = _replace(text, old, new)
    text = text.replace(
        "    # 与孵蛋生成帧一致，只保留菜单动作，不预扣未经本位置A/B验证的固定推进量。",
        "    # 普通目标已在等待参数中预扣128帧；御三家保留独立计时，不使用该推进补偿。",
    )
    text = text.replace(
        "PRINT 普通帧轴奇偶修正: 开关菜单一次（F1/F2数值保持原请求）",
        "PRINT 普通帧轴奇偶修正: 开关菜单一次（普通目标预扣128帧；御三家不预扣）",
    )
    return MENU_ADVANCE_MARKER + "\n" + text


def upgrade_starter_calibration(text: str) -> str:
    if "FUNC 执行RNG启动与目标获取" not in text:
        return text
    text = text.replace("\r\n", "\n")
    text = _upgrade_normal_menu_advance(text)
    if MARKER in text:
        return text
    asset = ASSET.read_text(encoding="utf-8")
    globals_text, functions = asset.split("# STARTER_CALIBRATION_FUNCTIONS_BEGIN", 1)
    pos = re.search(r"(?m)^FUNC ", text).start()
    text = text[:pos] + globals_text + "\n" + text[pos:]
    text += "\n# STARTER_CALIBRATION_FUNCTIONS_BEGIN" + functions
    text = _replace(text, "        $反查细分成功 = 执行识图反查直到候选唯一()\n", "        CALL 御三家准备共同筛选\n        $反查细分成功 = 执行识图反查直到候选唯一()\n")
    anchor = "        IF $反查细分成功 == 1 and $调试日志输出 == 1\n"
    text = _replace(text, anchor, """        IF $御三家严格筛选 == 1 or $跨组筛选回退启用 == 1
            IF $反查细分成功 != 1
                PRINT 御三家有界反查无结果，保留参数与跨轮候选，重试下一轮
                $循环计数 += 1
                BREAK
            ENDIF
            $御三家筛选结果 = 御三家应用共同候选()
            IF $御三家筛选结果 != 1
                $循环计数 += 1
                BREAK
            ENDIF
        ENDIF
""" + anchor)
    # New target resets paired evidence; legacy path reanchoring must not.
    text = _replace(text, "\nCALL 投票重置Seed校准\n", "\nCALL 投票重置Seed校准\nCALL 共同区重置\n")
    start = text.index("FUNC 执行识图反查直到候选唯一")
    stop = text.index("ENDFUNC", start) + len("ENDFUNC")
    block = text[start:stop]
    block = _replace(block, "        $有效最大消耗帧 = $最大消耗帧\n", "        $有效最大消耗帧 = $最大消耗帧\n        CALL 御三家准备反查窗口\n")
    anchor = "            IF $扩窗层数上限 <= 0 or $当前扩窗层 >= $扩窗层数上限\n"
    block = _replace(block, anchor, """            IF $御三家严格筛选 == 1
                IF $当前扩窗层 >= 1
                    BREAK
                ENDIF
                $当前扩窗层 = 1
                $有效最小消耗帧 = $御三家预测帧 - 500
                IF $有效最小消耗帧 < 0
                    $有效最小消耗帧 = 0
                ENDIF
                $有效最大消耗帧 = $御三家预测帧 + 500
                PRINT 御三家有界兜底窗: & $有效最小消耗帧 & - & $有效最大消耗帧 & " ADV；不使用千帧扩窗"
                CONTINUE
            ENDIF
""" + anchor)
    block = _replace(block, "        IF $反查扫描成功 == 0\n            RETURN 0\n        ENDIF\n", """        IF $反查扫描成功 == 0
            IF $御三家严格筛选 == 1
                RETURN 2
            ENDIF
            RETURN 0
        ENDIF
        IF $御三家严格筛选 == 1
            PRINT 御三家完整候选保留: & $本轮候选命中计数 & "；先提交跨轮共同区，再决定是否校准"
            RETURN 1
        ENDIF
        IF $跨组筛选收集启用 == 1 and $本轮候选命中计数 >= $跨组筛选候选阈值 and $本轮候选命中计数 <= $跨组筛选候选容量
            $跨组筛选回退启用 = 1
            PRINT 多候选跨组筛选: 本轮候选 & $本轮候选命中计数 & "，达到阈值 " & $跨组筛选候选阈值 & "；保留完整候选组，不按路径猜测"
            RETURN 1
        ENDIF
""")
    text = text[:start] + block + text[stop:]
    anchor = "    $投票忽略 = 投票记真值解($本轮真值解, $消耗帧本轮偏离中心)\n"
    text = _replace(text, anchor, """    IF ($御三家严格筛选 == 1 or $跨组筛选回退启用 == 1) and $御三家共同证据可信 == 1
        $Seed本轮可信 = 1
        $TV帧本轮可信 = 1
        IF $本轮剩余帧校准允许 == 1
            $剩余帧本轮可信 = 1
            $消耗帧本轮可信 = 1
        ENDIF
    ENDIF
""" + anchor)
    # Timeline already budgets the menu inside its absolute deadline.
    start = text.index("FUNC 执行RNG启动与目标获取")
    stop = text.index("ENDFUNC", start) + len("ENDFUNC")
    block = text[start:stop]
    if "$F2时间轴截止" not in block:
        anchor = "    # 普通帧轴菜单奇偶方案："
        block = _replace(block, anchor, "    $御三家F2执行等待MS = $F2等待MS\n    $御三家菜单耗时MS = 0\n" + anchor)
        anchor = "        X\n        WAIT 500\n        B\n        WAIT 500\n"
        block = _replace(block, anchor, """        $御三家菜单起始MS = TIME()
""" + anchor + """        IF $循环计数 > 0 and ($目标全国图鉴编号 == 1 or $目标全国图鉴编号 == 4 or $目标全国图鉴编号 == 7)
            $御三家菜单耗时MS = TIME() - $御三家菜单起始MS
            $御三家F2执行等待MS = 御三家计算菜单剩余等待($F2等待MS, $御三家菜单耗时MS)
            IF $御三家F2执行等待MS < 0
                PRINT 御三家菜单耗时超过F2等待预算，本轮不领取
                RETURN -1
            ENDIF
            PRINT 御三家菜单计时: 实耗 & $御三家菜单耗时MS & " ms；F2剩余等待 " & $御三家F2执行等待MS & " ms"
        ENDIF
""")
        block = _replace(block, "$遭遇地点, $F2等待MS, $TV等待MS, $钓鱼最长时间", "$遭遇地点, $御三家F2执行等待MS, $TV等待MS, $钓鱼最长时间", count=2)
    text = text[:start] + block + text[stop:]
    # Recompute diagnostics for the selected pair, without collecting/voting again.
    start = text.index("    # 路径一致性选择：", text.index("FUNC 处理匹配候选"))
    stop = text.index("    IF $最佳候选有效 == 0", start)
    text += "\nFUNC 御三家刷新候选距离\n    $当前候选帧原始 = $当前消耗帧 - $目标消耗帧\n" + text[start:stop] + "ENDFUNC\n"
    return MARKER + "\n" + text
