"""Run an EasyCon command while teeing its combined output to a UTF-8 log."""

import argparse
import codecs
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
            bufsize=0,
        )
        assert process.stdout is not None
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        try:
            # EasyCon terminates the previous log entry only when the next one
            # starts. Reading by line would therefore hide the final entry
            # throughout a long RNG scan (for example the SPE IV range).
            while chunk := process.stdout.read(4096):
                text = decoder.decode(chunk)
                if not text:
                    continue
                _write_console(text)
                log_file.write(text)
                log_file.flush()
            tail = decoder.decode(b"", final=True)
            if tail:
                _write_console(tail)
                log_file.write(tail)
                log_file.flush()
            return process.wait()
        except KeyboardInterrupt:
            if process.poll() is None:
                process.terminate()
            process.wait()
            return 130
        finally:
            process.stdout.close()


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
