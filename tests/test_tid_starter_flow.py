import json
from dataclasses import replace
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from automation.easycon118 import EGG_TEMPLATE_NAME, STANDARD_TEMPLATE_NAME, EasyConRuntimeCheck
from automation.tid_rng137 import (
    DEFAULT_TID_SOURCE_PATH, TID_LEGACY_SCRIPT_NAMES, TID_SCRIPT_NAMES, TidRngRequest,
)
from automation.tid_starter_save import (
    TID_STARTER_SAVE_NAME,
    is_starter_save_template,
    split_tid_modules,
    stabilize_english_name_page_wait,
)
from automation.tid_starter_flow import (
    DEFAULT_TID_SID_SEARCH_ADVANCES,
    STARTER_SEED_CALIBRATION_SCHEME,
    TidStarterFlowRequest,
    enable_any_tid_handoff,
    tid_starter_flow_request_from_dict,
    build_tid_starter_flow_plan,
    render_lab_bridge_ecs,
    resolve_exhaustive_starter_plan,
    validate_tid_starter_flow_runtime,
    write_tid_starter_flow_bundle,
    write_resolved_exhaustive_starter_project,
)

SOURCE_118 = Path(__file__).resolve().parents[1] / "local_assets" / "easycon118"
HAS_TID_ASSETS = any(
    (DEFAULT_TID_SOURCE_PATH / filename).is_file()
    for filename in (TID_STARTER_SAVE_NAME, TID_SCRIPT_NAMES["英文"], TID_LEGACY_SCRIPT_NAMES["英文"])
)


class TidStarterFlowTests(unittest.TestCase):
    def test_old_english_name_page_wait_is_upgraded_idempotently(self):
        legacy = """\
FUNC EN_切换到目标页
    FOR $MoveDelta
        Y DOWN
        WAIT 50
        Y UP
        $select基础次数 += 1
        550
    NEXT
ENDFUNC
"""
        upgraded = stabilize_english_name_page_wait(legacy)
        self.assertIn("$select基础次数 += 1\n        600", upgraded)
        self.assertNotIn("$select基础次数 += 1\n        550", upgraded)
        self.assertEqual(stabilize_english_name_page_wait(upgraded), upgraded)

    def test_random_mode_can_leave_sid_unrandomized_and_defer_starter_identity(self):
        request = TidStarterFlowRequest(
            tid_request=TidRngRequest(
                language="英文",
                mode=1,
                target_tid=12345,
                target_sid=8832,
                sid_random=True,
            ),
            version="火红",
            starter="妙蛙种子",
            starter_max_advances=1600,
        )
        plan = build_tid_starter_flow_plan(request)

        self.assertTrue(plan.request.deferred_identity)
        self.assertIsNone(plan.starter_target)
        self.assertIsNone(plan.starter_run_plan)
        self.assertTrue(plan.request.to_flow_tid_request().sid_random)
        payload = plan.to_dict()["request"]
        self.assertEqual(
            payload["sid_chain_search_advances"], DEFAULT_TID_SID_SEARCH_ADVANCES
        )
        restored = tid_starter_flow_request_from_dict(payload)
        self.assertTrue(restored.deferred_identity)
        self.assertEqual(
            restored.sid_chain_search_advances, DEFAULT_TID_SID_SEARCH_ADVANCES
        )

    def test_explicit_unbounded_sid_chain_remains_available_for_api_callers(self):
        request = TidStarterFlowRequest(
            tid_request=TidRngRequest(mode=1, sid_random=True),
            version="火红",
            starter="妙蛙种子",
            sid_chain_search_advances=None,
        )
        payload = build_tid_starter_flow_plan(request).to_dict()["request"]
        self.assertIsInstance(payload, dict)
        restored = tid_starter_flow_request_from_dict(
            {**payload, "sid_chain_search_advances": None}
        )
        self.assertIsNone(restored.sid_chain_search_advances)

    def test_any_tid_is_opt_in_exhaustive_only_and_survives_plan_reload(self):
        request = TidStarterFlowRequest(TidRngRequest(mode=0, sid_random=True), "火红", "妙蛙种子")
        self.assertFalse(request.accept_any_tid)
        self.assertTrue(request.any_tid_require_denoise)
        request = replace(request, accept_any_tid=True, any_tid_require_denoise=False)
        plan = build_tid_starter_flow_plan(request)
        restored = tid_starter_flow_request_from_dict(plan.to_dict()["request"])
        self.assertTrue(restored.accept_any_tid)
        self.assertFalse(restored.any_tid_require_denoise)
        restored.validate()
        with self.assertRaisesRegex(ValueError, "穷举"):
            replace(request, tid_request=TidRngRequest()).validate()

    def test_any_tid_insertion_refuses_to_bypass_digit_validation(self):
        with self.assertRaisesRegex(ValueError, "完整识别"):
            enable_any_tid_handoff("            CALL EN_匹配\nFUNC EN_匹配\nENDFUNC\nFUNC EN_打印参数\nENDFUNC\n")

    @staticmethod
    def handoff_module(prefix):
        return (
            "            IF $digits_ok == 0\n                CONTINUE\n            ENDIF\n"
            f"            CALL {prefix}去噪\n            CALL {prefix}匹配\n"
            f"FUNC {prefix}匹配\nENDFUNC\nFUNC {prefix}打印参数\nENDFUNC\n"
        )

    @classmethod
    def combined_handoff_template(cls, language):
        return (
            f"$连续流程_游戏版本 = {language}\n"
            "# ===== 英文版 TID/SID 主体（顶层全局分支） =====\n"
            + cls.handoff_module("EN_")
            + "# ===== 日文版 TID/SID 主体（顶层全局分支） =====\n"
            + cls.handoff_module("JP_")
            + "# 工具 ID 阶段结束：桥接与存档只在第二阶段执行。\nRETURN 0\n"
        )

    def test_combined_any_tid_handoff_only_changes_active_language(self):
        for language, prefix in ((0, "EN_"), (1, "JP_")):
            for denoise in (False, True):
                with self.subTest(language=language, denoise=denoise):
                    template = self.combined_handoff_template(language)
                    generated = enable_any_tid_handoff(template, require_denoise=denoise)
                    before, after = split_tid_modules(template), split_tid_modules(generated)
                    for index in range(4):
                        if index != language + 1:
                            self.assertEqual(before[index], after[index])
                    active = after[language + 1]
                    self.assertEqual(generated.count("# TIDFLOW_ANY_TID_BEGIN"), 1)
                    self.assertIn(f"CALL {prefix}打印参数", active)
                    self.assertEqual("$denoise_hit_count >= $denoise_need_hit" in active, denoise)
                    self.assertIn("$ID >= 0 and $ID <= 65535", active)
                    self.assertIn("$脚本固定延迟检查开关 == 0", active)
                    self.assertLess(active.index("IF $digits_ok == 0"), active.index("# TIDFLOW_ANY_TID_BEGIN"))
                    self.assertLess(active.index(f"CALL {prefix}打印参数"), active.index("PRINT TIDFLOW|ID|SID_ADV="))

    def test_combined_any_tid_handoff_rejects_missing_or_ambiguous_language(self):
        template = self.combined_handoff_template(1)
        for replacement in ("", "$连续流程_游戏版本 = 2\n", "$连续流程_游戏版本 = 0\n$连续流程_游戏版本 = 1\n"):
            with self.subTest(replacement=replacement), self.assertRaisesRegex(ValueError, "语言"):
                enable_any_tid_handoff(template.replace("$连续流程_游戏版本 = 1\n", replacement, 1))

    def test_japanese_guard_cannot_be_borrowed_from_inactive_english(self):
        parts = list(split_tid_modules(self.combined_handoff_template(1)))
        parts[2] = parts[2].replace("            IF $digits_ok == 0\n", "            IF $other == 0\n")
        with self.assertRaisesRegex(ValueError, "完整识别"):
            enable_any_tid_handoff("".join(parts))

    def test_standalone_any_tid_handoff_keeps_legacy_prefixes(self):
        for prefix in ("EN_", "JP_", ""):
            with self.subTest(prefix=prefix):
                generated = enable_any_tid_handoff(self.handoff_module(prefix), require_denoise=False)
                self.assertIn(f"CALL {prefix}打印参数", generated)
                self.assertEqual(generated.count("# TIDFLOW_ANY_TID_BEGIN"), 1)

    @unittest.skipUnless(HAS_TID_ASSETS and SOURCE_118.is_dir(), "requires TID assets")
    def test_any_tid_handoff_changes_only_the_opt_in_success_branch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for language, name, active, prefix in (("英文", "R", 1, "EN_"), ("日文", "レ", 2, "JP_")):
                request = TidStarterFlowRequest(
                    TidRngRequest(language=language, player_name=name, mode=0, sid_random=True,
                                  target_tid=65535, same_id=True),
                    "火红", "妙蛙种子", starter_max_advances=1600,
                )
                normal = None
                for enabled, denoise in ((False, True), (False, False), (True, True), (True, False)):
                    with self.subTest(language=language, enabled=enabled, denoise=denoise):
                        output = root / f"{active}-{enabled}-{denoise}"
                        plan = build_tid_starter_flow_plan(replace(
                            request, accept_any_tid=enabled, any_tid_require_denoise=denoise,
                        ))
                        write_tid_starter_flow_bundle(DEFAULT_TID_SOURCE_PATH, output, plan, starter_source_dir=SOURCE_118)
                        text = (output / "01_id" / "main.ecs").read_text(encoding="utf-8")
                        self.assertEqual((output / "01_id" / "main_attempt_000.ecs").read_text(encoding="utf-8"), text)
                        pattern = r"(?ms)^            # TIDFLOW_ANY_TID_BEGIN\n.*?^            # TIDFLOW_ANY_TID_END\n"
                        blocks = re.findall(pattern, text)
                        if not enabled:
                            self.assertEqual(blocks, [])
                            if normal is None:
                                normal = text
                            self.assertEqual(text, normal)
                            continue
                        self.assertEqual(len(blocks), 1)
                        block = blocks[0]
                        if is_starter_save_template(text):
                            parts = split_tid_modules(text)
                            self.assertIn(block, parts[active])
                            self.assertNotIn(block, parts[3 - active])
                            self.assertIn(f"CALL {prefix}打印参数", block)
                        self.assertEqual("$denoise_hit_count >= $denoise_need_hit" in block, denoise)
                        self.assertIn("$ID >= 0 and $ID <= 65535", block)
                        self.assertIn("$脚本固定延迟检查开关 == 0", block)
                        self.assertIn("PRINT TIDFLOW|ID|TID= & $ID", block)
                        self.assertIn("PRINT TIDFLOW|ID|SID_ADV= & $adv", block)
                        self.assertLess(block.index("打印参数"), block.index("TIDFLOW|ID|SID_ADV="))
                        self.assertNotIn("TARGET_TID", block)
                        self.assertEqual(re.sub(pattern, "", text), normal)

    def test_plan_uses_shared_target_search_and_first_sid_advance(self):
        request = TidStarterFlowRequest(
            tid_request=TidRngRequest(
                language="英文",
                sound=0,
                button_mode=1,
                seed_button=0,
                target_tid=12345,
                target_sid=8832,
                sid_advance_correction=5,
                include_65535=True,
            ),
            version="火红",
            starter="妙蛙种子",
            starter_max_advances=1600,
        )
        plan = build_tid_starter_flow_plan(request)

        self.assertEqual(plan.starter_target.advances, 1513)
        self.assertEqual(plan.starter_run_plan.initial_seed.advances, 1513)
        self.assertEqual(plan.starter_run_plan.request.category, "Starter")
        self.assertEqual(plan.starter_run_plan.species_id, 1)
        self.assertEqual(request.tid_request.button_mode, 1)
        self.assertEqual(request.to_starter_search_request().setting_key, "mono_h_a")
        self.assertEqual(plan.starter_run_plan.initial_seed.settings.setting_key, "mono_h_a")
        self.assertGreaterEqual(plan.earliest_sid_chain_advance, 0)
        self.assertEqual(plan.sid_retry_corrections[:5], (5, 7, 3, 9, 1))
        self.assertFalse(plan.request.to_flow_tid_request().include_65535)

    @unittest.skipUnless(HAS_TID_ASSETS and SOURCE_118.is_dir(), "requires TID assets")
    def test_japanese_starter_uses_japanese_seed_table_and_ocr_branch(self):
        request = TidStarterFlowRequest(
            tid_request=TidRngRequest(
                language="日文",
                target_tid=12345,
                target_sid=8832,
            ),
            version="火红",
            starter="妙蛙种子",
            starter_max_advances=3000,
        )
        plan = build_tid_starter_flow_plan(request)
        self.assertEqual(plan.starter_target.game_code, "fr_jpn_nx")
        self.assertEqual(plan.starter_target.setting_key, "mono_h_a")

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            write_tid_starter_flow_bundle(
                DEFAULT_TID_SOURCE_PATH,
                output,
                plan,
                starter_source_dir=SOURCE_118,
            )
            starter = (output / "03_starter_118" / "main.ecs").read_text(encoding="utf-8")
            fire_red = (output / "03_starter_118" / "lib" / "02_Seed表_火红_NX.ecs").read_text(encoding="utf-8-sig")

        self.assertIn("$Seed模式 = 10", starter)
        self.assertIn("FUNC 读取并输出日版御三家识图结果(): INT", starter)
        self.assertIn("@性格日版天真 > $识图阈值", starter)
        self.assertIn("$识图性格 = 24", starter)
        self.assertIn("# mode 10 = japanese_mono_h_a（临时日版御三家）", fire_red)
        self.assertIn("ELIF $mode == 10", fire_red)

    def test_japanese_starter_rejects_unavailable_seed_settings(self):
        request = TidStarterFlowRequest(
            tid_request=TidRngRequest(language="日文"),
            version="火红",
            starter="妙蛙种子",
            starter_sound=1,
        )
        with self.assertRaisesRegex(ValueError, "MONO.*HELP.*A"):
            request.validate()

    def test_starter_settings_are_serialized_separately_from_tid_settings(self):
        request = TidStarterFlowRequest(
            tid_request=TidRngRequest(
                language="英文",
                sound=1,
                button_mode=1,
                seed_button=2,
                target_tid=12345,
                target_sid=8832,
            ),
            version="火红",
            starter="妙蛙种子",
            starter_sound=0,
            starter_button_mode=0,
            starter_seed_button=0,
        )
        payload = build_tid_starter_flow_plan(request).to_dict()["request"]
        self.assertEqual(payload["tid_request"]["button_mode"], 1)
        self.assertEqual(payload["tid_request"]["seed_button"], 2)
        self.assertEqual(payload["starter_sound"], 0)
        self.assertEqual(payload["starter_button_mode"], 0)
        self.assertEqual(payload["starter_seed_button"], 0)
        self.assertEqual(payload["starter_seed_calibration_scheme"], 0)
        restored = tid_starter_flow_request_from_dict(payload)
        self.assertEqual(restored.tid_request.button_mode, 1)
        self.assertEqual(restored.tid_request.seed_button, 2)
        self.assertEqual(restored.to_starter_search_request().setting_key, "mono_h_a")

    def test_starter_template_and_precalibration_options_survive_plan_reload(self):
        request = TidStarterFlowRequest(
            tid_request=TidRngRequest(
                language="英文",
                target_tid=12345,
                target_sid=8832,
            ),
            version="火红",
            starter="妙蛙种子",
            starter_seed_startup_scheme=1,
            starter_template_name=EGG_TEMPLATE_NAME,
            update_precalibration=True,
            starter_debug_log_output=0,
            starter_frame_parity_scheme=0,
            starter_reverse_expansion_layers=2,
            starter_reverse_expansion_seed_tolerances=(11, 22, 33),
            starter_reverse_expansion_frame_half_widths=(1000, 2000, 3000),
            starter_max_advances=1600,
        )

        payload = build_tid_starter_flow_plan(request).to_dict()["request"]
        restored = tid_starter_flow_request_from_dict(payload)

        self.assertEqual(payload["starter_seed_startup_scheme"], 1)
        self.assertEqual(payload["starter_template_name"], EGG_TEMPLATE_NAME)
        self.assertTrue(payload["update_precalibration"])
        self.assertEqual(payload["starter_debug_log_output"], 0)
        self.assertEqual(payload["starter_frame_parity_scheme"], 0)
        self.assertEqual(payload["starter_reverse_expansion_layers"], 2)
        self.assertEqual(restored.starter_seed_startup_scheme, 1)
        self.assertEqual(restored.starter_template_name, EGG_TEMPLATE_NAME)
        self.assertTrue(restored.update_precalibration)
        self.assertEqual(restored.starter_debug_log_output, 0)
        self.assertEqual(restored.starter_frame_parity_scheme, 0)
        self.assertEqual(restored.starter_reverse_expansion_seed_tolerances, (11, 22, 33))
        restored.validate()

    @unittest.skipUnless(HAS_TID_ASSETS and SOURCE_118.is_dir(), "requires starter assets")
    def test_starter_locks_calibration_but_keeps_startup_scheme_selectable(self):
        request = TidStarterFlowRequest(
            tid_request=TidRngRequest(
                language="英文",
                target_tid=12345,
                target_sid=8832,
            ),
            version="火红",
            starter="妙蛙种子",
            starter_seed_startup_scheme=1,
            starter_max_advances=1600,
        )
        plan = build_tid_starter_flow_plan(request)

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            write_tid_starter_flow_bundle(
                DEFAULT_TID_SOURCE_PATH,
                output,
                plan,
                starter_source_dir=SOURCE_118,
            )
            starter = (output / "03_starter_118" / "main.ecs").read_text(
                encoding="utf-8"
            )

        self.assertIn("$Seed校准方案 = 0", starter)
        self.assertIn("$Seed启动方案 = 1", starter)
        self.assertIn(
            "# GUI 2.0 校准可信门控：不可信维度只观察，不写窗、不下发修正",
            starter,
        )
        self.assertIn("IF $Seed本轮可信 == 0", starter)
        self.assertIn("IF $TV帧本轮可信 == 0", starter)
        self.assertIn("IF $剩余帧本轮可信 == 0", starter)
        self.assertIn(
            "IF $消耗帧本轮可信 == 1 and $命中差索引 == 0 and $本轮消耗帧误差 == 0",
            starter,
        )
        self.assertEqual(STARTER_SEED_CALIBRATION_SCHEME, 0)

    def test_exhaustive_plan_defers_starter_search_until_actual_identity(self):
        request = TidStarterFlowRequest(
            tid_request=TidRngRequest(
                language="英文",
                mode=0,
                target_tid=99999 % 65536,
                target_sid=0,
                sid_random=True,
                same_id=True,
            ),
            version="火红",
            starter="妙蛙种子",
            starter_max_advances=1600,
        )
        plan = build_tid_starter_flow_plan(request)

        self.assertTrue(plan.request.deferred_identity)
        self.assertIsNone(plan.starter_target)
        self.assertIsNone(plan.starter_run_plan)
        self.assertTrue(plan.request.to_flow_tid_request().same_id)
        self.assertTrue(plan.request.to_flow_tid_request().sid_random)

        resolved = resolve_exhaustive_starter_plan(
            request,
            actual_tid=12345,
            sid_advance=199,
        )
        self.assertEqual(resolved.tid, 12345)
        self.assertEqual(resolved.sid, 8832)
        self.assertEqual(resolved.starter_target.tid, 12345)
        self.assertEqual(resolved.starter_target.sid, 8832)
        self.assertEqual(resolved.starter_run_plan.request.tid, 12345)
        self.assertEqual(resolved.starter_run_plan.request.sid, 8832)

    @unittest.skipUnless(SOURCE_118.is_dir(), "requires starter assets")
    def test_dynamic_starter_generation_installs_paired_selection_in_both_templates(self):
        for template in (STANDARD_TEMPLATE_NAME, EGG_TEMPLATE_NAME):
            with self.subTest(template=template), tempfile.TemporaryDirectory() as directory:
                request = TidStarterFlowRequest(
                    TidRngRequest(mode=0, sid_random=True), "火红", "小火龙",
                    starter_min_advances=1500, starter_max_advances=1600,
                    starter_template_name=template,
                )
                resolved = resolve_exhaustive_starter_plan(request, actual_tid=31056, sid_advance=2279)
                main = write_resolved_exhaustive_starter_project(SOURCE_118, Path(directory) / "03_starter_118", resolved)
                text = main.read_text(encoding="utf-8")
                self.assertEqual(text.count("# STARTER_CALIBRATION_V1"), 1)
                self.assertLess(text.index("共同区提交()"), text.index("$御三家筛选结果 = 御三家应用共同候选()"))
                self.assertIn("御三家有界兜底窗", text)
                self.assertEqual("$御三家菜单耗时MS = TIME() - $御三家菜单起始MS" in text, template == STANDARD_TEMPLATE_NAME)
                self.assertIn("FUNC 共同区选择本轮配对", (main.parent / "lib/25_校准_投票决策.ecs").read_text(encoding="utf-8"))

    def test_bridge_uses_only_selected_starter_horizontal_distance(self):
        bridge = render_lab_bridge_ecs("杰尼龟")
        self.assertIn("FOR 3\n        CALL 走右", bridge)
        self.assertIn("TIDFLOW|BRIDGE|DONE=1", bridge)
        self.assertNotIn("OP_当前目标", bridge)
        self.assertNotIn("总F12", bridge)

    @unittest.skipUnless(HAS_TID_ASSETS, "requires TID assets")
    def test_english_name_page_flip_waits_50ms_longer_before_moving(self):
        source = (DEFAULT_TID_SOURCE_PATH / TID_STARTER_SAVE_NAME).read_text(
            encoding="utf-8"
        )
        page_start = source.index("FUNC EN_切换到目标页")
        page_end = source.index("ENDFUNC", page_start)
        page = source[page_start:page_end]

        self.assertIn("Y UP\n        $select基础次数 += 1\n        600", page)
        self.assertNotIn("Y UP\n        $select基础次数 += 1\n        550", page)
        self.assertIn("$select基础次数 += 1", page)

    def test_runtime_validation_combines_id_and_bridge_checks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            id_main = root / "01_id" / "main.ecs"
            bridge_main = root / "02_lab_bridge" / "main.ecs"
            starter_main = root / "03_starter_118" / "main.ecs"
            id_main.parent.mkdir(parents=True)
            bridge_main.parent.mkdir(parents=True)
            starter_main.parent.mkdir(parents=True)
            id_main.write_text("RETURN 0\n", encoding="utf-8")
            bridge_main.write_text("RETURN 0\n", encoding="utf-8")
            starter_main.write_text("RETURN 0\n", encoding="utf-8")
            with (
                patch(
                    "automation.tid_starter_flow.validate_tid_runtime",
                    return_value=EasyConRuntimeCheck(True, (), ("ID预检通过",)),
                ),
                patch(
                    "automation.tid_starter_flow.subprocess.run",
                    return_value=SimpleNamespace(
                        returncode=0,
                        stdout="",
                        stderr="",
                    ),
                ) as format_run,
                patch(
                    "automation.tid_starter_flow.validate_runtime",
                    return_value=EasyConRuntimeCheck(True, (), ("1.1.8预检通过",)),
                ) as validate_starter,
            ):
                result = validate_tid_starter_flow_runtime(
                    root / "ezcon.exe",
                    id_main,
                    bridge_main,
                    starter_main,
                )

        self.assertTrue(result.ok)
        self.assertIn("ID预检通过", result.warnings)
        self.assertIn("研究所桥接脚本已通过EasyCon 1.6.4-a格式检查。", result.warnings)
        self.assertIn("1.1.8预检通过", result.warnings)
        format_run.assert_called_once()
        validate_starter.assert_called_once_with(
            (root / "ezcon.exe").resolve(),
            starter_main.resolve(),
        )

    def test_runtime_validation_rejects_missing_bridge(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with (
                patch(
                    "automation.tid_starter_flow.validate_tid_runtime",
                    return_value=EasyConRuntimeCheck(True, (), ()),
                ),
                patch(
                    "automation.tid_starter_flow.validate_runtime",
                    return_value=EasyConRuntimeCheck(True, (), ()),
                ),
            ):
                result = validate_tid_starter_flow_runtime(
                    root / "ezcon.exe",
                    root / "01_id" / "main.ecs",
                    root / "02_lab_bridge" / "main.ecs",
                    root / "03_starter_118" / "main.ecs",
                )

        self.assertFalse(result.ok)
        self.assertIn("找不到研究所桥接脚本", result.errors[0])

    def test_runtime_validation_allows_deferred_starter_stage(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            id_main = root / "01_id" / "main.ecs"
            bridge_main = root / "02_lab_bridge" / "main.ecs"
            id_main.parent.mkdir(parents=True)
            bridge_main.parent.mkdir(parents=True)
            id_main.write_text("RETURN 0\n", encoding="utf-8")
            bridge_main.write_text("RETURN 0\n", encoding="utf-8")
            with (
                patch(
                    "automation.tid_starter_flow.validate_tid_runtime",
                    return_value=EasyConRuntimeCheck(True, (), ()),
                ),
                patch(
                    "automation.tid_starter_flow.subprocess.run",
                    return_value=SimpleNamespace(returncode=0, stdout="", stderr=""),
                ),
                patch("automation.tid_starter_flow.validate_runtime") as validate_starter,
            ):
                result = validate_tid_starter_flow_runtime(
                    root / "ezcon.exe", id_main, bridge_main, None
                )

        self.assertTrue(result.ok)
        self.assertTrue(any("取得实际TID" in item for item in result.warnings))
        validate_starter.assert_not_called()

    @unittest.skipUnless(
        HAS_TID_ASSETS and SOURCE_118.is_dir(),
        "requires the external TID 1.3.7 package",
    )
    def test_bundle_keeps_language_template_separate_and_adds_marker(self):
        plan = build_tid_starter_flow_plan(
            TidStarterFlowRequest(
                tid_request=TidRngRequest(
                    language="英文",
                    target_tid=12345,
                    target_sid=8832,
                ),
                version="火红",
                starter="Bulbasaur",
                starter_max_advances=1600,
            )
        )
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            plan_path = write_tid_starter_flow_bundle(
                DEFAULT_TID_SOURCE_PATH,
                output,
                plan,
                starter_source_dir=SOURCE_118,
            )
            id_text = (output / "01_id" / "main.ecs").read_text(encoding="utf-8")
            id_attempt_1 = (output / "01_id" / "main_attempt_001.ecs").read_text(encoding="utf-8")
            bridge_text = (output / "02_lab_bridge" / "main.ecs").read_text(encoding="utf-8")
            starter_text = (output / "03_starter_118" / "main.ecs").read_text(encoding="utf-8")
            payload = json.loads(plan_path.read_text(encoding="utf-8"))

        self.assertIn("TIDFLOW|ID|MATCH=1", id_text)
        self.assertIn("TIDFLOW|ID|TID=", id_text)
        if is_starter_save_template(id_text):
            self.assertIn("$连续流程_游戏版本 = 0", id_text)
            self.assertNotIn("CALL FLOW_桥接到御三家存档点", id_text)
            self.assertEqual(bridge_text.count("CALL FLOW_桥接到御三家存档点"), 1)
            self.assertEqual(payload["lab_bridge_source"], TID_STARTER_SAVE_NAME)
        else:
            self.assertNotIn("FUNC JP_", id_text)
        self.assertIn("$SID_ADV修正 = 2", id_attempt_1)
        self.assertIn("TIDFLOW|BRIDGE|DONE=1", bridge_text)
        self.assertIn('$目标Seed = "9CA9"', starter_text)
        self.assertIn("$目标消耗帧 = 1513", starter_text)
        self.assertIn("$目标全国图鉴编号 = 1", starter_text)
        self.assertEqual(payload["starter_target"]["advances"], 1513)
        self.assertEqual(payload["starter_118_plan"]["request"]["category"], "Starter")

    @unittest.skipUnless(
        HAS_TID_ASSETS and SOURCE_118.is_dir(),
        "requires the external TID 1.3.7 package",
    )
    def test_exhaustive_bundle_preserves_filters_and_defers_starter_project(self):
        plan = build_tid_starter_flow_plan(
            TidStarterFlowRequest(
                tid_request=TidRngRequest(
                    language="英文",
                    mode=0,
                    sid_random=True,
                    same_id=True,
                    include_65535=True,
                ),
                version="火红",
                starter="小火龙",
                starter_max_advances=2000,
            )
        )
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            plan_path = write_tid_starter_flow_bundle(
                DEFAULT_TID_SOURCE_PATH,
                output,
                plan,
                starter_source_dir=SOURCE_118,
            )
            id_text = (output / "01_id" / "main_attempt_000.ecs").read_text(
                encoding="utf-8"
            )
            payload = json.loads(plan_path.read_text(encoding="utf-8"))

            self.assertFalse((output / "03_starter_118").exists())

        self.assertIn("$ID_RNG = 0", id_text)
        self.assertIn("$SID_RAND = 1", id_text)
        self.assertIn("$F3_Max_Rand_Range = 0", id_text)
        self.assertIn("$same_id_switch = 1", id_text)
        self.assertIn("$65535开关 = 1", id_text)
        self.assertTrue(payload["deferred_identity"])
        self.assertIsNone(payload["starter_target"])
        self.assertIsNone(payload["starter_118_plan"])


if __name__ == "__main__":
    unittest.main()
