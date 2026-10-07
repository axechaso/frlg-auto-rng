"""Launch the Qt interface connected to the existing formal services."""
import argparse
import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import QApplication

from pyside_app.services import AppPaths
from pyside_app.migration import CompleteWindow
from pyside_app.startup_notice import StartupNoticeDialog, should_show_startup_notice


def _schedule_screenshot(app, window, screenshot: Path) -> None:
    """Capture without network checks or abandoning live Qt worker threads."""
    controller = getattr(window, "app_update", None)
    if controller is not None:
        controller.auto_timer.stop()
    app.setQuitOnLastWindowClosed(False)

    def capture():
        screenshot.parent.mkdir(parents=True, exist_ok=True)
        ok = window.grab().save(str(screenshot))
        # closeEvent may defer closing until workers finish. Do not force
        # app.exit() after an ignored close and destroy a running QThread.
        app.lastWindowClosed.connect(lambda: app.exit(0 if ok else 2))
        window.close()

    QTimer.singleShot(400, capture)


def main(argv=None):
    parser = argparse.ArgumentParser(description="FRLG Auto RNG · PySide6")
    parser.add_argument("--page", default="wild", choices=("sid", "tid", "tid_records", "wild", "egg", "script_test", "logs", "history_logs"))
    parser.add_argument("--size", default="1360x840")
    parser.add_argument("--no-device-check", action="store_true")
    parser.add_argument("--data-dir", type=Path, help="Isolated user-data directory for testing")
    parser.add_argument("--screenshot", type=Path)
    args = parser.parse_args(argv)
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("FRLG.AutoRNG.PySide6")
    app = QApplication(sys.argv[:1])
    app.setApplicationName("FRLG Auto RNG")
    app.setStyle("Fusion")
    app.setFont(QFont("Microsoft YaHei UI", 9))
    app.setWindowIcon(QIcon(str(Path(__file__).resolve().parent / "assets/pyside_preview/app-icon.ico")))
    paths = AppPaths(user=args.data_dir.resolve(), output=args.data_dir.resolve() / "runtime") if args.data_dir else AppPaths()
    window = CompleteWindow(paths=paths, auto_detect=not (args.no_device_check or args.screenshot))
    width, height = map(int, args.size.lower().split("x"))
    window.resize(width, height)
    window.select_page(args.page)
    window.show()
    if should_show_startup_notice(paths.user, automated=bool(args.screenshot)):
        StartupNoticeDialog(paths.user, window).exec()
    if args.screenshot:
        _schedule_screenshot(app, window, args.screenshot)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
