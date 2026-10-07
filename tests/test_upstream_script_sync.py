import re
import hashlib
import tempfile
import unittest
from pathlib import Path

from automation import easycon118 as ecs


ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "local_assets/easycon118"


def unified_fixture():
    return "\n".join((
        "FUNC 计算Seed所选方案修正($原始样本已写入: INT): INT\n"
        "    IF $Seed校准方案 == 0\n"
        "        RETURN 计算Seed原始众数修正()\n    ENDIF\n"
        "    RETURN 计算Seed统一校准修正()\nENDFUNC",
        *[signature + "\n    RETURN 0\nENDFUNC" for signature in (
            "FUNC 重置Seed统一校准状态",
            "FUNC 计算Seed统一粗调修正(): INT",
            "FUNC 更新Seed统一校准阶段(): INT",
            "FUNC 计算Seed统一校准修正(): INT",
        )],
        "FUNC 计算Seed锁定众数修正(): INT\n"
        "    IF $Seed命中保持启用 == 1\n        RETURN 0\n"
        "    ELIF $Seed校准方案 != 0 and $方案2Seed接续启用 == 1\n"
        "        RETURN 0\n    ENDIF\n    RETURN 0\nENDFUNC",
        "FUNC 孵蛋流程_按观测Seed校正等待($Seed差索引: INT): INT\n"
        "    $Seed本次修正索引 = 计算Seed所选方案修正(0)\n"
        "    RETURN 1\nENDFUNC",
    ))


class UpstreamOverlayTests(unittest.TestCase):
    def test_manual_egg_seed_bounds_only_remove_audited_dynamic_defaults(self):
        dynamic = "\n".join(ecs.EGG_DYNAMIC_SEED_WINDOW_ASSIGNMENTS)
        original = ("$孵蛋野生最小消耗帧 = 0\n$孵蛋野生最大消耗帧 = 0\n"
                    "FUNC 孵蛋流程_解析并校验配置(): INT\n" + dynamic
                    + "\n    RETURN 1\nENDFUNC\n")
        configured = ecs._apply_egg_explicit_seed_window_text(original)
        self.assertIn("GUI_EGG_SEED_WINDOW_OVERRIDE", configured)
        self.assertNotIn(dynamic, configured)
        self.assertIn("$孵蛋野生最小消耗帧 = 0", configured)
        self.assertEqual(ecs._apply_egg_explicit_seed_window_text(configured), configured)
        with self.assertRaisesRegex(ValueError, "不完整"):
            ecs._apply_egg_explicit_seed_window_text(original.replace(
                ecs.EGG_DYNAMIC_SEED_WINDOW_ASSIGNMENTS[1], ""))
        with self.assertRaisesRegex(ValueError, "配置入口"):
            ecs._apply_egg_explicit_seed_window_text(original.replace(dynamic, "") + dynamic)

    def test_seed_backups_do_not_change_active_corpus_but_extra_library_does(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary)
            for name in ecs.EXPECTED_TEMPLATE_NAMES:
                (source / name).write_text("RETURN\n", encoding="utf-8")
            library = source / "lib"
            library.mkdir()
            (library / "table.ecs").write_text("$seed = 1\n", encoding="utf-8")
            expected = ecs.inspect_script_corpus(source)
            backup = library / "seed_backup/20260912"
            backup.mkdir(parents=True)
            (backup / "table.ecs").write_text("$seed = 2\n", encoding="utf-8")
            self.assertEqual(ecs.inspect_script_corpus(source), expected)
            (library / "unexpected.ecs").write_text("RETURN\n", encoding="utf-8")
            self.assertNotEqual(ecs.inspect_script_corpus(source)["sha256"], expected["sha256"])

    def test_egg_main_preserves_explicit_nx_argument(self):
        original = (
            "$孵蛋流程请求Held帧 = 0\n"
            "FUNC 孵蛋流程_计算两次命中时间(): INT\nRETURN 1\nENDFUNC\n"
            "FUNC 孵蛋流程_执行Seed预校准轮(): INT\n"
            + ecs.EGG_FORMAL_PARITY_REAL_CALL_NX_WAIT_MODE + "\nENDFUNC\n"
        )
        overlay = ecs.EGG_FORMAL_PARITY_OVERRIDE_PATH.read_text(encoding="utf-8")
        result = ecs._apply_egg_formal_parity_runtime_override_text(original, overlay)
        self.assertEqual(result.count(ecs.EGG_FORMAL_PARITY_REAL_CALL_NX_WAIT_MODE), 1)
        self.assertNotIn(ecs.EGG_FORMAL_PARITY_REAL_CALL_WAIT_MODE, result)
        self.assertEqual(ecs._apply_egg_formal_parity_runtime_override_text(result, overlay), result)

    def test_egg_library_preserves_nx_during_menu_upgrade(self):
        original = (
            ecs.EGG_PICKUP_PARITY_SIGNATURE_NX_WAIT_MODE + "\n"
            + ecs.EGG_PICKUP_PARITY_VALIDATION_CURRENT.replace(
                "$封面长按MS, $Seed启动方案)",
                "$封面长按MS, $NX机型, $Seed启动方案, $使用绝对时间轴)",
            )
            + "    IF $使用绝对时间轴 != 0 and $使用绝对时间轴 != 1\n"
            "        RETURN 0\n    ENDIF\n"
            "    $孵蛋库_出蛋误差MS = 孵蛋测试_按模式等待到($孵蛋库_游戏时间轴原点, $孵蛋库_出蛋目标MS, $精确尾段MS, $使用绝对时间轴)\n"
            "    LS DOWN\n    IF $孵蛋库_出蛋检测结果 != 1\n"
            "        RETURN 2\n    ENDIF\n    LS RIGHT\n    RETURN 1\nENDFUNC\n"
        )
        result = ecs._apply_egg_pickup_parity_menu_text(original)
        self.assertIn(ecs.EGG_PICKUP_PARITY_SIGNATURE_NX_WAIT_MODE, result)
        self.assertIn("$封面长按MS, $NX机型, $Seed启动方案, $使用绝对时间轴)", result)
        self.assertEqual(result.count(ecs.EGG_GENERATION_PARITY_MENU_MARKER), 1)
        self.assertEqual(result.count(ecs.EGG_PICKUP_PARITY_MENU_MARKER), 1)
        self.assertEqual(ecs._apply_egg_pickup_parity_menu_text(result), result)

    def test_seed_overlay_preserves_first_hit_majority_and_full_hold(self):
        original = (
            "$Seed命中保持样本数 = 5\n$Seed命中保持本轮刷新 = 0\n"
            "FUNC 计算Seed锁定众数修正(): INT\nRETURN 0\nENDFUNC\n"
        )
        result = ecs._apply_seed_hold_observation_window_text(original)
        self.assertEqual(len(re.findall(r"(?m)^\$Seed曾命中目标 = 0$", result)), 1)
        self.assertIn("$Seed锁定提前多数票数 = 3", result)
        self.assertIn("$Seed曾命中目标 = 1", result)
        self.assertIn("IF $Seed曾命中目标 == 0 and", result)
        self.assertIn("IF $Seed命中保持计数 < $Seed命中保持样本数", result)
        self.assertEqual(ecs._apply_seed_hold_observation_window_text(result), result)
        egg = ecs.EGG_SEED_CONTROLLER_OVERRIDE_PATH.read_text(encoding="utf-8")
        self.assertIn("    $Seed曾命中目标 = 0", egg)
        self.assertIn("IF $调试日志输出 == 1", egg)
        self.assertIn("PRINT 下轮Seed请求:", egg)

    def test_unified_controller_and_egg_dispatch_are_never_replaced(self):
        original = unified_fixture()
        self.assertTrue(ecs._uses_upstream_unified_seed_controller(original))
        self.assertEqual(ecs._apply_seed_hold_observation_window_text(original), original)
        self.assertEqual(
            ecs._apply_egg_seed_controller_runtime_override_text(original, "旧控制器不能注入"),
            original,
        )

    def test_partial_unified_controller_fails_instead_of_silently_downgrading(self):
        original = unified_fixture()
        for broken in (
            original.replace("RETURN 计算Seed统一校准修正()", "RETURN 0"),
            original.replace("FUNC 更新Seed统一校准阶段(): INT", "FUNC 未知阶段(): INT"),
            original.replace("ELIF $Seed校准方案 != 0", "ELIF $Seed校准方案 == 2"),
        ):
            with self.subTest(broken=broken):
                with self.assertRaises(ValueError):
                    ecs._apply_seed_hold_observation_window_text(broken)
        with self.assertRaisesRegex(ValueError, "统一方案分派"):
            ecs._apply_egg_seed_controller_runtime_override_text(
                original.replace("$Seed本次修正索引 = 计算Seed所选方案修正(0)", "RETURN 0"),
                "旧控制器不能注入",
            )

    def test_module_delegate_keeps_push_call_pull_and_rejects_partial_bridge(self):
        original = (
            "FUNC 孵蛋流程_推送校准上下文(): INT\nRETURN 1\nENDFUNC\n"
            "FUNC 孵蛋流程_回收校准上下文(): INT\nRETURN 1\nENDFUNC\n"
            + ecs.EGG_FORMAL_PARITY_ORIGINAL_FUNCTION + "\n"
            "    # EGG_MODULE_DELEGATE: 孵蛋校准_计算两次命中时间\n"
            "    $孵蛋模块推送结果 = 孵蛋流程_推送校准上下文()\n"
            "    $孵蛋模块调用结果 = 孵蛋校准_计算两次命中时间()\n"
            "    $孵蛋模块回收结果 = 孵蛋流程_回收校准上下文()\n"
            "    RETURN $孵蛋模块调用结果\nENDFUNC\n"
        )
        self.assertEqual(
            ecs._apply_egg_formal_parity_runtime_override_text(original, "旧计算不能注入"),
            original,
        )
        with self.assertRaisesRegex(ValueError, "委托不完整"):
            ecs._apply_egg_formal_parity_runtime_override_text(
                original.replace("$孵蛋模块回收结果 = 孵蛋流程_回收校准上下文()", "RETURN 0"),
                "旧计算不能注入",
            )

    def test_dark_closing_overlays_preserve_upstream_wait(self):
        recovery = ecs.HOME_BUFFER_RECOVERY_PATH.read_text(encoding="utf-8")
        self.assertIn("IF @正在关闭_暗 > $HOME_BUFFER恢复关闭中", recovery)
        self.assertIn("$HOME_BUFFER恢复未知 = 0\n            WAIT 2000\n            CONTINUE", recovery)
        restart = ecs.EGG_RESTART_OVERRIDE_PATH.read_text(encoding="utf-8")
        self.assertIn("$孵蛋库_正在关闭暗匹配 = @正在关闭_暗", restart)
        self.assertIn("正在关闭_暗.IL:>=:", restart)
        self.assertIn("$孵蛋库_正在关闭暗匹配 >= $识图阈值\n                    WAIT 2000", restart)


@unittest.skipUnless(CACHE.is_dir(), "requires current imported release assets")
class ImportedReleaseAssetsTests(unittest.TestCase):
    def test_imported_unified_seed_and_egg_bridge_match_reviewed_source(self):
        functions = {
            "FUNC 计算Seed所选方案修正($原始样本已写入: INT): INT":
                "d5953e513daa243462599ceaceb00837b3f50b39b40b352271cc6e9cf12f9dd2",
            "FUNC 计算Seed锁定众数修正(): INT":
                "c05b4d50e770307c65550e237657a1b5b3dbc6d7bbf0c36011b61fca9e246e24",
            "FUNC 更新Seed统一校准阶段(): INT":
                "6c446425a2542b72d80a6bfb68a60661df3c059bbd17167b1fcf650dca5fc338",
            "FUNC 孵蛋流程_按观测Seed校正等待($Seed差索引: INT): INT":
                "5a2c6c47830fdb7dfa7ec02e015b9a79abc7d83f6bfc2f267db6e38c9e678f90",
            ecs.EGG_FORMAL_PARITY_ORIGINAL_FUNCTION:
                "7ed9fad8a1a2db7b7bf24a33ade0bf8652238416466f884dc22482fce94122bf",
        }
        for name in ecs.EXPECTED_TEMPLATE_NAMES:
            text = (CACHE / name).read_text(encoding="utf-8")
            self.assertTrue(ecs._uses_upstream_unified_seed_controller(text))
            self.assertEqual(text.count("# EGG_MODULE_DELEGATE:"), 12)
            self.assertEqual(ecs._apply_seed_hold_observation_window_text(text), text)
            for signature, expected in functions.items():
                with self.subTest(name=name, signature=signature):
                    block = ecs._function_block(text, signature)[2]
                    self.assertEqual(hashlib.sha256(block.encode()).hexdigest(), expected)
            self.assertIn("$孵蛋野生最小消耗帧 = $孵蛋生成目标帧", text)
            self.assertIn("$孵蛋野生最大消耗帧 = $孵蛋领取目标帧 + 4000", text)
        self.assertEqual(
            hashlib.sha256((CACHE / "lib/29_孵蛋校准.ecs").read_bytes()).hexdigest(),
            "8a2404d18ef77fe1be72d425ec4dc834b8eeba0448b57d1c767c6059a1ceb4cf",
        )

    def test_nx_startup_and_roamer_route_are_current(self):
        for name in ecs.EXPECTED_TEMPLATE_NAMES:
            text = (CACHE / name).read_text(encoding="utf-8")
            self.assertIn("$SeedBlackout肩键保持MS = 25820 + $NXSeed平台偏移MS", text)
            self.assertIn(ecs.EGG_FORMAL_PARITY_REAL_CALL_NX_WAIT_MODE, text)
            self.assertIn("IF $Seed曾命中目标 == 0 and", text)
            self.assertIn("HOME_BUFFER_LATE_SUCCESS", text)
            self.assertIn("$HOME_BUFFER识别状态 = HOME_BUFFER重采样状态(1)", text)
            self.assertIn("$目标获取TV等待MS = 1000", text)
            self.assertIn("$F2阶段脚本固定延迟 = $time_F2 - $time_F1 - $第0轮TV等待请求", text)
        egg = (CACHE / "lib/27_孵蛋测试流程.ecs").read_text(encoding="utf-8")
        self.assertIn(ecs.EGG_PICKUP_PARITY_SIGNATURE_NX_WAIT_MODE, egg)
        self.assertIn("$孵蛋库_Blackout肩键保持MS -= 750", egg)
        self.assertIn("$孵蛋库_HOME_BUFFER正确退出NS2匹配 = @HOME_BUFFER正确退出_NS2", egg)
        self.assertFalse((CACHE / "lib/seed_backup").exists())
        route = (CACHE / "lib/18_获取_抓捕流程.ecs").read_text(encoding="utf-8")
        self.assertIn("$三圣兽喷雾已消耗步数 = 4", route)
        self.assertIn("$三圣兽喷雾已消耗步数 = 0", route)
        self.assertIn("FOR $三圣兽草丛往返轮次 = 1 TO 3", route)
        self.assertIn("喷雾计步结束但未识别到耗尽提示，停止游走", route)
