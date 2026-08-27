import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from tools.import_tid_rng137 import import_package

from automation.tid_rng137 import (
    DEFAULT_TID_SOURCE_PATH,
    EXPECTED_TID_LABEL_COUNT,
    EXPECTED_TID_LABEL_METHODS,
    EXPECTED_TID_LABEL_SHA256,
    EXPECTED_TID_SCRIPT_SHA256,
    SUPPORTED_TID_SCRIPT_SHA256,
    TID_LEGACY_SCRIPT_NAMES,
    TID_SCRIPT_NAMES,
    TidRngRequest,
    _TID_HOME_BUFFER_ORIGINAL,
    configure_tid_template_text,
    inspect_tid_package,
    referenced_image_labels,
    resolve_tid_template,
    verify_tid_package,
    write_configured_tid_project,
)
from automation.tid_starter_save import is_starter_save_template, split_tid_modules


class TidTemplateRevisionTests(unittest.TestCase):
    """Run in CI without the external TID scripts or image-label package."""

    def template(self, prefix):
        request = TidRngRequest(player_name="R")
        values = "\n".join(
            f"{name} = {json.dumps(value, ensure_ascii=False)}"
            for name, value in request.to_user_values().items()
        )
        home = _TID_HOME_BUFFER_ORIGINAL.replace(
            "FUNC HOME_BUFFER", f"FUNC {prefix}HOME_BUFFER"
        ).replace("CALL 关闭游戏", f"CALL {prefix}关闭游戏")
        success = "                IF $denoise_hit_count >= $denoise_need_hit\n                    BREAK 2\n                ENDIF\n"
        return (
            values + "\n# ======================== 用户自定义区结束\n"
            + f"CALL {prefix}HOME_BUFFER\n" + success * 5 + home
            + f'\nFUNC {prefix}calcname($n: STRING, $i): INT\n'
            + '    IF $char == "R"\n        RETURN 111\n    ENDIF\nENDFUNC\n'
        )

    def test_new_filename_wins_even_if_old_template_is_also_present(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            legacy = root / TID_LEGACY_SCRIPT_NAMES["英文"]
            legacy.write_text("legacy", encoding="utf-8")
            self.assertEqual(resolve_tid_template(root, "英文"), legacy.resolve())
            updated = root / TID_SCRIPT_NAMES["英文"]
            updated.write_text("updated", encoding="utf-8")
            self.assertEqual(resolve_tid_template(root, "英文"), updated.resolve())

    def test_unknown_new_fingerprint_does_not_silently_fall_back(self):
        manifest = {"scripts": {
            "英文": {"sha256": "unknown", "filename": TID_SCRIPT_NAMES["英文"]},
            "日文": {"sha256": EXPECTED_TID_SCRIPT_SHA256["日文"]},
        }}
        with patch("automation.tid_rng137.inspect_tid_package", return_value=manifest):
            with self.assertRaisesRegex(ValueError, "英文版.*指纹不一致"):
                verify_tid_package(".")

    def test_import_copies_selected_rewrite_and_preserves_old_text_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, destination = root / "source", root / "cache"
            (source / "ImgLabel").mkdir(parents=True)
            (destination / "ImgLabel").mkdir(parents=True)
            (source / "ImgLabel" / "sample.IL").write_bytes(b"label")
            for filename in TID_SCRIPT_NAMES.values():
                (source / filename).write_text("selected", encoding="utf-8")
            note = destination / "notes.txt"
            note.write_text("keep", encoding="utf-8")
            legacy = destination / TID_LEGACY_SCRIPT_NAMES["英文"]
            legacy.write_text("legacy", encoding="utf-8")
            manifest = {"scripts": {
                language: {"filename": filename}
                for language, filename in TID_SCRIPT_NAMES.items()
            }}
            with (
                patch("tools.import_tid_rng137.ROOT", root),
                patch("tools.import_tid_rng137.verify_tid_package", return_value=manifest),
            ):
                import_package(source, destination)
                # 原地校验不得删除自己的标签或模板。
                import_package(destination, destination)
            self.assertEqual(note.read_text(encoding="utf-8"), "keep")
            self.assertEqual(legacy.read_text(encoding="utf-8"), "legacy")
            self.assertEqual(resolve_tid_template(destination, "英文").name, TID_SCRIPT_NAMES["英文"])
            self.assertEqual((destination / "ImgLabel" / "sample.IL").read_bytes(), b"label")

    def test_legacy_and_rewrite_fingerprints_are_both_supported(self):
        for digest in SUPPORTED_TID_SCRIPT_SHA256["英文"]:
            manifest = {"scripts": {
                "英文": {"sha256": digest},
                "日文": {"sha256": EXPECTED_TID_SCRIPT_SHA256["日文"]},
            }, "labels": {
                "count": EXPECTED_TID_LABEL_COUNT,
                "methods": EXPECTED_TID_LABEL_METHODS,
                "sha256": EXPECTED_TID_LABEL_SHA256,
            }}
            with patch("automation.tid_rng137.inspect_tid_package", return_value=manifest):
                self.assertEqual(verify_tid_package("."), manifest)

    def test_adaptive_preserves_both_namespaces_and_flow_success_markers(self):
        for prefix in ("", "EN_"):
            with self.subTest(prefix=prefix):
                result = configure_tid_template_text(
                    self.template(prefix),
                    TidRngRequest(player_name="R", home_buffer_adaptive_threshold=True),
                    include_flow_marker=True,
                )
                self.assertEqual(result.count(f"FUNC {prefix}HOME_BUFFER\n"), 1)
                self.assertEqual(result.count(f"CALL {prefix}关闭游戏"), 2)
                self.assertIn(f"CALL {prefix}HOME_BUFFER\n", result)
                self.assertEqual(result.count("TIDFLOW|ID|TID="), 5)
                self.assertEqual(result.count("TIDFLOW|ID|SID_ADV="), 5)
                self.assertIn("$HOME_BUFFER自适应最低阈值 = 90", result)
                self.assertLess(
                    result.index("$HOME_BUFFER自适应稳定要求 = 3"),
                    result.index(f"CALL {prefix}HOME_BUFFER"),
                )
                if prefix:
                    self.assertNotRegex(result, r"(?m)^FUNC HOME_BUFFER$")
                    self.assertNotIn("CALL 关闭游戏", result)

    def test_disabled_adaptive_keeps_execution_body_unchanged(self):
        for prefix in ("", "EN_"):
            template = self.template(prefix)
            request = TidRngRequest(
                player_name="R", calibration_check=True,
                op_fixed_delay=30801, f1_fixed_delay=22901,
                f2_fixed_delay=4301, f3_fixed_delay=15001,
            )
            configured = configure_tid_template_text(template, request)
            marker = "# ======================== 用户自定义区结束"
            self.assertEqual(configured.partition(marker)[2], template.partition(marker)[2])
            self.assertNotIn("TID_HOME_BUFFER_ADAPTIVE", configured)
            self.assertIn("$脚本固定延迟检查开关 = 1", configured)
            for name, value in request.to_user_values().items():
                if name.endswith("脚本固定延迟"):
                    self.assertIn(f"{name} = {value}", configured)
            self.assertIn("$F3_Max_Rand_Range = 0", configured)


class TidRng137Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = DEFAULT_TID_SOURCE_PATH
        try:
            cls.english = resolve_tid_template(cls.source, "英文").read_text(encoding="utf-8-sig")
            cls.japanese = resolve_tid_template(cls.source, "日文").read_text(encoding="utf-8-sig")
        except FileNotFoundError as exc:
            raise unittest.SkipTest("需要本机外部 TID 1.3.7 资产包") from exc

    def test_pinned_source_scripts_and_labels(self):
        manifest = inspect_tid_package(self.source)
        for language, supported in SUPPORTED_TID_SCRIPT_SHA256.items():
            self.assertIn(manifest["scripts"][language]["sha256"], supported)
            if manifest["scripts"][language]["filename"] == TID_SCRIPT_NAMES[language]:
                self.assertEqual(
                    manifest["scripts"][language]["sha256"],
                    EXPECTED_TID_SCRIPT_SHA256[language],
                )
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
        original_body = self.english
        if is_starter_save_template(self.english):
            configured = split_tid_modules(configured)[1]
            original_body = split_tid_modules(self.english)[1]
        self.assertEqual(
            configured.partition(marker)[2],
            original_body.partition(marker)[2],
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
        if is_starter_save_template(self.japanese):
            for index in range(1, 11):
                self.assertIn(f"$输入目标字符 = $Name{index}", split_tid_modules(configured)[2])
        else:
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

    def test_home_buffer_adaptive_is_opt_in_for_both_languages(self):
        for language, template in (("英文", self.english), ("日文", self.japanese)):
            disabled = configure_tid_template_text(
                template,
                TidRngRequest(
                    language=language,
                    gender=0 if language == "日文" else 1,
                    player_name="レット゛" if language == "日文" else "RED",
                ),
            )
            self.assertNotIn("TID_HOME_BUFFER_ADAPTIVE", disabled, language)

            enabled = configure_tid_template_text(
                template,
                TidRngRequest(
                    language=language,
                    gender=0 if language == "日文" else 1,
                    player_name="レット゛" if language == "日文" else "RED",
                    home_buffer_adaptive_threshold=True,
                ),
            )
            self.assertIn("FUNC TID_HOME_BUFFER识别稳定状态(): INT", enabled, language)
            self.assertIn("$HOME_BUFFER自适应稳定要求 = 3", enabled, language)
            self.assertIn("$HOME_BUFFER自适应最低阈值 = 90", enabled, language)
            self.assertIn("$NS机型 == 1", enabled, language)
            self.assertEqual(
                len(re.findall(r"(?m)^FUNC (?:(?:EN|JP)_)?HOME_BUFFER$", enabled)),
                2 if is_starter_save_template(template) else 1, language,
            )

    def test_home_buffer_adaptive_flag_must_be_boolean(self):
        with self.assertRaisesRegex(ValueError, "必须是布尔值"):
            TidRngRequest(home_buffer_adaptive_threshold=1).validate(self.english)

    def test_flow_marker_reports_actual_tid_for_all_five_success_types(self):
        configured = configure_tid_template_text(
            self.english,
            TidRngRequest(mode=0, sid_random=True),
            include_flow_marker=True,
        )
        self.assertEqual(configured.count("TIDFLOW|ID|MATCH=1"), 5)
        self.assertEqual(configured.count("TIDFLOW|ID|TID="), 5)
        self.assertIn(
            (
                "TIDFLOW|ID|TID= & $ID"
                if is_starter_save_template(self.english)
                else "TIDFLOW|ID|TID= & $curr1 & $curr2 & $curr3 & $curr4 & $curr5"
            ),
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
            plan = json.loads((main.parent / "plan.json").read_text(encoding="utf-8"))
            self.assertEqual(plan["template"], resolve_tid_template(self.source, "英文").name)
            self.assertEqual(plan["tid_request"]["player_name"], "RED")
            self.assertFalse(main.read_text(encoding="utf-8").startswith("\ufeff"))


if __name__ == "__main__":
    unittest.main()
