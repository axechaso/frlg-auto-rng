import unittest
from unittest.mock import patch

from easycon import GamePadKey
from manual_tools import (
    KEYBOARD_GAMEPAD_MAP,
    ManualToolsManager,
    parse_video_device,
)


class ManualToolsTests(unittest.TestCase):
    def test_video_device_requires_non_negative_integer(self):
        self.assertEqual(parse_video_device(" 2 "), 2)
        for value in ("", "x", "-1"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    parse_video_device(value)

    def test_keyboard_mapping_matches_existing_manual_controller(self):
        self.assertEqual(KEYBOARD_GAMEPAD_MAP["w"], GamePadKey.TOP)
        self.assertEqual(KEYBOARD_GAMEPAD_MAP["a"], GamePadKey.LEFT)
        self.assertEqual(KEYBOARD_GAMEPAD_MAP["y"], GamePadKey.A)
        self.assertEqual(KEYBOARD_GAMEPAD_MAP["c"], GamePadKey.HOME)

    def test_direction_keys_send_diagonal_and_restore_remaining_direction(self):
        class FakeController:
            is_connected = True

            def __init__(self):
                self.pressed = []
                self.released = []

            def press(self, key):
                self.pressed.append(key)

            def release(self, key):
                self.released.append(key)

        from manual_tools import VirtualControllerWindow

        window = object.__new__(VirtualControllerWindow)
        window.controller = FakeController()
        window._pressed = set()

        window.press(GamePadKey.TOP)
        window.press(GamePadKey.RIGHT)
        window.release(GamePadKey.RIGHT)
        window.release(GamePadKey.TOP)

        self.assertEqual(
            window.controller.pressed,
            [GamePadKey.TOP, GamePadKey.TOP_RIGHT, GamePadKey.TOP],
        )
        self.assertEqual(window.controller.released, [GamePadKey.TOP])

    @patch("manual_tools.VirtualControllerWindow")
    def test_controller_window_is_reused(self, window_type):
        window = window_type.return_value
        window.is_open = True
        manager = ManualToolsManager(
            object(),
            port_provider=lambda: "COM4",
            video_provider=lambda: "0",
            process_running=lambda: False,
        )

        manager.open_virtual_controller()
        manager.open_virtual_controller()

        window_type.assert_called_once()
        window.show.assert_called_once()

    @patch("manual_tools.CaptureMonitorWindow")
    def test_monitor_window_is_reused(self, window_type):
        window = window_type.return_value
        window.is_open = True
        manager = ManualToolsManager(
            object(),
            port_provider=lambda: "COM4",
            video_provider=lambda: "0",
            process_running=lambda: False,
        )

        manager.open_monitor()
        manager.open_monitor()

        window_type.assert_called_once()
        window.show.assert_called_once()

    @patch("manual_tools.messagebox.showerror")
    @patch("manual_tools.VirtualControllerWindow")
    def test_tools_do_not_open_while_easycon_is_running(self, window_type, showerror):
        manager = ManualToolsManager(
            object(),
            port_provider=lambda: "COM4",
            video_provider=lambda: "0",
            process_running=lambda: True,
        )

        manager.open_virtual_controller()

        window_type.assert_not_called()
        showerror.assert_called_once()

    @patch("manual_tools.CaptureMonitorWindow")
    @patch("manual_tools.VirtualControllerWindow")
    def test_close_all_releases_both_tools(self, controller_type, monitor_type):
        controller = controller_type.return_value
        controller.is_open = True
        monitor = monitor_type.return_value
        monitor.is_open = True
        manager = ManualToolsManager(
            object(),
            port_provider=lambda: "COM4",
            video_provider=lambda: "0",
            process_running=lambda: False,
        )
        manager.open_virtual_controller()
        manager.open_monitor()

        manager.close_all()

        controller.close.assert_called_once()
        monitor.close.assert_called_once()
        self.assertIsNone(manager.controller_window)
        self.assertIsNone(manager.monitor_window)


if __name__ == "__main__":
    unittest.main()
