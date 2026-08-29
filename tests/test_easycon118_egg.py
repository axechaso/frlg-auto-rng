import re
import unittest
from pathlib import Path

from automation.easycon118 import (
    EGG_HOME_BUFFER_GLOBALS,
    EGG_HOME_BUFFER_OVERRIDE_PATH,
    HOME_BUFFER_ADAPTIVE_CLASSIFIER_PATH,
    HOME_BUFFER_ADAPTIVE_GLOBALS,
    STANDARD_HOME_BUFFER_OVERRIDE_PATH,
    EGG_HATCH_EXIT_OVERRIDE_PATH,
    EGG_FORMAL_PARITY_OVERRIDE_MARKER,
    EGG_FORMAL_PARITY_OVERRIDE_PATH,
    EGG_PARTY_SLOT_CANDY_OVERRIDE_PATH,
    EGG_PARTY_SLOT_MAIN_OVERRIDE_PATH,
    EGG_PICKUP_PARITY_MENU_MARKER,
    EGG_POST_PICKUP_RETRY_POLICY_MARKER,
    EGG_NO_EGG_EVIDENCE_OVERRIDE_MARKER,
    EGG_NO_EGG_SEED_GATE_CURRENT,
    EGG_NO_EGG_SEED_GATE_OLD,
    EGG_WILD_SEED_WINDOW_INIT,
    EGG_WILD_SEED_SCAN_CURRENT,
    EGG_WILD_SEED_SCAN_OLD,
    EGG_REVERSE_LOOKUP_LEGACY_POLICY_MARKER,
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
    EGG_TERMINAL_STOP_OVERRIDE_MARKER,
    PARTY_SUMMARY_NAVIGATION_PATH,
    SEED_HOLD_OBSERVATION_CURRENT_BRANCH,
    SEED_HOLD_OBSERVATION_CURRENT_DECISION,
    SEED_HOLD_OBSERVATION_MARKER,
    SEED_HOLD_OBSERVATION_MIN_GLOBAL,
    SEED_HOLD_OBSERVATION_OLD_BRANCH,
    SEED_HOLD_OBSERVATION_OLD_DECISION,
    TOGEPI_HATCH_CYCLE_OVERRIDE_PATH,
    WILD_PID_RETRY_LIMIT_MARKER,
    EggRunRequest,
    build_egg_held_availability,
    _apply_egg_home_resample_fix_text,
    _apply_egg_home_buffer_runtime_override_text,
    _apply_egg_hatch_exit_runtime_override_text,
    _apply_egg_formal_parity_runtime_override_text,
    _apply_egg_party_slot_candy_runtime_override_text,
    _apply_egg_party_slot_main_runtime_override_text,
    _apply_egg_pickup_parity_menu_text,
    _apply_egg_reverse_lookup_policy_text,
    _apply_egg_reverse_lookup_window_text,
    _apply_egg_pond_settle_delay_text,
    _apply_egg_prepared_254_runtime_override_text,
    _apply_egg_restart_runtime_override_text,
    _apply_egg_seed_controller_runtime_override_text,
    _apply_seed_hold_observation_window_text,
    _apply_seed_mode3_help_start_text,
    _apply_egg_summary_fix_text,
    _apply_egg_settings_runtime_override_text,
    _apply_egg_surf_battle_runtime_override_text,
    _apply_egg_transient_retry_runtime_override_text,
    _apply_egg_terminal_stop_policy_text,
    _apply_party_summary_navigation_text,
    _apply_egg_post_pickup_retry_policy_text,
    _apply_egg_no_egg_evidence_policy_text,
    _apply_egg_no_egg_seed_gate_text,
    _apply_egg_wild_seed_fallback_text,
    _apply_home_buffer_adaptive_classifier_text,
    _apply_standard_home_buffer_runtime_override_text,
    _apply_togepi_hatch_cycle_override_text,
    _apply_wild_pid_retry_limit_text,
    configure_egg_template_text,
    egg_held_availability_to_ecs_values,
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
    def test_seed_mode_three_help_start_acceptance_and_runtime_migration(self):
        for game in ("fr_nx", "fr_nx2", "lg_nx", "lg_nx2"):
            egg_request(game=game, seed_mode=3).validate()
        old = '''#   3 = stereo_r_a
    $孵蛋库_目标按键 = 0
    IF $Seed模式 == 3
        $孵蛋库_目标按键 = 1
    ENDIF
    IF $Seed模式 == 2 or $Seed模式 == 8 or $Seed模式 == 9
        X DOWN
    ELSE
        A DOWN
    ENDIF
'''
        new = _apply_seed_mode3_help_start_text(old)
        self.assertIn("#   3 = stereo_h_start", new)
        self.assertNotIn("$孵蛋库_目标按键 = 1", new)
        self.assertIn("$Seed模式 == 2 or $Seed模式 == 3 or $Seed模式 == 8 or $Seed模式 == 9", new)
        self.assertEqual(_apply_seed_mode3_help_start_text(new), new)

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
        self.assertIn(EGG_REVERSE_LOOKUP_LEGACY_POLICY_MARKER, configured)
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

    def test_cross_method_candidate_and_no_egg_point_jump_examples(self):
        candidates = [
            (1058, 3408),
            (1100, 3408),
            (1113, 3408),
            (1114, 3408),
            (1126, 3408),
            (1128, 3408),
        ]
        selected = min(
            candidates,
            key=lambda item: (
                -int(1128 <= item[0] <= 1132),
                abs(item[0] - 1127),
                abs(item[1] - 3405),
            ),
        )
        self.assertEqual(selected, (1128, 3408))

        different = [(16, 28, 25, 29, 12, 5), (8, 19, 25, 15, 12, 31)]
        same = [(16, 28, 25, 29, 12, 5), (16, 28, 25, 29, 12, 5)]
        self.assertNotEqual(len(set(different)), 1)
        self.assertEqual(len(set(same)), 1)

        def estimate(source, predicted, direction, target):
            value = min(max(predicted, source[0]), source[1])
            if value % 2 != target % 2:
                if direction > 0 and value + 1 <= source[1]:
                    value += 1
                elif direction < 0 and value - 1 >= source[0]:
                    value -= 1
                elif value - 1 >= source[0]:
                    value -= 1
                elif value + 1 <= source[1]:
                    value += 1
            return value

        def jump(source, estimated, destination, target):
            if destination[1] < source[0]:
                landing = destination[1]
                if landing % 2 != target % 2:
                    landing -= 1
                if landing < destination[0]:
                    return None
            else:
                landing = destination[0]
                if landing % 2 != target % 2:
                    landing += 1
                if landing > destination[1]:
                    return None
            return landing - estimated, landing

        source = (1116, 1120)
        estimated = estimate(source, 1115, 1, 1115)
        self.assertEqual(estimated, 1117)
        self.assertEqual(jump(source, estimated, (1113, 1115), 1115), (-2, 1115))
        self.assertEqual(jump(source, estimated, (1121, 1121), 1115), (4, 1121))
        self.assertEqual(jump(source, estimated, (1128, 1132), 1115), (12, 1129))
        self.assertIsNone(jump(source, estimated, (1124, 1124), 1115))

        choices = [
            (int(offset < 0), abs(offset), offset, landing)
            for offset, landing in (
                jump(source, estimated, (1113, 1115), 1115),
                jump(source, estimated, (1121, 1121), 1115),
            )
        ]
        _, _, offset, landing = min(choices)
        self.assertEqual(
            (offset, landing),
            (4, 1121),
            "向右修正时应优先选择右侧同奇偶出蛋帧",
        )

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
        self.assertEqual(values["道具乱数模式"], 0)
        self.assertEqual(values["队伍空位数量"], 1)
        self.assertEqual(values["目标Seed"], "75D1")
        self.assertEqual(values["目标消耗帧"], 8021)
        self.assertEqual(values["孵蛋领取目标帧"], 10021)
        self.assertEqual(values["孵蛋双亲A_HP"], 31)
        self.assertEqual(values["孵蛋双亲B_SPE"], 5)
        self.assertFalse(egg_request().to_dict()["start_from_prepared_254"])

    def test_held_availability_matches_ten_lines_vector(self):
        request = egg_request(
            target_seed="EDDE",
            held_advances=1115,
            pickup_advances=3405,
            compatibility=50,
        )
        availability = build_egg_held_availability(
            request,
            before=7,
            after=17,
        )
        self.assertTrue(availability["targetProducesEgg"])
        self.assertEqual(
            availability["noEggIntervals"],
            [
                (1108, 1109),
                (1111, 1112),
                (1116, 1120),
                (1122, 1123),
                (1125, 1125),
                (1127, 1127),
            ],
        )
        values = egg_held_availability_to_ecs_values(availability)
        self.assertEqual(values["孵蛋Held无蛋表Seed"], "EDDE")
        self.assertEqual(values["孵蛋Held无蛋区间起点表"][2], 1116)
        self.assertEqual(values["孵蛋Held无蛋区间终点表"][2], 1120)

    def test_old_cached_template_reports_how_to_refresh_held_table_fields(self):
        old_template = "\n".join(
            f"${name} = 0" for name in egg_request_to_user_values(egg_request())
        ) + "\n# ============================进阶设置\n"
        with self.assertRaisesRegex(ValueError, "local_assets仍为旧缓存"):
            configure_egg_template_text(
                old_template,
                egg_request(),
            )

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
            "道具乱数模式", "队伍空位数量",
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
        for name in (
            "孵蛋Held无蛋表Seed", "孵蛋Held无蛋表目标帧", "孵蛋Held无蛋表相性",
            "孵蛋Held无蛋表Offset", "孵蛋Held无蛋表最小帧", "孵蛋Held无蛋表最大帧",
            "孵蛋Held无蛋区间起点表", "孵蛋Held无蛋区间终点表",
        ):
            template += f"\n${name} = 0"
        configured = configure_egg_template_text(template, egg_request())
        self.assertIn('$静态或野生 = "孵蛋"', configured)
        self.assertIn("$道具乱数模式 = 0", configured)
        self.assertIn("$队伍空位数量 = 1", configured)
        self.assertIn('$目标Seed = "75D1"', configured)
        self.assertIn('$孵蛋双亲A_DEF = 29', configured)
        self.assertIn('$孵蛋双亲B_SPA = 3', configured)
        self.assertIn('$孵蛋Held无蛋表Seed = "75D1"', configured)
        self.assertIn('$孵蛋Held无蛋表目标帧 = 8021', configured)
        self.assertIn('$孵蛋Held无蛋表相性 = 70', configured)
        self.assertRegex(configured, r"\$孵蛋Held无蛋区间起点表 = \[\d")
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

    def test_egg_home_buffer_retries_selected_nx_without_unknown_brackets(self):
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
        self.assertIn(
            "$HOME_BUFFER识别状态 = HOME_BUFFER重采样状态(1)",
            configured,
        )
        self.assertNotIn(
            "IF @HOME_BUFFER正确退出 >= 95 or @HOME_BUFFER正确退出_NS2 >= 95",
            configured,
        )
        self.assertNotIn("$孵蛋HOME_BUFFER短边界 = $HOME_BUFFER延迟", configured)
        self.assertNotIn("没有达到当前识图阈值的整数延迟", configured)
        self.assertIn("$HOME_BUFFER恢复结果 = HOME_BUFFER恢复启动原点()", configured)
        self.assertIn("$HOME_BUFFER最小调整MS", configured)
        self.assertIn("$HOME_BUFFER锁定失败阈值", configured)
        self.assertIn("$HOME_BUFFER延迟 = $HOME_BUFFER锁定延迟", configured)
        self.assertIn(
            "$HOME_BUFFER锁定连续失败 < $HOME_BUFFER锁定失败阈值",
            configured,
        )
        self.assertIn("连续3次明确识别普通退出，解除锁定并重新校准", configured)
        self.assertIn("RETURN $HOME_BUFFER延迟 - $HOME_BUFFER最小调整MS", configured)
        self.assertNotIn("$HOME_BUFFER延迟 - 100", configured)
        self.assertNotIn("$HOME_BUFFER延迟 + 100", configured)
        self.assertIn("$孵蛋HOME_BUFFER尝试 > 20", configured)
        self.assertEqual(
            configured.count("孵蛋流程停止：HOME_BUFFER未找到当前主机的可用延迟"),
            2,
        )
        self.assertIn(
            "CALL 孵蛋流程_重开下一轮\n    IF $孵蛋HOME_BUFFER失败 == 1",
            configured,
        )

    def test_home_buffer_adaptive_classifier_is_shared_and_opt_in(self):
        original = """\
$HOME_BUFFER当前错误退出_NS2 = 0
FUNC HOME_BUFFER
    RETURN
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
        classifier = Path(HOME_BUFFER_ADAPTIVE_CLASSIFIER_PATH).read_text(
            encoding="utf-8"
        )
        standard = _apply_standard_home_buffer_runtime_override_text(
            original,
            Path(STANDARD_HOME_BUFFER_OVERRIDE_PATH).read_text(encoding="utf-8"),
        )
        standard = _apply_home_buffer_adaptive_classifier_text(
            standard,
            classifier,
            True,
        )
        standard_again = _apply_home_buffer_adaptive_classifier_text(
            standard,
            classifier,
            True,
        )

        egg = _apply_egg_home_buffer_runtime_override_text(
            original,
            Path(EGG_HOME_BUFFER_OVERRIDE_PATH).read_text(encoding="utf-8"),
        )
        egg = _apply_home_buffer_adaptive_classifier_text(
            egg,
            classifier,
            False,
        )

        self.assertEqual(standard_again, standard)
        self.assertIn(HOME_BUFFER_ADAPTIVE_GLOBALS.replace(" = 0\n", " = 1\n", 1), standard)
        self.assertIn("$HOME_BUFFER稳定低分自适应 = 0", egg)
        self.assertEqual(standard.count(classifier.rstrip()), 1)
        self.assertEqual(egg.count(classifier.rstrip()), 1)
        self.assertIn("FOR $HOME_BUFFER自适应采样 = 1 TO $HOME_BUFFER自适应稳定要求", standard)
        self.assertIn("$HOME_BUFFER自适应稳定要求 = 3", standard)
        self.assertIn("$HOME_BUFFER自适应最低阈值 = 90", standard)
        for configured in (standard, egg):
            self.assertIn("$HOME_BUFFER最小调整MS = 50", configured)
            self.assertIn("$HOME_BUFFER锁定失败阈值 = 3", configured)
            self.assertIn("$HOME_BUFFER锁定延迟 = $HOME_BUFFER延迟", configured)
            self.assertIn(
                "$HOME_BUFFER锁定连续失败 < $HOME_BUFFER锁定失败阈值",
                configured,
            )

        legacy_standard = standard
        for line in (
            "$HOME_BUFFER最小调整MS = 50",
            "$HOME_BUFFER锁定失败阈值 = 3",
            "$HOME_BUFFER锁定启用 = 0",
            "$HOME_BUFFER锁定延迟 = 0",
            "$HOME_BUFFER锁定连续失败 = 0",
            "$HOME_BUFFER尝试 = 0",
        ):
            legacy_standard = legacy_standard.replace(line + "\n", "", 1)
        upgraded_standard = _apply_home_buffer_adaptive_classifier_text(
            legacy_standard,
            classifier,
            True,
        )
        for line in (
            "$HOME_BUFFER最小调整MS = 50",
            "$HOME_BUFFER锁定失败阈值 = 3",
            "$HOME_BUFFER锁定启用 = 0",
            "$HOME_BUFFER锁定延迟 = 0",
            "$HOME_BUFFER锁定连续失败 = 0",
            "$HOME_BUFFER尝试 = 0",
        ):
            self.assertEqual(
                len(re.findall(rf"(?m)^{re.escape(line)}\r?$", upgraded_standard)),
                1,
            )

        legacy_egg = egg.replace("$孵蛋HOME_BUFFER调整差 = 0\n", "", 1)
        upgraded_egg = _apply_egg_home_buffer_runtime_override_text(
            legacy_egg,
            Path(EGG_HOME_BUFFER_OVERRIDE_PATH).read_text(encoding="utf-8"),
        )
        self.assertEqual(
            len(
                re.findall(
                    r"(?m)^\$孵蛋HOME_BUFFER调整差 = 0\r?$",
                    upgraded_egg,
                )
            ),
            1,
        )
        self.assertIn(
            "$HOME_BUFFER选中正确 >= $HOME_BUFFER有效识图阈值",
            standard,
        )
        self.assertIn(
            "$HOME_BUFFER选中正确 > $HOME_BUFFER选中普通 and $HOME_BUFFER选中正确 > $HOME_BUFFER选中错误",
            standard,
        )

    def test_home_buffer_adaptive_request_flag_must_be_boolean(self):
        with self.assertRaisesRegex(ValueError, "HOME_BUFFER"):
            egg_request(home_buffer_adaptive_threshold=1).validate()

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
        self.assertIn("反查失败，关闭游戏并直接重试生成领取", configured)
        self.assertIn("孵化动作失败，关闭游戏并继续下一轮", configured)
        self.assertIn("$孵蛋流程Seed已预校准 = 1", configured)
        self.assertEqual(configured.count("RETURN 2"), 3)

    def test_post_pickup_seed_retry_keeps_completed_precalibration(self):
        original = """\
    ELIF $孵蛋流程Seed验证结果 == 2
        PRINT 领取后未命中目标Seed，本轮丢弃并重新预校准
        $孵蛋流程Seed已预校准 = 0
        $孵蛋流程Seed校正结果 = 孵蛋流程_按观测Seed校正等待($候选同一Seed值)
        IF $孵蛋流程Seed校正结果 != 1
            CALL 孵蛋流程_重开下一轮
            RETURN 0
        ENDIF
        CALL 孵蛋流程_重开下一轮
        RETURN 2
    ENDIF
    PRINT 领取后野生Seed反查失败，关闭游戏并重新预校准
    $孵蛋流程Seed已预校准 = 0
    CALL 孵蛋流程_重开下一轮
    RETURN 2
"""
        configured = _apply_egg_post_pickup_retry_policy_text(original)
        configured_again = _apply_egg_post_pickup_retry_policy_text(configured)

        self.assertEqual(configured_again, configured)
        self.assertIn(EGG_POST_PICKUP_RETRY_POLICY_MARKER, configured)
        self.assertIn("首次不领蛋预校准已经完成", configured)
        self.assertIn("直接重试生成领取", configured)
        self.assertEqual(configured.count("$孵蛋流程Seed已预校准 = 1"), 2)
        self.assertNotIn("重新预校准", configured)

    def test_no_egg_evidence_survives_non_target_seed_for_same_held_request(self):
        original = """\
    IF $孵蛋流程上次无蛋请求Held帧 != $孵蛋流程请求Held帧
        $孵蛋流程无蛋连续次数 = 0
        $孵蛋流程上次无蛋请求Held帧 = $孵蛋流程请求Held帧
    ENDIF
        ELIF $孵蛋流程Seed验证结果 == 2
            PRINT 无蛋后未命中目标Seed：本轮只校正Seed等待，不累计Held无蛋区间证据
            $孵蛋流程目标Seed无蛋次数 = 0
            $孵蛋流程目标Seed无蛋区间索引 = -1
            $孵蛋流程目标Seed无蛋区间确认次数 = 0
            $孵蛋流程无蛋连续次数 = 0
"""
        configured = _apply_egg_no_egg_evidence_policy_text(original)
        configured_again = _apply_egg_no_egg_evidence_policy_text(configured)

        self.assertEqual(configured_again, configured)
        self.assertIn(EGG_NO_EGG_EVIDENCE_OVERRIDE_MARKER, configured)
        request_change, non_target = configured.split(
            "ELIF $孵蛋流程Seed验证结果 == 2",
            1,
        )
        self.assertIn("$孵蛋流程目标Seed无蛋区间确认次数 = 0", request_change)
        self.assertNotIn("$孵蛋流程目标Seed无蛋区间确认次数 = 0", non_target)
        self.assertIn("保留同一Held请求已有无蛋区间证据", non_target)

    def test_no_egg_seed_gate_after_held_is_idempotent_and_preserves_other_policy(self):
        prefix = (
            "$孵蛋Held固定预校准帧 = 230\n"
            "$孵蛋流程上次确认实际Held帧 = -1\n"
            "$孵蛋普通无蛋复核阈值 = 3\n"
            "$Seed命中保持样本数 = 10\n"
        )
        suffix = (
            "$孵蛋流程目标Seed无蛋区间确认次数 = 0\n"
            "$孵蛋Held执行修正帧 = 0\n"
        )
        original = prefix + EGG_NO_EGG_SEED_GATE_OLD + suffix
        configured = _apply_egg_no_egg_seed_gate_text(original)
        self.assertEqual(configured, prefix + EGG_NO_EGG_SEED_GATE_CURRENT + suffix)
        self.assertEqual(_apply_egg_no_egg_seed_gate_text(configured), configured)

    def test_no_egg_seed_gate_checks_first_miss_after_held_even_without_stable_pickup(self):
        configured = _apply_egg_no_egg_seed_gate_text(EGG_NO_EGG_SEED_GATE_OLD)
        conditions = re.findall(r"^\s*(?:IF|ELIF) (.+)$", configured, re.M)
        self.assertEqual(len(conditions), 2)
        for held, stable, misses, expected in (
            (-1, 0, 0, False),  # Fixed precalibration is not a Held observation.
            (-1, 0, 1, False),
            (-1, 0, 2, True),   # Original third-consecutive-miss threshold.
            (1114, 0, 0, True), # Pickup not yet stable / has drifted again.
            (1115, 0, 0, True), # Even if the dynamic Held correction is zero.
            (0, 0, 0, True),
            (-1, 1, 0, True),   # Preserve the prior Pickup-stable behavior.
        ):
            with self.subTest(held=held, stable=stable, misses=misses):
                values = {
                    "$孵蛋流程上次确认实际Held帧": held,
                    "$孵蛋流程Pickup已稳定": stable,
                    "$孵蛋流程无蛋连续次数": misses,
                    "$孵蛋普通无蛋复核阈值": 3,
                }
                # Evaluate the actual patched ECS IF/ELIF expressions, not a second rule.
                observed = any(
                    eval(
                        re.sub(r"\$\w+", lambda m: str(values[m.group()]), expression),
                        {"__builtins__": {}},
                        {},
                    )
                    for expression in conditions
                )
                self.assertEqual(observed, expected)

    def test_no_egg_seed_gate_rejects_missing_or_ambiguous_branches(self):
        for source in (
            "", EGG_NO_EGG_SEED_GATE_OLD * 2, EGG_NO_EGG_SEED_GATE_CURRENT * 2,
            EGG_NO_EGG_SEED_GATE_OLD + EGG_NO_EGG_SEED_GATE_CURRENT,
        ):
            with self.subTest(source=source), self.assertRaisesRegex(ValueError, "唯一"):
                _apply_egg_no_egg_seed_gate_text(source)

    def test_egg_wild_seed_fallback_is_scoped_idempotent_and_keeps_lower_bound(self):
        prefix = "$孵蛋野生最小消耗帧 = 500\n$孵蛋Held反查帧容差 = 100\n"
        old_function = (
            "FUNC 孵蛋流程_验证野生Seed($队伍位置: INT): INT\n"
            "    FOR\n" + EGG_WILD_SEED_SCAN_OLD
            + "        IF $候选全部同一Seed == 1\n            RETURN 1\n        ENDIF\n"
            "        CALL 打开能力值识图页面\n    NEXT\n    RETURN 0\nENDFUNC\n"
        )
        # Identical scan text elsewhere must not be changed by the egg-only overlay.
        suffix = "FUNC 普通野生测试\n" + EGG_WILD_SEED_SCAN_OLD + "ENDFUNC\n"
        expected = old_function.replace(
            EGG_WILD_SEED_SCAN_OLD, EGG_WILD_SEED_SCAN_CURRENT
        ).replace("    FOR\n", EGG_WILD_SEED_WINDOW_INIT + "    FOR\n")
        configured = _apply_egg_wild_seed_fallback_text(prefix + old_function + suffix)
        self.assertEqual(configured, prefix + expected + suffix)
        self.assertEqual(_apply_egg_wild_seed_fallback_text(configured), configured)
        self.assertEqual(
            re.findall(r"^\s*\$有效最小消耗帧 = (.+)$", expected, re.M),
            ["$孵蛋野生最小消耗帧"],
        )
        self.assertIn("$有效Seed容差 = $孵蛋野生Seed容差 + 5", expected)
        self.assertIn("$有效最大消耗帧 = $孵蛋野生最大消耗帧 + 1000", expected)
        self.assertIn(
            "IF $孵蛋流程扫描结果 != 1 and $有效Seed容差 == $孵蛋野生Seed容差",
            expected,
        )
        self.assertEqual(expected.count("$孵蛋流程扫描结果 = 执行反查扫描()"), 2)

    def test_egg_wild_seed_fallback_rejects_unknown_or_repeated_scan(self):
        signature = "FUNC 孵蛋流程_验证野生Seed($队伍位置: INT): INT\n"
        for text in (
            "", signature + "ENDFUNC", signature * 2 + "ENDFUNC",
            signature + "    FOR\n" + EGG_WILD_SEED_SCAN_OLD * 2 + "    NEXT\nENDFUNC",
        ):
            with self.subTest(text=text), self.assertRaises(ValueError):
                _apply_egg_wild_seed_fallback_text(text)

    def test_terminal_egg_lookup_failure_keeps_the_current_game_screen(self):
        original = """\
FUNC 孵蛋流程_执行孵化与个体反查(): INT
    IF $孵蛋流程蛋反查结果 == 3
        CALL 孵蛋流程_重开下一轮
        RETURN 2
    ELIF $孵蛋流程蛋反查结果 == 2
        PRINT 蛋个体在自动扩窗后仍无结果，停止以检查亲本或目标数据
        CALL 孵蛋流程_重开下一轮
        RETURN 0
    ELIF $孵蛋流程蛋反查结果 != 1
        PRINT 蛋个体反查失败，请检查双亲、相性、目标帧或识图配置
        CALL 孵蛋流程_重开下一轮
        RETURN 0
    ENDIF
    RETURN 1
ENDFUNC
"""
        configured = _apply_egg_terminal_stop_policy_text(original)
        configured_again = _apply_egg_terminal_stop_policy_text(configured)

        self.assertEqual(configured_again, configured)
        self.assertIn(EGG_TERMINAL_STOP_OVERRIDE_MARKER, configured)
        self.assertEqual(configured.count("停止前保留当前游戏画面"), 2)
        self.assertEqual(configured.count("CALL 孵蛋流程_重开下一轮"), 1)
        retry_branch = configured.split("IF $孵蛋流程蛋反查结果 == 3", 1)[1].split(
            "ELIF $孵蛋流程蛋反查结果 == 2",
            1,
        )[0]
        self.assertIn("CALL 孵蛋流程_重开下一轮", retry_branch)

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
        self.assertIn("$Seed精细固定半步MS", configured)
        self.assertIn("$Seed命中保持样本数", configured)
        self.assertIn("$Seed命中保持计数", configured)
        self.assertIn("$Seed预校准索引_NS1", configured)
        self.assertIn("$Seed预校准索引_NS2", configured)
        self.assertIn("正式版±1五次多数、固定半步与命中后10次可信反查观察窗", configured)
        self.assertNotIn("$孵蛋Seed等待MS = $孵蛋Seed等待MS -", configured)

    def test_seed_hold_uses_ten_observations_but_only_plus_minus_one_votes(self):
        original = (
            "$Seed命中保持样本数 = 10\n"
            "FUNC 计算Seed锁定众数修正(): INT\n"
            + SEED_HOLD_OBSERVATION_OLD_BRANCH
            + SEED_HOLD_OBSERVATION_OLD_DECISION
            + "        IF $Seed命中保持正方向票数 > $Seed命中保持负方向票数\n"
            + "            RETURN 1\n"
            + "        ENDIF\n"
            + "    ENDIF\n"
            + "    RETURN 0\n"
            + "ENDFUNC\n"
        )
        configured = _apply_seed_hold_observation_window_text(original)
        configured_again = _apply_seed_hold_observation_window_text(configured)

        self.assertEqual(configured_again, configured)
        self.assertIn(SEED_HOLD_OBSERVATION_MARKER, configured)
        self.assertIn(SEED_HOLD_OBSERVATION_MIN_GLOBAL, configured)
        self.assertIn(SEED_HOLD_OBSERVATION_CURRENT_BRANCH, configured)
        self.assertIn(SEED_HOLD_OBSERVATION_CURRENT_DECISION, configured)
        self.assertNotIn(SEED_HOLD_OBSERVATION_OLD_BRANCH, configured)
        self.assertNotIn(SEED_HOLD_OBSERVATION_OLD_DECISION, configured)
        hold_branch = configured.split("ELIF $Seed命中保持启用 == 1", 1)[1]
        self.assertLess(
            hold_branch.index("$Seed命中保持计数 = $Seed命中保持计数 + 1"),
            hold_branch.index("IF $Seed差绝对 == 1"),
        )
        self.assertIn("本轮大波动不投方向票", configured)
        self.assertIn("±1方向样本不足3", configured)

    def test_egg_timeline_uses_formal_held_parity_and_pickup_menu_phase(self):
        original = """\
$孵蛋流程请求Held帧 = 0
FUNC 孵蛋流程_计算两次命中时间(): INT
    RETURN 0
ENDFUNC

FUNC 孵蛋流程_执行Seed预校准轮(): INT
    RETURN 1
ENDFUNC

$孵蛋测试结果 = 孵蛋测试_执行同Seed两次命中($Seed模式, $孵蛋Seed等待MS, $时间轴精确尾段MS, $孵蛋奇偶等待MS, $孵蛋封面长按MS, $孵蛋流程TV过帧开关, $孵蛋流程TV等待MS, $孵蛋流程生成目标截止MS, $孵蛋流程领取目标截止MS, $孵蛋出蛋检测阈值, $识图阈值, 1, $孵蛋流程无蛋复核Seed开关)
"""
        override = Path(EGG_FORMAL_PARITY_OVERRIDE_PATH).read_text(
            encoding="utf-8"
        )
        configured = _apply_egg_formal_parity_runtime_override_text(
            original,
            override,
        )
        configured_again = _apply_egg_formal_parity_runtime_override_text(
            configured,
            override,
        )

        self.assertEqual(configured_again, configured)
        self.assertIn(EGG_FORMAL_PARITY_OVERRIDE_MARKER, configured)
        self.assertIn(
            "$孵蛋流程奇偶F1修正帧 = 奇偶修正后F1帧(0, $孵蛋流程请求Held帧)",
            configured,
        )
        self.assertIn(
            "$孵蛋流程执行Held帧 = 奇偶修正后F2帧($孵蛋流程请求Held帧)",
            configured,
        )
        self.assertIn(
            "$孵蛋流程Pickup奇偶基准帧 = $孵蛋流程请求Pickup帧 - $孵蛋流程奇偶F2扣除帧",
            configured,
        )
        self.assertIn(
            "$孵蛋流程执行Pickup帧 = $孵蛋流程Pickup奇偶基准帧 - $孵蛋流程Pickup菜单推进帧",
            configured,
        )
        self.assertEqual(
            configured.count("$孵蛋流程奇偶F2扣除帧 = $孵蛋流程请求Held帧 - $孵蛋流程执行Held帧"),
            1,
        )
        self.assertIn("$孵蛋流程本轮奇偶等待MS, $孵蛋封面长按MS", configured)
        self.assertIn(
            "$孵蛋流程Pickup菜单奇偶开关, $孵蛋出蛋检测阈值",
            configured,
        )
        self.assertNotIn("$孵蛋奇偶等待MS, $孵蛋封面长按MS", configured)

    def test_pickup_parity_menu_is_after_confirmed_egg_and_idempotent(self):
        original = """\
FUNC 孵蛋测试_执行同Seed两次命中($Seed模式: INT, $Seed等待MS: INT, $精确尾段MS: INT, $奇偶等待MS: INT, $封面长按MS: INT, $TV开关: INT, $TV等待MS: INT, $出蛋目标MS: INT, $领蛋目标MS: INT, $出蛋识图阈值: INT, $抓捕识图阈值: INT, $出闪后继续抓捕: INT, $无蛋后复核Seed: INT): INT
    IF $无蛋后复核Seed != 0 and $无蛋后复核Seed != 1
        PRINT 孵蛋无蛋后Seed复核开关无效: & $无蛋后复核Seed
        RETURN 0
    ENDIF
    $孵蛋库_启动结果 = 孵蛋测试_启动并进入存档($Seed模式, $Seed等待MS, $精确尾段MS, $奇偶等待MS, $封面长按MS)
    IF $孵蛋库_出蛋检测结果 != 1
        RETURN 2
    ENDIF
    LS RIGHT
    RETURN 1
ENDFUNC

FUNC 孵蛋测试_执行前置准备($Seed模式: INT, $识图阈值: INT): INT
    RETURN 1
ENDFUNC
"""
        configured = _apply_egg_pickup_parity_menu_text(original)
        configured_again = _apply_egg_pickup_parity_menu_text(configured)

        self.assertEqual(configured_again, configured)
        self.assertIn(EGG_PICKUP_PARITY_MENU_MARKER, configured)
        self.assertIn("$Pickup菜单奇偶开关: INT", configured)
        self.assertIn("孵蛋Pickup菜单奇偶开关无效", configured)
        action = configured.split(EGG_PICKUP_PARITY_MENU_MARKER, 1)[1].split(
            "LS RIGHT",
            1,
        )[0]
        self.assertIn("IF $Pickup菜单奇偶开关 == 1", action)
        self.assertIn("X\n        WAIT 500\n        B\n        WAIT 500", action)
        self.assertLess(
            configured.index("RETURN 2"),
            configured.index(EGG_PICKUP_PARITY_MENU_MARKER),
        )

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
        self.assertIn(EGG_TERMINAL_STOP_OVERRIDE_MARKER, template)
        self.assertIn(EGG_FORMAL_PARITY_OVERRIDE_MARKER, template)
        self.assertIn("抓捕失败，关闭游戏并继续下一轮", template)
        self.assertIn("RETURN 2", template)
        self.assertIn("$候选细分累计范围有效 = 0", template)
        self.assertIn("$孵蛋流程IV范围合并结果 = 合并候选细分IV范围()", template)
        self.assertIn("$孵蛋Held固定预校准帧 = 230", template)
        self.assertIn("$孵蛋Pickup固定预校准帧 = 230", template)
        self.assertIn("$孵蛋Held反查帧容差 = 100", template)
        self.assertIn("$孵蛋Pickup反查帧容差 = 2000", template)
        self.assertIn(
            "Pickup尚未稳定：仍登记本轮Held无蛋区间证据，仅使用临时跳区，不修改正式Held修正",
            template,
        )
        self.assertIn(
            "无蛋后未命中目标Seed：本轮只校正Seed等待；保留同一Held请求已有无蛋区间证据",
            template,
        )
        request_change = template.split(
            "IF $孵蛋流程上次无蛋请求Held帧 != $孵蛋流程请求Held帧",
            1,
        )[1].split("ENDIF", 1)[0]
        for reset in (
            "$孵蛋流程目标Seed无蛋次数 = 0",
            "$孵蛋流程目标Seed无蛋区间索引 = -1",
            "$孵蛋流程目标Seed无蛋区间确认次数 = 0",
        ):
            self.assertIn(reset, request_change)
        non_target_no_egg = template.split(
            "PRINT 无蛋后未命中目标Seed：本轮只校正Seed等待；保留同一Held请求已有无蛋区间证据",
            1,
        )[1].split("CALL 孵蛋流程_重开下一轮", 1)[0]
        for forbidden_reset in (
            "$孵蛋流程目标Seed无蛋次数 = 0",
            "$孵蛋流程目标Seed无蛋区间索引 = -1",
            "$孵蛋流程目标Seed无蛋区间确认次数 = 0",
        ):
            self.assertNotIn(forbidden_reset, non_target_no_egg)
        self.assertIn("连续命中目标Seed且无蛋超过处理上限，停止以避免死循环", template)
        self.assertIn("FUNC 孵蛋流程_候选个体是否完全一致(): INT", template)
        self.assertIn("FUNC 孵蛋流程_合并当前方法候选($方法: INT): INT", template)
        self.assertIn("FUNC 孵蛋流程_选择校准候选(): INT", template)
        self.assertIn(EGG_REVERSE_LOOKUP_POLICY_MARKER, template)
        self.assertIn(
            "$孵蛋流程跨方法候选总数 += $孵蛋流程合并方法总数",
            template,
        )
        self.assertIn(
            "$孵蛋流程实际方法 = $孵蛋流程最佳候选方法",
            template,
        )
        method_scan = template.split(EGG_REVERSE_LOOKUP_POLICY_MARKER, 1)[1]
        method_scan = method_scan.split("            NEXT", 1)[0]
        self.assertNotIn("BREAK", method_scan)
        self.assertIn(
            "$孵蛋流程候选参考Held帧 = $孵蛋流程上次确认实际Held帧 + $孵蛋流程本轮Held总执行修正帧 - $孵蛋流程上次确认Held总执行修正帧",
            template,
        )
        self.assertIn("$孵蛋流程无蛋跳出估计落点", template)
        self.assertIn("$孵蛋流程无蛋跳出最佳预测落点", template)
        self.assertIn(
            "$孵蛋流程无蛋跳出候选预测落点 % 2 != $孵蛋生成目标帧 % 2",
            template,
        )
        self.assertIn(
            "$孵蛋流程无蛋跳出候选偏移 = $孵蛋流程无蛋跳出候选预测落点 - $孵蛋流程无蛋跳出估计落点",
            template,
        )
        self.assertIn(
            "$孵蛋流程无蛋预测Held帧 = $孵蛋流程无蛋跳出最佳预测落点",
            template,
        )
        self.assertIn(
            "$孵蛋流程候选参考Held帧 = $孵蛋流程无蛋跳出最佳预测落点",
            template,
        )
        self.assertNotIn("$孵蛋流程无蛋跳出包络宽度", template)
        self.assertIn("已在孵化蛋能力页识别到闪光，目标命中并结束反查", template)
        self.assertIn(
            "$孵蛋流程请求Held帧 = $孵蛋生成目标帧 - $孵蛋Held固定预校准帧 + $孵蛋Held执行修正帧",
            template,
        )
        self.assertIn(
            "$孵蛋流程请求Pickup帧 = $孵蛋领取目标帧 - $孵蛋Pickup固定预校准帧 + $孵蛋Pickup执行修正帧",
            template,
        )
        self.assertIn(
            "$孵蛋流程执行Pickup帧 = $孵蛋流程Pickup奇偶基准帧 - $孵蛋流程Pickup菜单推进帧",
            template,
        )
        self.assertIn("孵蛋正式版奇偶校准: F1增加", template)
        self.assertIn("$孵蛋流程本轮奇偶等待MS, $孵蛋封面长按MS", template)
        self.assertIn(
            "$孵蛋流程Pickup菜单奇偶开关, $孵蛋出蛋检测阈值",
            template,
        )
        library = library_path.read_text(encoding="utf-8")
        self.assertIn(EGG_PICKUP_PARITY_MENU_MARKER, library)
        self.assertIn("出培育屋后开关一次菜单，物理增加7 advance", library)
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
