"""Console-independent cancellation for GUI-owned worker process trees."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import threading


def terminate_process_tree(process: subprocess.Popen) -> None:
    """Only target the still-live Popen instance owned by this task."""
    if process.poll() is not None:
        return
    if os.name == "nt":
        # terminate()/CTRL_BREAK on the wrapper alone can leave ezcon alive.
        # Pass argv, not a shell command; never kill by executable name.
        result = subprocess.run(
            ["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode != 0 and process.poll() is None:
            raise RuntimeError("本次进程树终止失败：" + result.stdout.strip())
    else:
        process.terminate()


class StopFileWatcher:
    """A private per-run file works with pythonw, packaged GUIs and new consoles."""
    def __init__(self, path: Path | None, on_stop):
        self.path = Path(path) if path is not None else None
        self.on_stop = on_stop
        self.finished = threading.Event()
        self.thread = None
        self.error: Exception | None = None

    @property
    def requested(self) -> bool:
        return self.path is not None and self.path.is_file()

    def __enter__(self):
        if self.path is not None:
            self.thread = threading.Thread(target=self._watch, daemon=True, name="worker-stop")
            self.thread.start()
        return self

    def _watch(self):
        while not self.finished.is_set():
            if self.requested:
                try:
                    self.on_stop()
                except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
                    self.error = exc
                return
            self.finished.wait(0.1)

    def __exit__(self, *_):
        self.finished.set()
        if self.thread is not None:
            self.thread.join(timeout=0.5)
