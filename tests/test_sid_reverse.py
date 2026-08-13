import unittest

from rng.sid_reverse import (
    canonical_sid_for_psv,
    first_sid_advances,
    PIDCandidate,
    ShinyEvidence,
    intersect_candidate_psvs,
    is_shiny_for_ids,
    pid_to_psv,
    recover_pid_candidates,
    reverse_sid,
    sid_candidates_for_psv,
)
from rng.tenlines import METHOD_1, METHOD_2, METHOD_4


class SIDReverseTests(unittest.TestCase):
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
