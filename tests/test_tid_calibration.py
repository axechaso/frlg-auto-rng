from contextlib import ExitStack
from dataclasses import asdict, replace
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from automation.easycon118 import EasyConRuntimeCheck
from automation.tid_calibration import (
    calibrated_tid_request, parse_tid_calibration_result, parse_tid_fixed_delays,
    validate_tid_plan_runtime,
)
from automation.tid_rng137 import TidRngRequest
from automation.tid_starter_flow import TidStarterFlowRequest
from run_auto_rng_gui import AutoRngApp
from run_tid_starter_flow import FlowRunner, run_tid_plan
from tid_records import TidRecordContext, TidRecordingSession


MEASUREMENT = (
    "OP修正增加50ms：当前修正=100ms，实际固定WAIT=30700ms\n"
    "OP脚本固定延迟：30700\nF1脚本固定延迟：22100\n"
    "F2脚本固定延迟：4300\nF3脚本固定延迟：15000\n"
)
VALUES = {"OP": 30700, "F1": 22100, "F2": 4300, "F3": 15000, "OP_CORRECTION": 100}
OK = EasyConRuntimeCheck(True, (), ())
BAD = EasyConRuntimeCheck(False, ("test failure",), ())


def save_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def flow_payload(request):
    return {"request": asdict(request), "sid_retry_corrections": [0, 1],
            "deferred_identity": request.deferred_identity, "starter_source_dir": "source118"}


class StubFlow:
    def __init__(self, lines=MEASUREMENT, calibration_code=0):
        self.lines = lines
        self.calibration_code = calibration_code
        self.stop_requested = False
        self.stop_after_calibration = False
        self.stage_lines = []
        self.calls = []
        self.messages = []
        self.recording = Mock()

    def output(self, message):
        self.messages.append(message)

    def run_stage(self, number, name, path, **kwargs):
        self.calls.append((number, path))
        self.stage_lines = self.lines.splitlines() if number == 0 else []
        if number == 0:
            self.stop_requested = self.stop_after_calibration
            return self.calibration_code
        return 0


class TidCalibrationTests(unittest.TestCase):
    def fixture(self, root, request, is_flow):
        initial = replace(request, calibration_check=True)
        plan = TidStarterFlowRequest(request, "叶绿", "妙蛙种子", starter_max_advances=1600)
        if is_flow and request.mode == 0:
            plan = replace(plan, accept_any_tid=True, any_tid_require_denoise=False)
        if is_flow:
            save_json(root / "flow_plan.json", flow_payload(plan))
        else:
            save_json(root / "plan.json", {"tid_request": request.to_dict()})
        save_json(root / "00_calibration" / "plan.json", {
            "tid_request": initial.to_dict(), "source": "source", "source_manifest": {},
        })
        return initial

    def patches(self, stack, *, initial_check=OK, final_check=OK):
        mocks = {}
        for name, result in (
            ("validate_tid_runtime", initial_check),
            ("validate_tid_plan_runtime", final_check),
            ("verify_tid_package", {}),
            ("write_configured_tid_project", None),
            ("run_flow_attempts", 0),
            ("run_exhaustive_flow", 0),
        ):
            mocks[name] = stack.enter_context(patch("run_tid_starter_flow." + name, return_value=result))
        mocks["build"] = stack.enter_context(patch(
            "run_tid_starter_flow.build_tid_starter_flow_plan",
            side_effect=lambda request: SimpleNamespace(request=request),
        ))
        mocks["bundle"] = stack.enter_context(patch(
            "run_tid_starter_flow.write_tid_starter_flow_bundle",
            side_effect=lambda source, output, plan, **kwargs: save_json(output / "flow_plan.json", flow_payload(plan.request)),
        ))
        return mocks

    def test_measurement_only_changes_delays_and_actual_correction(self):
        for nx in (1, 2):
            for language in ("英文", "日文"):
                original = TidRngRequest(nx_model=nx, language=language, calibration_check=True, op_correction=50)
                updated = calibrated_tid_request(original, parse_tid_calibration_result(MEASUREMENT, 50))
                expected = asdict(original)
                expected.update(calibration_check=False, op_fixed_delay=30700, f1_fixed_delay=22100,
                                f2_fixed_delay=4300, f3_fixed_delay=15000, op_correction=100)
                self.assertEqual(asdict(updated), expected)
                self.assertTrue(original.calibration_check)

    def test_measurement_never_combines_different_blocks(self):
        with self.assertRaisesRegex(ValueError, "F1/F2/F3"):
            parse_tid_fixed_delays(MEASUREMENT + "OP脚本固定延迟：31000\n")

    def test_negative_incomplete_and_cancelled_results_are_rejected(self):
        for text in (MEASUREMENT.replace("F3脚本固定延迟：15000", ""),
                     MEASUREMENT.replace("30700\n", "-1\n"),
                     MEASUREMENT + "System.OperationCanceledException: The operation was canceled."):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_tid_calibration_result(text, 0)
        with self.assertRaises(ValueError):
            calibrated_tid_request(TidRngRequest(), {**VALUES, "OP": True})

    def test_standalone_calibration_regenerates_preflights_and_runs_for_both_languages(self):
        for language in ("英文", "日文"):
            for mode in (0, 1):
                with self.subTest(language=language, mode=mode), tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
                    root = Path(directory)
                    initial = self.fixture(root, TidRngRequest(language=language, mode=mode), False)
                    flow = StubFlow()
                    mocks = self.patches(stack)
                    code = run_tid_plan(flow, root, Path("ezcon.exe"), is_flow=False,
                                        calibrate_first=True, result_path=root / "result.json")
                    self.assertEqual(code, 0)
                    self.assertEqual([call[0] for call in flow.calls], [0, 1])
                    updated = mocks["write_configured_tid_project"].call_args.args[2]
                    self.assertEqual(updated, calibrated_tid_request(initial, VALUES))
                    self.assertNotEqual(flow.calls[1][1].parent, root)
                    mocks["validate_tid_plan_runtime"].assert_called_once()
                    flow.recording.update_request.assert_called_once_with(updated)
                    result = json.loads((root / "result.json").read_text(encoding="utf-8"))
                    self.assertEqual(result["initial_request"], initial.to_dict())
                    self.assertEqual(result["request"], updated.to_dict())
                    self.assertEqual(json.loads((root / "plan.json").read_text(encoding="utf-8"))["tid_request"]["op_fixed_delay"], initial.op_fixed_delay)

    def test_target_and_exhaustive_flow_continue_with_calibrated_snapshot(self):
        for mode in (0, 1):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
                root = Path(directory)
                initial = self.fixture(root, TidRngRequest(mode=mode, sid_random=mode == 0), True)
                flow = StubFlow()
                mocks = self.patches(stack)
                code = run_tid_plan(flow, root, Path("ezcon.exe"), is_flow=True,
                                    calibrate_first=True, result_path=root / "result.json")
                self.assertEqual(code, 0)
                updated_flow = mocks["build"].call_args.args[0]
                self.assertEqual(updated_flow.tid_request, calibrated_tid_request(initial, VALUES))
                self.assertEqual(updated_flow.version, "叶绿")
                self.assertEqual(updated_flow.starter_max_advances, 1600)
                self.assertEqual(updated_flow.accept_any_tid, mode == 0)
                self.assertEqual(updated_flow.any_tid_require_denoise, mode != 0)
                self.assertEqual(mocks["run_exhaustive_flow"].call_count, int(mode == 0))
                self.assertEqual(mocks["run_flow_attempts"].call_count, int(mode == 1))

    def test_failed_cancelled_or_incomplete_calibration_never_launches_formal_stage(self):
        for failure in ("exit", "stop", "incomplete", "cancel_log", "initial_preflight", "mismatch"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
                root = Path(directory)
                self.fixture(root, TidRngRequest(), False)
                flow = StubFlow(calibration_code=130 if failure == "exit" else 0)
                flow.stop_after_calibration = failure == "stop"
                if failure == "incomplete":
                    flow.lines = "OP脚本固定延迟：30700"
                if failure == "cancel_log":
                    flow.lines += "\nSystem.OperationCanceledException: cancelled"
                if failure == "mismatch":
                    save_json(root / "plan.json", {"tid_request": TidRngRequest(target_tid=1).to_dict()})
                mocks = self.patches(stack, initial_check=BAD if failure == "initial_preflight" else OK)
                code = run_tid_plan(flow, root, Path("ezcon.exe"), is_flow=False,
                                    calibrate_first=True, result_path=root / "result.json")
                self.assertNotEqual(code, 0)
                self.assertFalse((root / "result.json").exists())
                self.assertFalse(any(number == 1 for number, _ in flow.calls))
                mocks["write_configured_tid_project"].assert_not_called()
                flow.recording.update_request.assert_not_called()

    def test_regeneration_failure_or_stop_keeps_measurement_but_never_runs(self):
        for failure in ("preflight", "source_changed", "generation", "stop"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
                root = Path(directory)
                self.fixture(root, TidRngRequest(), False)
                flow = StubFlow()
                mocks = self.patches(stack, final_check=BAD if failure == "preflight" else OK)
                if failure == "source_changed":
                    mocks["verify_tid_package"].return_value = {"changed": True}
                if failure == "generation":
                    mocks["write_configured_tid_project"].side_effect = ValueError("generation failed")
                if failure == "stop":
                    def stop(*args, **kwargs):
                        flow.stop_requested = True
                        return OK
                    mocks["validate_tid_plan_runtime"].side_effect = stop
                code = run_tid_plan(flow, root, Path("ezcon.exe"), is_flow=False,
                                    calibrate_first=True, result_path=root / "result.json")
                self.assertNotEqual(code, 0)
                self.assertTrue((root / "result.json").is_file())
                self.assertEqual([number for number, _ in flow.calls], [0])
                flow.recording.update_request.assert_not_called()

    def test_source_manifest_comparison_normalizes_json_integer_keys(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            root = Path(directory)
            self.fixture(root, TidRngRequest(), False)
            path = root / "00_calibration" / "plan.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            manifest = {"labels": {"methods": {0: 1, 2: 327}}}
            payload["source_manifest"] = manifest
            save_json(path, payload)
            flow = StubFlow()
            mocks = self.patches(stack)
            mocks["verify_tid_package"].return_value = manifest
            self.assertEqual(run_tid_plan(flow, root, Path("ezcon.exe"), is_flow=False,
                calibrate_first=True, result_path=root / "result.json"), 0)
            self.assertEqual([number for number, _ in flow.calls], [0, 1])

    def test_preflight_checks_calibration_and_formal_stages(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for deferred in (False, True):
                save_json(root / "flow_plan.json", {"deferred_identity": deferred})
                with patch("automation.tid_calibration.validate_tid_starter_flow_runtime", return_value=OK) as formal, patch("automation.tid_calibration.validate_tid_runtime", return_value=BAD) as calibration:
                    check = validate_tid_plan_runtime(Path("ezcon.exe"), root, is_flow=True, calibrate_first=True)
                    self.assertFalse(check.ok)
                    self.assertEqual(formal.call_args.args[-1], None if deferred else root / "03_starter_118" / "main.ecs")
                    self.assertEqual(calibration.call_args.args[-1], root / "00_calibration" / "main.ecs")

    def test_all_stages_share_preview_port_and_stopped_runner_does_not_spawn(self):
        with tempfile.TemporaryDirectory() as directory:
            main = Path(directory) / "main.ecs"
            main.write_text("RETURN 0\n", encoding="utf-8")
            runner = FlowRunner(Path("runner.exe"), port="COM4", video_device=3, log=io.StringIO(), preview_port=43123)
            processes = [SimpleNamespace(stdout=io.StringIO("done\n"), wait=lambda: 0) for _ in range(2)]
            with patch("run_tid_starter_flow.subprocess.Popen", side_effect=processes) as popen, patch("run_tid_starter_flow.print"):
                self.assertEqual(runner.run_stage(0, "calibration", main), 0)
                self.assertEqual(runner.run_stage(1, "formal", main), 0)
                runner.stop_requested = True
                self.assertEqual(runner.run_stage(2, "bridge", main), 130)
            self.assertEqual(popen.call_count, 2)
            for call in popen.call_args_list:
                command = call.args[0]
                self.assertEqual(command[command.index("--preview-port") + 1], "43123")

    def test_tid_records_switch_to_measured_context_and_preserve_game_model(self):
        initial = TidRngRequest(nx_model=2)
        store = Mock()
        recorded = []
        store.append.side_effect = lambda run_id, rows, log_path: recorded.extend(rows)
        session = TidRecordingSession(TidRecordContext.from_request("叶绿", initial), store, Path("test.log"), flow=True)
        session.feed("========== 第0阶段：检测 ==========\n当前TID：11111\n")
        updated = calibrated_tid_request(initial, VALUES)
        session.update_request(updated)
        self.assertEqual(session.parser.base_context, TidRecordContext.from_request("叶绿", updated))
        session.feed("========== 第1阶段：正式 ==========\n当前TID：12345\n【OP】3693【F1】2693【F2】2105\nselect执行次数：2\n")
        row = recorded[0][1]
        self.assertEqual((row.tid, row.context.game, row.context.nx_model, row.context.op_fixed_delay), (12345, "叶绿", 2, 30700))


class Variable:
    def __init__(self, value=None):
        self.value = value
    def get(self):
        return self.value
    def set(self, value):
        self.value = value


class TidCalibrationGuiTests(unittest.TestCase):
    def test_starter_controls_do_not_disable_or_clear_calibration(self):
        app = SimpleNamespace(
            tid_starter_flow_var=Variable(True), tid_mode_var=Variable("乱数模式"),
            tid_calibration_var=Variable(True), tid_sid_mode_var=Variable(""),
            _updating=False, tid_mode_combo=Mock(), tid_sid_mode_combo=Mock(),
            tid_sid_entry=Mock(), tid_calibration_check=Mock(), tid_special_checks=[],
            tid_starter_flow_controls=[], _update_tid_delay_controls=Mock(),
            tid_any_tid_var=Variable(False), tid_any_tid_check=Mock(), tid_target_entry=Mock(),
            tid_any_tid_denoise_check=Mock(),
        )
        AutoRngApp._update_tid_flow_controls(app)
        self.assertTrue(app.tid_calibration_var.get())
        app.tid_calibration_check.configure.assert_called_with(state="normal")

    def test_collect_flow_strips_calibration_only_from_formal_request(self):
        app = SimpleNamespace(tid_starter_flow_var=Variable(True), tid_game_var=Variable("火红"),
                              tid_starter_var=Variable("妙蛙种子"), tid_starter_min_adv_var=Variable("1500"),
                              tid_starter_max_adv_var=Variable("1600"), tid_sid_retry_radius_var=Variable("20"))
        app.tid_any_tid_var = Variable(False)
        app.tid_any_tid_denoise_var = Variable(True)
        initial = TidRngRequest(calibration_check=True)
        formal = AutoRngApp.collect_tid_starter_flow_request(app, initial)
        self.assertEqual(formal.tid_request, replace(initial, calibration_check=False))
        self.assertTrue(initial.calibration_check)

    def test_collect_flow_keeps_tid_and_starter_game_settings_independent(self):
        app = SimpleNamespace(
            tid_starter_flow_var=Variable(True),
            tid_game_var=Variable("火红"),
            tid_starter_var=Variable("妙蛙种子"),
            tid_starter_min_adv_var=Variable("1500"),
            tid_starter_max_adv_var=Variable("1600"),
            tid_sid_retry_radius_var=Variable("20"),
            tid_starter_sound_var=Variable("STEREO"),
            tid_starter_button_mode_var=Variable("HELP"),
            tid_starter_seed_button_var=Variable("A"),
            tid_any_tid_var=Variable(False),
            tid_any_tid_denoise_var=Variable(True),
        )
        initial = TidRngRequest(sound=0, button_mode=1, seed_button=2)
        formal = AutoRngApp.collect_tid_starter_flow_request(app, initial)
        self.assertEqual((formal.tid_request.sound, formal.tid_request.button_mode, formal.tid_request.seed_button), (0, 1, 2))
        self.assertEqual((formal.starter_sound, formal.starter_button_mode, formal.starter_seed_button), (1, 0, 0))
        self.assertEqual(formal.to_starter_search_request().setting_key, "stereo_h_a")

    def test_any_tid_option_disables_target_filters_only_for_exhaustive_flow(self):
        for enabled, exhaustive in ((True, True), (True, False), (False, True)):
            app = SimpleNamespace(
                tid_starter_flow_var=Variable(enabled), tid_mode_var=Variable("穷举模式" if exhaustive else "乱数模式"),
                tid_calibration_var=Variable(True), tid_sid_mode_var=Variable(""),
                tid_any_tid_var=Variable(True), tid_any_tid_check=Mock(), tid_target_entry=Mock(),
                tid_any_tid_denoise_check=Mock(),
                _updating=False, tid_mode_combo=Mock(), tid_sid_mode_combo=Mock(),
                tid_sid_entry=Mock(), tid_calibration_check=Mock(), tid_special_checks=[Mock()],
                tid_sid_retry_radius_entry=Mock(), tid_starter_flow_controls=[], _update_tid_delay_controls=Mock(),
            )
            AutoRngApp._update_tid_flow_controls(app)
            app.tid_any_tid_check.configure.assert_called_with(state="normal" if enabled and exhaustive else "disabled")
            app.tid_target_entry.configure.assert_called_with(state="disabled" if enabled and exhaustive else "normal")
            app.tid_any_tid_denoise_check.configure.assert_called_with(state="normal" if enabled and exhaustive else "disabled")
            self.assertTrue(app.tid_calibration_var.get())

    def test_gui_fills_measurements_once_but_preserves_new_user_input(self):
        for state in ("unchanged", "edited", "wrong_run", "tampered"):
            with self.subTest(state=state), tempfile.TemporaryDirectory() as directory:
                initial = TidRngRequest(calibration_check=True)
                path = Path(directory) / "result.json"
                payload = {"schema": 1, "initial_request": initial.to_dict(), "values": VALUES,
                           "request": calibrated_tid_request(initial, VALUES).to_dict()}
                if state == "wrong_run":
                    payload["initial_request"]["target_tid"] = 1
                if state == "tampered":
                    payload["request"]["nx_model"] = 2
                save_json(path, payload)
                app = SimpleNamespace(
                    tid_calibration_result_path=path, tid_calibration_applied=False,
                    tid_calibration_snapshot=initial, tid_calibration_input_fingerprint=("start",),
                    input_fingerprint=lambda: ("edited",) if state == "edited" else ("start",),
                    tid_op_delay_var=Variable("30600"), tid_f1_delay_var=Variable("22050"),
                    tid_f2_delay_var=Variable("4250"), tid_f3_delay_var=Variable("14900"),
                    tid_op_correction_var=Variable("0"), tid_calibration_var=Variable(True),
                    status_var=Variable(""), _updating=False, invalidate_plan=Mock(),
                )
                AutoRngApp._poll_tid_calibration_result(app)
                AutoRngApp._poll_tid_calibration_result(app)
                self.assertEqual(app.tid_op_delay_var.get(), "30700" if state == "unchanged" else "30600")
                self.assertEqual(app.invalidate_plan.call_count, int(state == "unchanged"))
                self.assertEqual(app.tid_calibration_var.get(), state != "unchanged")


if __name__ == "__main__":
    unittest.main()
