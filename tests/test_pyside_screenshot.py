import importlib.util
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


@unittest.skipUnless(importlib.util.find_spec("PySide6"), "PySide6 is optional")
class ScreenshotLifecycleTests(unittest.TestCase):
    def run_capture(self, *, ok=True, controller=True):
        from run_pyside6_gui import _schedule_screenshot

        app = Mock()
        timer = Mock()
        window = Mock()
        window.app_update = SimpleNamespace(auto_timer=timer) if controller else None
        window.grab.return_value.save.return_value = ok
        window.close.return_value = False  # A worker still owns the close.
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "screenshots" / "page.png"
            with patch("run_pyside6_gui.QTimer.singleShot") as schedule:
                _schedule_screenshot(app, window, destination)
            schedule.assert_called_once()
            self.assertEqual(schedule.call_args.args[0], 400)
            schedule.call_args.args[1]()
            self.assertTrue(destination.parent.is_dir())
            window.grab.return_value.save.assert_called_once_with(str(destination))
        return app, window, timer

    def test_automated_capture_stops_auto_update_but_does_not_force_exit(self):
        app, window, timer = self.run_capture()
        timer.stop.assert_called_once()
        app.setQuitOnLastWindowClosed.assert_called_once_with(False)
        window.close.assert_called_once()
        app.exit.assert_not_called()
        app.lastWindowClosed.connect.call_args.args[0]()
        app.exit.assert_called_once_with(0)

    def test_save_failure_reports_nonzero_only_after_workers_allow_close(self):
        app, _, _ = self.run_capture(ok=False)
        app.exit.assert_not_called()
        app.lastWindowClosed.connect.call_args.args[0]()
        app.exit.assert_called_once_with(2)

    def test_capture_without_update_controller_uses_same_safe_close_path(self):
        app, _, timer = self.run_capture(controller=False)
        timer.stop.assert_not_called()
        app.exit.assert_not_called()
        app.lastWindowClosed.connect.call_args.args[0]()
        app.exit.assert_called_once_with(0)
