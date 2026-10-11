import importlib.util
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


@unittest.skipUnless(importlib.util.find_spec("PySide6"), "PySide6 is optional")
class AutoConnectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(["connection-tests", "-platform", "offscreen"])

    def setUp(self):
        from pyside_app.services import AppPaths
        from pyside_app.migration import CompleteWindow
        self.temp = tempfile.TemporaryDirectory()
        self.paths = AppPaths(user=Path(self.temp.name), output=Path(self.temp.name) / "runtime")
        self.w = CompleteWindow(paths=self.paths, auto_detect=False)
        self.w.app_update.auto_timer.stop()
        self.w._fill(self.w.fields["port"], [("COM2", "COM2"), ("COM7", "COM7")])
        self.w.devices = ({"COM2", "COM7"}, {})
        self.w.refresh_state()

    def tearDown(self):
        self.w.close()
        for _ in range(5):
            self.app.processEvents()
        self.w.deleteLater()
        self.app.processEvents()
        self.temp.cleanup()

    def wait(self):
        from PySide6.QtTest import QTest
        for _ in range(150):
            if not self.w.accessories.controller.job:
                break
            QTest.qWait(10)
        self.assertIsNone(self.w.accessories.controller.job)

    def test_auto_connect_selects_verified_port_without_opening_keyboard_or_pad(self):
        connection = Mock(port_name="COM7", baudrate=9600, is_connected=True)
        with patch("easycon.EasyConController", return_value=connection), patch("pyside_app.controller_keyboard.ControllerKeyboard.start") as keyboard:
            self.w.actions["自动连接"].click()
            self.wait()
        self.assertEqual(connection.connect.call_args.args, (None,))
        self.assertEqual(connection.connect.call_args.kwargs["preferred_port"], "COM2")
        self.assertEqual(self.w.fields["port"].currentData(), "COM7")
        self.assertEqual(self.w.preferred_controller_port, "COM7")
        self.assertEqual(self.w.actions["自动连接"].text(), "断开单片机")
        self.assertFalse(self.w.accessories.controller.isVisible())
        self.assertFalse(self.w.accessories.controller.overlay.isVisible())
        self.assertFalse(self.w.accessories.controller.keyboard_active)
        keyboard.assert_not_called()
        connection.press.assert_not_called()
        connection.set_stick.assert_not_called()
        with patch("pyside_app.controller_keyboard.ControllerKeyboard.start"):
            self.w.accessories.open_controller()
        self.assertTrue(self.w.accessories.controller.keyboard_active)
        self.assertTrue(self.w.accessories.controller.overlay.isVisible())
        self.w.actions["自动连接"].click()
        connection.disconnect.assert_called_once()
        self.assertIsNone(self.w.accessories.controller.controller)

    def test_cancel_connection_rejects_late_result_and_releases_handle(self):
        gate, entered = threading.Event(), threading.Event()
        connection = Mock(port_name="COM7", baudrate=115200, is_connected=True)
        connection.connect.side_effect = lambda *args, **kwargs: (entered.set(), gate.wait(2), True)[-1]
        try:
            with patch("easycon.EasyConController", return_value=connection):
                self.w.actions["自动连接"].click()
                self.assertTrue(entered.wait(1))
                self.assertEqual(self.w.actions["自动连接"].text(), "取消连接")
                self.assertTrue(self.w.actions["自动连接"].isEnabled())
                self.assertFalse(self.w.search_button.isEnabled())
                self.assertFalse(self.w.launch_job(Mock(), Mock(), "must not start"))
                self.w.actions["自动连接"].click()
                gate.set()
                self.wait()
        finally:
            gate.set()
        self.assertIsNone(self.w.accessories.controller.controller)
        self.assertEqual(self.w.fields["port"].currentData(), "COM2")
        self.assertEqual(self.w.preferred_controller_port, "")
        connection.disconnect.assert_called_once()

    def test_port_change_cancels_automatic_probe_without_stealing_new_selection(self):
        gate, entered = threading.Event(), threading.Event()
        connection = Mock(port_name="COM2", baudrate=115200, is_connected=True)
        connection.connect.side_effect = lambda *args, **kwargs: (entered.set(), gate.wait(2), True)[-1]
        try:
            with patch("easycon.EasyConController", return_value=connection):
                self.w.actions["自动连接"].click()
                self.assertTrue(entered.wait(1))
                self.w.fields["port"].setCurrentIndex(1)
                gate.set()
                self.wait()
        finally:
            gate.set()
        self.assertEqual(self.w.fields["port"].currentData(), "COM7")
        self.assertIsNone(self.w.accessories.controller.controller)
        connection.disconnect.assert_called_once()

    def test_run_release_closes_auto_connection_for_existing_runner(self):
        connection = Mock(port_name="COM7", baudrate=115200, is_connected=True)
        with patch("easycon.EasyConController", return_value=connection):
            self.w.actions["自动连接"].click()
            self.wait()
        self.assertTrue(self.w.accessories.release_for_run())
        connection.disconnect.assert_called_once()
        self.assertIsNone(self.w.accessories.controller.controller)
        self.assertEqual(self.w.fields["port"].currentData(), "COM7")

    def test_auto_connect_can_reuse_controller_after_overlay_and_dialog_close(self):
        connections = [Mock(port_name="COM7", baudrate=115200, is_connected=True) for _ in range(3)]
        with patch("easycon.EasyConController", side_effect=connections), patch(
            "pyside_app.controller_keyboard.ControllerKeyboard.start"):
            self.w.actions["自动连接"].click()
            self.wait()
            self.w.accessories.open_controller()
            controller = self.w.accessories.controller
            controller.overlay.exit_control()
            self.assertFalse(controller.overlay_requested)
            self.w.actions["自动连接"].click()
            self.wait()
            self.assertIs(controller.controller, connections[1])
            self.assertFalse(controller.keyboard_active)
            self.assertFalse(controller.overlay.isVisible())
            controller.close()
            self.assertTrue(controller.shutting_down)
            self.w.actions["自动连接"].click()
            self.wait()
            self.assertIs(controller.controller, connections[2])
            self.assertFalse(controller.shutting_down)
            self.assertFalse(controller.keyboard_active)
            self.assertFalse(controller.isVisible())

    def test_no_connection_during_script_or_device_job(self):
        with patch("easycon.EasyConController") as constructor:
            self.w.running = True
            self.w.accessories.auto_connect()
            self.w.running = False
            self.w.job = Mock()
            self.w.accessories.auto_connect()
            self.w.job = None
        constructor.assert_not_called()

    def test_failed_handshake_does_not_select_or_remember_an_unverified_port(self):
        connection = Mock(port_name="COM7", baudrate=115200, is_connected=False,
                          connection_error="COM7 拒绝访问，串口可能已被占用")
        connection.connect.return_value = False
        with patch("easycon.EasyConController", return_value=connection):
            self.w.actions["自动连接"].click()
            self.wait()
        self.assertEqual(self.w.fields["port"].currentData(), "COM2")
        self.assertEqual(self.w.preferred_controller_port, "")
        self.assertIsNone(self.w.accessories.controller.controller)
        self.assertIn("占用", self.w.status_text)
        self.assertEqual(self.w.actions["自动连接"].text(), "自动连接")

    def test_successful_port_is_saved_and_prioritized_on_next_detection(self):
        from pyside_app.migration import CompleteWindow
        connection = Mock(port_name="COM7", baudrate=115200, is_connected=True)
        with patch("easycon.EasyConController", return_value=connection):
            self.w.actions["自动连接"].click()
            self.wait()
        self.w.close()
        self.app.processEvents()
        old, self.w = self.w, CompleteWindow(paths=self.paths, auto_detect=False)
        self.w.app_update.auto_timer.stop()
        old.deleteLater()
        self.assertEqual(self.w.preferred_controller_port, "COM7")
        def job(work, finish, status):
            finish(work(lambda: False, lambda text: None))
        with patch("pyside_app.window.probe_easycon_devices", return_value=({"COM2", "COM7"}, {3: "Fake video"}, "devices")), patch.object(self.w, "launch_job", side_effect=job):
            self.w.detect_devices()
        self.assertEqual(self.w.fields["port"].currentData(), "COM7")

    def test_device_actions_do_not_overlap_at_minimum_window_width(self):
        from PySide6.QtCore import QPoint
        from PySide6.QtTest import QTest
        buttons = [self.w.actions[title] for title in
                   ("重新检测", "自动连接", "虚拟手柄", "监视窗口")]
        for width in (900, 1180, 1360, 900):
            self.w.resize(width, 740)
            self.w.show()
            QTest.qWait(30)
            self.w._layout_quick_settings()
            self.app.processEvents()
            for left, right in zip(buttons, buttons[1:]):
                left_end = left.mapTo(self.w, QPoint(left.width(), 0)).x()
                right_start = right.mapTo(self.w, QPoint(0, 0)).x()
                self.assertLessEqual(left_end, right_start, f"buttons overlap at {width}px")
            end = buttons[-1].mapTo(self.w, QPoint(buttons[-1].width(), 0)).x()
            self.assertLess(end, self.w.width())


if __name__ == "__main__":
    unittest.main()
