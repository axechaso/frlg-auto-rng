"""Run an ECS project with the in-process EasyCon implementation."""

from __future__ import annotations

import argparse
from contextlib import ExitStack
import signal
import threading
from pathlib import Path

from capture_broker_process import CaptureBrokerProcess
from capture_broker import CAPTURE_API_DIRECTSHOW
from console_output import write_console
from easycon.native_backend import NativeEasyConBackend
from easycon.native.preview import NativePreviewServer
from process_control import StopFileWatcher
from tid_records import recording_session


def run_native(
    project: Path,
    *,
    port: str,
    video: int,
    capture_api: int = CAPTURE_API_DIRECTSHOW,
    preview_port: int = 0,
    verbose: bool = False,
    log_path: Path | None = None,
    stop_file: Path | None = None,
    tid_context: Path | None = None,
    tid_records: Path | None = None,
    fingerprint_warnings: bool = False,
    expected_marker: list[str] | None = None,
) -> int:
    project = Path(project).resolve()
    if stop_file is not None and stop_file.is_file():
        return 130
    log_path = Path(log_path) if log_path is not None else project.parent / "native-easycon.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    lock = threading.Lock()
    cancelled = threading.Event()
    with ExitStack() as stack:
        log = stack.enter_context(log_path.open("w", encoding="utf-8", newline=""))
        recording = stack.enter_context(recording_session(tid_context, tid_records, log_path))
        def emit(level: str, message: str) -> None:
            if level == "DEBUG" and not verbose:
                return
            # Machine records must retain their exact line prefix for TID/SID
            # parsers. PRINT continuation is also preserved byte for byte.
            line = message if level == "SCRIPT" else f"[{level}] {message}\n"
            with lock:
                log.write(line)
                log.flush()
                if recording is not None:
                    recording.feed(line)
            write_console(line)

        broker = CaptureBrokerProcess(device_index=video, capture_api=capture_api)
        backend = NativeEasyConBackend(
            frame_client_factory=lambda: broker.client(),
            log_callback=emit,
        )
        watcher = StopFileWatcher(stop_file, cancelled.set)
        stack.enter_context(watcher)
        if threading.current_thread() is threading.main_thread():
            for sig in (signal.SIGINT, signal.SIGTERM, *([signal.SIGBREAK] if hasattr(signal, "SIGBREAK") else [])):
                previous = signal.signal(sig, lambda *_: cancelled.set())
                stack.callback(signal.signal, sig, previous)
        preview = None
        try:
            # Compile before opening either device, including when invoked
            # directly without a GUI preflight.
            from automation.native_runtime import validate_native_runtime
            check = validate_native_runtime(project, fingerprint_warning_only=fingerprint_warnings)
            if not check.ok:
                emit("ERROR", "\n".join(check.errors))
                return 2
            for warning in check.warnings:
                emit("WARNING", warning)
            if cancelled.is_set():
                return 130
            emit("INFO", f"启动原生视频源: device={video}, api={capture_api}")
            if not broker.start(cancel_event=cancelled):
                if cancelled.is_set():
                    return 130
                emit("ERROR", broker.failure or "共享视频源启动失败")
                return 1
            if cancelled.is_set():
                return 130
            if preview_port:
                preview = NativePreviewServer(preview_port, broker.client)
                preview.start()
            backend.connect(port)
            if cancelled.is_set():
                return 130
            result = backend.run_script_text(project.read_text(encoding="utf-8-sig"),
                name=str(project), script_dir=project.parent, cancel_event=cancelled)
            if cancelled.is_set():
                return 130
            if result.exit_code == 0 and expected_marker and not any(marker in result.stdout for marker in expected_marker):
                emit("ERROR", "脚本结束前没有输出完成/失败状态，本次不能视为流程正常完成。")
                return 2
            return int(result.exit_code or 0)
        except Exception as exc:
            emit("ERROR", f"原生伊机控运行失败: {exc}")
            return 1
        finally:
            try:
                try:
                    backend.disconnect()
                except Exception as exc:
                    emit("WARNING", f"断开原生伊机控失败: {exc}")
            finally:
                try:
                    if preview is not None:
                        preview.close()
                finally:
                    broker.stop()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--port", required=True)
    parser.add_argument("--video", required=True, type=int)
    parser.add_argument("--capture-api", type=int, default=CAPTURE_API_DIRECTSHOW)
    parser.add_argument("--preview-port", type=int, default=0)
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--fingerprint-warnings", action="store_true")
    parser.add_argument("--expected-marker", action="append")
    parser.add_argument("--log-path", type=Path)
    parser.add_argument("--stop-file", type=Path)
    parser.add_argument("--tid-context", type=Path)
    parser.add_argument("--tid-records", type=Path)
    args = parser.parse_args(argv)
    return run_native(**vars(args))


if __name__ == "__main__":
    raise SystemExit(main())
