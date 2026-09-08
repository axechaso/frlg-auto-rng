"""Exercise packaged worker parsers and log streaming without EasyCon/devices."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def verify(executable: Path) -> None:
    executable = executable.resolve(strict=True)
    environment = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    checks = {"sid-capture": "--request-json", "tid-flow": "--flow-dir",
              "sid-traversal": "--named-rival", "easycon-log": "--expected-marker"}
    for worker, option in checks.items():
        result = subprocess.run([str(executable), "--worker", worker, "--help"],
                                capture_output=True, timeout=30, env=environment)
        text = (result.stdout + result.stderr).decode("utf-8", errors="replace")
        if result.returncode != 0 or option not in text or "--screenshot" in text:
            raise RuntimeError(f"{worker} did not enter its worker parser: {result.returncode}\n{text}")
        print(f"PASS: frozen {worker} parser", flush=True)
    with tempfile.TemporaryDirectory(prefix="frlg-worker-smoke-") as temp:
        root = Path(temp)
        log, stop = root / "输出 log.txt", root / "worker.stop"
        expected = "后台输出：中文 / SID / TID\n"
        code = f"import sys; sys.stdout.buffer.write({expected.encode('utf-8')!r}); sys.stdout.buffer.flush(); sys.exit(7)"
        command = [str(executable), "--worker", "easycon-log", "--log-path", str(log),
                   "--cwd", str(root), "--stop-file", str(stop), "--", sys.executable, "-u", "-c", code]
        result = subprocess.run(command, capture_output=True, timeout=30, env=environment)
        if result.returncode != 7 or expected not in result.stdout.decode("utf-8", errors="replace"):
            raise RuntimeError(f"Frozen worker lost output/exit status: {result.returncode} {result.stdout!r} {result.stderr!r}")
        if log.read_text(encoding="utf-8") != expected:
            raise RuntimeError("Frozen worker did not save the exact UTF-8 log")
        log.unlink()
        stop.touch()
        result = subprocess.run(command, capture_output=True, timeout=30, env=environment)
        if result.returncode != 130 or log.exists():
            raise RuntimeError("Frozen worker ignored the stop file")
        print("PASS: frozen log worker UTF-8 pipes, file log, exit code and pre-start cancellation", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", required=True, type=Path)
    args = parser.parse_args()
    verify(args.exe)


if __name__ == "__main__":
    main()
