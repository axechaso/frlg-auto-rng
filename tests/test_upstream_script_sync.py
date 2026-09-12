import re
import unittest
from pathlib import Path

from automation import easycon118 as ecs


ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "local_assets/easycon118"


class UpstreamOverlayTests(unittest.TestCase):
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


@unittest.skipUnless(CACHE.is_dir(), "requires current imported release assets")
class ImportedReleaseAssetsTests(unittest.TestCase):
    def test_nx_startup_and_roamer_route_are_current(self):
        for name in ecs.EXPECTED_TEMPLATE_NAMES:
            text = (CACHE / name).read_text(encoding="utf-8")
            self.assertIn("$SeedBlackout肩键保持MS = 25820 + $NXSeed平台偏移MS", text)
            self.assertIn(ecs.EGG_FORMAL_PARITY_REAL_CALL_NX_WAIT_MODE, text)
            self.assertIn("IF $Seed曾命中目标 == 0 and", text)
            self.assertIn("HOME_BUFFER_LATE_SUCCESS", text)
        egg = (CACHE / "lib/27_孵蛋测试流程.ecs").read_text(encoding="utf-8")
        self.assertIn(ecs.EGG_PICKUP_PARITY_SIGNATURE_NX_WAIT_MODE, egg)
        self.assertIn("$孵蛋库_Blackout肩键保持MS -= 750", egg)
        route = (CACHE / "lib/18_获取_抓捕流程.ecs").read_text(encoding="utf-8")
        self.assertIn("$三圣兽喷雾已消耗步数 = 4", route)
        self.assertIn("$三圣兽喷雾已消耗步数 = 0", route)
        self.assertIn("FOR $三圣兽草丛往返轮次 = 1 TO 3", route)
        self.assertIn("喷雾计步结束但未识别到耗尽提示，停止游走", route)
