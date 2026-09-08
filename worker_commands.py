"""Launch the same background workers from source and windowed EXE builds."""
from __future__ import annotations

import sys
from pathlib import Path

from app_paths import RESOURCE_ROOT


WORKER_SCRIPTS = {
    "sid-capture": "run_sid_reverse_capture.py",
    "sid-traversal": "run_sid_traversal.py",
    "tid-flow": "run_tid_starter_flow.py",
    "easycon-log": "run_easycon_logged.py",
}


def build_worker_command(worker: str, arguments) -> list[str]:
    try:
        script = WORKER_SCRIPTS[worker]
    except KeyError as exc:
        raise ValueError(f"未知后台工作模式: {worker}") from exc
    if getattr(sys, "frozen", False):
        return [sys.executable, "--worker", worker, *arguments]
    interpreter = Path(sys.executable)
    # pythonw has no stdout even when QProcess supplies pipes.
    if interpreter.name.lower() == "pythonw.exe":
        interpreter = interpreter.with_name("python.exe")
    return [str(interpreter), "-u", str(RESOURCE_ROOT / script), *arguments]
