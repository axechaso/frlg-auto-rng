import json
import errno
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from run_easycon_logged import run_logged


class EasyConLoggedTests(unittest.TestCase):
    def test_invalid_console_preserves_real_child_output_marker_and_exit_code(self):
        for operation in ("write", "flush"):
            for child_exit in (0, 7):
                with self.subTest(operation=operation, child_exit=child_exit), tempfile.TemporaryDirectory() as temp:
                    root = Path(temp)
                    log = root / "runner.log"
                    stream = mock.Mock(encoding="utf-8")
                    getattr(stream, operation).side_effect = OSError(errno.EINVAL, "Invalid argument")
                    recorder = mock.Mock()
                    with mock.patch("run_easycon_logged.sys.stdout", stream), \
                         mock.patch("run_easycon_logged.recording_session") as session:
                        session.return_value.__enter__.return_value = recorder
                        result = run_logged(
                            [sys.executable, "-c", f"print('TID_FLOW_DONE'); raise SystemExit({child_exit})"],
                            root, log, ("TID_FLOW_DONE",),
                        )
                    self.assertEqual(result, child_exit)
                    self.assertEqual(log.read_text(encoding="utf-8"), "TID_FLOW_DONE\n")
                    self.assertIn("TID_FLOW_DONE", "".join(call.args[0] for call in recorder.feed.call_args_list))

    def test_partial_last_line_is_written_before_the_child_prints_a_newline(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            log_path = root / "runner.log"
            release_path = root / "release"
            partial_line = "SPE:20-24"
            child_code = "\n".join(
                (
                    "import sys, time",
                    "from pathlib import Path",
                    f"release = Path({json.dumps(str(release_path))})",
                    f"sys.stdout.write({json.dumps(partial_line)})",
                    "sys.stdout.flush()",
                    "deadline = time.monotonic() + 10",
                    "while not release.exists() and time.monotonic() < deadline:",
                    "    time.sleep(0.02)",
                    "sys.stdout.write('\\n')",
                    "sys.stdout.flush()",
                )
            )
            result: list[int] = []
            worker = threading.Thread(
                target=lambda: result.append(
                    run_logged([sys.executable, "-c", child_code], root, log_path)
                )
            )

            with mock.patch("run_easycon_logged._write_console"):
                worker.start()
                try:
                    deadline = time.monotonic() + 3
                    observed = ""
                    while time.monotonic() < deadline:
                        if log_path.is_file():
                            observed = log_path.read_text(encoding="utf-8")
                            if partial_line in observed:
                                break
                        time.sleep(0.02)
                    self.assertIn(partial_line, observed)
                    self.assertTrue(worker.is_alive())
                finally:
                    release_path.touch()
                    worker.join(timeout=5)

            self.assertFalse(worker.is_alive())
            self.assertEqual(result, [0])
            self.assertEqual(log_path.read_text(encoding="utf-8"), partial_line + "\n")

    def test_missing_expected_marker_is_reported_as_abnormal_exit(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            log_path = root / "runner.log"
            child_code = "print('RUNNER_DONE')"
            with mock.patch("run_easycon_logged._write_console"):
                result = run_logged(
                    [sys.executable, "-c", child_code],
                    root,
                    log_path,
                    ("EGG_DONE", "EGG_FAILED"),
                )
            log_text = log_path.read_text(encoding="utf-8")
            self.assertEqual(result, 2)
            self.assertIn("RUNNER_DONE", log_text)
            self.assertIn("[EASYCON_DIAGNOSTIC]", log_text)

    def test_expected_marker_keeps_success_exit_code(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            log_path = root / "runner.log"
            child_code = "print('EGG_FAILED'); print('RUNNER_DONE')"
            with mock.patch("run_easycon_logged._write_console"):
                result = run_logged(
                    [sys.executable, "-c", child_code],
                    root,
                    log_path,
                    ("EGG_DONE", "EGG_FAILED"),
                )
            self.assertEqual(result, 0)
            self.assertNotIn(
                "[EASYCON_DIAGNOSTIC]",
                log_path.read_text(encoding="utf-8"),
            )

    def test_fatal_easycon_output_overrides_zero_exit_code_and_success_marker(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            log_path = root / "runner.log"
            child_code = (
                "print('WILD_DONE'); "
                "print('!!意外错误!!Index was outside the bounds of the array.')"
            )
            with mock.patch("run_easycon_logged._write_console"):
                result = run_logged(
                    [sys.executable, "-c", child_code],
                    root,
                    log_path,
                    ("WILD_DONE", "WILD_FAILED"),
                )

            self.assertEqual(result, 3)
            log_text = log_path.read_text(encoding="utf-8")
            self.assertIn("未处理异常", log_text)
            self.assertIn("[EASYCON_DIAGNOSTIC]", log_text)

    def test_headless_package_logs_when_stdout_is_unavailable(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            log_path = root / "runner.log"
            with mock.patch("run_easycon_logged.sys.stdout", None):
                result = run_logged(
                    [sys.executable, "-c", "print('TID_FLOW_DONE')"],
                    root,
                    log_path,
                )

            self.assertEqual(result, 0)
            self.assertIn("TID_FLOW_DONE", log_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
