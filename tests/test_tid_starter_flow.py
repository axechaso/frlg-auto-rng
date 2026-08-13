import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from automation.easycon118 import EasyConRuntimeCheck
from automation.tid_rng137 import DEFAULT_TID_SOURCE_PATH, TidRngRequest
from automation.tid_starter_flow import (
    TidStarterFlowRequest,
    build_tid_starter_flow_plan,
    render_lab_bridge_ecs,
    validate_tid_starter_flow_runtime,
    write_tid_starter_flow_bundle,
)

SOURCE_118 = Path(__file__).resolve().parents[1] / "local_assets" / "easycon118"


class TidStarterFlowTests(unittest.TestCase):
    def test_plan_uses_shared_target_search_and_first_sid_advance(self):
        request = TidStarterFlowRequest(
            tid_request=TidRngRequest(
                language="英文",
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
        self.assertGreaterEqual(plan.earliest_sid_chain_advance, 0)
        self.assertEqual(plan.sid_retry_corrections[:5], (5, 6, 4, 7, 3))
        self.assertFalse(plan.request.to_exact_tid_request().include_65535)

    def test_bridge_uses_only_selected_starter_horizontal_distance(self):
        bridge = render_lab_bridge_ecs("杰尼龟")
        self.assertIn("FOR 3\n        CALL 走右", bridge)
        self.assertIn("TIDFLOW|BRIDGE|DONE=1", bridge)
        self.assertNotIn("OP_当前目标", bridge)
        self.assertNotIn("总F12", bridge)

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
        validate_starter.assert_called_once_with(root / "ezcon.exe", starter_main)

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

    @unittest.skipUnless(
        (
            DEFAULT_TID_SOURCE_PATH
            / "【TID+SID乱数&穷举】英文版-火红叶绿1.3.7.txt"
        ).is_file(),
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
        self.assertNotIn("FUNC JP_", id_text)
        self.assertIn("$SID_ADV修正 = 1", id_attempt_1)
        self.assertIn("TIDFLOW|BRIDGE|DONE=1", bridge_text)
        self.assertIn('$目标Seed = "9CA9"', starter_text)
        self.assertIn("$目标消耗帧 = 1513", starter_text)
        self.assertIn("$目标全国图鉴编号 = 1", starter_text)
        self.assertEqual(payload["starter_target"]["advances"], 1513)
        self.assertEqual(payload["starter_118_plan"]["request"]["category"], "Starter")


if __name__ == "__main__":
    unittest.main()
