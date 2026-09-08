import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import package_entry
from automation import EasyCon118Options, EasyConRuntimeCheck, TidRngRequest
from pyside_app.services import AppPaths, PreparedWild, WildInputs, prepare_run
from pyside_app.workflows import PreparedWorkflow, WorkflowInputs, prepare_workflow_run
from tests.test_pyside_services import sample_result
from worker_commands import WORKER_SCRIPTS, build_worker_command


class WorkerCommandTests(unittest.TestCase):
    def test_source_python_and_pythonw_preserve_unbuffered_scripts_and_arguments(self):
        args = ["--request-json", "含空格 path/plan.json", "--port", "COM3"]
        with patch.object(sys, "frozen", False, create=True):
            for executable in ("C:/Python/python.exe", "C:/Python/pythonw.exe"):
                for worker, script in WORKER_SCRIPTS.items():
                    with self.subTest(executable=executable, worker=worker), patch.object(sys, "executable", executable):
                        command = build_worker_command(worker, args)
                        self.assertEqual(Path(command[0]).name, "python.exe")
                        self.assertEqual(command[1], "-u")
                        self.assertEqual(Path(command[2]).name, script)
                        self.assertEqual(command[3:], args)

    def test_frozen_worker_dispatch_keeps_arguments_exit_code_and_bypasses_gui(self):
        args = ["--request-json", "中文 path/plan.json", "--port", "COM3"]
        for worker, script in WORKER_SCRIPTS.items():
            with self.subTest(worker=worker):
                target = Mock(return_value=17)
                gui = Mock(side_effect=AssertionError("worker must not launch a GUI"))
                with patch.object(sys, "frozen", True, create=True), \
                     patch.object(sys, "executable", "C:/Portable/FRLG-Auto-RNG.exe"), \
                     patch.object(sys, "argv", ["FRLG-Auto-RNG.exe"]), \
                     patch.dict(sys.modules, {script[:-3]: SimpleNamespace(main=target),
                                             "run_pyside6_gui": SimpleNamespace(main=gui)}):
                    command = build_worker_command(worker, args)
                    self.assertEqual(command, [sys.executable, "--worker", worker, *args])
                    self.assertEqual(package_entry.main(command[1:]), 17)
                    self.assertEqual(sys.argv[1:], args)
                    target.assert_called_once_with(*([] if worker == "tid-flow" else [args]))
                    gui.assert_not_called()

    def test_unknown_worker_is_rejected_in_source_and_frozen(self):
        for frozen in (False, True):
            with patch.object(sys, "frozen", frozen, create=True):
                with self.assertRaisesRegex(ValueError, "未知后台工作模式"):
                    build_worker_command("unknown", [])

    def test_packaged_worker_configures_utf8_pipes_before_running(self):
        stdout, stderr = Mock(), Mock()
        def run(args):
            for stream in (stdout, stderr):
                stream.reconfigure.assert_called_once_with(
                    encoding="utf-8", errors="backslashreplace", newline="\n",
                    line_buffering=True, write_through=True)
            return 0
        with patch.object(sys, "stdout", stdout), patch.object(sys, "stderr", stderr), \
             patch.object(sys, "argv", ["FRLG-Auto-RNG.exe"]), \
             patch.dict(sys.modules, {"run_easycon_logged": SimpleNamespace(main=run)}):
            self.assertEqual(package_entry.main(["--worker", "easycon-log"]), 0)

    def test_all_qt_workflow_commands_use_frozen_dispatch_and_keep_runtime_options(self):
        cases = (
            ("sid", "sid-capture", SimpleNamespace(game="fr_nx"), {}),
            ("tid", "tid-flow", TidRngRequest(mode=0, calibration_check=True),
             {"game": "火红", "flow": None, "resume": False}),
            ("tid", "tid-flow", TidRngRequest(), {"game": "火红", "flow": True, "resume": True}),
            ("sid_traversal", "sid-traversal", None,
             {"max_advances": 10000, "named_rival": True, "start_advance": 1900}),
            ("egg", "easycon-log", None, {}),
            ("script_test", "easycon-log", None, {}),
        )
        check = EasyConRuntimeCheck(True, (), ())
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "main.ecs"
            project.write_text("# no hardware", encoding="utf-8")
            for mode, worker, request, extra in cases:
                with self.subTest(mode=mode, worker=worker, flow=extra.get("flow")):
                    extra = {**extra, "progress_dir": str(root / "progress")}
                    prepared = PreparedWorkflow(
                        WorkflowInputs(mode, request, root, root / "ezcon.exe", advanced=True,
                                       capture_name="Capture", extra=extra),
                        root, project, check, {}, "", (), root / "label overrides")
                    with patch.object(sys, "frozen", True, create=True), \
                         patch.object(sys, "executable", str(root / "FRLG-Auto-RNG.exe")), \
                         patch("pyside_app.workflows.probe_easycon_devices", return_value=({"COM3"}, {1: "Capture"}, "")), \
                         patch("pyside_app.workflows.check_workflow", return_value=check), \
                         patch("pyside_app.workflows.prepare_compat_runner", return_value=root / "runner.exe"):
                        command = prepare_workflow_run(prepared, AppPaths(user=root), "COM3", 1, "Capture")
                    self.assertEqual(command.program, str(root / "FRLG-Auto-RNG.exe"))
                    self.assertEqual(command.arguments[:2], ("--worker", worker))
                    self.assertNotIn("-u", command.arguments)
                    self.assertIn(str(command.stop_path), command.arguments)
                    self.assertIn(str(command.log_path), command.arguments)
                    self.assertIn("COM3", command.arguments)
                    self.assertTrue(command.preview_url.startswith("http://127.0.0.1:"))
                    if mode in ("tid", "sid", "sid_traversal"):
                        self.assertIn("--fingerprint-warnings", command.arguments)
                        self.assertIn(str(prepared.profile), command.arguments)
                    if mode == "tid":
                        self.assertIn("--flow-dir" if extra["flow"] else "--tid-dir", command.arguments)
                        self.assertIn("--tid-context", command.arguments)
                        if request.calibration_check:
                            self.assertIn("--calibrate-first", command.arguments)
                            self.assertIn("--fresh-exhaustive", command.arguments)
                    if mode == "egg":
                        self.assertIn("--expected-marker", command.arguments)

    def test_wild_and_static_commands_use_frozen_log_worker(self):
        result = sample_result()
        check = EasyConRuntimeCheck(True, (), ())
        inputs = WildInputs(result.plan.request, EasyCon118Options(), Path("source"), Path("ezcon.exe"), capture_name="Capture")
        prepared = PreparedWild(inputs, result, Path("project/main.ecs"), Path("plan.json"), check)
        with patch.object(sys, "frozen", True, create=True), \
             patch.object(sys, "executable", "C:/Portable/FRLG-Auto-RNG.exe"), \
             patch("pyside_app.services.probe_easycon_devices", return_value=({"COM3"}, {1: "Capture"}, "")), \
             patch("pyside_app.services.validate_generated_project_consistency"), \
             patch("pyside_app.services.validate_runtime", return_value=check), \
             patch("pyside_app.services.prepare_compat_runner", return_value=Path("runner.exe")):
            command = prepare_run(prepared, "COM3", 1, "Capture")
        self.assertEqual(command.program, "C:/Portable/FRLG-Auto-RNG.exe")
        self.assertEqual(command.arguments[:2], ("--worker", "easycon-log"))
        self.assertNotIn("-u", command.arguments)
        self.assertIn(str(command.stop_path), command.arguments)
        self.assertIn(str(command.log_path), command.arguments)


if __name__ == "__main__":
    unittest.main()
