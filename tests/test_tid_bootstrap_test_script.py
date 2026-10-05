"""Offline guardrails for the standalone, opt-in no-save preparation test."""

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "assets/tid_rng137_tests/无存档自动建档-164a测试.ecs"


def function(text, name):
    return re.search(
        rf"^FUNC {re.escape(name)}(?:\([^\n]*\))?[^\n]*\n(.*?)^ENDFUNC$",
        text, re.MULTILINE | re.DOTALL,
    ).group(1)


class TidBootstrapScriptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = SCRIPT.read_text(encoding="utf-8-sig")

    def test_defaults_are_ns1_english_and_not_a_formal_rng_plan(self):
        self.assertIn("$测试ROM语言 = 0", self.text)
        self.assertIn("$测试NS机型 = 1", self.text)
        self.assertIn("$测试建档后重启验证 = 1", self.text)
        self.assertNotIn("CALL FLOW_桥接", self.text)
        self.assertNotIn("$targetID", self.text)
        self.assertNotIn("OCR(", self.text)

    def test_menu_classifier_has_exact_fixed_threshold_and_conflict_guard(self):
        body = function(self.text, "测试_判定存档状态")
        self.assertIn("$有存档分 >= 95 and $无存档分 >= 95", body)
        self.assertLess(body.index("RETURN -1"), body.index("RETURN 1"))
        self.assertIn("ELIF $无存档分 >= 95\n        RETURN 2", body)
        self.assertNotIn("90", body)

    def test_only_confirmed_no_save_reaches_creation(self):
        main = self.text.split("\nFUNC ", 1)[0]
        guard = main[main.index("IF $测试OP结果 == 1"):main.index("CALL 测试_创建新游戏")]
        self.assertIn("ELIF $测试OP结果 == -1", guard)
        self.assertIn("ELIF $测试OP结果 != 2", guard)
        self.assertEqual(guard.count("\n    RETURN\n"), 3)
        self.assertEqual(main.count("CALL 测试_创建新游戏"), 1)

    def test_detection_is_after_all_op_key_releases_and_before_retry(self):
        body = function(self.text, "测试_启动并判断存档")
        detection = body.index("$测试OP结果 = 测试_OP后检测存档()")
        for release in ("A UP", "X UP", "L UP"):
            self.assertLess(body.rindex(release), detection)
        return_guard = body.index("IF $测试OP结果 != 0", detection)
        correction = body.index("$测试运行结果 = 测试_增加OP等待()")
        self.assertLess(return_guard, correction)
        self.assertNotIn("LS DOWN", body)

    def test_sampling_stays_in_original_500ms_window(self):
        body = function(self.text, "测试_OP后检测存档")
        self.assertIn("$测试采样截止 = 400", body)
        self.assertIn("$测试采样截止 += 50", body)
        self.assertIn("$测试采样剩余 = 500 -", body)
        self.assertEqual(body.count("IF $测试采样剩余 > 0"), 2)
        self.assertIn("$测试存档分 = @存档", body)
        self.assertIn("$测试无存档分 = @无存档", body)

    def test_op_recovery_is_bounded_and_does_not_change_other_delays(self):
        body = function(self.text, "测试_增加OP等待")
        self.assertLess(body.index("RETURN 0"), body.index("$测试OP修正MS += 50"))
        self.assertNotIn("$测试HOME_BUFFER延迟MS", body)
        self.assertNotIn("$测试关闭等待MS", body)
        self.assertIn("$测试OP修正次数 += 1", body)

    def test_no_save_entry_does_not_press_down_before_new_game(self):
        body = function(self.text, "测试_创建新游戏")
        opening = body[:body.index("PRINT 【创建进度】选择主角性别")]
        self.assertNotIn("LS DOWN", opening)
        self.assertIn("IF $测试ROM语言 == 1\n        FOR 2", opening)

    def test_japanese_text_speed_labels_are_not_english_aliases(self):
        body = function(self.text, "测试_读取语速")
        japanese, english = body.split("    ELSE", 1)
        for speed in ("FAST", "MID", "SLOW"):
            self.assertIn(f"@日版TEXT_SPEED_{speed}", japanese)
            self.assertIn(f"@TEXT_SPEED_{speed}", english)

    def test_fast_is_confirmed_before_first_save_and_no_overwrite_up(self):
        body = function(self.text, "测试_设置语速并首次保存")
        self.assertLess(body.index("IF $测试语速状态 != 0"), body.index("【第4段：首次保存】"))
        saving = body[body.index("【第4段：首次保存】"):]
        self.assertNotIn("LS UP", saving)
        self.assertNotRegex(saving, r"(?m)^\s*UP(?: DOWN)?\s*$")
        self.assertIn("WAIT 8000", saving)
        self.assertIn("不修改声音、战斗动画、按键设置", body)

    def test_post_save_failure_cannot_loop_back_into_creation(self):
        main = self.text.split("\nFUNC ", 1)[0]
        verify = main[main.index("$测试验证阶段 = 1"):]
        self.assertNotIn("CALL 测试_创建新游戏", verify)
        self.assertNotIn("CONTINUE", verify)
        self.assertIn("不再次建档", verify)
        self.assertIn("不能确认保存结果", verify)

    def test_actual_home_labels_are_selected_only_by_explicit_model(self):
        body = function(self.text, "测试_读取NS标签")
        ns2, ns1 = body.split("    ELSE", 1)
        self.assertIn("IF $测试NS机型 == 2", ns2)
        self.assertIn("@正确退出_NS2", ns2)
        self.assertIn("@正确退出\n", ns1)
        self.assertNotIn("@正确退出_NS2", ns1)

    def test_settings_failure_stops_before_save_or_restart(self):
        main = self.text.split("\nFUNC ", 1)[0]
        section = main[main.index("$测试运行结果 = 测试_设置语速并首次保存()"):]
        self.assertLess(section.index("IF $测试运行结果 != 1"), section.index("$测试验证阶段 = 1"))
        self.assertIn("不执行保存或重启", section)


if __name__ == "__main__":
    unittest.main()
