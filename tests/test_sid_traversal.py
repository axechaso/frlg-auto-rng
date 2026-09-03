import json
import tempfile
import unittest
from pathlib import Path

from rng.sid_reverse import sid_at_advance
from run_sid_traversal import traversal_candidate_request
from sid_traversal import (
    DEFAULT_START_ADVANCE,
    NAMED_RIVAL_START_ADVANCE,
    SID_ADVANCE_STEP,
    SIDTraversalSession,
    progress_path,
    read_progress,
    sid_traversal_start_advance,
    traversal_context,
)


def make_context(*, named=False, max_advances=2000, target_max_advances=3000):
    return traversal_context(
        tid=12345,
        named_rival=named,
        wild_request={
            "game": "fr_nx",
            "method": "All Wild Methods",
            "location": "Viridian Forest",
            "pokemon": "Pikachu",
        },
        easycon_options={"seed_startup_scheme": 0, "item_rng_mode": False},
        source_sha256="0" * 64,
        max_advances=max_advances,
        target_max_advances=target_max_advances,
    )


class SIDTraversalProgressTests(unittest.TestCase):
    def test_candidate_search_preserves_the_requested_minimum_advance(self):
        from automation.planner import AutoSearchRequest

        request = AutoSearchRequest(
            game="fr_nx",
            tid=12345,
            sid=0,
            method="Wild",
            category="Grass",
            location="Viridian Forest",
            pokemon="Pikachu",
            min_advances=500,
            max_advances=6500,
        )
        candidate = traversal_candidate_request(request, 4567, target_max_advances=3000)
        self.assertEqual(candidate.min_advances, 500)
        self.assertEqual(candidate.max_advances, 3000)
        with self.assertRaisesRegex(ValueError, "下限不能大于上限"):
            traversal_candidate_request(request, 4567, target_max_advances=499)

    def test_start_depends_on_rival_name(self):
        self.assertEqual(sid_traversal_start_advance(False), DEFAULT_START_ADVANCE)
        self.assertEqual(sid_traversal_start_advance(True), NAMED_RIVAL_START_ADVANCE)
        self.assertEqual(sid_traversal_start_advance(False, 2451), 2451)
        self.assertEqual(sid_traversal_start_advance(True, 2450), 2450)
        with self.assertRaisesRegex(ValueError, "奇数"):
            sid_traversal_start_advance(False, 2450)
        with self.assertRaisesRegex(ValueError, "偶数"):
            sid_traversal_start_advance(True, 2451)

    def test_custom_start_is_part_of_context_identity(self):
        self.assertNotEqual(
            make_context(),
            traversal_context(
                tid=12345,
                named_rival=False,
                wild_request=make_context()["wild_request"],
                easycon_options=make_context()["easycon_options"],
                source_sha256="0" * 64,
                max_advances=2000,
                start_advance=1951,
            ),
        )

    def test_target_search_bound_is_part_of_context_identity(self):
        self.assertNotEqual(
            make_context(target_max_advances=3000),
            make_context(target_max_advances=3500),
        )

    def test_interrupted_candidate_is_retried(self):
        with tempfile.TemporaryDirectory() as tmp:
            context = make_context()
            with SIDTraversalSession(tmp, context) as session:
                sid = session.begin_candidate(DEFAULT_START_ADVANCE)
                self.assertEqual(sid, sid_at_advance(12345, DEFAULT_START_ADVANCE))
                session.pause("stop-file")
            with SIDTraversalSession(tmp, context) as resumed:
                self.assertEqual(resumed.next_sid_advance, DEFAULT_START_ADVANCE)
                self.assertEqual(resumed.current_sid_advance, DEFAULT_START_ADVANCE)
                self.assertEqual(resumed.state["attempt_count"], 1)

    def test_only_confirmed_non_shiny_completion_advances(self):
        with tempfile.TemporaryDirectory() as tmp:
            context = make_context()
            with SIDTraversalSession(tmp, context) as session:
                session.begin_candidate(DEFAULT_START_ADVANCE)
                self.assertEqual(session.complete_non_shiny(), DEFAULT_START_ADVANCE + SID_ADVANCE_STEP)
            payload = read_progress(tmp, context)
            self.assertEqual(payload["state"]["next_sid_advance"], DEFAULT_START_ADVANCE + SID_ADVANCE_STEP)
            self.assertIsNone(payload["state"]["current_sid_advance"])

    def test_context_round_trip_normalizes_tuple_values(self):
        context = make_context()
        loaded_shape = json.loads(json.dumps(context, ensure_ascii=False))
        self.assertEqual(loaded_shape, context)
        self.assertEqual(progress_path("progress", context), progress_path("progress", loaded_shape))

    def test_last_inclusive_candidate_can_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            context = make_context(max_advances=DEFAULT_START_ADVANCE)
            with SIDTraversalSession(tmp, context) as session:
                session.begin_candidate(DEFAULT_START_ADVANCE)
                self.assertEqual(session.complete_non_shiny(), DEFAULT_START_ADVANCE + SID_ADVANCE_STEP)
                self.assertEqual(session.state["status"], "exhausted")

    def test_paused_candidate_resumes_after_previous_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            context = make_context(max_advances=DEFAULT_START_ADVANCE + 2)
            with SIDTraversalSession(tmp, context) as session:
                session.begin_candidate(DEFAULT_START_ADVANCE)
                session.complete_non_shiny()
                session.begin_candidate(DEFAULT_START_ADVANCE + SID_ADVANCE_STEP)
                session.pause("stop-file")
            with SIDTraversalSession(tmp, context) as resumed:
                self.assertEqual(resumed.next_sid_advance, DEFAULT_START_ADVANCE + SID_ADVANCE_STEP)
                self.assertEqual(resumed.current_sid_advance, DEFAULT_START_ADVANCE + SID_ADVANCE_STEP)
                self.assertEqual(resumed.state["attempt_count"], 2)

    def test_context_records_the_route_parity_and_two_advance_step(self):
        unnamed = make_context(named=False)
        named = make_context(named=True)
        self.assertEqual(unnamed["sid_advance_parity"], 1)
        self.assertEqual(named["sid_advance_parity"], 0)
        self.assertEqual(unnamed["sid_advance_step"], SID_ADVANCE_STEP)
        self.assertNotEqual(unnamed, named)

    def test_progress_rejects_the_other_sid_parity(self):
        with tempfile.TemporaryDirectory() as tmp:
            context = make_context()
            with SIDTraversalSession(tmp, context) as session:
                session.begin_candidate(DEFAULT_START_ADVANCE)
            path = progress_path(tmp, context)
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
            payload["state"]["next_sid_advance"] = DEFAULT_START_ADVANCE + 1
            Path(path).write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "奇偶"):
                read_progress(tmp, context)

    def test_context_isolation_and_atomic_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = make_context()
            second = make_context(named=True)
            self.assertNotEqual(progress_path(tmp, first), progress_path(tmp, second))
            with SIDTraversalSession(tmp, first) as session:
                session.begin_candidate(DEFAULT_START_ADVANCE)
            path = progress_path(tmp, first)
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
            self.assertEqual(payload["context"], first)
            self.assertEqual(payload["state"]["current_sid"], sid_at_advance(12345, DEFAULT_START_ADVANCE))

    def test_completed_hit_does_not_resume_at_next_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            context = make_context()
            with SIDTraversalSession(tmp, context) as session:
                session.begin_candidate(DEFAULT_START_ADVANCE)
                session.hit()
            with SIDTraversalSession(tmp, context) as resumed:
                self.assertTrue(resumed.completed)
                self.assertEqual(resumed.state["hit_sid_advance"], DEFAULT_START_ADVANCE)
                self.assertEqual(resumed.state["hit_sid"], sid_at_advance(12345, DEFAULT_START_ADVANCE))


if __name__ == "__main__":
    unittest.main()
