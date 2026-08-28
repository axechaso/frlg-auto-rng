from dataclasses import replace
import io
import json
from pathlib import Path
import re
import tempfile
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

from automation.easycon118 import EasyConRuntimeCheck
from automation.tid_calibration import calibrated_tid_request
from automation.tid_checkpoint import (
    CHECKPOINT_PREFIX, DONE_MARKER, STATE_VARIABLES, instrument_tid_checkpoint,
    parse_checkpoint, validate_checkpoint,
)
from automation.tid_rng137 import TidRngRequest
from automation.tid_starter_save import _EN_MARKER, _JP_MARKER, _ID_END, split_tid_modules
from run_tid_starter_flow import FlowRunner, run_tid_plan
from tid_session import (
    TidProgressSession, load_tid_settings, progress_context, progress_path,
    read_progress, write_json_atomic,
)


def state_for(request, **changes):
    correction = request.op_correction + 100
    state = dict(OP=4, F1=6, F2=8, STAGE=2, COUNT=25,
        OP_CORRECTION=correction,
        OP_FIXED=(30550 if request.language == "英文" else 30600) + correction
                 + (0 if request.nx_model == 1 else -750),
        OP_RETRIES=2, HOME=1300, CLOSE=1600)
    return {**state, **changes}


def state_line(state):
    return CHECKPOINT_PREFIX + "|".join(f"{name}={state[name]}" for name in STATE_VARIABLES) + "|END=1"


def fixture():
    modules = []
    for marker, prefix in ((_EN_MARKER, "EN"), (_JP_MARKER, "JP")):
        modules.append(marker + f"\nIF 1 == 1\n$OP = 0\nFOR\n"
            f"    $select基础次数 = 0\n    CALL {prefix}_计算操作延迟\n"
            "    PRINT ========================\n    CALL TID_关闭游戏\n"
            "    FOR\n        BREAK 2\n    NEXT\nNEXT\n\nENDIF\n\n"
            f"FUNC {prefix}_识图\n    RETURN\nENDFUNC\n"
            f"FUNC {prefix}_计算操作延迟\n    RETURN\nENDFUNC\n")
    return "# globals\n" + "".join(modules) + _ID_END


class TidCheckpointTests(unittest.TestCase):
    def test_all_new_exhaustive_starts_are_zero(self):
        request = TidRngRequest()
        self.assertEqual((request.op_start, request.f1_start, request.f2_start), (0, 0, 0))

    def test_round_checkpoint_is_complete_and_coloured_log_compatible(self):
        request = TidRngRequest(mode=0)
        state = state_for(request)
        line = state_line(state)
        self.assertEqual(parse_checkpoint("\x1b[90m[12:00]\x1b[0m " + line + "\x1b[0m\n", request), state)
        self.assertIsNone(parse_checkpoint(line[:-5], request))
        self.assertIsNone(parse_checkpoint("OP:4 F1:6", request))
        for bad in (line.replace("F1=6|", ""), line.replace("STAGE=2", "STAGE=3"),
                    line.replace("OP=4", "OP=3"), line.replace("OP=4", "OP=602"),
                    line.replace("|END=1", "|OP=4|END=1")):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                parse_checkpoint(bad, request)

    def test_recovered_op_values_are_checked_for_language_and_model(self):
        for language in ("英文", "日文"):
            for model in (1, 2):
                request = TidRngRequest(mode=0, language=language, nx_model=model, op_correction=50)
                state = state_for(request)
                self.assertEqual(validate_checkpoint(state, request), state)
                for field in ("OP_FIXED", "OP_CORRECTION", "OP_RETRIES"):
                    with self.assertRaises(ValueError):
                        validate_checkpoint({**state, field: state[field] + 1}, request)

    def test_instrumentation_keeps_all_original_code_and_other_language(self):
        original = fixture()
        for language in ("英文", "日文"):
            request = TidRngRequest(mode=0, language=language)
            state = state_for(request)
            for resume in (None, state):
                generated = instrument_tid_checkpoint(original, request, resume)
                restored = re.sub(
                    r"(?ms)^[ \t]*# TID_CHECKPOINT_BEGIN\n.*?^[ \t]*# TID_CHECKPOINT_END\n", "", generated)
                self.assertEqual(restored, original)
                other = 2 if language == "英文" else 1
                self.assertEqual(split_tid_modules(generated)[other], split_tid_modules(original)[other])
                self.assertEqual(generated.count(CHECKPOINT_PREFIX), 1)
                self.assertEqual(generated.count(DONE_MARKER), 1)
                if resume:
                    self.assertIn("$SearchStage = 2", generated)
                    self.assertIn("$F2 = 8", generated)
                    self.assertNotIn("$Slot1 =", generated)
                    self.assertLess(generated.index("$SearchStage = 2"), generated.index(CHECKPOINT_PREFIX))
                with self.assertRaises(ValueError):
                    instrument_tid_checkpoint(generated, request)

    def test_no_silent_injection_into_rng_calibration_or_unknown_structure(self):
        for request in (TidRngRequest(), TidRngRequest(mode=0, calibration_check=True)):
            with self.assertRaises(ValueError):
                instrument_tid_checkpoint(fixture(), request)
        with self.assertRaises(ValueError):
            instrument_tid_checkpoint(fixture().replace("$select基础次数 = 0", "$select基础次数 = 1"), TidRngRequest(mode=0))


class TidPersistenceTests(unittest.TestCase):
    def test_settings_preserve_chinese_drafts_and_explicit_zero(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "settings.json"
            self.assertEqual(load_tid_settings(path), {})
            payload = {"schema": 1, "values": {"tid_name_var": "レット゛", "tid_op_start_var": "0",
                "tid_f1_start_var": "", "tid_resume_var": True}}
            write_json_atomic(path, payload)
            self.assertEqual(load_tid_settings(path), payload)
            self.assertEqual(list(Path(temp).glob("*.tmp")), [])

    def test_malformed_settings_are_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "settings.json"
            path.write_text("broken", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_tid_settings(path)
            self.assertEqual(path.read_text(encoding="utf-8"), "broken")

    def test_failed_atomic_write_preserves_previous_parameters(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "settings.json"
            write_json_atomic(path, {"old": 1})
            with patch.object(Path, "replace", side_effect=OSError("busy")):
                with self.assertRaises(OSError):
                    write_json_atomic(path, {"new": 2})
            self.assertEqual(json.loads(path.read_text()), {"old": 1})

    def test_context_separates_game_model_parameters_flow_and_script(self):
        request = TidRngRequest(mode=0)
        contexts = [progress_context(request, "火红", "a" * 64),
            progress_context(request, "叶绿", "a" * 64),
            progress_context(replace(request, nx_model=2), "火红", "a" * 64),
            progress_context(replace(request, target_tid=33333), "火红", "a" * 64),
            progress_context(request, "火红", "b" * 64),
            progress_context(request, "火红", "a" * 64, {"accept_any_tid": True})]
        self.assertEqual(len({progress_path(Path("test"), context) for context in contexts}), len(contexts))

    def test_stop_reopen_and_fresh_run(self):
        request = TidRngRequest(mode=0)
        context = progress_context(request, "火红", "a" * 64)
        state = state_for(request)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with TidProgressSession(root, context) as session:
                session.feed(state_line(state))
                self.assertEqual(read_progress(root, context)["state"], state)
                with self.assertRaises(RuntimeError):
                    with TidProgressSession(root, context):
                        pass
            self.assertEqual(read_progress(root, context)["status"], "paused")
            with TidProgressSession(root, context) as session:
                self.assertEqual(session.state, state)
                session.feed(state_line(state)[:-8])
                self.assertEqual(read_progress(root, context)["state"], state)
            with TidProgressSession(root, context, resume=False) as session:
                self.assertIsNone(session.state)

    def test_success_never_resumes_completed_search(self):
        request = TidRngRequest(mode=0)
        context = progress_context(request, "火红", "a" * 64)
        with tempfile.TemporaryDirectory() as temp:
            with TidProgressSession(Path(temp), context) as session:
                session.feed(state_line(state_for(request)))
                session.feed("[00:00] " + DONE_MARKER)
            self.assertEqual(read_progress(Path(temp), context)["status"], "completed")
            with TidProgressSession(Path(temp), context) as session:
                self.assertIsNone(session.state)

    def test_corrupt_resume_refuses_and_retains_file(self):
        request = TidRngRequest(mode=0)
        context = progress_context(request, "火红", "a" * 64)
        with tempfile.TemporaryDirectory() as temp:
            path = progress_path(Path(temp), context)
            path.write_text("broken", encoding="utf-8")
            with self.assertRaises(ValueError):
                with TidProgressSession(Path(temp), context):
                    pass
            self.assertEqual(path.read_text(), "broken")

    def test_worker_resumes_in_new_copy_and_preflights_without_overwriting_plan(self):
        request = TidRngRequest(mode=0)
        context = progress_context(request, "火红", "a" * 64)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plan = root / "plan"
            (plan / "ImgLabel").mkdir(parents=True)
            (plan / "main.ecs").write_text(fixture(), encoding="utf-8")
            write_json_atomic(plan / "plan.json", {"tid_request": request.to_dict(),
                "source_manifest": {"scripts": {"英文": {"sha256": "a" * 64}}}})
            with TidProgressSession(root / "progress", context) as session:
                session.feed(state_line(state_for(request)))
            runner = FlowRunner(Path("unused"), port="COM4", video_device=3, log=io.StringIO())
            runner.run_stage = Mock(return_value=130)
            with patch("run_tid_starter_flow.validate_tid_runtime", return_value=EasyConRuntimeCheck(True, (), ())) as check:
                code = run_tid_plan(runner, plan, Path("unused"), is_flow=False,
                    progress_dir=root / "progress", game="火红")
            self.assertEqual(code, 130)
            main = runner.run_stage.call_args.args[2]
            self.assertNotEqual(main, plan / "main.ecs")
            self.assertIn("$SearchStage = 2", main.read_text(encoding="utf-8"))
            self.assertEqual((plan / "main.ecs").read_text(encoding="utf-8"), fixture())
            check.assert_called_once_with(Path("unused"), main)

    def test_worker_does_not_feed_other_stages_into_progress(self):
        runner = FlowRunner(Path("unused"), port="COM4", video_device=3, log=io.StringIO())
        runner.progress = Mock()
        for stage in (0, 2, 3):
            runner.active_stage = stage
            runner.output(DONE_MARKER)
        runner.progress.feed.assert_not_called()
        runner.active_stage = 1
        runner.output(DONE_MARKER)
        runner.progress.feed.assert_called_once_with(DONE_MARKER)

    def test_preflight_failure_keeps_checkpoint_and_never_starts_game(self):
        request = TidRngRequest(mode=0)
        context = progress_context(request, "火红", "a" * 64)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plan = root / "plan"
            (plan / "ImgLabel").mkdir(parents=True)
            (plan / "main.ecs").write_text(fixture(), encoding="utf-8")
            write_json_atomic(plan / "plan.json", {"tid_request": request.to_dict(),
                "source_manifest": {"scripts": {"英文": {"sha256": "a" * 64}}}})
            state = state_for(request)
            with TidProgressSession(root / "progress", context) as session:
                session.feed(state_line(state))
            runner = FlowRunner(Path("unused"), port="COM4", video_device=3, log=io.StringIO())
            runner.run_stage = Mock()
            with patch("run_tid_starter_flow.validate_tid_runtime", return_value=EasyConRuntimeCheck(False, ("bad",), ())):
                code = run_tid_plan(runner, plan, Path("unused"), is_flow=False,
                    progress_dir=root / "progress", game="火红")
            self.assertEqual(code, 2)
            runner.run_stage.assert_not_called()
            self.assertEqual(read_progress(root / "progress", context)["state"], state)


class TidGuiPersistenceTests(unittest.TestCase):
    def app(self):
        from run_auto_rng_gui import AutoRngApp
        app = AutoRngApp.__new__(AutoRngApp)
        app.root = tk.Tcl()
        app.tid_name_var = tk.StringVar(app.root, "Alxe")
        app.tid_op_start_var = tk.StringVar(app.root, "0")
        app.tid_resume_var = tk.BooleanVar(app.root, True)
        app.tid_starter_flow_var = tk.BooleanVar(app.root, False)
        app.tid_progress_status_var = tk.StringVar(app.root, "")
        app.tid_record_filter_var = tk.StringVar(app.root, "12345")
        app._update_tid_flow_controls = Mock()
        app._restore_pending_tid_calibration = Mock()
        app._refresh_tid_progress = Mock()
        return app

    def test_reopening_restores_tid_inputs_but_not_record_filters(self):
        with tempfile.TemporaryDirectory() as temp, patch("run_auto_rng_gui.TID_SETTINGS_PATH", Path(temp) / "tid.json"):
            app = self.app()
            app._install_tid_persistence()
            app.tid_name_var.set("レット゛")
            app.tid_op_start_var.set("42")
            app.tid_resume_var.set(False)
            app._save_tid_settings()
            saved = load_tid_settings(Path(temp) / "tid.json")
            self.assertNotIn("tid_record_filter_var", saved["values"])
            reopened = self.app()
            reopened._install_tid_persistence()
            self.assertEqual(reopened.tid_name_var.get(), "レット゛")
            self.assertEqual(reopened.tid_op_start_var.get(), "42")
            self.assertFalse(reopened.tid_resume_var.get())

    def test_completed_background_calibration_is_loaded_on_reopen(self):
        from run_auto_rng_gui import AutoRngApp
        from tests.test_tid_calibration import VALUES
        with tempfile.TemporaryDirectory() as temp:
            app = self.app()
            initial = TidRngRequest(calibration_check=True)
            for name in ("tid_op_delay_var", "tid_f1_delay_var", "tid_f2_delay_var", "tid_f3_delay_var", "tid_op_correction_var"):
                setattr(app, name, tk.StringVar(app.root, "0"))
            app.tid_calibration_var = tk.BooleanVar(app.root, True)
            app.status_var = tk.StringVar(app.root, "")
            app.input_fingerprint = lambda: ("same",)
            app.invalidate_plan = Mock()
            path = Path(temp) / "calibration.json"
            updated = calibrated_tid_request(initial, VALUES)
            write_json_atomic(path, {"schema": 1, "initial_request": initial.to_dict(),
                "values": VALUES, "request": updated.to_dict()})
            app._tid_pending_calibration = {"path": str(path), "request": initial.to_dict(),
                "values": app._tid_settings_fingerprint()}
            AutoRngApp._restore_pending_tid_calibration(app)
            self.assertEqual(app.tid_op_delay_var.get(), str(updated.op_fixed_delay))
            self.assertEqual(app.tid_op_correction_var.get(), str(updated.op_correction))
            self.assertFalse(app.tid_calibration_var.get())
            self.assertIsNone(app._tid_pending_calibration)

    def test_closing_exhaustive_can_pause_keep_running_or_cancel(self):
        from run_auto_rng_gui import AutoRngApp
        for answer in (True, False, None):
            app = self.app()
            app.busy = False
            app.process = Mock(poll=Mock(return_value=None))
            app.close_when_stopped = False
            app.running_tid_exhaustive = True
            app._save_tid_settings = Mock()
            app._request_stop = Mock()
            app._finish_close = Mock()
            with patch("run_auto_rng_gui.messagebox.askyesnocancel", return_value=answer):
                AutoRngApp.on_close(app)
            self.assertEqual(app._request_stop.called, answer is True)
            self.assertEqual(app._finish_close.called, answer is False)
            self.assertEqual(app.close_when_stopped, answer is True)


if __name__ == "__main__":
    unittest.main()
