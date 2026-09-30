import io
import errno
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from automation.easycon118 import EasyConRuntimeCheck
import automation.tid_starter_flow as starter_flow

from run_tid_starter_flow import (
    FlowRunner,
    ID_MARKER,
    STARTER_SHINY_MARKER,
    STARTER_STRUCTURED_SHINY_MARKER,
    STARTER_SID_MISS_MARKER,
    classify_starter_output,
    build_flow_report,
    parse_any_tid_snapshot,
    parse_id_identity,
    run_exhaustive_flow,
    run_flow_attempts,
)


class _FakeProcess:
    def __init__(self, lines, returncode=0):
        self.stdout = io.StringIO("".join(lines))
        self.returncode = returncode

    def wait(self):
        return self.returncode

    def poll(self):
        return self.returncode


class TidStarterRunnerTests(unittest.TestCase):
    def test_denoised_snapshot_requires_one_complete_consistent_stage(self):
        values = {
            "TID": 12345, "DIGITS_OK": 1, "DENOISE_HITS": 2, "DENOISE_NEED": 2,
            "OP": 300, "F1": 200, "F2": 1500, "SELECT_CORRECTION": 0,
            "NX_MODEL": 2, "GENDER": 1, "SOUND": 0, "BUTTON_MODE": 0,
            "SEED_BUTTON": 0, "OP_FIXED": 100, "F1_FIXED": 500,
            "F2_FIXED": 800, "F3_FIXED": 14900, "OP_CORRECTION": 3,
            "SID_CORRECTION": 0, "OBSERVATION": 9, "DENOISE_TRY": 10,
        }
        lines = [f"TIDFLOW|ID|SNAPSHOT|{key}={value}" for key, value in values.items()]
        self.assertEqual(parse_any_tid_snapshot(lines), values)
        with self.assertRaisesRegex(ValueError, "缺少字段"):
            parse_any_tid_snapshot(lines[:-1])
        with self.assertRaisesRegex(ValueError, "字段在同一阶段出现冲突"):
            parse_any_tid_snapshot([*lines, "TIDFLOW|ID|SNAPSHOT|TID=12346"])

    def test_structured_flow_report_only_claims_verified_identity_with_complete_evidence(self):
        from automation.tid_rng137 import TidRngRequest

        request = starter_flow.TidStarterFlowRequest(
            tid_request=TidRngRequest(mode=1, target_tid=12345, target_sid=0),
            version="火红",
            starter="妙蛙种子",
        )
        flow = FlowRunner(
            Path("runner.exe"), port="COM4", video_device=0, log=io.StringIO()
        )
        flow.report_request = request
        flow.report_original_request = request
        flow.report_plan = {"request": request.to_dict() if hasattr(request, "to_dict") else {}}
        flow.final_identity = {"tid": 12345, "sid": 0, "sid_advance": 0, "sid_correction": 0}
        flow.final_target = {
            "tid": 12345, "sid": 0, "seed_hex": "A1B2", "advances": 1513,
            "pid_hex": "01234567",
        }
        flow.final_attempt_correction = 0
        flow.sid_verified = True
        flow.verified_marker_seen = True
        flow.input_plan_sha256 = "plan-hash"

        report = build_flow_report(flow, code=0, run_id="current-run")
        self.assertEqual(report["status"], "sid_verified")
        self.assertEqual(report["final_identity"]["sid"], 0)
        self.assertTrue(report["sid_verification"]["verified"])
        self.assertEqual(report["evidence"]["sid_candidate"], 0)
        self.assertEqual(report["input_plan_sha256"], "plan-hash")

        flow.sid_verified = False
        report = build_flow_report(flow, code=0, run_id="current-run")
        self.assertEqual(report["status"], "completed_without_sid_verification")
        flow.stop_requested = True
        report = build_flow_report(flow, code=130, run_id="current-run")
        self.assertEqual(report["status"], "stopped")

    def test_invalid_stdout_does_not_break_stage_logs_markers_or_progress(self):
        for operation in ("write", "flush"):
            with self.subTest(operation=operation), tempfile.TemporaryDirectory() as directory:
                main = Path(directory) / "main.ecs"
                main.write_text("RETURN 0\n", encoding="utf-8")
                console = Mock(encoding="utf-8")
                getattr(console, operation).side_effect = OSError(errno.EINVAL, "Invalid argument")
                recording, progress = Mock(), Mock()
                log = io.StringIO()
                runner = FlowRunner(Path("runner.exe"), port="COM4", video_device=0,
                                    log=log, recording=recording)
                runner.progress = progress
                lines = [ID_MARKER, "TIDFLOW|ID|TID=39792", "TIDFLOW|ID|SID_ADV=2295"]
                process = _FakeProcess([line + "\n" for line in lines])
                with patch("run_tid_starter_flow.sys.stdout", console), \
                     patch("run_tid_starter_flow.subprocess.Popen", return_value=process):
                    code = runner.run_stage(1, "TID/SID", main, required_marker=ID_MARKER)
                self.assertEqual(code, 0)
                self.assertEqual(parse_id_identity(runner.stage_lines), (39792, 2295))
                self.assertIn("[流程完成] 第1阶段已完成。", log.getvalue())
                for line in lines:
                    self.assertIn(line, log.getvalue())
                    recording.feed.assert_any_call(line + "\n")
                    progress.feed.assert_any_call(line)
                self.assertIsNone(runner.current_process)
                self.assertTrue(process.stdout.closed)

    def test_invalid_stdout_does_not_mask_child_failure_or_missing_marker(self):
        for lines, exit_code, expected in ((["failed\n"], 7, 7), (["done\n"], 0, 3)):
            with self.subTest(exit_code=exit_code), tempfile.TemporaryDirectory() as directory:
                main = Path(directory) / "main.ecs"
                main.write_text("RETURN 0\n", encoding="utf-8")
                console = Mock(encoding="utf-8")
                console.write.side_effect = OSError(errno.EINVAL, "Invalid argument")
                log = io.StringIO()
                runner = FlowRunner(Path("runner.exe"), port="COM4", video_device=0, log=log)
                with patch("run_tid_starter_flow.sys.stdout", console), \
                     patch("run_tid_starter_flow.subprocess.Popen", return_value=_FakeProcess(lines, exit_code)):
                    self.assertEqual(runner.run_stage(1, "TID/SID", main, required_marker=ID_MARKER), expected)
                self.assertIn("[流程错误]", log.getvalue())

    def test_missing_stdout_still_records_file_and_progress(self):
        log = io.StringIO()
        runner = FlowRunner(Path("runner.exe"), port="COM4", video_device=0, log=log)
        with patch("run_tid_starter_flow.sys.stdout", None):
            runner.output("TIDFLOW|ID|TID=39792")
        self.assertEqual(log.getvalue(), "TIDFLOW|ID|TID=39792\n")

    def test_real_log_file_errors_are_not_silenced(self):
        log = Mock()
        log.write.side_effect = OSError(errno.ENOSPC, "No space left on device")
        runner = FlowRunner(Path("runner.exe"), port="COM4", video_device=0, log=log)
        with patch("run_tid_starter_flow.sys.stdout", io.StringIO()), self.assertRaises(OSError) as caught:
            runner.output("test")
        self.assertEqual(caught.exception.errno, errno.ENOSPC)

    def test_only_confirmed_shiny_completion_exposes_successful_sid_correction(self):
        parser = getattr(starter_flow, "parse_successful_sid_advance_correction", None)
        self.assertTrue(callable(parser))
        self.assertEqual(
            parser("[流程完成] 已确认闪光御三家；成功使用SID ADV修正 -2。\n"),
            -2,
        )
        self.assertEqual(
            parser("noise\n[流程完成] 已确认闪光御三家；成功使用SID ADV修正 +4。\n"),
            4,
        )
        self.assertIsNone(parser("[SID未命中] 将使用下一个SID ADV修正重新建档。\n"))
        self.assertIsNone(parser("[流程结束] 已用完SID ADV重试范围。\n"))

    def test_console_output_falls_back_when_active_code_page_cannot_encode_chinese(self):
        class Cp1252Stream:
            encoding = "cp1252"

            def __init__(self):
                self.text = ""

            def write(self, value):
                value.encode(self.encoding)
                self.text += value

            def flush(self):
                pass

        console = Cp1252Stream()
        log = io.StringIO()
        runner = FlowRunner(Path("runner.exe"), port="COM4", video_device=0, log=log)
        with patch("run_tid_starter_flow.sys.stdout", console):
            runner.output("第一阶段")

        self.assertIn("????", console.text)
        self.assertIn("第一阶段", log.getvalue())

    def test_existing_118_terminal_messages_drive_sid_retry(self):
        self.assertEqual(classify_starter_output([STARTER_SHINY_MARKER]), "unverified_shiny")
        self.assertEqual(
            classify_starter_output([STARTER_SHINY_MARKER, STARTER_STRUCTURED_SHINY_MARKER]),
            "shiny",
        )
        self.assertEqual(classify_starter_output([STARTER_SID_MISS_MARKER]), "sid_miss")
        self.assertEqual(classify_starter_output(["普通校准继续"]), "unknown")

    def test_actual_tid_and_sid_advance_are_parsed_from_stage_markers(self):
        self.assertEqual(
            parse_id_identity(
                [
                    "\x1b[90mTIDFLOW|ID|MATCH=1\x1b[0m",
                    "TIDFLOW|ID|TID=12345",
                    "TIDFLOW|ID|SID_ADV=199",
                ]
            ),
            (12345, 199),
        )
        with self.assertRaisesRegex(ValueError, "没有输出完整"):
            parse_id_identity(["TIDFLOW|ID|MATCH=1"])

    def test_sid_miss_restarts_all_three_stages_with_next_attempt(self):
        from automation.tid_rng137 import TidRngRequest

        request = starter_flow.TidStarterFlowRequest(
            tid_request=TidRngRequest(
                mode=1,
                target_tid=12345,
                target_sid=8832,
            ),
            version="火红",
            starter="妙蛙种子",
            starter_max_advances=1600,
        )
        plan_payload = starter_flow.build_tid_starter_flow_plan(request).to_dict()

        class StubFlow:
            def __init__(self):
                self.calls = []
                self.messages = []
                self.stage_lines = []
                self.stop_requested = False
                self.starter_results = iter(
                    (
                        [STARTER_SID_MISS_MARKER],
                        [STARTER_SHINY_MARKER, STARTER_STRUCTURED_SHINY_MARKER],
                    )
                )
                self.final_identity = None
                self.final_target = None
                self.report_request = None
                self.report_plan = None
                self.sixv_state = None
                self.sixv_state_path = None

            def output(self, message):
                self.messages.append(message)

            def run_stage(self, number, name, main_path, required_marker=None):
                self.calls.append((number, Path(main_path), required_marker))
                if number == 1:
                    self.stage_lines = [
                        ID_MARKER,
                        "TIDFLOW|ID|TID=12345",
                        "TIDFLOW|ID|SID_ADV=199",
                    ]
                elif number == 3:
                    self.stage_lines = next(self.starter_results)
                return 0

        with tempfile.TemporaryDirectory() as directory:
            flow_dir = Path(directory) / "flow"
            flow_dir.mkdir()
            (flow_dir / "flow_plan.json").write_text(
                json.dumps(plan_payload), encoding="utf-8"
            )
            flow = StubFlow()
            code = run_flow_attempts(flow, flow_dir, [0, 1])

        self.assertEqual(code, 0)
        self.assertEqual([call[0] for call in flow.calls], [1, 2, 3, 1, 2, 3])
        self.assertEqual(flow.calls[0][1].name, "main_attempt_000.ecs")
        self.assertEqual(flow.calls[3][1].name, "main_attempt_001.ecs")
        self.assertTrue(any("重新建档" in message for message in flow.messages))
        self.assertTrue(flow.sid_verified)
        self.assertTrue(flow.verified_marker_seen)
        self.assertEqual(flow.final_attempt_correction, 1)

    def test_wrong_runtime_sid_restarts_before_bridge_or_starter(self):
        from automation.tid_rng137 import TidRngRequest

        request = starter_flow.TidStarterFlowRequest(
            tid_request=TidRngRequest(mode=1, target_tid=12345, target_sid=8832),
            version="火红",
            starter="妙蛙种子",
            starter_max_advances=1600,
        )
        plan_payload = starter_flow.build_tid_starter_flow_plan(request).to_dict()

        class StubFlow:
            def __init__(self):
                self.calls = []
                self.messages = []
                self.stage_lines = []
                self.stop_requested = False
                self.final_identity = None
                self.final_target = None
                self.report_request = None
                self.report_plan = None
                self.sixv_state = None
                self.sixv_state_path = None

            def output(self, message):
                self.messages.append(message)

            def run_stage(self, number, name, main_path, required_marker=None):
                self.calls.append((number, Path(main_path), required_marker))
                if number == 1:
                    sid_advance = 0 if len([call for call in self.calls if call[0] == 1]) == 1 else 199
                    self.stage_lines = [
                        ID_MARKER,
                        "TIDFLOW|ID|TID=12345",
                        f"TIDFLOW|ID|SID_ADV={sid_advance}",
                    ]
                elif number == 3:
                    self.stage_lines = [STARTER_SHINY_MARKER, STARTER_STRUCTURED_SHINY_MARKER]
                return 0

        with tempfile.TemporaryDirectory() as directory:
            flow_dir = Path(directory) / "flow"
            flow_dir.mkdir()
            (flow_dir / "flow_plan.json").write_text(
                json.dumps(plan_payload), encoding="utf-8"
            )
            flow = StubFlow()
            code = run_flow_attempts(flow, flow_dir, [0, 1])

        self.assertEqual(code, 0)
        self.assertEqual([call[0] for call in flow.calls], [1, 1, 2, 3])
        self.assertTrue(any("目标 SID=08832" in message for message in flow.messages))
        self.assertEqual(flow.final_identity["sid"], 8832)

    def test_sixv_sid_retries_replan_same_sid_at_each_correction_floor(self):
        from automation.tid_rng137 import TidRngRequest

        request = starter_flow.TidStarterFlowRequest(
            tid_request=TidRngRequest(
                mode=1,
                target_tid=12345,
                target_sid=8832,
                f3_fixed_delay=0,
            ),
            version="火红",
            starter="妙蛙种子",
            starter_max_advances=1600,
        )
        plan_payload = starter_flow.build_tid_starter_flow_plan(request).to_dict()
        plan_payload["sid_retry_corrections"] = [0, 1]

        class StubFlow:
            def __init__(self, state_path):
                self.calls = []
                self.messages = []
                self.stage_lines = []
                self.stop_requested = False
                self.final_identity = None
                self.final_target = None
                self.report_request = None
                self.report_plan = None
                self.final_attempt_correction = None
                self.sid_verified = False
                self.verified_marker_seen = False
                self.sixv_state = {
                    "selected_sid": 8832,
                    "selected_sid_advance": 199,
                    "minimum_executable_sid_advance": 10,
                    "attempt_plans": {},
                }
                self.sixv_state_path = state_path
                self.starter_results = iter(
                    (
                        [STARTER_SID_MISS_MARKER],
                        [STARTER_SHINY_MARKER, STARTER_STRUCTURED_SHINY_MARKER],
                    )
                )

            def output(self, message):
                self.messages.append(message)

            def run_stage(self, number, name, main_path, required_marker=None):
                self.calls.append((number, Path(main_path), required_marker))
                if number == 1:
                    self.stage_lines = [
                        ID_MARKER,
                        "TIDFLOW|ID|TID=12345",
                        "TIDFLOW|ID|SID_ADV=199",
                    ]
                elif number == 3:
                    self.stage_lines = next(self.starter_results)
                return 0

        with tempfile.TemporaryDirectory() as directory:
            flow_dir = Path(directory) / "flow"
            flow_dir.mkdir()
            (flow_dir / "flow_plan.json").write_text(
                json.dumps(plan_payload), encoding="utf-8"
            )
            state_path = Path(directory) / "sixv-state.json"
            flow = StubFlow(state_path)
            with patch(
                "run_tid_starter_flow.sid_min_advances_for_f3",
                side_effect=[10, 20],
            ) as minimum_for_correction, patch(
                "run_tid_starter_flow.first_sid_advances",
                side_effect=[(SimpleNamespace(sid=8832, advance=199),)] * 2,
            ) as search_sid, patch(
                "run_tid_starter_flow.update_starter_precalibration"
            ):
                code = run_flow_attempts(flow, flow_dir, [0, 1])

            self.assertEqual(code, 0)
            self.assertEqual(
                [call.kwargs["sid_advance_correction"] for call in minimum_for_correction.call_args_list],
                [0, 1],
            )
            self.assertEqual(
                [call.kwargs["min_advances"] for call in search_sid.call_args_list],
                [10, 20],
            )
            self.assertEqual(
                [call.args[1] for call in search_sid.call_args_list],
                [(8832,), (8832,)],
            )
            self.assertEqual(
                [call[0] for call in flow.calls], [1, 2, 3, 1, 2, 3]
            )
            state = json.loads(state_path.read_text(encoding="utf-8"))

        self.assertEqual(state["attempt_plans"]["0"]["minimum_executable_advance"], 10)
        self.assertEqual(state["attempt_plans"]["1"]["minimum_executable_advance"], 20)
        self.assertEqual(state["attempt_plans"]["1"]["selected_sid"], 8832)
        self.assertEqual(state["attempt_plans"]["1"]["actual_sid"], 8832)
        self.assertEqual(state["current_attempt_sid_advance"], 199)

    def test_stage_requires_success_marker_before_advancing(self):
        with tempfile.TemporaryDirectory() as directory:
            main_path = Path(directory) / "main.ecs"
            main_path.write_text("RETURN 0\n", encoding="utf-8")
            log = io.StringIO()
            runner = FlowRunner(Path(directory) / "runner.exe", port="COM4", video_device=0, log=log)
            fake = _FakeProcess(["boot\n", f"{ID_MARKER}\n"])
            with patch("run_tid_starter_flow.subprocess.Popen", return_value=fake) as popen:
                code = runner.run_stage(1, "TID/SID", main_path, required_marker=ID_MARKER)

        self.assertEqual(code, 0)
        self.assertIn(ID_MARKER, log.getvalue())
        command = popen.call_args.args[0]
        self.assertIn("--videotype", command)
        self.assertIn("DSHOW", command)

    def test_stage_rejects_clean_exit_without_marker(self):
        with tempfile.TemporaryDirectory() as directory:
            main_path = Path(directory) / "main.ecs"
            main_path.write_text("RETURN 0\n", encoding="utf-8")
            log = io.StringIO()
            runner = FlowRunner(Path(directory) / "runner.exe", port="COM4", video_device=0, log=log)
            with patch(
                "run_tid_starter_flow.subprocess.Popen",
                return_value=_FakeProcess(["no match\n"]),
            ):
                code = runner.run_stage(1, "TID/SID", main_path, required_marker=ID_MARKER)

        self.assertEqual(code, 3)
        self.assertIn("没有看到成功标记", log.getvalue())

    def test_exhaustive_flow_generates_starter_after_stage_one_identity(self):
        class StubFlow:
            def __init__(self):
                self.calls = []
                self.messages = []
                self.stage_lines = []
                self.stop_requested = False

            def output(self, message):
                self.messages.append(message)

            def run_stage(self, number, name, main_path, required_marker=None):
                self.calls.append((number, Path(main_path), required_marker))
                if number == 1:
                    self.stage_lines = [
                        ID_MARKER,
                        "TIDFLOW|ID|TID=12345",
                        "TIDFLOW|ID|SID_ADV=199",
                    ]
                elif number == 3:
                    self.stage_lines = [STARTER_SHINY_MARKER, STARTER_STRUCTURED_SHINY_MARKER]
                return 0

        resolved = SimpleNamespace(
            tid=12345,
            sid_advance=199,
            sid=8832,
            starter_target=SimpleNamespace(
                seed_hex="9CA9",
                advances=1513,
                pid_hex="01234567",
                tid=12345,
                sid=8832,
                to_dict=lambda: {
                    "seed_hex": "9CA9",
                    "advances": 1513,
                    "pid_hex": "01234567",
                    "tid": 12345,
                    "sid": 8832,
                },
            ),
        )
        flow = StubFlow()
        request = starter_flow.TidStarterFlowRequest(
            tid_request=starter_flow.TidRngRequest(mode=0, sid_random=True),
            version="火红",
            starter="妙蛙种子",
        )
        payload = {
            "request": starter_flow.build_tid_starter_flow_plan(request).to_dict()["request"],
            "starter_source_dir": "source118",
        }
        with (
            patch(
                "run_tid_starter_flow.tid_starter_flow_request_from_dict",
                return_value=request,
            ),
            patch(
                "run_tid_starter_flow.resolve_exhaustive_starter_plan",
                return_value=resolved,
            ) as resolve,
            patch("run_tid_starter_flow.write_resolved_exhaustive_starter_project") as write,
            patch(
                "run_tid_starter_flow.validate_runtime",
                return_value=EasyConRuntimeCheck(True, (), ()),
            ),
        ):
            code = run_exhaustive_flow(
                flow,
                Path("flow"),
                payload,
                Path("ezcon.exe"),
            )

        self.assertEqual(code, 0)
        self.assertEqual([item[0] for item in flow.calls], [1, 2, 3])
        resolve.assert_called_once()
        self.assertEqual(resolve.call_args.kwargs["actual_tid"], 12345)
        self.assertEqual(resolve.call_args.kwargs["sid_advance"], 199)
        write.assert_called_once()
        self.assertTrue(any("计算SID=08832" in item for item in flow.messages))


if __name__ == "__main__":
    unittest.main()
