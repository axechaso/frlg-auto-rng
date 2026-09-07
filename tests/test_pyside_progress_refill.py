"""Refilling the visible position must not rebase a resumable TID search."""
import importlib.util
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from automation.tid_checkpoint import SEARCH_STATE_VARIABLES, _exhaustive_start, fixed_frame, validate_checkpoint
from pyside_app.services import AppPaths
from tid_session import progress_path, read_progress, write_json_atomic


@unittest.skipUnless(importlib.util.find_spec("PySide6"), "PySide6 is optional")
class ProgressRefillTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(["refill-tests", "-platform", "offscreen"])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.template = self.root / "template.ecs"
        self.template.write_text("checkpoint identity fixture", encoding="utf-8")
        self.resolve = patch("pyside_app.tid_state.resolve_tid_template", return_value=self.template)
        self.resolve.start()
        self.open_window()
        self.w.tid_flow_check.setChecked(False)
        self.w.fields["tid_mode"].setCurrentIndex(1)
        self.w.fields["tid_sid_mode"].setCurrentIndex(1)

    def open_window(self):
        from pyside_app.migration import CompleteWindow
        self.w = CompleteWindow(paths=AppPaths(user=self.root, output=self.root / "runtime"), auto_detect=False)
        self.w.select_page("tid")

    def close_window(self):
        self.w.close()
        self.w.deleteLater()
        self.app.processEvents()

    def tearDown(self):
        self.w.running = False
        self.w.job = None
        self.close_window()
        self.resolve.stop()
        self.temp.cleanup()

    def starts(self):
        return {axis: self.w.fields[f"tid_{axis}_start"].text() for axis in ("op", "f1", "f2")}

    def checkpoint(self, *, switched=False, completed=False, sid_offset=0):
        request, _, context = self.w.tid_state._context(self.w.reader.tid())
        if sid_offset:
            request = replace(request, sid_advance_correction=request.sid_advance_correction + sid_offset)
            context = {**context, "request": request.to_dict()}
        state = {key: 0 for key in SEARCH_STATE_VARIABLES}
        for key in state:
            if key.startswith("H") and key.endswith("_TARGET"):
                state[key] = -1
        state.update(MODE=1 if switched else request.mode, SWITCHED=int(switched), TARGET=request.target_tid,
            STAGE=1, COUNT=123, OP_CORRECTION=request.op_correction,
            OP_FIXED=(30550 if request.language == "英文" else 30600) + request.op_correction - (750 if request.nx_model == 2 else 0),
            HOME=request.home_buffer_delay, CLOSE=request.close_game_delay)
        for axis, offset in zip(("OP", "F1", "F2"), (4, 6, 8)):
            low = axis.lower()
            if switched or request.mode == 1:
                delay = getattr(request, low + "_fixed_delay") + (request.select_correction * 600 if axis == "F2" else 0)
                center = _exhaustive_start(request, axis) + offset if switched else max(
                    fixed_frame(delay, axis), getattr(request, low + "_target_frame"))
                radius = getattr(request, ("auto_" if switched else "") + low + "_rng_range")
                state.update({axis: radius, axis + "_CENTER": center, axis + "_RANGE": radius,
                    axis + "_NEG": min(radius, center - fixed_frame(delay, axis)) // 2 * 2})
                if switched:
                    state["RETURN_" + axis] = offset
            else:
                state.update({axis: offset, axis + "_CENTER": getattr(request, low + "_target_frame"),
                    axis + "_RANGE": getattr(request, low + "_rng_range")})
        if switched:
            state.update(RETURN_STAGE=1, LOCAL_CORRECTION=request.op_correction)
            # Current local OP is center + 2; its exhaustive return position is center.
            state["OP"] += 2
            state.update(OP_POS=1, RADIUS=2)
        validate_checkpoint(state, request)
        path = progress_path(self.root / "tid_progress", context)
        write_json_atomic(path, {"schema": 1, "context": context, "status": "completed" if completed else "paused",
            "state": state, "updated_at": "2026-09-06T04:00:00+00:00"})
        return request, context, state, path

    def test_refill_preserves_worker_origin_repeat_refresh_and_reopen(self):
        self.w.fields["tid_op_start"].setText("4000")
        self.w.fields["tid_select"].setText("3")
        request, context, state, path = self.checkpoint()
        original_file = path.read_bytes()
        before = self.w.collect_workflow().fingerprint()
        expected = {axis.lower(): str(_exhaustive_start(request, axis) + state[axis]) for axis in ("OP", "F1", "F2")}
        self.w.tid_state.refresh_progress(fill_starts=True)
        self.assertEqual(self.starts(), expected)
        self.assertEqual(self.w.reader.tid(), request)
        self.assertEqual(self.w.collect_workflow().fingerprint(), before)
        self.w.tid_state.refresh_progress(fill_starts=True)
        self.assertEqual(self.starts(), expected)
        draft = json.loads((self.root / "tid_settings.json").read_text(encoding="utf-8"))
        self.assertEqual(draft["values"]["tid_op_start_var"], "4000")
        self.assertEqual(draft["qt_progress_refill"]["displayed_starts"], expected)
        self.close_window()
        self.open_window()
        self.assertEqual(self.starts(), expected)
        self.assertEqual(self.w.reader.tid(), request)
        self.assertIn("存在同参数进度", self.w.tid_progress_status.text())
        self.assertEqual(read_progress(self.root / "tid_progress", context)["state"], state)
        self.assertEqual(path.read_bytes(), original_file)

    def test_switched_progress_refills_return_center_not_local_offset(self):
        self.w.tid_auto_rng_check.setChecked(True)
        request, context, state, path = self.checkpoint(switched=True)
        self.w.tid_state.refresh_progress(fill_starts=True)
        self.assertEqual(self.starts(), {a.lower(): str(state[a + "_CENTER"]) for a in ("OP", "F1", "F2")})
        self.assertEqual(self.w.reader.tid(), request)
        self.assertEqual(read_progress(self.root / "tid_progress", context)["state"], state)

    def test_background_refresh_and_busy_windows_do_not_change_inputs(self):
        self.checkpoint()
        original = self.starts()
        self.w.tid_state.refresh_progress()
        self.w.tid_state.save()
        self.assertEqual(self.starts(), original)
        self.w.running = True
        self.w.tid_state.refresh_progress(fill_starts=True)
        self.assertEqual(self.starts(), original)
        self.w.running = False
        self.w.job = object()
        self.w.tid_state.refresh_progress(fill_starts=True)
        self.assertEqual(self.starts(), original)
        self.w.job = None

    def test_missing_completed_and_invalid_progress_do_not_refill(self):
        original = self.starts()
        self.w.tid_state.refresh_progress(fill_starts=True)
        self.assertEqual(self.starts(), original)
        _, _, _, path = self.checkpoint(completed=True)
        self.w.tid_state.refresh_progress(fill_starts=True)
        self.assertEqual(self.starts(), original)
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["status"] = "paused"
        payload["state"]["OP"] = 999999
        write_json_atomic(path, payload)
        self.w.tid_state.refresh_progress(fill_starts=True)
        self.assertEqual(self.starts(), original)
        self.assertIn("暂不能匹配进度", self.w.tid_progress_status.text())

    def test_manual_edit_or_changed_identity_removes_origin_binding(self):
        self.checkpoint()
        self.w.tid_state.refresh_progress(fill_starts=True)
        shown = self.starts()
        self.w.fields["tid_f1_start"].setText("3000")
        actual = self.w.reader.tid()
        self.assertEqual(actual.f1_start, 3000)
        self.assertEqual(actual.op_start, int(shown["op"]))
        self.assertIsNone(self.w.tid_state.refill)
        self.checkpoint()
        self.w.tid_state.refresh_progress(fill_starts=True)
        shown = self.starts()
        self.w.fields["tid_target"].setText("00007")
        self.assertEqual(self.w.reader.tid().op_start, int(shown["op"]))
        self.assertIsNone(self.w.tid_state.refill)

    def test_disabling_resume_uses_the_visible_filled_start(self):
        self.checkpoint()
        self.w.tid_state.refresh_progress(fill_starts=True)
        shown = self.starts()
        self.w.tid_resume_check.setChecked(False)
        self.assertEqual(self.w.reader.tid().op_start, int(shown["op"]))
        self.w.tid_state.save()
        draft = json.loads((self.root / "tid_settings.json").read_text(encoding="utf-8"))
        self.assertNotIn("qt_progress_refill", draft)
        self.assertEqual(draft["values"]["tid_op_start_var"], shown["op"])

    def test_resume_toggle_clears_binding_before_the_autosave_delay(self):
        self.checkpoint()
        self.w.tid_state.refresh_progress(fill_starts=True)
        shown = self.starts()
        self.w.tid_resume_check.setChecked(False)
        self.w.tid_resume_check.setChecked(True)
        self.assertIsNone(self.w.tid_state.refill)
        self.assertEqual(self.w.reader.tid().op_start, int(shown["op"]))

    def test_exhaustive_starter_flow_keeps_the_original_flow_context(self):
        self.w.tid_flow_check.setChecked(True)
        self.w.tid_any_check.setChecked(False)
        original = self.w.collect_workflow().fingerprint()
        self.checkpoint()
        self.w.tid_state.refresh_progress(fill_starts=True)
        self.assertIsNotNone(self.w.tid_state.refill)
        self.assertEqual(self.w.collect_workflow().fingerprint(), original)

    def test_manual_rng_sid_retry_does_not_fill_exhaustive_starts(self):
        self.w.fields["tid_mode"].setCurrentIndex(0)
        self.w.fields["tid_sid_mode"].setCurrentIndex(0)
        self.w.fields["tid_op_radius"].setText("20")
        self.w.tid_flow_check.setChecked(True)
        self.w.tid_any_check.setChecked(False)
        self.assertFalse(self.w.reader.flow(self.w.reader.tid()).deferred_identity)
        original = self.w.collect_workflow().fingerprint()
        shown = self.starts()
        self.checkpoint(sid_offset=1)
        self.w.tid_state.refresh_progress(fill_starts=True)
        self.assertEqual(self.starts(), shown)
        self.assertIsNone(self.w.tid_state.refill)
        self.assertIn("手动乱数进度", self.w.tid_progress_status.text())
        self.assertEqual(self.w.collect_workflow().fingerprint(), original)

    def test_changed_template_does_not_restore_old_display_binding(self):
        self.checkpoint()
        self.w.tid_state.refresh_progress(fill_starts=True)
        self.close_window()
        self.template.write_text("different template", encoding="utf-8")
        self.open_window()
        self.assertEqual(self.starts(), dict.fromkeys(("op", "f1", "f2"), "0"))
        self.assertIsNone(self.w.tid_state.refill)

    def test_confirmed_shiny_sid_correction_is_saved_as_the_next_base(self):
        log_path = self.root / "tid-flow.log"
        log_path.write_text(
            "[SID未命中] retry\n"
            "[流程完成] 已确认闪光御三家；成功使用SID ADV修正 -2。\n",
            encoding="utf-8",
        )
        apply_result = getattr(self.w.tid_state, "apply_successful_sid_correction", None)
        self.assertTrue(callable(apply_result))
        self.assertEqual(apply_result(log_path, 0), -2)
        self.assertEqual(self.w.fields["tid_sid_correction"].text(), "-2")
        saved = json.loads((self.root / "tid_settings.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["values"]["tid_sid_adv_correction_var"], "-2")

        self.close_window()
        self.open_window()
        self.assertEqual(self.w.fields["tid_sid_correction"].text(), "-2")

    def test_failed_flow_never_learns_sid_correction_even_if_log_contains_old_success(self):
        original = self.w.fields["tid_sid_correction"].text()
        log_path = self.root / "failed-tid-flow.log"
        log_path.write_text(
            "[流程完成] 已确认闪光御三家；成功使用SID ADV修正 +6。\n",
            encoding="utf-8",
        )
        apply_result = getattr(self.w.tid_state, "apply_successful_sid_correction", None)
        self.assertTrue(callable(apply_result))
        self.assertIsNone(apply_result(log_path, 5))
        self.assertEqual(self.w.fields["tid_sid_correction"].text(), original)


if __name__ == "__main__":
    unittest.main()
