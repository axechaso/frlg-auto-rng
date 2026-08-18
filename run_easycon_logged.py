"""Run an EasyCon command while teeing its combined output to a UTF-8 log."""

import argparse
import subprocess
import sys
from pathlib import Path


def _write_console(text: str) -> None:
    try:
        sys.stdout.write(text)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "ascii"
        safe_text = text.encode(encoding, errors="replace").decode(encoding)
        sys.stdout.write(safe_text)
    sys.stdout.flush()


def run_logged(command: list[str], cwd: Path, log_path: Path) -> int:
    if not command:
        raise ValueError("缺少要执行的 EasyCon 命令")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8", newline="") as log_file:
        process = subprocess.Popen(
            command,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        assert process.stdout is not None
        try:
            for line in process.stdout:
                _write_console(line)
                log_file.write(line)
                log_file.flush()
            return process.wait()
        except KeyboardInterrupt:
            if process.poll() is None:
                process.terminate()
            return 130


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--log-path", required=True, type=Path)
    parser.add_argument("--cwd", required=True, type=Path)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = list(args.command)
    if command and command[0] == "--":
        command.pop(0)
    return run_logged(command, args.cwd, args.log_path)


if __name__ == "__main__":
    raise SystemExit(main())
