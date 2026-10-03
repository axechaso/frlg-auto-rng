"""Isolated 5,000-log / 100 MiB history-page responsiveness benchmark."""
import argparse
import json
import os
from pathlib import Path
import platform
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QTimer, QEventLoop
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication


def benchmark(output, app_root=None):
    if app_root is not None:
        sys.path.insert(0, str(app_root.resolve()))
    from pyside_app.migration import CompleteWindow
    from pyside_app.services import AppPaths
    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory(prefix="frlg-history-benchmark-") as temp:
        root = Path(temp)
        for i in range(5000):
            folder = root / "runtime" / "pyside6" / f"egg-{i:032x}" / "nested"
            folder.mkdir(parents=True)
            (folder / "run.log").write_text(f"trace {i}\n", encoding="utf-8")
            if i % 100 == 0:
                resource = folder.parent / "ImgLabel"
                resource.mkdir()
                for j in range(10):
                    (resource / f"label-{j}.IL").write_text("asset", encoding="utf-8")
        big = root / "runtime" / "pyside6" / "wild-big.log"
        with big.open("wb") as stream:
            stream.seek(100 * 1024 * 1024)
            stream.write(b"last line\n" * 4000)
        original = (big.stat().st_size, big.stat().st_mtime_ns)
        w = CompleteWindow(paths=AppPaths(user=root / "user", output=root / "runtime" / "pyside6"), auto_detect=False)
        w.show()
        delays = []
        last = time.perf_counter()
        def heartbeat():
            nonlocal last
            now = time.perf_counter()
            delays.append((now - last) * 1000)
            last = now
        timer = QTimer(w)
        timer.timeout.connect(heartbeat)
        timer.start(16)
        QTest.qWait(100)
        start = time.perf_counter()
        w.select_page("history_logs")
        entry_ms = (time.perf_counter() - start) * 1000
        def wait_idle():
            # exec() releases the Python GIL while Qt waits, as the real app
            # does. Repeated QTest.qWait starves an I/O-heavy Python scanner.
            loop=QEventLoop()
            poll=QTimer()
            timeout=time.monotonic()+60
            failure=[]
            def check():
                if time.monotonic()>timeout:
                    failure.append("history workers deadline")
                    loop.quit()
                elif not hasattr(w,"history_controller") or not w.history_controller.busy:
                    poll.stop()
                    QTimer.singleShot(220,loop.quit)
            poll.timeout.connect(check)
            poll.start(20)
            loop.exec()
            poll.stop()
            if failure:
                w.close()
                raise TimeoutError(failure[0])
        wait_idle()
        cold_ms = (time.perf_counter() - start) * 1000
        w.fields["history_search"].setText("trace-no-match")
        wait_idle()
        w.fields["history_search"].clear()
        wait_idle()
        w.select_page("sid")
        start = time.perf_counter()
        w.select_page("history_logs")
        warm_ms = (time.perf_counter() - start) * 1000
        wait_idle()
        timer.stop()
        ordered = sorted(delays)
        result = {"machine": platform.platform(), "wait_method":"qt-event-loop", "logs":5001, "large_log_bytes":original[0],
                  "entry_ms":entry_ms, "cold_complete_ms":cold_ms, "warm_entry_ms":warm_ms,
                  "heartbeat_p95_ms":ordered[int(len(ordered)*.95)], "heartbeat_max_ms":max(ordered),
                  "preview_characters":len(w.history_log_view.toPlainText()),
                  "big_log_unchanged":original == (big.stat().st_size, big.stat().st_mtime_ns)}
        w.close()
        deadline = time.monotonic() + 10
        while w.isVisible() and time.monotonic() < deadline:
            QTest.qWait(10)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--app-root", type=Path, help="Isolated baseline checkout, for the same benchmark method")
    args=parser.parse_args()
    benchmark(args.output, args.app_root)
