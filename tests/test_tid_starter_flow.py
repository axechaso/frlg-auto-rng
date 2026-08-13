import json
import tempfile
import unittest
from pathlib import Path

from automation.tid_rng137 import DEFAULT_TID_SOURCE_PATH, TidRngRequest
from automation.tid_starter_flow import (
    TidStarterFlowRequest,
    build_tid_starter_flow_plan,
    render_lab_bridge_ecs,
    write_tid_starter_flow_bundle,
)


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
        self.assertGreaterEqual(plan.earliest_sid_chain_advance, 0)
        self.assertEqual(plan.sid_retry_corrections[:5], (5, 6, 4, 7, 3))
        self.assertFalse(plan.request.to_exact_tid_request().include_65535)

    def test_bridge_uses_only_selected_starter_horizontal_distance(self):
        bridge = render_lab_bridge_ecs("杰尼龟")
        self.assertIn("FOR 3\n        CALL 走右", bridge)
        self.assertIn("TIDFLOW|BRIDGE|DONE=1", bridge)
        self.assertNotIn("OP_当前目标", bridge)
        self.assertNotIn("总F12", bridge)

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
            )
            id_text = (output / "01_id" / "main.ecs").read_text(encoding="utf-8")
            bridge_text = (output / "02_lab_bridge" / "main.ecs").read_text(encoding="utf-8")
            payload = json.loads(plan_path.read_text(encoding="utf-8"))

        self.assertIn("TIDFLOW|ID|MATCH=1", id_text)
        self.assertNotIn("FUNC JP_", id_text)
        self.assertIn("TIDFLOW|BRIDGE|DONE=1", bridge_text)
        self.assertEqual(payload["starter_target"]["advances"], 1513)


if __name__ == "__main__":
    unittest.main()
