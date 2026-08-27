import json
from pathlib import Path
import re
import tempfile
import unittest

from automation.tid_rng137 import (
    TidRngRequest, _TID_HOME_BUFFER_ORIGINAL, configure_tid_template_text,
    resolve_tid_template,
)
from automation.tid_starter_save import (
    DEFAULT_TID_STARTER_SAVE_SOURCE, TID_STARTER_SAVE_NAME,
    _blocking_buttons, configure_starter_save_id, render_starter_save_bridge,
    set_starter_save_sid_correction, split_tid_modules,
)


def functions(text):
    return {
        match[1]: match[0]
        for match in re.finditer(r"(?ms)^FUNC ([^\s(]+)[^\n]*\n.*?^ENDFUNC", text)
    }


def fixture():
    head = """$连续流程_游戏版本 = 0
$连续流程_御三家选择 = 0
$连续流程_步进间隔 = 200
$连续流程_按键时长 = 200
$连续流程_Oak文本推进次数 = 30
$SID_ADV修正 = 0
$EN_TARGET_TID = 0
$JP_TARGET_TID = 0
# 唤醒设备
FOR 5
    LCLICK 120
    100
NEXT
"""
    for name in ("走一步上", "走一步下", "走一步左", "走一步右", "桥接到御三家存档点"):
        head += f"FUNC FLOW_{name}\n    WAIT 100\nENDFUNC\n"
    for language, prefix, index, name in (("英文", "EN", 0, "R"), ("日文", "JP", 1, "レ")):
        values = TidRngRequest(language=language, player_name=name).to_user_values()
        values[f"${prefix}_TARGET_TID"] = values.pop("_TARGET_TID")
        values[f"${prefix}_TARGET_SID"] = values.pop("_TARGET_SID")
        head += f"# ===== {language}版 TID/SID 主体（顶层全局分支） =====\n"
        head += f"IF $连续流程_游戏版本 == {index}\n"
        head += "\n".join(f"{key} = {json.dumps(value, ensure_ascii=False)}" for key, value in values.items())
        head += "\n# ======================== 用户自定义区结束\n"
        head += f"CALL {prefix}_HOME_BUFFER\n"
        head += "                IF $denoise_hit_count >= $denoise_need_hit\n                    BREAK 2\n                ENDIF\n" * 5
        head += "ENDIF\n"
        head += _blocking_buttons(_TID_HOME_BUFFER_ORIGINAL).replace(
            "FUNC HOME_BUFFER", f"FUNC {prefix}_HOME_BUFFER"
        ).replace("CALL 关闭游戏", f"CALL {prefix}_关闭游戏") + "\n"
        head += f'FUNC {prefix}_calcname($n: STRING, $i): INT\n    IF $char == "{name}"\n        RETURN 111\n    ENDIF\nENDFUNC\n'
    return head + """# =========================================================
# 顶层入口收尾：ID 主体结束后才进入研究所桥接。
CALL FLOW_桥接到御三家存档点
RETURN
"""


class TidStarterSaveTests(unittest.TestCase):
    def test_confirmed_file_has_priority_for_both_languages(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / TID_STARTER_SAVE_NAME
            source.write_text(fixture(), encoding="utf-8")
            for language in ("英文", "日文"):
                self.assertEqual(resolve_tid_template(root, language), source.resolve())

    def test_only_active_user_section_changes_and_id_never_walks_route(self):
        source = fixture()
        for language, index, name in (("英文", 1, "R"), ("日文", 2, "レ")):
            request = TidRngRequest(language=language, player_name=name, target_tid=12345, sid_advance_correction=7, calibration_check=True)
            configured = configure_tid_template_text(source, request)
            before, after = split_tid_modules(source), split_tid_modules(configured)
            self.assertEqual(before[3 - index], after[3 - index])
            self.assertIn("$SID_ADV修正 = 0\n", after[0])
            self.assertIn("$SID_ADV修正 = 7\n", after[index])
            self.assertIn("$脚本固定延迟检查开关 = 1\n", after[index])
            self.assertNotIn("CALL FLOW_桥接到御三家存档点", configured)
            self.assertEqual(functions(source), functions(configured))
            self.assertIn("FOR 5\n    LCLICK 120\n    100\nNEXT", configured)

    def test_exhaustive_markers_report_actual_identity_for_all_five_successes(self):
        configured = configure_starter_save_id(
            fixture(), TidRngRequest(player_name="R", mode=0, sid_random=True), include_flow_marker=True
        )
        english = split_tid_modules(configured)[1]
        self.assertEqual(english.count("TIDFLOW|ID|MATCH=1"), 5)
        self.assertEqual(english.count("TIDFLOW|ID|TID= & $ID"), 5)
        self.assertEqual(english.count("TIDFLOW|ID|SID_ADV= & $adv"), 5)
        self.assertNotIn("TIDFLOW|ID|TID= & $EN_TARGET_TID", english)
        self.assertNotIn("TIDFLOW", split_tid_modules(configured)[2])

    def test_retry_correction_never_changes_global_or_other_language(self):
        configured = configure_starter_save_id(fixture(), TidRngRequest(player_name="R"))
        updated = set_starter_save_sid_correction(configured, "英文", -13)
        before, after = split_tid_modules(configured), split_tid_modules(updated)
        self.assertEqual(before[0], after[0])
        self.assertEqual(before[2:], after[2:])
        self.assertIn("$SID_ADV修正 = -13", after[1])

    def test_adaptive_is_global_and_preserves_synchronous_buttons(self):
        for language, prefix, index, name in (("英文", "EN", 1, "R"), ("日文", "JP", 2, "レ")):
            source = fixture()
            configured = configure_starter_save_id(source, TidRngRequest(language=language, player_name=name, home_buffer_adaptive_threshold=True))
            parts = split_tid_modules(configured)
            self.assertIn("$HOME_BUFFER自适应稳定要求 = 3", parts[0])
            self.assertIn("$HOME_BUFFER自适应最低阈值 = 90", parts[0])
            home = functions(configured)[f"{prefix}_HOME_BUFFER"]
            self.assertIn("A DOWN\n        WAIT 50\n        A UP", home)
            self.assertIn("HOME DOWN\n        WAIT 100\n        HOME UP", home)
            self.assertIn(f"CALL {prefix}_关闭游戏", home)
            self.assertNotRegex(home, r"(?m)^\s*(A|B|HOME)(?: \d+)?$")
            self.assertEqual(split_tid_modules(source)[3 - index], parts[3 - index])

    def test_bridge_reuses_original_functions_once(self):
        for starter, choice in (("妙蛙种子", 0), ("杰尼龟", 1), ("小火龙", 2)):
            source = fixture()
            bridge = render_starter_save_bridge(source, starter)
            self.assertIn(f"$连续流程_御三家选择 = {choice}", bridge)
            self.assertEqual(bridge.count("CALL FLOW_桥接到御三家存档点"), 1)
            self.assertIn("IF $连续流程_桥接完成 == 1\n    PRINT TIDFLOW|BRIDGE|DONE=1", bridge)
            self.assertEqual(functions(bridge), {name: body for name, body in functions(source).items() if name.startswith("FLOW_")})

    def test_language_name_validation_does_not_use_other_language_alphabet(self):
        with self.assertRaisesRegex(ValueError, "不支持的字符"):
            configure_starter_save_id(fixture(), TidRngRequest(player_name="レ"))


@unittest.skipUnless(DEFAULT_TID_STARTER_SAVE_SOURCE.is_file(), "requires the confirmed external TID/save source")
class TidStarterSaveSourceTests(unittest.TestCase):
    def test_real_source_preserves_all_timing_and_route_functions(self):
        source = DEFAULT_TID_STARTER_SAVE_SOURCE.read_text(encoding="utf-8-sig")
        for language, name in (("英文", "Alxed"), ("日文", "レット゛")):
            for adaptive in (False, True):
                configured = configure_starter_save_id(source, TidRngRequest(language=language, player_name=name, home_buffer_adaptive_threshold=adaptive), include_flow_marker=True)
                original_functions, generated_functions = functions(source), functions(configured)
                changed_home = ("EN" if language == "英文" else "JP") + "_HOME_BUFFER"
                for function, body in original_functions.items():
                    if adaptive and function == changed_home:
                        continue
                    self.assertEqual(body, generated_functions[function], function)
                self.assertNotIn("CALL FLOW_桥接到御三家存档点", configured)
                self.assertEqual(configured.count("TIDFLOW|ID|TID="), 5)

    def test_real_bridge_keeps_all_original_route_functions(self):
        source = DEFAULT_TID_STARTER_SAVE_SOURCE.read_text(encoding="utf-8-sig")
        bridge = render_starter_save_bridge(source, "小火龙")
        self.assertEqual(functions(bridge), {name: body for name, body in functions(source).items() if name.startswith("FLOW_")})


if __name__ == "__main__":
    unittest.main()
