import unittest
from pathlib import Path

from automation.easycon118 import (
    EGG_SETTINGS_GLOBALS,
    EGG_SETTINGS_OVERRIDE_PATH,
    EggRunRequest,
    _apply_egg_settings_runtime_override_text,
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
        template += "\n# ============================进阶设置\n$内部参数 = 1"
        configured = configure_egg_template_text(template, egg_request())
        self.assertIn('$静态或野生 = "孵蛋"', configured)
        self.assertIn('$目标Seed = "75D1"', configured)
        self.assertIn('$孵蛋双亲A_DEF = 29', configured)
        self.assertIn('$孵蛋双亲B_SPA = 3', configured)

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


if __name__ == "__main__":
    unittest.main()
