"""Context-safe, incremental history replay for TID progress (no hardware)."""
from dataclasses import replace
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from automation.tid_checkpoint import CHECKPOINT_V3_PREFIX, DONE_MARKER, SEARCH_STATE_VARIABLES, validate_checkpoint
from automation.tid_rng137 import TidRngRequest
from tid_progress_logs import TidProgressLogReader, recover_log_progress
from tid_session import progress_context, progress_lease, progress_path, read_progress, write_json_atomic


def state_for(request, *, count=25, op=4):
    state = dict.fromkeys(SEARCH_STATE_VARIABLES, 0)
    state.update({key: -1 for key in state if key.startswith("H") and key.endswith("_TARGET")})
    state.update(MODE=0, TARGET=request.target_tid, OP=op, F1=6, F2=8, STAGE=2, COUNT=count,
        OP_CORRECTION=request.op_correction,
        OP_FIXED=(30550 if request.language == "英文" else 30600) + request.op_correction
                 - (750 if request.nx_model == 2 else 0),
        HOME=request.home_buffer_delay, CLOSE=request.close_game_delay)
    for axis in ("OP", "F1", "F2"):
        state[axis + "_CENTER"] = getattr(request, axis.lower() + "_target_frame")
        state[axis + "_RANGE"] = getattr(request, axis.lower() + "_rng_range")
    return validate_checkpoint(state, request)


def state_line(state):
    return CHECKPOINT_V3_PREFIX + "|".join(f"{key}={state[key]}" for key in SEARCH_STATE_VARIABLES) + "|END=1"


class TidProgressLogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.output = self.root / "runtime" / "pyside6"
        self.user = self.root / "user"
        self.directory = self.user / "tid_progress"
        self.request = TidRngRequest(mode=0)
        self.context = progress_context(self.request, "火红", "a" * 64)
        self.state = state_for(self.request)
        self.reader = TidProgressLogReader()
        self.path = self.output / ("tid-" + "1" * 32) / "run-test.log"
        self.path.parent.mkdir(parents=True)

    def tearDown(self):
        self.temp.cleanup()

    def scope(self, context=None):
        # Only the context hash is portable across installation/user paths.
        key = progress_path(self.directory, context or self.context).stem
        return f"[TID进度] C:\\old-user\\tid_progress\\{key}.json\n"

    def write(self, text, *, path=None):
        (path or self.path).write_text(text, encoding="utf-8")

    def scan(self, contexts=None, **kwargs):
        return self.reader.scan(self.output, self.user, tuple(contexts or [self.context]), **kwargs)

    def record(self, *, completed=False):
        self.write(self.scope() + state_line(self.state) + "\n" + (DONE_MARKER + "\n" if completed else ""))
        return self.scan()[0]

    def saved(self, *, state=None, status="paused", updated="1970-01-01T00:00:00+00:00"):
        payload = {"schema": 1, "context": self.context, "state": state,
                   "status": status, "updated_at": updated}
        path = progress_path(self.directory, self.context)
        write_json_atomic(path, payload)
        return path

    def test_coloured_log_restores_full_state_without_changing_log(self):
        self.write("\x1b[90m" + self.scope().rstrip() + "\x1b[0m\n" +
                   "\x1b[90m[12:00]\x1b[0m " + state_line(self.state) + "\x1b[0m\n")
        original = self.path.read_bytes()
        record, = self.scan()
        self.assertEqual(record.state, self.state)
        self.assertTrue(recover_log_progress(self.directory, record))
        self.assertEqual(read_progress(self.directory, self.context)["state"], self.state)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(read_progress(self.directory, self.context)["source_log"], str(self.path))

    def test_no_scope_or_plain_human_parameters_are_never_replayed(self):
        self.write(state_line(self.state) + "\nOP/F1/F2: 4/6/8\n")
        self.assertEqual(self.scan(), ())
        self.write(self.scope() + "OP/F1/F2: 4/6/8\n")
        self.assertEqual(self.scan(), ())

    def test_different_game_model_language_template_and_request_are_isolated(self):
        self.record()
        contexts = [progress_context(self.request, "叶绿", "a" * 64),
            progress_context(replace(self.request, nx_model=2), "火红", "a" * 64),
            progress_context(replace(self.request, language="日文"), "火红", "a" * 64),
            progress_context(replace(self.request, target_tid=33333), "火红", "a" * 64),
            progress_context(self.request, "火红", "b" * 64),
            progress_context(self.request, "火红", "a" * 64, {"accept_any_tid": True})]
        self.assertEqual(self.scan(contexts), ())
        self.assertEqual(self.scan()[0].state, self.state)

    def test_other_stage_cannot_complete_or_update_tid_progress(self):
        other = state_for(self.request, count=99, op=10)
        self.write(self.scope() + "========== 第1阶段：TID ==========" + "\n" + state_line(self.state) +
                   "\n========== 第2阶段：研究所 ==========" + "\n" + state_line(other) + "\n" + DONE_MARKER + "\n")
        record, = self.scan()
        self.assertEqual(record.state, self.state)
        self.assertFalse(record.completed)

    def test_multiple_sid_attempt_scopes_do_not_mix(self):
        retry = progress_context(replace(self.request, sid_advance_correction=-2), "火红", "a" * 64)
        new = state_for(self.request, count=3, op=8)
        self.write(self.scope() + state_line(self.state) + "\n" + DONE_MARKER + "\n" +
                   self.scope(retry) + state_line(new) + "\n")
        records = {progress_path(self.directory, r.context).stem: r for r in self.scan([self.context, retry])}
        self.assertTrue(records[progress_path(self.directory, self.context).stem].completed)
        self.assertEqual(records[progress_path(self.directory, retry).stem].state, new)
        self.assertFalse(records[progress_path(self.directory, retry).stem].completed)

    def test_new_scope_resets_done_and_repeated_point_counts(self):
        new = state_for(self.request, count=1, op=0)
        self.write(self.scope() + state_line(self.state) + "\n" + DONE_MARKER + "\n" +
                   self.scope() + state_line(new) + "\n")
        record, = self.scan()
        self.assertEqual(record.state, new)
        self.assertFalse(record.completed)

    def test_trailing_half_line_is_only_accepted_after_newline_arrives(self):
        self.write(self.scope() + state_line(self.state))
        self.assertEqual(self.scan(), ())
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write("\n")
        self.assertEqual(self.scan()[0].state, self.state)

    def test_append_reads_only_new_bytes_and_retains_last_valid_checkpoint(self):
        self.record()
        new = state_for(self.request, count=26, op=6)
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(state_line(new) + "\n" + state_line({**new, "OP": 7}) + "\n")
        self.assertEqual(self.scan()[0].state, new)
        with patch.object(Path, "open", side_effect=AssertionError("unchanged log reread")):
            self.assertEqual(self.scan()[0].state, new)

    def test_truncation_does_not_leave_an_old_cached_position(self):
        self.record()
        self.write("empty replacement\n")
        self.assertEqual(self.scan(), ())

    def test_oversized_line_is_ignored_as_a_whole(self):
        self.write(self.scope() + "x" * (128 * 1024) + state_line(self.state) + "\n")
        self.assertEqual(self.scan(), ())
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(state_line(self.state) + "\n")
        self.assertEqual(self.scan()[0].state, self.state)

    def test_archived_log_is_discovered_and_latest_matching_log_wins(self):
        self.record()
        os.utime(self.path, ns=(1_000_000_000, 1_000_000_000))
        archived = self.user / "logs" / "generated-plans" / ("tid-" + "2" * 32) / "run-old.log"
        archived.parent.mkdir(parents=True)
        new = state_for(self.request, count=40, op=10)
        self.write(self.scope() + state_line(new) + "\n", path=archived)
        reader = TidProgressLogReader()
        record, = reader.scan(self.output, self.user, (self.context,))
        self.assertEqual(record.state, new)
        self.assertEqual(record.log_path, archived)

    def test_current_run_is_read_without_waiting_for_discovery_cache(self):
        self.assertEqual(self.scan(), ())
        new_path = self.output / ("tid-" + "3" * 32) / "run-new.log"
        new_path.parent.mkdir(parents=True)
        self.write(self.scope() + state_line(self.state) + "\n", path=new_path)
        self.assertEqual(self.scan(extra_logs=(new_path,))[0].state, self.state)

    def test_cancelled_scan_never_returns_partial_candidates(self):
        self.record()
        self.assertEqual(self.scan(cancelled=lambda: True), ())

    def test_incomplete_or_old_schema_checkpoints_are_not_upgraded(self):
        from automation.tid_checkpoint import CHECKPOINT_PREFIX, STATE_VARIABLES
        old = CHECKPOINT_PREFIX + "|".join(f"{key}={self.state[key]}" for key in STATE_VARIABLES) + "|END=1\n"
        self.write(self.scope() + old + state_line(self.state).replace("|END=1", "") + "\n")
        self.assertEqual(self.scan(), ())

    def test_last_completed_scope_without_a_state_does_not_claim_success(self):
        self.write(self.scope() + DONE_MARKER + "\n")
        self.assertEqual(self.scan(), ())

    def test_completed_log_marks_completed_and_will_not_resume(self):
        self.assertTrue(recover_log_progress(self.directory, self.record(completed=True)))
        self.assertEqual(read_progress(self.directory, self.context)["status"], "completed")

    def test_current_worker_lease_prevents_gui_overwrite(self):
        record = self.record()
        path = self.saved(state=self.state, status="running")
        original = path.read_bytes()
        with progress_lease(path.with_suffix(".lock")):
            self.assertFalse(recover_log_progress(self.directory, record))
        self.assertEqual(path.read_bytes(), original)

    def test_corrupt_json_is_preserved_even_with_valid_log(self):
        record = self.record()
        path = progress_path(self.directory, self.context)
        path.parent.mkdir(parents=True)
        path.write_text("broken", encoding="utf-8")
        with self.assertRaises(ValueError):
            recover_log_progress(self.directory, record)
        self.assertEqual(path.read_text(), "broken")

    def test_fresh_empty_and_completed_files_are_authoritative(self):
        record = self.record()
        for state, status in ((None, "paused"), (self.state, "completed")):
            path = self.saved(state=state, status=status)
            original = path.read_bytes()
            self.assertFalse(recover_log_progress(self.directory, record))
            self.assertEqual(path.read_bytes(), original)

    def test_log_can_advance_a_stale_checkpoint_but_never_move_it_back(self):
        record = self.record()
        self.saved(state=state_for(self.request, count=24, op=2))
        self.assertTrue(recover_log_progress(self.directory, record))
        path = self.saved(state=state_for(self.request, count=30, op=8))
        original = path.read_bytes()
        self.assertFalse(recover_log_progress(self.directory, record))
        self.assertEqual(path.read_bytes(), original)

    def test_newer_json_and_equal_count_conflicts_are_not_overwritten(self):
        record = self.record()
        for state, updated in ((state_for(self.request, count=24), "2999-01-01T00:00:00+00:00"),
                               (state_for(self.request, op=8), "1970-01-01T00:00:00+00:00")):
            path = self.saved(state=state, updated=updated)
            original = path.read_bytes()
            self.assertFalse(recover_log_progress(self.directory, record))
            self.assertEqual(path.read_bytes(), original)

    def test_done_can_complete_an_equal_state_without_advancing_position(self):
        record = self.record(completed=True)
        self.saved(state=self.state)
        self.assertTrue(recover_log_progress(self.directory, record))
        self.assertEqual(read_progress(self.directory, self.context)["state"], self.state)
        self.assertEqual(read_progress(self.directory, self.context)["status"], "completed")


if __name__ == "__main__":
    unittest.main()
