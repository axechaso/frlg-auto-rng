"""Run an EasyCon command while teeing its combined output to a UTF-8 log."""

import argparse
import codecs
import subprocess
import sys
from pathlib import Path

from tid_records import recording_session
from process_control import StopFileWatcher, terminate_process_tree


def _write_console(text: str) -> None:
    stream = sys.stdout
    if stream is None:
        return
    try:
        stream.write(text)
    except UnicodeEncodeError:
        encoding = getattr(stream, "encoding", None) or "ascii"
        safe_text = text.encode(encoding, errors="replace").decode(encoding)
        stream.write(safe_text)
    stream.flush()


def run_logged(
    command: list[str],
    cwd: Path,
    log_path: Path,
    expected_markers: tuple[str, ...] = (),
    *,
    tid_context: Path | None = None,
    tid_records: Path | None = None,
    stop_file: Path | None = None,
) -> int:
    if not command:
        raise ValueError("缺少要执行的 EasyCon 命令")
    if stop_file is not None and stop_file.is_file():
        return 130
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8", newline="") as log_file, recording_session(
        tid_context, tid_records, log_path, warning=lambda message: log_file.write(message + "\n")
    ) as recording:
        process = subprocess.Popen(
            command,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=0,
        )
        assert process.stdout is not None
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        marker_window = ""
        marker_seen = not expected_markers
        marker_window_size = max((len(marker) for marker in expected_markers), default=1)

        def consume_text(text: str) -> None:
            nonlocal marker_seen, marker_window
            if not text:
                return
            combined = marker_window + text
            if not marker_seen and any(marker in combined for marker in expected_markers):
                marker_seen = True
            marker_window = combined[-marker_window_size:]
            _write_console(text)
            log_file.write(text)
            log_file.flush()
            if recording is not None:
                recording.feed(text)

        stop = StopFileWatcher(stop_file, lambda: terminate_process_tree(process))
        stop.__enter__()
        try:
            # EasyCon terminates the previous log entry only when the next one
            # starts. Reading by line would therefore hide the final entry
            # throughout a long RNG scan (for example the SPE IV range).
            while chunk := process.stdout.read(4096):
                text = decoder.decode(chunk)
                consume_text(text)
            tail = decoder.decode(b"", final=True)
            consume_text(tail)
            exit_code = process.wait()
            if stop.requested:
                consume_text("\n[EASYCON_DIAGNOSTIC][工具诊断] 已按用户请求停止本次EasyCon进程。\n")
                return 130
            if not marker_seen:
                diagnostic = (
                    "\n[EASYCON_DIAGNOSTIC][工具诊断] EasyCon 在脚本输出完成/失败状态前结束。"
                    "这通常表示终端收到 Ctrl+C/CTRL_BREAK 或运行被外部取消；"
                    "本次不能视为脚本正常完成。\n"
                )
                consume_text(diagnostic)
                return exit_code if exit_code != 0 else 2
            return exit_code
        except KeyboardInterrupt:
            consume_text(
                "\n[EASYCON_DIAGNOSTIC][工具诊断] 日志运行器收到 Ctrl+C/CTRL_BREAK，"
                "正在终止 EasyCon；本次不是脚本正常完成。\n"
            )
            if process.poll() is None:
                terminate_process_tree(process)
            process.wait()
            return 130
        finally:
            stop.__exit__(None, None, None)
            process.stdout.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--log-path", required=True, type=Path)
    parser.add_argument("--cwd", required=True, type=Path)
    parser.add_argument("--expected-marker", action="append", default=[])
    parser.add_argument("--tid-context", type=Path)
    parser.add_argument("--tid-records", type=Path)
    parser.add_argument("--stop-file", type=Path)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = list(args.command)
    if command and command[0] == "--":
        command.pop(0)
    return run_logged(
        command,
        args.cwd,
        args.log_path,
        tuple(args.expected_marker),
        tid_context=args.tid_context,
        tid_records=args.tid_records,
        stop_file=args.stop_file,
    )


if __name__ == "__main__":
    raise SystemExit(main())
