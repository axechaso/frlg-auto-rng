"""Exercise Japanese Switch 2 beyond the successful TID stage."""
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from automation.easycon118 import (
    EGG_TEMPLATE_NAME, STANDARD_TEMPLATE_NAME, EasyConRuntimeCheck,
)
from automation.planner import AutoSearchRequest
from automation.tid_rng137 import TidRngRequest
from automation.tid_starter_flow import (
    TidStarterFlowRequest, build_tid_starter_flow_plan,
    resolve_exhaustive_starter_plan,
)
from rng.sid_reverse import sid_at_advance
from rng.tenlines import HELD_BUTTON_OFFSETS, get_contiguous_seed_list, load_frlg_seed_data
from rng.tenlines_utils import get_seed_time
from run_tid_starter_flow import (
    ID_MARKER, STARTER_SHINY_MARKER, STARTER_STRUCTURED_SHINY_MARKER,
    parse_id_identity, run_exhaustive_flow,
)


SOURCE = Path(__file__).resolve().parents[1] / "local_assets/easycon118"
IDENTITY_LINES = [
    "[15:11:58.599] TIDFLOW|ID|MATCH=1",
    "[15:11:58.599] TIDFLOW|ID|TID=39792",
    "[15:11:58.599] TIDFLOW|ID|SID_ADV=2295",
    "[15:11:58.599] TIDPROGRESS|DONE=1",
]


def flow_request(version="火红", nx_model=2, mode=0):
    return TidStarterFlowRequest(
        TidRngRequest(language="日文", player_name="レ", nx_model=nx_model,
                      mode=mode, sid_random=True, target_tid=39792),
        version, "妙蛙种子", starter_max_advances=3000,
        accept_any_tid=mode == 0,
    )


class JapaneseNx2HandoffTests(unittest.TestCase):
    def test_both_japanese_console_codes_are_valid_planner_inputs(self):
        for family in ("fr", "lg"):
            for console in ("nx", "nx2"):
                with self.subTest(family=family, console=console):
                    AutoSearchRequest(
                        game=f"{family}_jpn_{console}", tid=39792, sid=1,
                        method="Static 1", category="Starter", location="",
                        pokemon="Bulbasaur", max_advances=3000,
                    ).validate()

    def test_nx2_uses_japanese_seed_data_and_supported_offsets(self):
        for family in ("fr", "lg"):
            with self.subTest(family=family):
                base = f"{family}_jpn_nx"
                nx2 = base + "2"
                first = load_frlg_seed_data(base)
                second = load_frlg_seed_data(nx2)
                self.assertTrue(first[0])
                self.assertEqual(second, first)
                self.assertEqual(set(second[1]), {"mono_h_a"})
                self.assertEqual(HELD_BUTTON_OFFSETS[nx2], HELD_BUTTON_OFFSETS[base])
                seeds = get_contiguous_seed_list(second, "mono_h_a", nx2, "none")
                self.assertEqual(seeds, get_contiguous_seed_list(first, "mono_h_a", base, "none"))
                seed = seeds[0]
                self.assertEqual(get_seed_time(f'{seed["initial_seed"]:04X}', nx2), seed["seed_time"])

    def test_logged_identity_resolves_for_both_games_consoles_and_deferred_modes(self):
        tid, sid_adv = parse_id_identity(IDENTITY_LINES)
        self.assertEqual((tid, sid_adv), (39792, 2295))
        for version, family in (("火红", "fr"), ("叶绿", "lg")):
            baseline = None
            for nx in (1, 2):
                for mode in (0, 1):
                    with self.subTest(version=version, nx=nx, mode=mode):
                        resolved = resolve_exhaustive_starter_plan(
                            flow_request(version, nx, mode), actual_tid=tid, sid_advance=sid_adv,
                        )
                        self.assertEqual(resolved.sid, sid_at_advance(tid, sid_adv))
                        self.assertEqual(resolved.starter_run_plan.request.game,
                                         f"{family}_jpn_nx" + ("2" if nx == 2 else ""))
                        self.assertEqual(resolved.starter_target.game_code, f"{family}_jpn_nx")
                        self.assertGreaterEqual(resolved.starter_target.advances, 1500)
                        self.assertGreater(resolved.starter_target.shiny, 0)
                        pid = resolved.starter_target.pid
                        self.assertLess(tid ^ resolved.sid ^ (pid >> 16) ^ (pid & 0xFFFF), 8)
                        if baseline is None:
                            baseline = resolved.starter_target
                        self.assertEqual(resolved.starter_target, baseline)

    def test_known_identity_random_mode_also_keeps_nx2(self):
        for version, family in (("火红", "fr"), ("叶绿", "lg")):
            with self.subTest(version=version):
                request = flow_request(version, mode=1)
                request = replace(request, tid_request=replace(
                    request.tid_request, sid_random=False,
                    target_sid=sid_at_advance(39792, 2295),
                ))
                plan = build_tid_starter_flow_plan(request)
                self.assertFalse(plan.request.deferred_identity)
                self.assertEqual(plan.starter_run_plan.request.game, f"{family}_jpn_nx2")

    @unittest.skipUnless(SOURCE.is_dir(), "requires imported starter assets")
    def test_real_runtime_resolution_and_generation_reaches_bridge_and_starter(self):
        class DeviceFreeFlow:
            def __init__(self):
                self.calls = []
                self.messages = []
                self.stage_lines = []
                self.stop_requested = False

            def output(self, message):
                self.messages.append(message)

            def run_stage(self, number, name, main_path, required_marker=None):
                self.calls.append(number)
                if number == 1:
                    self.stage_lines = IDENTITY_LINES
                    assert required_marker == ID_MARKER
                elif number == 3:
                    assert Path(main_path).is_file()
                    self.stage_lines = [STARTER_SHINY_MARKER, STARTER_STRUCTURED_SHINY_MARKER]
                return 0

        for version, family in (("火红", "fr"), ("叶绿", "lg")):
            for template in (STANDARD_TEMPLATE_NAME, EGG_TEMPLATE_NAME):
                with self.subTest(version=version, template=template), tempfile.TemporaryDirectory() as temporary:
                    request = replace(flow_request(version), starter_template_name=template)
                    payload = build_tid_starter_flow_plan(request).to_dict()
                    payload["starter_source_dir"] = str(SOURCE)
                    output = Path(temporary)
                    flow = DeviceFreeFlow()
                    with patch("run_tid_starter_flow.validate_runtime", return_value=EasyConRuntimeCheck(True, (), ())):
                        code = run_exhaustive_flow(flow, output, payload, Path("unused-ezcon.exe"))
                    self.assertEqual(code, 0, flow.messages)
                    self.assertEqual(flow.calls, [1, 2, 3])
                    generated = (output / "03_starter_118/main.ecs").read_text(encoding="utf-8")
                    self.assertIn("$NX机型 = 2", generated)
                    self.assertIn("$Seed模式 = 10", generated)
                    self.assertIn("$游戏版本文本 = \"" + version + "\"", generated)
                    self.assertIn("FUNC 读取并输出日版御三家识图结果(): INT", generated)
                    self.assertTrue(any("实际TID=39792 / SID ADV=2295" in message for message in flow.messages))
