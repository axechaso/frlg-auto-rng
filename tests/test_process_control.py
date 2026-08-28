import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from process_control import StopFileWatcher, terminate_process_tree
from run_auto_rng_gui import AutoRngApp
from run_easycon_logged import run_logged
from run_sid_reverse_capture import _run_easycon
from run_tid_starter_flow import FlowRunner


ROOT = Path(__file__).resolve().parents[1]


def wait_until(predicate, seconds=6):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def pid_alive(pid):
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
    import ctypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.OpenProcess.argtypes = (ctypes.c_ulong, ctypes.c_bool, ctypes.c_ulong)
    kernel.WaitForSingleObject.argtypes = (ctypes.c_void_p, ctypes.c_ulong)
    kernel.CloseHandle.argtypes = (ctypes.c_void_p,)
    handle = kernel.OpenProcess(0x100000, False, pid)
    if not handle:
        return False
    try:
        return kernel.WaitForSingleObject(handle, 0) == 258
    finally:
        kernel.CloseHandle(handle)


class ProcessControlTests(unittest.TestCase):
    def test_gui_writes_stop_file_instead_of_sending_cross_console_signal(self):
        with tempfile.TemporaryDirectory() as temp:
            process = Mock(poll=Mock(return_value=None))
            app = SimpleNamespace(process=process, stop_request_path=Path(temp) / "private.stop",
                root=Mock(), stop_button=Mock(), status_var=Mock(), _force_stop_process=Mock(),
                finish_stop_request=Mock())
            AutoRngApp._request_stop(app)
            self.assertTrue(app.stop_request_path.is_file())
            process.send_signal.assert_not_called()
            process.terminate.assert_not_called()
            self.assertEqual(app.root.after.call_args.args[0], 5000)

    def test_old_stop_timeout_cannot_kill_new_run(self):
        old = Mock(poll=Mock(return_value=None))
        new = Mock(poll=Mock(return_value=None))
        app = SimpleNamespace(process=new, _force_stop_process=Mock(), status_var=Mock())
        AutoRngApp.finish_stop_request(app, old)
        app._force_stop_process.assert_not_called()
        AutoRngApp.finish_stop_request(app, new)
        app._force_stop_process.assert_called_once_with(new)

    def test_existing_stop_file_prevents_easycon_start(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            stop = root / "stop"
            stop.touch()
            with patch("run_easycon_logged.subprocess.Popen") as spawn:
                self.assertEqual(run_logged(["unused"], root, root / "log", stop_file=stop), 130)
                spawn.assert_not_called()

    def test_tid_and_sid_silent_child_stop_without_waiting_for_next_log_line(self):
        for mode in ("tid", "sid"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                stop = root / "stop"
                ready = root / "ready"
                command = [sys.executable, "-c", f"from pathlib import Path; import time; Path({str(ready)!r}).touch(); time.sleep(20)"]
                results = []
                flow = FlowRunner(Path("unused"), port="COM4", video_device=3, log=io.StringIO())
                main = root / "main.ecs"
                main.touch()
                def run():
                    if mode == "tid":
                        with StopFileWatcher(stop, flow.request_stop):
                            results.append(flow.run_stage(1, "test", main))
                    else:
                        results.append(_run_easycon(command, root, pokemon_index=1, game="fr_nx", stop_file=stop)[0])
                with patch("run_tid_starter_flow.build_run_command", return_value=command):
                    thread = threading.Thread(target=run)
                    thread.start()
                    try:
                        self.assertTrue(wait_until(ready.is_file))
                        stop.touch()
                        thread.join(8)
                        self.assertFalse(thread.is_alive())
                        self.assertEqual(results, [130])
                    finally:
                        stop.touch()
                        if flow.current_process is not None:
                            terminate_process_tree(flow.current_process)
                        thread.join(22)

    @unittest.skipUnless(os.name == "nt", "Windows console/process-tree regression")
    def test_hidden_new_console_worker_stops_child_and_grandchild(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            stop = root / "stop"
            log = root / "log"
            ready = root / "pids.json"
            child_code = (
                "import json, os, subprocess, sys, time; from pathlib import Path; "
                "child=subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(25)']); "
                f"Path({str(ready)!r}).write_text(json.dumps([os.getpid(), child.pid])); "
                "print('READY', flush=True); time.sleep(25)"
            )
            startup = subprocess.STARTUPINFO()
            startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startup.wShowWindow = 0
            process = subprocess.Popen(
                [sys.executable, str(ROOT / "run_easycon_logged.py"), "--log-path", str(log),
                 "--cwd", str(root), "--stop-file", str(stop), "--",
                 sys.executable, "-c", child_code],
                creationflags=subprocess.CREATE_NEW_CONSOLE | subprocess.CREATE_NEW_PROCESS_GROUP,
                startupinfo=startup,
            )
            pids = []
            try:
                self.assertTrue(wait_until(ready.is_file))
                pids = json.loads(ready.read_text())
                self.assertTrue(all(pid_alive(pid) for pid in pids))
                stop.touch()
                self.assertEqual(process.wait(timeout=8), 130)
                self.assertTrue(wait_until(lambda: not any(pid_alive(pid) for pid in pids)))
                self.assertIn("用户请求停止", log.read_text(encoding="utf-8"))
            finally:
                terminate_process_tree(process)
                for pid in pids:
                    if pid_alive(pid):
                        terminate_process_tree(SimpleNamespace(pid=pid, poll=lambda: None))


if __name__ == "__main__":
    unittest.main()
