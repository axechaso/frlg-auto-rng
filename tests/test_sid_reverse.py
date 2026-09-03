import unittest

from rng.sid_reverse import (
    DEFAULT_TID_SID_SEARCH_ADVANCES,
    LCG_FULL_PERIOD,
    SID_ADV_COMPENSATION_BY_LANGUAGE,
    canonical_sid_for_psv,
    first_sid_advances,
    fixed_delay_to_frames,
    find_earliest_shiny_sid,
    PIDCandidate,
    parse_pid_hex,
    ShinyEvidence,
    intersect_candidate_psvs,
    is_shiny_for_ids,
    pid_to_psv,
    recover_pid_candidates,
    reverse_sid,
    sid_at_advance,
    sid_candidates_for_psv,
    sid_min_advances_for_f3,
)
from rng.tenlines import METHOD_1, METHOD_2, METHOD_4


class SIDReverseTests(unittest.TestCase):
    def test_parse_pid_hex_accepts_common_notations_and_rejects_overflow(self):
        self.assertEqual(parse_pid_hex("7942EF72"), 0x7942EF72)
        self.assertEqual(parse_pid_hex("0x7942ef72"), 0x7942EF72)
        self.assertEqual(parse_pid_hex("  1  "), 1)
        for value in ("", "0x", "100000000", "-1", "not-a-pid"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "PID"):
                    parse_pid_hex(value)

    def test_matches_pokefinder_method2_vector(self):
        candidates = recover_pid_candidates(
            (31, 31, 31, 0, 31, 31),
            nature=0,
        )
        match = [
            item
            for item in candidates
            if item.method == METHOD_2 and item.pid == 45092875
        ]
        self.assertEqual(len(match), 1)
        self.assertEqual(match[0].origin_seed, 921075850)

    def test_matches_second_pokefinder_method2_vector(self):
        candidates = recover_pid_candidates(
            (31, 31, 31, 31, 31, 31),
            nature=0,
        )
        match = [
            item
            for item in candidates
            if item.method == METHOD_2 and item.pid == 4017276575
        ]
        self.assertEqual(len(match), 1)
        self.assertEqual(match[0].origin_seed, 902592441)

    def test_sid_candidates_are_the_eight_valid_low_bit_variants(self):
        tid = 12345
        pid = 45092875
        psv = pid_to_psv(pid)
        candidates = sid_candidates_for_psv(tid, psv)
        self.assertEqual(len(candidates), 8)
        self.assertIn(8832, candidates)
        self.assertEqual(canonical_sid_for_psv(tid, psv), 8832)
        self.assertTrue(all(is_shiny_for_ids(pid, tid, sid) for sid in candidates))

    def test_sid_candidates_use_first_hit_in_first_10000_advances(self):
        candidates = sid_candidates_for_psv(12345, pid_to_psv(45092875))
        hits = first_sid_advances(12345, candidates)
        self.assertEqual(
            [(item.sid, item.advance) for item in hits],
            [(8832, 199), (8839, 8461)],
        )
        self.assertEqual(first_sid_advances(12345, candidates, max_advances=10), ())

    def test_sid_search_can_reserve_the_fixed_f3_frame_prefix(self):
        candidates = sid_candidates_for_psv(12345, pid_to_psv(45092875))
        hits = first_sid_advances(12345, candidates, min_advances=200)
        self.assertEqual(
            [(item.sid, item.advance) for item in hits], [(8839, 8461)]
        )
        hit = find_earliest_shiny_sid(12345, 45092875, min_advances=200)
        self.assertIsNotNone(hit)
        self.assertEqual((hit.sid, hit.advance), (8839, 8461))
        with self.assertRaisesRegex(ValueError, "non-negative"):
            first_sid_advances(12345, candidates, min_advances=-1)

    def test_fixed_delay_to_frames_matches_tid_ecs_rounding(self):
        self.assertEqual(fixed_delay_to_frames(0), 0)
        self.assertEqual(fixed_delay_to_frames(14900), 1789)
        self.assertEqual(fixed_delay_to_frames(15000), 1801)
        with self.assertRaisesRegex(ValueError, "非负整数"):
            fixed_delay_to_frames(-1)

    def test_sid_f3_lower_bound_includes_script_prefix_and_never_drops_below_f3(self):
        self.assertEqual(SID_ADV_COMPENSATION_BY_LANGUAGE, {"英文": 490, "日文": 380})
        self.assertEqual(sid_min_advances_for_f3(14900), 2279)
        self.assertEqual(sid_min_advances_for_f3(15950, language="日文"), 2295)
        self.assertEqual(
            sid_min_advances_for_f3(14900, sid_advance_correction=5), 2284
        )
        # A large negative correction must not violate the explicit F3 floor.
        self.assertEqual(
            sid_min_advances_for_f3(14900, sid_advance_correction=-5000), 1789
        )
        with self.assertRaisesRegex(ValueError, "英文或日文"):
            sid_min_advances_for_f3(14900, language="other")

    def test_sid_f3_lower_bound_matches_the_tid_script_executable_window(self):
        # This target's first raw hit (2022) is after the bare F3 floor (1789)
        # but still inside the 490-ADV English script prefix.  The button must
        # skip it and choose the next executable SID candidate.
        pid = parse_pid_hex("7942EF72")
        minimum = sid_min_advances_for_f3(14900, language="英文")
        hit = find_earliest_shiny_sid(
            24, pid, min_advances=minimum, max_advances=100_000
        )
        self.assertEqual((hit.sid, hit.advance), (38441, 8862))

    def test_unbounded_shiny_sid_search_can_reach_past_10000_advances(self):
        pid = parse_pid_hex("7942EF72")
        candidates = sid_candidates_for_psv(1, pid_to_psv(pid))
        self.assertEqual(first_sid_advances(1, candidates, max_advances=10_000), ())
        self.assertEqual(DEFAULT_TID_SID_SEARCH_ADVANCES, 1_000_000)
        hit = find_earliest_shiny_sid(1, pid)
        self.assertEqual((hit.sid, hit.advance), (38449, 18_135))
        self.assertEqual(sid_at_advance(1, hit.advance), hit.sid)
        self.assertTrue(is_shiny_for_ids(pid, 1, hit.sid))

    def test_sid_at_advance_uses_same_zero_based_convention_as_search(self):
        self.assertEqual(sid_at_advance(12345, 199), 8832)
        self.assertEqual(sid_at_advance(12345, 8461), 8839)
        self.assertEqual(first_sid_advances(12345, (), max_advances=None), ())
        # ADV 2**32 - 1 is the last result before the LCG returns to its
        # initial state; the next ADV therefore repeats ADV 0.
        self.assertEqual(
            sid_at_advance(12345, LCG_FULL_PERIOD - 1),
            0,
        )
        self.assertEqual(
            sid_at_advance(12345, LCG_FULL_PERIOD),
            sid_at_advance(12345, 0),
        )
        with self.assertRaisesRegex(ValueError, "non-negative"):
            sid_at_advance(12345, -1)

    def test_multiple_pokemon_intersect_psv_not_pid(self):
        first = PIDCandidate(0x12345678, METHOD_1, 0, (0, 0, 0, 0, 0, 0))
        same_psv = PIDCandidate(0x56781234, METHOD_4, 1, (1, 1, 1, 1, 1, 1))
        other = PIDCandidate(0x11112222, METHOD_2, 2, (2, 2, 2, 2, 2, 2))
        evidence = (
            ShinyEvidence(1, (first, other)),
            ShinyEvidence(2, (same_psv,)),
        )
        self.assertEqual(intersect_candidate_psvs(evidence), (first.psv,))
        result = reverse_sid(54321, evidence)
        self.assertTrue(result.psv_is_unique)
        self.assertEqual(len(result.sid_candidates), 8)
        self.assertEqual(result.selected_sid, result.sid_advances[0].sid)

    def test_empty_intersection_is_reported(self):
        first = PIDCandidate(0x00000000, METHOD_1, 0, (0, 0, 0, 0, 0, 0))
        second = PIDCandidate(0x00000008, METHOD_1, 0, (0, 0, 0, 0, 0, 0))
        result = reverse_sid(
            1,
            (ShinyEvidence(1, (first,)), ShinyEvidence(2, (second,))),
        )
        self.assertEqual(result.common_psvs, ())
        self.assertEqual(result.sid_candidates, ())
        self.assertEqual(result.sid_advances, ())


if __name__ == "__main__":
    unittest.main()
