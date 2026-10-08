import importlib.util
import sys
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch


@unittest.skipUnless(importlib.util.find_spec("PySide6"), "PySide6 is optional")
class MonitorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(["monitor-tests", "-platform", "offscreen"])

    def setUp(self):
        from PySide6.QtWidgets import QWidget
        from pyside_app.manual import MonitorWindow
        self.host = QWidget()
        self.host.running = False
        self.host.fields = {"video": Mock(currentData=Mock(return_value=0))}
        self.host.run_command = None
        self.w = MonitorWindow(self.host)
        self.w.show()
        self.app.processEvents()

    def tearDown(self):
        self.w.close()
        self.w.deleteLater()
        self.host.close()
        self.host.deleteLater()
        self.app.processEvents()

    def wheel(self, delta):
        from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
        from PySide6.QtGui import QWheelEvent
        event = QWheelEvent(QPointF(60, 60), QPointF(self.w.picture.mapToGlobal(QPoint(60, 60))), QPoint(), QPoint(0, delta), Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
        self.app.sendEvent(self.w.picture, event)
        self.app.processEvents()

    def test_topmost_is_checkable_and_never_adds_a_main_window_owner(self):
        from PySide6.QtCore import Qt

        self.assertIs(self.w.host, self.host)
        self.assertIsNone(self.w.parentWidget())
        self.assertIsNone(self.w.windowHandle().transientParent())
        self.assertFalse(self.w.testAttribute(Qt.WidgetAttribute.WA_QuitOnClose))
        self.assertTrue(self.w.topmost_button.isCheckable())
        self.assertFalse(self.w.topmost_button.isChecked())
        for enabled in (True, False, True):
            self.w.topmost_button.click()
            self.app.processEvents()
            self.assertEqual(self.w.topmost_button.isChecked(), enabled)
            self.assertEqual(bool(self.w.windowFlags() & Qt.WindowType.WindowStaysOnTopHint), enabled)
            self.assertIsNone(self.w.windowHandle().transientParent())
            self.assertTrue(self.w.isVisible())

    def test_minimizing_host_keeps_topmost_preview_visible_without_reconnecting(self):
        self.host.show()
        self.w.toggle_topmost()
        reader = SimpleNamespace(frame=None, status="fake", stop=threading.Event(), thread=Mock(is_alive=Mock(return_value=False)))
        self.w.reader = reader
        with patch.object(self.w, "restart") as restart:
            self.host.showMinimized()
            self.app.processEvents()
            self.assertTrue(self.host.isMinimized())
            self.assertTrue(self.w.isVisible())
            self.assertTrue(self.w.timer.isActive())
            self.assertIs(self.w.reader, reader)
            self.assertFalse(reader.stop.is_set())
            self.host.showNormal()
            self.app.processEvents()
            self.assertTrue(self.w.isVisible())
            restart.assert_not_called()

    def test_topmost_toggle_keeps_picture_only_geometry_and_capture(self):
        self.w.toggle_picture_only()
        reader = SimpleNamespace(frame=None, status="fake", stop=threading.Event(), thread=Mock(is_alive=Mock(return_value=False)))
        self.w.reader = reader
        geometry = self.w.geometry()
        for _ in range(2):
            self.w.toggle_topmost()
            self.app.processEvents()
            self.assertTrue(self.w.picture_only)
            self.assertFalse(self.w.toolbar.isVisible())
            self.assertFalse(self.w.window_chrome.titlebar.isVisible())
            self.assertEqual(self.w.geometry(), geometry)
            self.assertIs(self.w.reader, reader)
            self.assertFalse(reader.stop.is_set())

    def test_close_and_reopen_stop_and_restart_only_the_render_timer(self):
        self.assertTrue(self.w.timer.isActive())
        self.w.close()
        self.assertFalse(self.w.timer.isActive())
        self.w.show()
        self.app.processEvents()
        self.assertTrue(self.w.timer.isActive())
        self.assertIsNone(self.w.windowHandle().transientParent())

    def test_destroying_host_releases_and_disposes_detached_monitor(self):
        from PySide6.QtCore import QCoreApplication, QEvent
        from PySide6.QtWidgets import QWidget
        from pyside_app.manual import MonitorWindow
        from shiboken6 import isValid

        host = QWidget()
        monitor = MonitorWindow(host)
        reader = SimpleNamespace(frame=None, status="fake", stop=threading.Event(), thread=Mock(is_alive=Mock(return_value=False)))
        monitor.reader = reader
        monitor.show()
        host.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.assertTrue(reader.stop.is_set())
        self.assertFalse(isValid(monitor))

    def test_anamorphic_buffer_uses_switch_display_ratio_without_mutating_frame(self):
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QColor, QImage, QPainter
        from pyside_app.monitor_view import VideoSurface
        frame = QImage(640, 480, QImage.Format.Format_RGB32)
        frame.fill(QColor("black"))
        painter = QPainter(frame)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("red"))
        painter.drawEllipse(260, 160, 120, 160)
        painter.end()
        view = VideoSurface()
        view.resize(640, 360)
        view.set_frame(frame)
        rendered = view.grab().toImage()
        xs = [x for x in range(640) if rendered.pixelColor(x, 180).red() > 128]
        ys = [y for y in range(360) if rendered.pixelColor(320, y).red() > 128]
        self.assertAlmostEqual(len(xs), len(ys), delta=2)
        self.assertEqual((frame.width(), frame.height()), (640, 480))
        view.deleteLater()

    def test_wheel_and_buttons_enlarge_and_shrink_without_layout_limit(self):
        self.w.resize_video(640)
        self.app.processEvents()
        initial = self.w.size()
        self.wheel(120)
        larger = self.w.size()
        self.assertGreater(larger.width(), initial.width())
        self.wheel(-120)
        self.assertEqual(self.w.size(), initial)
        self.w.zoom_buttons["−"].click()
        self.app.processEvents()
        self.assertLess(self.w.width(), initial.width())
        self.w.zoom_buttons["+"].click()
        self.app.processEvents()
        self.assertEqual(self.w.size(), initial)
        self.wheel(50)
        self.assertEqual(self.w.size(), initial)
        self.wheel(70)
        self.assertGreater(self.w.width(), initial.width())
        self.w.status.setText("Long capture connection message " * 10)
        self.w.resize_video(320)
        self.app.processEvents()
        self.assertEqual((self.w.picture.width(), self.w.picture.height()), (320, 180))

    def test_picture_only_removes_all_chrome_and_restores_after_zoom(self):
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtTest import QTest
        w = self.w
        QTest.mouseDClick(w.picture, Qt.MouseButton.LeftButton)
        self.app.processEvents()
        self.assertTrue(w.picture_only)
        self.assertFalse(w.toolbar.isVisible())
        self.assertFalse(w.window_chrome.titlebar.isVisible())
        self.assertEqual(w.picture.mapTo(w, QPoint()), QPoint())
        self.assertEqual(w.picture.size(), w.size())
        self.assertAlmostEqual(w.width() / w.height(), 16 / 9, delta=.01)
        self.wheel(-120)
        self.assertFalse(w.window_chrome.titlebar.isVisible())
        self.assertEqual(w.picture.size(), w.size())
        QTest.mouseDClick(w.picture, Qt.MouseButton.LeftButton)
        self.app.processEvents()
        self.assertFalse(w.picture_only)
        self.assertTrue(w.toolbar.isVisible())
        self.assertTrue(w.window_chrome.titlebar.isVisible())
        self.assertGreater(w.picture.mapTo(w, QPoint()).y(), 34)

    def test_escape_restores_window_instead_of_closing_picture_only(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        self.w.toggle_picture_only()
        QTest.keyClick(self.w.picture, Qt.Key.Key_Escape)
        self.app.processEvents()
        self.assertTrue(self.w.isVisible())
        self.assertFalse(self.w.picture_only)

    def test_zoom_does_not_restart_reader_and_close_releases_it(self):
        reader = SimpleNamespace(frame=None, status="fake", stop=threading.Event(), thread=Mock(is_alive=Mock(return_value=False)))
        self.w.reader = reader
        self.w.zoom_by(-1)
        self.w.toggle_picture_only()
        self.w.toggle_picture_only()
        self.assertIs(self.w.reader, reader)
        self.assertFalse(reader.stop.is_set())
        self.w.close()
        self.assertTrue(reader.stop.is_set())

    def test_running_monitor_reuses_preview_and_never_selects_capture(self):
        self.host.running = True
        self.host.run_command = SimpleNamespace(preview_url="http://127.0.0.1:12345/mjpeg")
        self.assertEqual(self.w.current_source(), self.host.run_command.preview_url)
        self.host.fields["video"].currentData.assert_not_called()
        self.host.run_command.preview_url = ""
        with self.assertRaisesRegex(ValueError, "共享画面"):
            self.w.current_source()

    def test_capture_requests_widescreen_and_releases_device(self):
        import numpy as np
        from pyside_app.manual import FrameReader
        reader = object.__new__(FrameReader)
        reader.source = 0
        reader.stop = threading.Event()
        reader.frame = None
        capture = Mock()
        def read():
            reader.stop.set()
            return True, np.zeros((480, 640, 3), dtype=np.uint8)
        capture.read.side_effect = read
        cv = SimpleNamespace(VideoCapture=Mock(return_value=capture), CAP_DSHOW=700, CAP_PROP_FRAME_WIDTH=3, CAP_PROP_FRAME_HEIGHT=4, CAP_PROP_BUFFERSIZE=38, COLOR_BGR2RGB=4, cvtColor=lambda frame, code: frame)
        with patch.dict("sys.modules", cv2=cv):
            reader.run()
        capture.set.assert_any_call(3, 1280)
        capture.set.assert_any_call(4, 720)
        capture.release.assert_called_once()
        self.assertEqual((reader.frame.width(), reader.frame.height()), (640, 480))


@unittest.skipUnless(sys.platform == "win32" and importlib.util.find_spec("PySide6"), "Native Windows / PySide6 required")
class NativeFloatingWindowTests(unittest.TestCase):
    def test_real_application_minimize_pin_and_close_without_devices(self):
        import json
        import os
        from pathlib import Path
        import subprocess
        import sys

        root = Path(__file__).resolve().parents[1]
        environment = dict(os.environ, PYTHONIOENCODING="utf-8", QT_QPA_PLATFORM="windows")
        result = subprocess.run(
            [sys.executable, str(root / "tools/verify_floating_windows.py")],
            cwd=root, env=environment, capture_output=True, text=True, encoding="utf-8", timeout=45,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["platform"], "windows")
        self.assertFalse(report["hardware_connected"])
        self.assertGreaterEqual(report["checks"], 60)
        minimized = [state for state in report["states"] if state["stage"] == "main_minimized"]
        self.assertEqual({state["window"] for state in minimized}, {"monitor", "overlay"})
        for state in minimized:
            self.assertTrue(state["native_visible"])
            self.assertTrue(state["native_topmost"])
            self.assertEqual(state["native_owner"], 0)


if __name__ == "__main__":
    unittest.main()
