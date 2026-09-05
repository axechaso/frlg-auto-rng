"""Search coverage, historical windows, and persistent local-search lifecycle."""
from dataclasses import replace
from itertools import product
import json
from pathlib import Path
import unittest

from automation.tid_checkpoint import instrument_tid_checkpoint, validate_checkpoint, fixed_frame
from automation.tid_rng137 import TidRngRequest
from automation.tid_starter_save import DEFAULT_TID_STARTER_SAVE_SOURCE
from tests import test_tid_search as replay_support


@unittest.skipUnless(DEFAULT_TID_STARTER_SAVE_SOURCE.is_file(), "requires audited TID template")
class PolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        replay_support.TidSearchTests.setUpClass()
        cls.replay = replay_support.TidSearchTests()

    def restore(self, request, source, state):
        generated = instrument_tid_checkpoint(source, request, state)
        block = generated.split("# TID_CHECKPOINT_BEGIN\n", 1)[1].split("# TID_CHECKPOINT_END", 1)[0]
        fresh, p, _ = self.replay.setup_machine(request, offset=0)
        fresh.source += "\nFUNC RESTORE\n" + block + "\nENDFUNC\n"
        fresh.call("RESTORE")
        fresh.call(p + "_计算操作延迟")
        return fresh, p

    def test_historical_windows_keep_early_near_results_without_inventing_votes(self):
        data = json.loads((Path(__file__).parent / "fixtures/tid_historical_windows.json").read_text(encoding="utf-8"))
        for record, expected, votes in zip(data["windows"], (54, 84), (1, 2)):
            request = TidRngRequest(mode=0, auto_rng=True, sid_random=True, include_65535=False)
            m, p, _ = self.replay.setup_machine(request)
            for tid in record["tids"][:10]:
                m.state.update({f"curr{i}": int(v) for i, v in enumerate(tid, 1)})
                m.call(p + "_去噪")
                m.call(p + "_检测目标区域")
            self.assertEqual(m.state["ID_RNG"], 0)
            self.assertEqual(m.state["TID区域次数"], votes)
            current, hits = m.state["ID"], m.state["denoise_hit_count"]
            m.call(p + "_采用窗口候选")
            self.assertEqual((m.state["targetID"], m.state["AbsDelta"]), (0, expected))
            self.assertEqual((m.state["ID"], m.state["denoise_hit_count"]), (current, hits))
            m.state["OP"] = 0
            m.call(p + "_穷举推进到下一个搜索点")
            self.assertEqual((m.state["SearchStage"], m.state["OP"]), (2, 2))

    def test_window_candidate_votes_and_auto_ties_ignore_last_outlier(self):
        request = TidRngRequest(mode=0, auto_rng=True, near_tid_hits=5, target_tid=33333,
                                additional_target_tids=(0,), include_65535=False, sid_random=True)
        m, p, _ = self.replay.setup_machine(request)
        for i, tid in enumerate((33334, 33350, 5, 6, 60000), 1):
            m.state[f"Slot{i}"] = tid
        m.state.update(ID=60000, denoise_try_count=5)
        m.call(p + "_检测目标区域")
        self.assertEqual(m.state["TID区域目标"], 0)  # equal counts; smaller total distance
        m.state["Slot6"] = 33340
        m.call(p + "_采用窗口候选")
        self.assertEqual(m.state["targetID"], 33333)  # more near samples beat one closer sample

    def test_asymmetric_boundary_keeps_all_executable_positive_points(self):
        for language in ("英文", "日文"):
            request = TidRngRequest(language=language, player_name="Alxe" if language == "英文" else "レット゛",
                                    sid_random=True, op_target_frame=fixed_frame(30600, "OP") + 4,
                                    op_fixed_delay=30600, op_rng_range=20)
            m, p, source = self.replay.setup_machine(request)
            self.assertEqual((m.state["OP_RNG_Min_Range"], m.state["OP_RNG_Max_Range"]), (4, 20))
            seen = []
            for _ in range(13):
                state = self.replay.state(m, p)
                validate_checkpoint(state, request)
                seen.append(state["OP"] - state["OP_RANGE"])
                m.call(p + "_计算操作延迟")
                self.assertGreaterEqual(m.state["OPms"], 0)
                fresh, _ = self.restore(request, source, state)
                fresh.call(p + "_乱数推进到下一个壳层组合")
                m.call(p + "_乱数推进到下一个壳层组合")
                self.assertEqual(self.replay.state(fresh, p), self.replay.state(m, p))
            self.assertEqual(set(seen), set(range(-4, 21, 2)))
            self.assertEqual(m.state["RNGRadius"], 0)

    def test_full_default_radius_has_4851_unique_points(self):
        request = TidRngRequest(sid_random=True, op_rng_range=20, f1_rng_range=20, f2_rng_range=10)
        m, p, _ = self.replay.setup_machine(request)
        seen = set()
        for _ in range(4851):
            seen.add(tuple(m.state[a] - m.state[a + "_RNG_Max_Range"] for a in ("OP", "F1", "F2")))
            m.call(p + "_乱数推进到下一个壳层组合")
        self.assertEqual(seen, set(product(range(-20,21,2), range(-20,21,2), range(-10,11,2))))
        self.assertEqual(m.state["RNGRadius"], 0)

    def test_local_sweep_returns_and_history_survives_resume(self):
        for language in ("英文", "日文"):
            request = TidRngRequest(language=language, player_name="Alxe" if language == "英文" else "レット゛",
                mode=0, auto_rng=True, sid_random=True, additional_target_tids=(33333,),
                auto_op_rng_range=4, auto_f1_rng_range=2, auto_f2_rng_range=2)
            m, p, source = self.replay.setup_machine(request, offset=4)
            m.state.update(TID区域目标=33333, SearchStage=1, Slot1=33334, denoise_try_count=1)
            m.call(p + "_自动转乱数")
            seen = set()
            for point in range(45):
                state = self.replay.state(m, p)
                validate_checkpoint(state, request)
                seen.add(tuple(state[a] for a in ("OP", "F1", "F2")))
                if point == 43:  # resume across the final point and return boundary
                    m, _ = self.restore(request, source, state)
                m.call(p + "_乱数推进到下一个壳层组合")
            self.assertEqual(len(seen), 45)
            self.assertEqual((m.state["ID_RNG"], m.state["SearchStage"], m.state["OP"], m.state["F1"], m.state["F2"]), (0, 2, 6, 4, 4))
            state = self.replay.state(m, p)
            validate_checkpoint(state, request)
            self.assertEqual(state["COMPLETED_REGIONS"], 1)
            self.assertEqual(state["H1_TARGET"], 33333)
            fresh, _ = self.restore(request, source, state)
            self.assertEqual(self.replay.state(fresh, p), state)
            fresh.state.update(Slot1=33334, Slot2=33335, Slot3=33336, denoise_try_count=3, ID=33336)
            fresh.call(p + "_检测目标区域")
            self.assertEqual(fresh.state["ID_RNG"], 0)  # covered center, same target
            fresh.state.update(Slot1=1, Slot2=2, Slot3=3, ID=3)
            fresh.call(p + "_检测目标区域")
            self.assertEqual(fresh.state[p + "_TARGET_TID"], 0)  # different target still eligible
            self.assertEqual(fresh.state["ID_RNG"], 1)
            for field, value in (("H1_TARGET", 12345), ("H1_OP", 1), ("HISTORY_SLOT", 2), ("RETURN_OP", 2)):
                with self.assertRaises(ValueError): validate_checkpoint({**state, field:value}, request)

    def test_op_recovery_does_not_mark_mixed_timing_as_completed(self):
        request = TidRngRequest(mode=0, auto_rng=True, sid_random=True, auto_op_rng_range=0,
                                auto_f1_rng_range=0, auto_f2_rng_range=0)
        m, p, _ = self.replay.setup_machine(request)
        m.call(p + "_自动转乱数")
        m.state["OP修正"] += 50
        m.state["OP固定"] += 50
        m.state["OP自动修正次数"] += 1
        m.call(p + "_乱数推进到下一个壳层组合")
        self.assertEqual(m.state["ID_RNG"], 0)
        self.assertEqual(m.state["TID完成区域数"], 0)
        validate_checkpoint(self.replay.state(m, p), request)

    def test_near_rng_observation_is_not_discarded_by_repeated_other_tid(self):
        request = TidRngRequest(sid_random=True, target_tid=0, op_rng_range=4)
        m, p, _ = self.replay.setup_machine(request)
        m.state.update(Slot1=3, Slot2=64594, Slot3=64594, ID=64594, denoise_try_count=3, denoise_hit_count=2)
        m.call(p + "_乱数模式偏移运算")
        self.assertEqual(m.state["OPSearchPos"], 0)
        m.state["denoise_try_count"] = 10
        m.call(p + "_乱数模式偏移运算")
        self.assertEqual(m.state["OPSearchPos"], 1)

    def test_history_wraps_at_sixteen_and_different_correction_is_not_suppressed(self):
        request = TidRngRequest(mode=0, auto_rng=True, sid_random=True, auto_op_rng_range=0,
                                auto_f1_rng_range=0, auto_f2_rng_range=0)
        m, p, source = self.replay.setup_machine(request, offset=0)
        for _ in range(17):
            m.state.update(Slot1=1, denoise_try_count=1, TID区域目标=0)
            m.call(p + "_自动转乱数")
            m.call(p + "_乱数推进到下一个壳层组合")
            validate_checkpoint(self.replay.state(m, p), request)
        state = self.replay.state(m, p)
        self.assertEqual((state["COMPLETED_REGIONS"], state["HISTORY_SLOT"]), (17, 1))
        m, _ = self.restore(request, source, state)
        m.state.update({a + "总帧": state["H1_" + a] for a in ("OP", "F1", "F2")})
        m.state["TID区域检测目标"] = 0
        m.call(p + "_当前区域已经搜索")
        self.assertEqual(m.state["TID区域已搜索"], 1)
        m.state["OP修正"] += 50
        m.call(p + "_当前区域已经搜索")
        self.assertEqual(m.state["TID区域已搜索"], 0)

    def test_sid_branch_and_padding_are_restored_after_every_local_sweep(self):
        for language in ("英文", "日文"):
            request = TidRngRequest(language=language, player_name="Alxe" if language == "英文" else "レット゛",
                mode=0, auto_rng=True, additional_target_tids=(33333,), f1_fixed_delay=21500,
                f2_fixed_delay=3450, select_correction=3, auto_op_rng_range=0, auto_f1_rng_range=0, auto_f2_rng_range=0)
            m, p, _ = self.replay.setup_machine(request)
            initial = {k:m.state[k] for k in ("F1脚本固定延迟", "F2脚本固定延迟", "F3脚本固定延迟",
                "F1脚本固定延迟补偿", "F2脚本固定延迟补偿", "same_id_switch", "continue_id_switch", "65535开关", "个位检测开关")}
            # Model both native SID helpers' outputs; their original bodies are
            # protected by the preservation test and native compiler checks.
            m.compiled[p + "_SID计算_奇"] = ([], lambda: m.state.update(Name_GREEN=1, adv=50001))
            m.compiled[p + "_SID计算_偶"] = ([], lambda: m.state.update(adv=50002))
            for target in (33333, 0):
                m.state["TID区域目标"] = target
                m.call(p + "_自动转乱数")
                self.assertEqual(m.state["Name_GREEN"], 1)
                self.assertEqual(m.state["F3脚本固定延迟"], request.f3_fixed_delay + (3750 if p == "EN" else 3210))
                m.call(p + "_乱数推进到下一个壳层组合")
                self.assertEqual({k:m.state[k] for k in initial}, initial)
                self.assertEqual(m.state["Name_GREEN"], 0)
                self.assertEqual(m.state[p + "_TARGET_TID"], request.target_tid)
                validate_checkpoint(self.replay.state(m, p), request)


if __name__ == "__main__":
    unittest.main()
