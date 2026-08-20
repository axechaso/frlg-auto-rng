import unittest
from pathlib import Path

from automation.easycon118 import (
    EGG_HOME_BUFFER_GLOBALS,
    EGG_HOME_BUFFER_OVERRIDE_PATH,
    EGG_PARTY_SLOT_CANDY_OVERRIDE_PATH,
    EGG_PARTY_SLOT_MAIN_OVERRIDE_PATH,
    EGG_RESTART_GLOBALS,
    EGG_RESTART_OVERRIDE_PATH,
    EGG_SETTINGS_GLOBALS,
    EGG_SETTINGS_OVERRIDE_PATH,
    WILD_PID_RETRY_LIMIT_MARKER,
    EggRunRequest,
    _apply_egg_home_resample_fix_text,
    _apply_egg_home_buffer_runtime_override_text,
    _apply_egg_party_slot_candy_runtime_override_text,
    _apply_egg_party_slot_main_runtime_override_text,
    _apply_egg_restart_runtime_override_text,
    _apply_egg_summary_fix_text,
    _apply_egg_settings_runtime_override_text,
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
    RETURN 1
ENDFUNC
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

    def test_bundled_egg_flow_soft_resets_before_254_steps(self):
        root = Path(__file__).resolve().parents[1]
        template_path = root / "local_assets" / "easycon118" / "NS火叶全自动一键乱数1.1.8-TV时间轴测试.ecs"
        library_path = root / "local_assets" / "easycon118" / "lib" / "27_孵蛋测试流程.ecs"
        if not template_path.is_file() or not library_path.is_file():
            self.skipTest("requires the imported 1.1.8 egg runtime")
        template = template_path.read_text(encoding="utf-8")
        self.assertIn("$调试日志输出 = 1", template)
        library = library_path.read_text(encoding="utf-8")
        self.assertIn("FUNC 孵蛋测试_软重启并跳过回忆", library)
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
