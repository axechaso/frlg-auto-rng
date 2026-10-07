from itertools import product
from pathlib import Path
import re
import tempfile
import unittest

from automation.easycon118 import EASYCON118_EXTENSION_LABEL_NAMES, EXPECTED_LABEL_COUNT
from automation.tid_bootstrap import EXTENSION_PATH, GUARD_BEGIN, MARKER, entry_guard, install_tid_bootstrap
from automation.tid_rng137 import TidRngRequest, configure_tid_template_text, write_configured_tid_project
from automation.tid_starter_save import DEFAULT_TID_STARTER_SAVE_SOURCE, split_tid_modules
from tests.test_tid_starter_save import functions, fixture


ROOT = Path(__file__).resolve().parents[1]


def canonical(body):
    return "\n".join(line.split("#", 1)[0].strip() for line in body.splitlines()
                     if line.split("#", 1)[0].strip() and not line.strip().startswith("PRINT "))


def integration_fixture():
    text = fixture()
    detector = """FUNC TID_检测新建存档(): INT
    $OP检查截止 = 400
    $OP检查耗时 = TIME()
    $OP检查剩余 = 500 - $OP检查耗时
    $OP界面匹配分 = @存档
    IF $OP连续匹配 >= 2
        RETURN 1
    ENDIF
    RETURN 0
ENDFUNC
"""
    text = text.replace("# 唤醒设备", detector + "# 唤醒设备", 1)
    for prefix in ("EN", "JP"):
        text = text.replace(f"CALL {prefix}_HOME_BUFFER\n", f"""CALL {prefix}_HOME_BUFFER
FOR
    $OP新建存档检查 = TID_检测新建存档()
    IF $OP新建存档检查 == 0
        $OP可重试 = TID_增加OP修正()
        CALL {prefix}_清空窗口
        $denoise_hit_count = 0
        IF $OP可重试 == 0
            RETURN
        ENDIF
        CONTINUE
    ENDIF
    PRINT "FRLG_STAGE|BEGIN|tid.new_save_entry|test|15000|main.ecs|test|test|stop|OR;存档.IL:>=:" & $识图判断阈值 & "|!"
    LS DOWN
    WAIT 50
    LS RESET
    BREAK
NEXT
""", 1)
    return text


class TidBootstrapIntegrationTests(unittest.TestCase):
    def test_production_actions_equal_user_accepted_standalone(self):
        standalone = (ROOT / "assets/tid_rng137_tests/无存档自动建档-164a测试.ecs").read_text(encoding="utf-8")
        actual = functions(EXTENSION_PATH.read_text(encoding="utf-8"))
        original = functions(standalone)
        for name in ("创建新游戏", "判定存档状态", "判定语速", "读取语速", "设置语速并首次保存"):
            expected = original[f"测试_{name}"].replace("$测试ROM语言", "$连续流程_游戏版本").replace("$测试主角性别", "$gender")
            expected = expected.replace("$测试", "$TID建档").replace("测试_", "TID建档_")
            self.assertEqual(canonical(expected), canonical(actual[f"TID建档_{name}"]), name)

    def test_only_selected_language_guard_changes(self):
        source = integration_fixture()
        before = split_tid_modules(source)
        for language, index in (("英文", 1), ("日文", 2)):
            result = install_tid_bootstrap(source, language)
            after = split_tid_modules(result)
            self.assertEqual(before[3 - index], after[3 - index])
            self.assertEqual(before[3], after[3])
            guard = entry_guard("EN" if index == 1 else "JP")
            restored = after[index].replace(guard, "", 1).replace(
                'OR;存档.IL:>=:95,无存档.IL:>=:95|!"',
                'OR;存档.IL:>=:" & $识图判断阈值 & "|!"')
            self.assertEqual(before[index], restored)
            self.assertEqual(after[0].count(MARKER), 1)
            self.assertEqual(after[index].count(GUARD_BEGIN), 1)

    def test_install_is_idempotent_and_partial_extensions_fail(self):
        source = integration_fixture()
        result = install_tid_bootstrap(source, "英文")
        self.assertEqual(install_tid_bootstrap(result, "英文"), result)
        with self.assertRaisesRegex(ValueError, "不完整"):
            install_tid_bootstrap(result.replace(MARKER, "# REMOVED", 1), "英文")

    def test_unknown_op_timing_is_rejected(self):
        source = integration_fixture()
        with self.assertRaisesRegex(ValueError, "OP检测结构"):
            install_tid_bootstrap(source.replace("$OP检查截止 = 400", "$OP检查截止 = 300"), "英文")
        with self.assertRaisesRegex(ValueError, "原OP恢复路径"):
            install_tid_bootstrap(source.replace("TID_增加OP修正()", "UNKNOWN()"), "英文")

    def test_formal_generator_supports_both_languages_modes_and_calibration(self):
        source = integration_fixture()
        for language, mode, checking, flow in product(("英文", "日文"), (0, 1), (False, True), (False, True)):
            with self.subTest(language=language, mode=mode, checking=checking, flow=flow):
                request = TidRngRequest(language=language, player_name="R" if language == "英文" else "レ",
                                        mode=mode, calibration_check=checking)
                configured = configure_tid_template_text(source, request, include_flow_marker=flow)
                self.assertIn(MARKER, configured)
                self.assertEqual(configured.count("CALL TID建档_创建新游戏"), 1)
                self.assertEqual(configured.count(GUARD_BEGIN), 1)
                self.assertIn(f"$脚本固定延迟检查开关 = {int(checking)}", configured)

    def test_creation_is_single_attempt_and_restarts_without_search_advance(self):
        guard = entry_guard("EN")
        self.assertLess(guard.index("$TID建档已尝试 == 1"), guard.index("CALL TID建档_创建新游戏"))
        self.assertLess(guard.index("$TID建档已尝试 = 1"), guard.index("CALL TID建档_创建新游戏"))
        self.assertIn("CALL EN_清空窗口\n", guard)
        self.assertIn("$denoise_hit_count = 0", guard)
        self.assertNotIn("OP修正 +=", guard)
        self.assertNotIn("推进", guard)
        self.assertNotIn("TIDFLOW|ID|TID=", guard)
        self.assertNotIn("$OP_NOW", guard)
        self.assertNotIn("$F1_NOW", guard)
        self.assertNotIn("$OP脚本固定延迟", guard)

    def test_bootstrap_label_is_audited_and_full_corpus_kept(self):
        self.assertIn("无存档.IL", EASYCON118_EXTENSION_LABEL_NAMES)
        self.assertEqual(EXPECTED_LABEL_COUNT, 1155)
        self.assertTrue((ROOT / "assets/easycon118_extensions/无存档.IL").is_file())

    def test_speed_failure_does_not_close_or_save(self):
        guard = entry_guard("JP")
        self.assertNotIn("TID_关闭游戏()", guard)
        self.assertNotIn("TID_HOME_BUFFER()", guard)
        self.assertLess(guard.index("IF $TID建档结果 != 1"), guard.index("$TID建档等待验证 = 1"))
        creating = functions(EXTENSION_PATH.read_text(encoding="utf-8"))["TID建档_创建新游戏"]
        self.assertNotIn("$连续流程_游戏版本", creating)


@unittest.skipUnless(DEFAULT_TID_STARTER_SAVE_SOURCE.is_file(), "requires local TID mother")
class RealTidBootstrapTests(unittest.TestCase):
    def test_real_generation_preserves_normal_timeline_and_all_other_helpers(self):
        from automation.tid_starter_save import configure_starter_save_id
        source = DEFAULT_TID_STARTER_SAVE_SOURCE.read_text(encoding="utf-8-sig")
        for language, prefix, index, name in (("英文", "EN", 1, "Alxe"), ("日文", "JP", 2, "レット゛")):
            request = TidRngRequest(language=language, player_name=name)
            old = configure_starter_save_id(source, request)
            updated = install_tid_bootstrap(old, language)
            old_parts, new_parts = split_tid_modules(old), split_tid_modules(updated)
            restored = new_parts[index].replace(entry_guard(prefix), "", 1).replace(
                'OR;存档.IL:>=:95,无存档.IL:>=:95|!"',
                'OR;存档.IL:>=:" & $识图判断阈值 & "|!"')
            self.assertEqual(restored, old_parts[index])
            self.assertEqual(new_parts[3 - index], old_parts[3 - index])
            for name, body in functions(old).items():
                if name != "TID_检测新建存档":
                    self.assertEqual(functions(updated)[name], body, name)

    def test_real_project_contains_new_label_and_feature_record(self):
        import json
        with tempfile.TemporaryDirectory() as directory:
            main = write_configured_tid_project(DEFAULT_TID_STARTER_SAVE_SOURCE.parent, directory, TidRngRequest())
            self.assertTrue((main.parent / "ImgLabel/无存档.IL").is_file())
            self.assertEqual(len(list((main.parent / "ImgLabel").glob("*.IL"))), 1155)
            self.assertTrue(json.loads((main.parent / "plan.json").read_text(encoding="utf-8"))["tid_no_save_bootstrap"])


if __name__ == "__main__":
    unittest.main()
