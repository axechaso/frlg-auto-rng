import unittest
from pathlib import Path

from automation.easycon118 import (
    EGG_HOME_BUFFER_GLOBALS,
    EGG_HOME_BUFFER_OVERRIDE_PATH,
    EGG_HATCH_EXIT_OVERRIDE_PATH,
    EGG_PARTY_SLOT_CANDY_OVERRIDE_PATH,
    EGG_PARTY_SLOT_MAIN_OVERRIDE_PATH,
    EGG_REVERSE_LOOKUP_POLICY_MARKER,
    EGG_REVERSE_LOOKUP_WINDOW_MARKER,
    EGG_POND_SETTLE_FIXED,
    EGG_POND_SETTLE_ORIGINAL,
    EGG_PREPARED_254_OVERRIDE_MARKER,
    EGG_RESTART_GLOBALS,
    EGG_RESTART_OVERRIDE_PATH,
    EGG_SEED_CONTROLLER_OVERRIDE_PATH,
    EGG_SETTINGS_GLOBALS,
    EGG_SETTINGS_OVERRIDE_PATH,
    EGG_SURF_BATTLE_OVERRIDE_PATH,
    EGG_TRANSIENT_RETRY_OVERRIDE_MARKER,
    PARTY_SUMMARY_NAVIGATION_PATH,
    TOGEPI_HATCH_CYCLE_OVERRIDE_PATH,
    WILD_PID_RETRY_LIMIT_MARKER,
    EggRunRequest,
    _apply_egg_home_resample_fix_text,
    _apply_egg_home_buffer_runtime_override_text,
    _apply_egg_hatch_exit_runtime_override_text,
    _apply_egg_party_slot_candy_runtime_override_text,
    _apply_egg_party_slot_main_runtime_override_text,
    _apply_egg_reverse_lookup_policy_text,
    _apply_egg_reverse_lookup_window_text,
    _apply_egg_pond_settle_delay_text,
    _apply_egg_prepared_254_runtime_override_text,
    _apply_egg_restart_runtime_override_text,
    _apply_egg_seed_controller_runtime_override_text,
    _apply_egg_summary_fix_text,
    _apply_egg_settings_runtime_override_text,
    _apply_egg_surf_battle_runtime_override_text,
    _apply_egg_transient_retry_runtime_override_text,
    _apply_party_summary_navigation_text,
    _apply_togepi_hatch_cycle_override_text,
    _apply_wild_pid_retry_limit_text,
    configure_egg_template_text,
    egg_request_to_user_values,
)


def egg_request(**changes):
    values = {
        "game": "fr_nx",
        "seed_mode": 1,
        "target_seed": "75d1",
        "held_advances": 8021,
        "pickup_advances": 10021,
        "species_id": 148,
        "compatibility": 70,
        "parent_a_gender": "雌",
        "parent_a_ivs": (31, 30, 29, 28, 27, 26),
        "parent_b_gender": "雄",
        "parent_b_ivs": (0, 1, 2, 3, 4, 5),
    }
    values.update(changes)
    return EggRunRequest(**values)


class EasyCon118EggTests(unittest.TestCase):
    def test_egg_reverse_lookup_prefers_normal_then_split_without_mixing_methods(self):
        original = """\
$孵蛋蛋反查最多糖果 = 8
FUNC 孵蛋流程_执行蛋个体反查(): INT
            # FRLG常用Split优先；Split有候选时不再混入其他方法，避免扩大歧义。
            FOR $孵蛋流程方法顺序 = 0 TO 3
                IF $孵蛋流程方法顺序 == 0
                    $孵蛋流程扫描方法 = 12
                ELIF $孵蛋流程方法顺序 == 1
                    $孵蛋流程扫描方法 = 11
                ELIF $孵蛋流程方法顺序 == 2
                    $孵蛋流程扫描方法 = 13
                ELSE
                    $孵蛋流程扫描方法 = 14
                ENDIF
                $孵蛋流程当前方法候选数 = 孵蛋反查_取总命中数()
                IF $孵蛋流程当前方法候选数 > 0
                    PRINT 孵蛋方法 & $孵蛋流程扫描方法
                    IF $孵蛋流程候选总数 == 0 and $孵蛋流程当前方法候选数 == 1
                        $孵蛋流程实际方法 = $孵蛋流程扫描方法
                    ENDIF
                    $孵蛋流程候选总数 += $孵蛋流程当前方法候选数
                    IF $孵蛋流程扫描方法 == 12
                        BREAK
                    ENDIF
                ENDIF
            NEXT
            IF $孵蛋流程候选总数 > 0
                BREAK
            ENDIF
# -------------------- 总控与重试
"""
        configured = _apply_egg_reverse_lookup_policy_text(original)
        configured_again = _apply_egg_reverse_lookup_policy_text(configured)

        self.assertEqual(configured_again, configured)
        self.assertIn(EGG_REVERSE_LOOKUP_POLICY_MARKER, configured)
        self.assertIn("$孵蛋蛋反查最多糖果 = 20", configured)
        self.assertLess(
            configured.index("$孵蛋流程扫描方法 = 11"),
            configured.index("$孵蛋流程扫描方法 = 12"),
        )
        self.assertIn(
            "$孵蛋流程候选总数 = $孵蛋流程当前方法候选数",
            configured,
        )
        self.assertNotIn("Split已有候选", configured)
        self.assertNotIn("$孵蛋流程候选总数 += $孵蛋流程当前方法候选数", configured)

    def test_egg_reverse_lookup_does_not_expand_frame_window(self):
        original = """\
FUNC 孵蛋流程_执行蛋个体反查(): INT
        FOR $孵蛋流程蛋扩窗层 = 0 TO 2
            IF $孵蛋流程蛋扩窗层 == 0
                $孵蛋流程蛋帧半宽 = $孵蛋个体反查帧容差
            ELIF $孵蛋流程蛋扩窗层 == 1
                $孵蛋流程蛋帧半宽 = 5000
            ELSE
                $孵蛋流程蛋帧半宽 = 10000
            ENDIF
            PRINT 孵蛋蛋个体反查第 & $孵蛋流程蛋扩窗层 & " 层无结果，自动扩窗"
        NEXT
ENDFUNC

# -------------------- 总控与重试
"""
        configured = _apply_egg_reverse_lookup_window_text(original)

        self.assertEqual(
            _apply_egg_reverse_lookup_window_text(configured),
            configured,
        )
        self.assertIn(EGG_REVERSE_LOOKUP_WINDOW_MARKER, configured)
        self.assertIn("FOR $孵蛋流程蛋扩窗层 = 0 TO 0", configured)
        self.assertIn("$孵蛋流程蛋帧半宽 = $孵蛋个体反查帧容差", configured)
        self.assertNotIn("5000", configured)
        self.assertNotIn("10000", configured)
        self.assertNotIn("自动扩窗", configured)
        self.assertIn("孵蛋蛋个体反查固定帧窗无结果", configured)

    def test_generated_projects_use_the_reviewed_wild_pid_retry_limit(self):
        imported = """\\
$野生PID尝试上限 = 1000
FUNC 测试(): INT
    RETURN 1
ENDFUNC
"""
        configured = _apply_wild_pid_retry_limit_text(imported)

        self.assertIn(WILD_PID_RETRY_LIMIT_MARKER, configured)
        self.assertIn("$野生PID尝试上限 = 200", configured)
        self.assertNotIn("$野生PID尝试上限 = 1000", configured)
        self.assertEqual(_apply_wild_pid_retry_limit_text(configured), configured)
        with self.assertRaises(ValueError):
            _apply_wild_pid_retry_limit_text("$野生PID尝试上限 = 100\n")

    def test_request_maps_same_seed_egg_fields(self):
        values = egg_request_to_user_values(egg_request())
        self.assertEqual(values["静态或野生"], "孵蛋")
        self.assertEqual(values["目标Seed"], "75D1")
        self.assertEqual(values["目标消耗帧"], 8021)
        self.assertEqual(values["孵蛋领取目标帧"], 10021)
        self.assertEqual(values["孵蛋双亲A_HP"], 31)
        self.assertEqual(values["孵蛋双亲B_SPE"], 5)
        self.assertFalse(egg_request().to_dict()["start_from_prepared_254"])

    def test_prepared_254_mode_skips_only_one_time_preparation(self):
        original = """\
$孵蛋同Seed模式 = 1
FUNC 孵蛋流程_执行(): INT
    $孵蛋前置结果 = 孵蛋测试_执行前置准备($Seed模式, $游戏设置识图阈值)
    IF $孵蛋前置结果 != 1
        RETURN 0
    ENDIF
    CALL 孵蛋流程_重开下一轮

    $孵蛋流程尝试次数 = 0
    RETURN 1
ENDFUNC
"""
        configured = _apply_egg_prepared_254_runtime_override_text(original, True)

        self.assertIn(EGG_PREPARED_254_OVERRIDE_MARKER, configured)
        self.assertIn("$孵蛋从已完成254步开始 = 1", configured)
        self.assertIn("跳过走位、设置检查和存档", configured)
        self.assertIn("CALL 孵蛋流程_重开下一轮", configured)
        self.assertIn("孵蛋测试_执行前置准备", configured)
        self.assertEqual(
            _apply_egg_prepared_254_runtime_override_text(configured, True),
            configured,
        )
        full_mode = _apply_egg_prepared_254_runtime_override_text(configured, False)
        self.assertIn("$孵蛋从已完成254步开始 = 0", full_mode)

    def test_template_replaces_all_required_egg_inputs(self):
        names = (
            "游戏版本文本", "Seed模式", "NX机型", "目标Seed", "目标消耗帧",
            "目标宝可梦名称", "目标全国图鉴编号", "静态或野生",
            "孵蛋同Seed模式", "孵蛋领取目标帧", "孵蛋双亲相性",
            "孵蛋亲本A性别", "孵蛋亲本B性别",
            "孵蛋双亲A_HP", "孵蛋双亲A_ATK", "孵蛋双亲A_DEF",
            "孵蛋双亲A_SPA", "孵蛋双亲A_SPD", "孵蛋双亲A_SPE",
            "孵蛋双亲B_HP", "孵蛋双亲B_ATK", "孵蛋双亲B_DEF",
            "孵蛋双亲B_SPA", "孵蛋双亲B_SPD", "孵蛋双亲B_SPE",
        )
        template = "\n".join(f'${name} = "old"' for name in names)
        template += (
            "\n    PRINT 孵蛋蛋种: & 目标中文名称($游戏版本, $孵蛋蛋种族全国图鉴编号)"
            " & \"（全国图鉴 \" & $孵蛋蛋种族全国图鉴编号 & \"）\""
        )
        template += (
            "\n    PRINT 亲本: A \" & $孵蛋亲本A性别 & \"，B \""
            " & $孵蛋亲本B性别 & \"，相性 \" & $孵蛋双亲相性"
        )
        template += "\n# ============================进阶设置\n$内部参数 = 1"
        configured = configure_egg_template_text(template, egg_request())
        self.assertIn('$静态或野生 = "孵蛋"', configured)
        self.assertIn('$目标Seed = "75D1"', configured)
        self.assertIn('$孵蛋双亲A_DEF = 29', configured)
        self.assertIn('$孵蛋双亲B_SPA = 3', configured)
        self.assertIn(
            "$孵蛋蛋种名称文本 = 目标中文名称($游戏版本, $孵蛋蛋种族全国图鉴编号)",
            configured,
        )
        self.assertIn("PRINT 亲本: A & $孵蛋亲本A性别", configured)

    def test_request_rejects_unsupported_timeline_inputs(self):
        invalid = (
            ({"target_seed": ""}, "Seed"),
            ({"target_seed": "GGGG"}, "Seed"),
            ({"pickup_advances": 9800}, "1800"),
            ({"compatibility": 60}, "20、50 或 70"),
            ({"parent_a_gender": "雄"}, "亲本 A"),
            ({"parent_a_ivs": (31, 31, 31, 31, 31, 32)}, "0-31"),
            ({"start_from_prepared_254": 1}, "布尔值"),
        )
        for changes, message in invalid:
            with self.subTest(changes=changes):
                with self.assertRaisesRegex(ValueError, message):
                    egg_request(**changes).validate()

    def test_settings_runtime_override_is_bounded_and_idempotent(self):
        original = """\
$孵蛋库_设置结果 = 0
FUNC 孵蛋测试_检查校正并保存游戏设置($Seed模式: INT, $识图阈值: INT): INT
    PRINT 原始单次检查
    RETURN 0
ENDFUNC

FUNC 孵蛋测试_执行前置准备($Seed模式: INT, $识图阈值: INT): INT
    RETURN 1
ENDFUNC
"""
        override = Path(EGG_SETTINGS_OVERRIDE_PATH).read_text(encoding="utf-8")
        configured = _apply_egg_settings_runtime_override_text(original, override)
        configured_again = _apply_egg_settings_runtime_override_text(configured, override)

        self.assertEqual(configured_again, configured)
        self.assertIn(EGG_SETTINGS_GLOBALS, configured)
        self.assertNotIn("原始单次检查", configured)
        self.assertEqual(configured.count("FOR $孵蛋库_设置识别尝试 = 1 TO 3"), 4)
        self.assertIn("设置识别 TEXT 第", configured)
        self.assertIn("设置识别 BATTLE 第", configured)
        self.assertIn("设置识别 SOUND 第", configured)
        self.assertIn("设置识别 BUTTON 第", configured)
        self.assertIn("WAIT 2000", configured)

    def test_game_restart_uses_original_flow_with_exit_state_priority(self):
        original = """\
$孵蛋库_正在关闭匹配 = 0
FUNC 孵蛋测试_关闭游戏($识图阈值: INT): INT
    FOR
        IF $孵蛋库_主页匹配 < $识图阈值 and $孵蛋库_主页NS2匹配 < $识图阈值
            HOME 100
            WAIT 1500
        ENDIF
        PRINT 不应使用按HOME前的旧分数
    NEXT
ENDFUNC

FUNC 孵蛋测试_软重启并跳过回忆($识图阈值: INT): INT
    RETURN 1
ENDFUNC
"""
        override = Path(EGG_RESTART_OVERRIDE_PATH).read_text(encoding="utf-8")
        configured = _apply_egg_restart_runtime_override_text(original, override)
        configured_again = _apply_egg_restart_runtime_override_text(configured, override)

        self.assertEqual(configured_again, configured)
        self.assertIn(EGG_RESTART_GLOBALS, configured)
        self.assertLess(
            configured.index("IF ($孵蛋库_正确退出匹配"),
            configured.index("ELIF $孵蛋库_主页匹配"),
        )
        self.assertEqual(configured.count("HOME 100"), 1)
        self.assertIn("$孵蛋库_已请求主页 == 0", configured)
        self.assertIn("$孵蛋库_重启识别尝试 < 3", configured)
        self.assertIn("已从游戏内请求主页，重新采样", configured)

    def test_egg_summary_fix_is_idempotent(self):
        original = """\
    PRINT 孵蛋蛋种: & 目标中文名称($游戏版本, $孵蛋蛋种族全国图鉴编号) & "（全国图鉴 " & $孵蛋蛋种族全国图鉴编号 & "）"
    PRINT 亲本: A " & $孵蛋亲本A性别 & "，B " & $孵蛋亲本B性别 & "，相性 " & $孵蛋双亲相性
"""
        configured = _apply_egg_summary_fix_text(original)
        configured_again = _apply_egg_summary_fix_text(configured)
        self.assertEqual(configured_again, configured)
        self.assertNotIn("PRINT 孵蛋蛋种: & 目标中文名称", configured)
        self.assertIn("$孵蛋蛋种名称文本 = 目标中文名称", configured)
        self.assertIn("PRINT 亲本: A & $孵蛋亲本A性别", configured)
        self.assertNotIn('PRINT 亲本: A " &', configured)

    def test_egg_home_buffer_brackets_selected_nx_window(self):
        original = """\
$HOME_BUFFER当前错误退出_NS2 = 0
FUNC HOME_BUFFER
    IF @HOME_BUFFER正确退出 >= 95 or @HOME_BUFFER正确退出_NS2 >= 95
        RETURN
    ENDIF
ENDFUNC

FUNC 各阶段脚本固定延迟转帧数
    RETURN
ENDFUNC

FUNC 孵蛋流程_执行(): INT
    CALL 孵蛋流程_重开下一轮

    $孵蛋流程尝试次数 = 0
    FOR
        $孵蛋流程尝试次数 += 1
    NEXT
    RETURN 1
ENDFUNC
"""
        override = Path(EGG_HOME_BUFFER_OVERRIDE_PATH).read_text(encoding="utf-8")
        configured = _apply_egg_home_buffer_runtime_override_text(original, override)
        configured_again = _apply_egg_home_buffer_runtime_override_text(
            configured,
            override,
        )

        self.assertEqual(configured_again, configured)
        self.assertIn(EGG_HOME_BUFFER_GLOBALS, configured)
        self.assertIn("IF $NX机型 == 1", configured)
        self.assertIn(
            "$孵蛋HOME_BUFFER选中正确 = $HOME_BUFFER当前正确退出\n",
            configured,
        )
        self.assertIn(
            "$孵蛋HOME_BUFFER选中正确 = $HOME_BUFFER当前正确退出_NS2\n",
            configured,
        )
        self.assertIn("IF $孵蛋HOME_BUFFER选中正确 >= 95", configured)
        self.assertNotIn(
            "IF @HOME_BUFFER正确退出 >= 95 or @HOME_BUFFER正确退出_NS2 >= 95",
            configured,
        )
        self.assertIn(
            "$孵蛋HOME_BUFFER下一延迟 = ($孵蛋HOME_BUFFER短边界 + $孵蛋HOME_BUFFER长边界) / 2",
            configured,
        )
        self.assertIn("$孵蛋HOME_BUFFER尝试 > 20", configured)
        self.assertEqual(
            configured.count("孵蛋流程停止：HOME_BUFFER未找到当前主机的可用延迟"),
            2,
        )
        self.assertIn(
            "CALL 孵蛋流程_重开下一轮\n    IF $孵蛋HOME_BUFFER失败 == 1",
            configured,
        )

    def test_wild_reverse_uses_party_tail_but_egg_keeps_fixed_fifth_slot(self):
        original = """\
FUNC 孵蛋流程_选择队伍槽($队伍位置: INT): INT
    RETURN 1
ENDFUNC

FUNC 孵蛋流程_打开指定槽能力页($队伍位置: INT): INT
    RETURN 1
ENDFUNC

# -------------------- 野生Seed验证 --------------------
FUNC 孵蛋流程_验证野生Seed($队伍位置: INT): INT
    $孵蛋流程开页结果 = 孵蛋流程_打开指定槽能力页($队伍位置)
    $神奇糖果结果 = 孵蛋测试_使用神奇糖果指定槽($队伍位置)
    RETURN 1
ENDFUNC

FUNC 孵蛋流程_执行蛋个体反查(): INT
    $孵蛋流程开页结果 = 孵蛋流程_打开指定槽能力页(5)
    $神奇糖果结果 = 孵蛋测试_使用神奇糖果指定槽(5)
    $刚使用神奇糖果 = 1
    CALL 打开能力值识图页面
    RETURN 1
ENDFUNC

# -------------------- 总控与重试
"""
        override = Path(EGG_PARTY_SLOT_MAIN_OVERRIDE_PATH).read_text(encoding="utf-8")
        configured = _apply_egg_party_slot_main_runtime_override_text(original, override)
        configured_again = _apply_egg_party_slot_main_runtime_override_text(
            configured,
            override,
        )

        self.assertEqual(configured_again, configured)
        self.assertIn(
            "孵蛋流程_打开指定槽能力页($队伍位置, 1)",
            configured,
        )
        self.assertIn(
            "孵蛋测试_使用神奇糖果指定槽($队伍位置, 1)",
            configured,
        )
        self.assertIn("孵蛋流程_打开指定槽能力页(5, 0)", configured)
        self.assertIn("孵蛋测试_使用神奇糖果指定槽(5, 0)", configured)

        egg_section = configured.split(
            "FUNC 孵蛋流程_执行蛋个体反查(): INT",
            1,
        )[1].split("# -------------------- 总控与重试", 1)[0]
        self.assertIn(
            "$孵蛋流程开页结果 = 孵蛋流程_喂糖后打开蛋能力页()",
            egg_section,
        )
        self.assertNotIn("CALL 打开能力值识图页面", egg_section)
        helper = configured.split(
            "FUNC 孵蛋流程_喂糖后打开蛋能力页(): INT",
            1,
        )[1].split("ENDFUNC", 1)[0]
        self.assertEqual(helper.count("    UP\n"), 4)

        tail_branch = configured.split("IF $目标为队伍末位 == 1", 1)[1].split(
            "ELIF $队伍位置 == 5",
            1,
        )[0]
        fifth_slot_branch = configured.split("ELIF $队伍位置 == 5", 1)[1].split(
            "ELIF $队伍位置 == 6",
            1,
        )[0]
        self.assertIn("反查_队伍页按上移次数选择目标(2)", tail_branch)
        self.assertIn("反查_队伍页按上移次数选择目标(3)", fifth_slot_branch)
        self.assertNotIn("        UP\n", tail_branch)
        self.assertNotIn("        UP\n", fifth_slot_branch)

    def test_normal_and_egg_summary_navigation_share_the_up_count_helper(self):
        original = """\
FUNC 打开能力值识图页面
    IF $刚使用神奇糖果 == 0
        IF $目标全国图鉴编号 != 1
            IF $道具乱数模式 == 1
                CALL 选择道具乱数本轮捕获位置
            ELSE
                UP
                500
                UP
                500
            ENDIF
        ENDIF
    ENDIF
ENDFUNC
"""
        helper = Path(PARTY_SUMMARY_NAVIGATION_PATH).read_text(encoding="utf-8")
        configured = _apply_party_summary_navigation_text(original, helper)
        configured_again = _apply_party_summary_navigation_text(configured, helper)

        self.assertEqual(configured_again, configured)
        self.assertEqual(
            configured.count("FUNC 反查_队伍页按上移次数选择目标"),
            1,
        )
        summary = configured.split("FUNC 打开能力值识图页面", 1)[1]
        self.assertIn(
            "$反查队伍槽选择结果 = 反查_队伍页按上移次数选择目标(2)",
            summary,
        )
        self.assertNotIn("ELSE\n            UP\n", summary)

        egg_override = Path(EGG_PARTY_SLOT_MAIN_OVERRIDE_PATH).read_text(
            encoding="utf-8"
        )
        fifth_slot = egg_override.split("ELIF $队伍位置 == 5", 1)[1].split(
            "ELIF $队伍位置 == 6",
            1,
        )[0]
        self.assertIn("反查_队伍页按上移次数选择目标(3)", fifth_slot)

    def test_candy_navigation_uses_the_same_party_tail_rule(self):
        original = """\
FUNC 孵蛋测试_使用神奇糖果指定槽($队伍位置: INT): INT
    RETURN 1
ENDFUNC

# ============================================================
# Seed启动与同Seed两次命中
"""
        override = Path(EGG_PARTY_SLOT_CANDY_OVERRIDE_PATH).read_text(encoding="utf-8")
        configured = _apply_egg_party_slot_candy_runtime_override_text(original, override)
        configured_again = _apply_egg_party_slot_candy_runtime_override_text(
            configured,
            override,
        )

        self.assertEqual(configured_again, configured)
        self.assertIn(
            "FUNC 孵蛋测试_使用神奇糖果指定槽($队伍位置: INT, $目标为队伍末位: INT): INT",
            configured,
        )
        tail_branch = configured.split("IF $目标为队伍末位 == 1", 1)[1].split(
            "ELIF $队伍位置 == 5",
            1,
        )[0]
        fifth_slot_branch = configured.split("ELIF $队伍位置 == 5", 1)[1].split(
            "ELIF $队伍位置 == 6",
            1,
        )[0]
        self.assertEqual(tail_branch.count("        UP\n"), 2)
        self.assertEqual(fifth_slot_branch.count("        UP\n"), 3)

    def test_pond_route_waits_for_battle_before_name_ocr(self):
        original = """\
FUNC 孵蛋测试_前往池塘并甜甜香气抓捕($识图阈值: INT, $出闪后继续抓捕: INT): INT
    WAIT 800
    $孵蛋库_抓捕对象名称 = 识别抓捕对象名称优先OCR($识图阈值)
    RETURN 1
ENDFUNC

FUNC 孵蛋测试_执行骑车孵化($全国图鉴编号: INT, $周期覆盖: INT, $每循环步数: INT, $安全循环数: INT): INT
    RETURN 1
ENDFUNC
"""
        override = Path(EGG_SURF_BATTLE_OVERRIDE_PATH).read_text(encoding="utf-8")
        configured = _apply_egg_surf_battle_runtime_override_text(original, override)
        configured_again = _apply_egg_surf_battle_runtime_override_text(
            configured,
            override,
        )

        self.assertEqual(configured_again, configured)
        self.assertIn("WAIT 2000", configured)
        self.assertIn("WAIT 2500", configured)
        self.assertIn("ELSE\n            A\n        ENDIF", configured)
        self.assertIn("@冲浪", configured)
        self.assertNotIn("@三代菜单栏", configured)
        self.assertIn("@野生出现", configured)
        self.assertIn("@抓捕就绪", configured)
        surf_gate = configured[
            configured.index("FUNC 孵蛋测试_等待池塘冲浪结束") : configured.index(
                "FUNC 孵蛋测试_等待池塘野生战斗"
            )
        ]
        self.assertIn("$孵蛋库_池塘冲浪匹配 > 95", surf_gate)
        self.assertNotIn("\n        X\n", surf_gate)
        self.assertNotIn("\n        DOWN\n", surf_gate)
        battle_gate = configured[
            configured.index("FUNC 孵蛋测试_等待池塘野生战斗") : configured.index(
                "FUNC 孵蛋测试_前往池塘并甜甜香气抓捕"
            )
        ]
        self.assertIn("$孵蛋库_池塘野生出现匹配 > 90", battle_gate)
        self.assertIn("$孵蛋库_池塘抓捕就绪匹配 > 95", battle_gate)
        self.assertNotIn("\n        A\n", battle_gate)
        self.assertIn("本轮安全重启", configured)
        sweet_scent_route = configured.split(
            "PRINT 【孵蛋Seed验证】冲浪结束，打开菜单并使用队首甜甜香气",
            1,
        )[1]
        self.assertLess(
            sweet_scent_route.index("\n    X\n"),
            sweet_scent_route.index("\n    DOWN\n"),
        )
        self.assertLess(
            configured.index("孵蛋测试_等待池塘冲浪结束()"),
            configured.index("\n    X\n", configured.index("孵蛋测试_等待池塘冲浪结束()")),
        )
        self.assertLess(
            configured.index("孵蛋测试_等待池塘野生战斗()"),
            configured.index("识别抓捕对象名称优先OCR"),
        )

    def test_transient_egg_action_failures_restart_and_continue(self):
        original = """\
    ELIF $孵蛋测试结果 != 1
        PRINT 孵蛋生成、领取或Seed复核野生抓捕失败
        CALL 孵蛋流程_重开下一轮
        RETURN 0
    ENDIF

    PRINT 领取后野生Seed反查失败
    CALL 孵蛋流程_重开下一轮
    RETURN 0

    IF $孵蛋流程孵化结果 != 1
        RETURN 0
    ENDIF
"""
        configured = _apply_egg_transient_retry_runtime_override_text(original)
        configured_again = _apply_egg_transient_retry_runtime_override_text(configured)

        self.assertEqual(configured_again, configured)
        self.assertIn(EGG_TRANSIENT_RETRY_OVERRIDE_MARKER, configured)
        self.assertIn("抓捕失败，关闭游戏并继续下一轮", configured)
        self.assertIn("反查失败，关闭游戏并重新预校准", configured)
        self.assertIn("孵化动作失败，关闭游戏并继续下一轮", configured)
        self.assertIn("$孵蛋流程Seed已预校准 = 0", configured)
        self.assertEqual(configured.count("RETURN 2"), 3)

    def test_pond_route_waits_after_the_final_down_input(self):
        configured = _apply_egg_pond_settle_delay_text(EGG_POND_SETTLE_ORIGINAL)

        self.assertEqual(configured, EGG_POND_SETTLE_FIXED)
        self.assertEqual(_apply_egg_pond_settle_delay_text(configured), configured)

    def test_egg_seed_correction_reuses_formal_lock_controller(self):
        original = """\
FUNC 孵蛋流程_按观测Seed校正等待($Seed差索引: INT): INT
    $孵蛋流程观测Seed差MS = 取MS($游戏版本, $目标索引 + $Seed差索引) - 取MS($游戏版本, $目标索引)
    $孵蛋Seed等待MS = $孵蛋Seed等待MS - $孵蛋流程观测Seed差MS
    RETURN 1
ENDFUNC

# -------------------- 蛋个体反查 --------------------
"""
        override = Path(EGG_SEED_CONTROLLER_OVERRIDE_PATH).read_text(
            encoding="utf-8"
        )
        configured = _apply_egg_seed_controller_runtime_override_text(
            original,
            override,
        )
        configured_again = _apply_egg_seed_controller_runtime_override_text(
            configured,
            override,
        )

        self.assertEqual(configured_again, configured)
        self.assertIn("计算Seed锁定众数修正()", configured)
        self.assertIn("$Seed精细修正MS", configured)
        self.assertIn("$Seed预校准索引_NS1", configured)
        self.assertIn("$Seed预校准索引_NS2", configured)
        self.assertIn("正式版锁定与相邻Seed毫秒细调", configured)
        self.assertNotIn("$孵蛋Seed等待MS = $孵蛋Seed等待MS -", configured)

    def test_hatch_waits_between_all_menu_exit_layers_before_walking(self):
        original = """\
FUNC 孵蛋测试_执行骑车孵化($全国图鉴编号: INT, $周期覆盖: INT, $每循环步数: INT, $安全循环数: INT): INT
    B
    WAIT 500
    B
    WAIT 500
    B
    WAIT 800
    UP 200
    RETURN 1
ENDFUNC

FUNC 孵蛋测试_使用神奇糖果指定槽($队伍位置: INT): INT
    RETURN 1
ENDFUNC
"""
        override = Path(EGG_HATCH_EXIT_OVERRIDE_PATH).read_text(encoding="utf-8")
        configured = _apply_egg_hatch_exit_runtime_override_text(original, override)
        configured_again = _apply_egg_hatch_exit_runtime_override_text(
            configured,
            override,
        )

        self.assertEqual(configured_again, configured)
        exit_section = configured[
            configured.index("PRINT 【孵化准备】正在逐层退出能力页与菜单") : configured.index(
                "PRINT 【孵化准备】开始位置校正与骑车"
            )
        ]
        self.assertIn("FOR $孵蛋库_孵化退出层 = 1 TO 5", exit_section)
        self.assertIn("WAIT 1500", exit_section)
        self.assertNotIn("WAIT 500", exit_section)
        self.assertLess(
            configured.index("孵化退出进度:"),
            configured.index("UP 200"),
        )
        self.assertIn("孵化骑车进度:", configured)
        self.assertIn("FUNC 孵蛋测试_执行周期骑车与孵化收尾", configured)
        shared_hatch = configured.split(
            "FUNC 孵蛋测试_执行周期骑车与孵化收尾", 1
        )[1].split("ENDFUNC", 1)[0]
        self.assertNotIn("@蛋孵化", shared_hatch)
        self.assertIn("WAIT 500\n    B\n    WAIT 12000\n    B\n    WAIT 1500\n    B\n    WAIT 1500", shared_hatch)
        wrapper = configured.split("FUNC 孵蛋测试_执行骑车孵化", 1)[1].split(
            "ENDFUNC", 1
        )[0]
        self.assertIn("RETURN 孵蛋测试_执行周期骑车与孵化收尾", wrapper)

    def test_static_togepi_uses_the_shared_fixed_cycle_hatch(self):
        original = """\
# 175: 波克比 / Togepi
FUNC 获取波克比($F2: INT, $目标全国图鉴编号: INT, $进入TV: INT): INT
    FOR
        LEFT DOWN
        IF @蛋孵化 > 95
            BREAK
        ENDIF
    NEXT
    RETURN 1
ENDFUNC

# 243: 雷公 / Raikou
FUNC 获取游走($F2: INT, $目标全国图鉴编号: INT, $进入TV: INT, $出闪后继续抓捕: INT, $识图阈值: INT): INT
    RETURN 1
ENDFUNC
"""
        override = Path(TOGEPI_HATCH_CYCLE_OVERRIDE_PATH).read_text(
            encoding="utf-8"
        )
        configured = _apply_togepi_hatch_cycle_override_text(original, override)
        configured_again = _apply_togepi_hatch_cycle_override_text(
            configured,
            override,
        )

        self.assertEqual(configured_again, configured)
        togepi = configured.split("FUNC 获取波克比", 1)[1].split("ENDFUNC", 1)[0]
        self.assertNotIn("@蛋孵化", togepi)
        self.assertNotIn("FOR\n        LEFT DOWN", togepi)
        self.assertIn(
            "RETURN 孵蛋测试_执行周期骑车与孵化收尾($目标全国图鉴编号, 0, 38, 1)",
            togepi,
        )

    def test_bundled_egg_flow_soft_resets_before_254_steps(self):
        root = Path(__file__).resolve().parents[1]
        template_path = root / "local_assets" / "easycon118" / "NS火叶全自动一键乱数1.1.8-TV时间轴测试.ecs"
        library_path = root / "local_assets" / "easycon118" / "lib" / "27_孵蛋测试流程.ecs"
        if not template_path.is_file() or not library_path.is_file():
            self.skipTest("requires the imported 1.1.8 egg runtime")
        template = template_path.read_text(encoding="utf-8")
        self.assertIn("$调试日志输出 = 1", template)
        self.assertIn(EGG_TRANSIENT_RETRY_OVERRIDE_MARKER, template)
        self.assertIn("抓捕失败，关闭游戏并继续下一轮", template)
        self.assertIn("RETURN 2", template)
        library = library_path.read_text(encoding="utf-8")
        self.assertIn("识别冲浪结束后再打开菜单", library)
        self.assertIn(EGG_POND_SETTLE_FIXED, library)
        self.assertIn("FUNC 孵蛋测试_软重启并跳过回忆", library)
        self.assertIn("FUNC 孵蛋测试_执行周期骑车与孵化收尾", library)
        self.assertNotIn(
            "@蛋孵化",
            library.split("FUNC 孵蛋测试_执行周期骑车与孵化收尾", 1)[1].split(
                "ENDFUNC", 1
            )[0],
        )
        static_library = (
            root / "local_assets" / "easycon118" / "lib" / "16_获取_静态目标.ecs"
        ).read_text(encoding="utf-8")
        togepi = static_library.split("FUNC 获取波克比", 1)[1].split(
            "ENDFUNC", 1
        )[0]
        self.assertNotIn("@蛋孵化", togepi)
        self.assertIn("孵蛋测试_执行周期骑车与孵化收尾", togepi)
        soft_reset = library.split(
            "FUNC 孵蛋测试_软重启并跳过回忆", 1
        )[1].split("ENDFUNC", 1)[0]
        library = _apply_egg_home_resample_fix_text(library)
        close_game = library.split(
            "FUNC 孵蛋测试_关闭游戏", 1
        )[1].split("ENDFUNC", 1)[0]
        self.assertIn("HOME 100", close_game)
        self.assertIn("@主页", close_game)
        self.assertIn("@正确退出", close_game)
        self.assertIn("@正在关闭", close_game)
        self.assertIn("孵蛋重启识图|主页=", close_game)
        self.assertIn("孵蛋重启识图失败", close_game)
        self.assertIn("已从游戏内请求主页，重新采样", close_game)
        self.assertIn("CONTINUE", close_game)
        self.assertLess(
            close_game.index("IF ($孵蛋库_正确退出匹配"),
            close_game.index("ELIF $孵蛋库_主页匹配"),
        )
        self.assertEqual(close_game.count("HOME 100"), 1)
        self.assertIn(
            "WAIT 1500\n    A\n    WAIT 1200\n    A\n    WAIT 8000",
            soft_reset,
        )
        self.assertIn(
            "A DOWN\n    WAIT 3000\n    A UP\n    WAIT 500\n    A DOWN\n    WAIT 1000\n    A UP\n    WAIT 500\n    B\n    WAIT 2500",
            soft_reset,
        )
        preparation = library.split(
            "FUNC 孵蛋测试_执行前置准备", 1
        )[1].split("ENDFUNC", 1)[0]
        self.assertLess(
            preparation.index("孵蛋测试_软重启并跳过回忆($识图阈值)"),
            preparation.index("CALL 孵蛋测试_跑到254步准备位"),
        )
        self.assertIn("孵蛋测试_软重启并跳过回忆($识图阈值)", preparation)
        self.assertIn("重启识图失败，停止前置流程", preparation)


if __name__ == "__main__":
    unittest.main()
