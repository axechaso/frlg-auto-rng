import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from run_tid_starter_flow import (
    FlowRunner,
    ID_MARKER,
    STARTER_SHINY_MARKER,
    STARTER_SID_MISS_MARKER,
    classify_starter_output,
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
    def test_existing_118_terminal_messages_drive_sid_retry(self):
        self.assertEqual(classify_starter_output([STARTER_SHINY_MARKER]), "shiny")
        self.assertEqual(classify_starter_output([STARTER_SID_MISS_MARKER]), "sid_miss")
        self.assertEqual(classify_starter_output(["普通校准继续"]), "unknown")

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


if __name__ == "__main__":
    unittest.main()
