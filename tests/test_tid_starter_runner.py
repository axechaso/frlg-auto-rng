import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from automation.easycon118 import EasyConRuntimeCheck

from run_tid_starter_flow import (
    FlowRunner,
    ID_MARKER,
    STARTER_SHINY_MARKER,
    STARTER_SID_MISS_MARKER,
    classify_starter_output,
    parse_id_identity,
    run_exhaustive_flow,
    run_flow_attempts,
)


class _FakeProcess:
    def __init__(self, lines, returncode=0):
        self.stdout = iter(lines)
        self.returncode = returncode

    def wait(self):
        return self.returncode

    def poll(self):
        return self.returncode


class TidStarterRunnerTests(unittest.TestCase):
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
        self.assertEqual(classify_starter_output([STARTER_SHINY_MARKER]), "shiny")
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
        class StubFlow:
            def __init__(self):
                self.calls = []
                self.messages = []
                self.stage_lines = []
                self.starter_results = iter(
                    ([STARTER_SID_MISS_MARKER], [STARTER_SHINY_MARKER])
                )

            def output(self, message):
                self.messages.append(message)

            def run_stage(self, number, name, main_path, required_marker=None):
                self.calls.append((number, Path(main_path), required_marker))
                if number == 3:
                    self.stage_lines = next(self.starter_results)
                return 0

        flow = StubFlow()
        code = run_flow_attempts(flow, Path("flow"), [0, 1])

        self.assertEqual(code, 0)
        self.assertEqual([call[0] for call in flow.calls], [1, 2, 3, 1, 2, 3])
        self.assertEqual(flow.calls[0][1].name, "main_attempt_000.ecs")
        self.assertEqual(flow.calls[3][1].name, "main_attempt_001.ecs")
        self.assertTrue(any("重新建档" in message for message in flow.messages))

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
                    self.stage_lines = [STARTER_SHINY_MARKER]
                return 0

        resolved = SimpleNamespace(
            tid=12345,
            sid_advance=199,
            sid=8832,
            starter_target=SimpleNamespace(
                seed_hex="9CA9", advances=1513, pid_hex="01234567"
            ),
        )
        flow = StubFlow()
        payload = {
            "request": {"tid_request": {}},
            "starter_source_dir": "source118",
        }
        with (
            patch(
                "run_tid_starter_flow.tid_starter_flow_request_from_dict",
                return_value=object(),
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
