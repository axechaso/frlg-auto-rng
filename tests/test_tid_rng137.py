import tempfile
import unittest
from pathlib import Path

from automation.tid_rng137 import (
    DEFAULT_TID_SOURCE_PATH,
    EXPECTED_TID_LABEL_COUNT,
    EXPECTED_TID_LABEL_METHODS,
    EXPECTED_TID_LABEL_SHA256,
    EXPECTED_TID_SCRIPT_SHA256,
    TID_SCRIPT_NAMES,
    TidRngRequest,
    configure_tid_template_text,
    inspect_tid_package,
    referenced_image_labels,
    write_configured_tid_project,
)


class TidRng137Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = DEFAULT_TID_SOURCE_PATH
        cls.english = (cls.source / TID_SCRIPT_NAMES["英文"]).read_text(encoding="utf-8")
        cls.japanese = (cls.source / TID_SCRIPT_NAMES["日文"]).read_text(encoding="utf-8")

    def test_pinned_source_scripts_and_labels(self):
        manifest = inspect_tid_package(self.source)
        for language, expected in EXPECTED_TID_SCRIPT_SHA256.items():
            self.assertEqual(manifest["scripts"][language]["sha256"], expected)
        self.assertEqual(manifest["labels"]["count"], EXPECTED_TID_LABEL_COUNT)
        self.assertEqual(manifest["labels"]["methods"], EXPECTED_TID_LABEL_METHODS)
        self.assertEqual(manifest["labels"]["sha256"], EXPECTED_TID_LABEL_SHA256)

    def test_all_referenced_labels_exist(self):
        for language, text in (("英文", self.english), ("日文", self.japanese)):
            missing = [
                name for name in referenced_image_labels(text)
                if not (self.source / "ImgLabel" / f"{name}.IL").is_file()
            ]
            self.assertEqual(missing, [], language)

    def test_user_values_are_replaced_only_in_user_section(self):
        request = TidRngRequest(
            target_tid=12345,
            target_sid=54321,
            player_name="RED",
            op_rng_range=4,
            f1_rng_range=6,
            f2_rng_range=8,
            same_id=True,
        )
        configured = configure_tid_template_text(self.english, request)
        self.assertIn("_TARGET_TID = 12345", configured)
        self.assertIn("_TARGET_SID = 54321", configured)
        self.assertIn('$name = "RED"', configured)
        self.assertIn("$OP_RNG_Max_Range = 4", configured)
        self.assertIn("$same_id_switch = 1", configured)
        self.assertIn("# ======================== 用户自定义区结束", configured)

        marker = "# ======================== 用户自定义区结束 ========================"
        self.assertEqual(
            configured.partition(marker)[2],
            self.english.partition(marker)[2],
        )

    def test_japanese_template_gets_only_the_164a_loop_compatibility_fix(self):
        request = TidRngRequest(
            language="日文",
            gender=0,
            player_name="レット゛",
            op_fixed_delay=30650,
            f1_fixed_delay=27600,
            f2_fixed_delay=8960,
            f3_fixed_delay=15950,
        )
        configured = configure_tid_template_text(self.japanese, request)
        self.assertNotIn("FOR $InputLen", configured)
        self.assertIn("$有效名称末索引 = $InputLen - 1", configured)
        self.assertIn("FOR $NameIndex = 0 TO $有效名称末索引", configured)
        self.assertNotIn("$NameIndex += 1", configured)

    def test_name_rules_reject_unsupported_characters(self):
        with self.assertRaisesRegex(ValueError, "不支持的字符"):
            TidRngRequest(player_name="中文").validate(self.english)
        with self.assertRaisesRegex(ValueError, "最多按键 7 次"):
            TidRngRequest(player_name="ABCDEFGH").validate(self.english)

    def test_removed_f3_random_mode_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "F3随机模式已移除"):
            TidRngRequest(sid_random=True, f3_random_range=10).validate(self.english)

    def test_flow_marker_reports_actual_tid_for_all_five_success_types(self):
        configured = configure_tid_template_text(
            self.english,
            TidRngRequest(mode=0, sid_random=True),
            include_flow_marker=True,
        )
        self.assertEqual(configured.count("TIDFLOW|ID|MATCH=1"), 5)
        self.assertEqual(configured.count("TIDFLOW|ID|TID="), 5)
        self.assertIn(
            "TIDFLOW|ID|TID= & $curr1 & $curr2 & $curr3 & $curr4 & $curr5",
            configured,
        )

    def test_write_project_copies_full_pinned_label_package(self):
        with tempfile.TemporaryDirectory() as temp:
            main = write_configured_tid_project(
                self.source, Path(temp) / "tid", TidRngRequest(player_name="RED")
            )
            self.assertTrue(main.is_file())
            labels = list((main.parent / "ImgLabel").glob("*.IL"))
            self.assertEqual(len(labels), EXPECTED_TID_LABEL_COUNT)
            self.assertTrue((main.parent / "plan.json").is_file())


if __name__ == "__main__":
    unittest.main()
