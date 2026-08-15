import base64
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from manual_tools import (
    DEFAULT_GAMEPAD_KEYBOARD_MAP,
    GamePadKey,
    KEYBOARD_GAMEPAD_MAP,
    ManualToolsManager,
    assign_keyboard_key,
    encode_tk_png,
    load_key_mapping,
    mapping_button_text,
    parse_video_device,
    pressed_keys_text,
    save_key_mapping,
)


class ManualToolsTests(unittest.TestCase):
    def test_import_does_not_eagerly_load_easycon(self):
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; import manual_tools; raise SystemExit('easycon' in sys.modules)",
            ],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

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

    def test_key_mapping_round_trip_and_invalid_file_falls_back_to_defaults(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "keymap.json"
            mapping = dict(DEFAULT_GAMEPAD_KEYBOARD_MAP)
            assign_keyboard_key(mapping, GamePadKey.A, "p")
            save_key_mapping(mapping, path)
            self.assertEqual(load_key_mapping(path), mapping)

            invalid = dict(mapping)
            invalid[GamePadKey.B] = invalid[GamePadKey.A]
            path.write_text(json.dumps(invalid), encoding="utf-8")
            self.assertEqual(load_key_mapping(path), DEFAULT_GAMEPAD_KEYBOARD_MAP)

    def test_assigning_an_in_use_key_swaps_the_two_mappings(self):
        mapping = dict(DEFAULT_GAMEPAD_KEYBOARD_MAP)
        assign_keyboard_key(mapping, GamePadKey.A, "u")
        self.assertEqual(mapping[GamePadKey.A], "u")
        self.assertEqual(mapping[GamePadKey.B], "y")

    def test_pressed_key_display_is_compact_and_ordered(self):
        self.assertEqual(
            pressed_keys_text({GamePadKey.RIGHT, GamePadKey.A, GamePadKey.TOP}),
            "A + ↑ + →",
        )
        self.assertEqual(pressed_keys_text(set()), "无")

    def test_mapping_button_text_shows_controller_and_keyboard_key(self):
        self.assertEqual(mapping_button_text(GamePadKey.A, "y"), "A\n[Y]")
        self.assertEqual(mapping_button_text(GamePadKey.TOP, "w"), "↑\n[W]")

    def test_monitor_frames_are_encoded_as_png_for_tk(self):
        class FakePng:
            def tobytes(self):
                return b"\x89PNG\r\n\x1a\nframe"

        class FakeCv2:
            IMWRITE_PNG_COMPRESSION = 16

            def __init__(self):
                self.arguments = None

            def imencode(self, *arguments):
                self.arguments = arguments
                return True, FakePng()

        cv2_module = FakeCv2()
        payload = encode_tk_png(object(), cv2_module)
        self.assertTrue(base64.b64decode(payload).startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertEqual(cv2_module.arguments[0], ".png")
        self.assertEqual(cv2_module.arguments[2], [16, 1])

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

        class FakeVariable:
            def __init__(self):
                self.value = ""

            def set(self, value):
                self.value = value

        from manual_tools import VirtualControllerWindow

        window = object.__new__(VirtualControllerWindow)
        window.controller = FakeController()
        window._native_gamepad_key = GamePadKey
        window._pressed = set()
        window.pressed_var = FakeVariable()

        window.press(GamePadKey.TOP)
        window.press(GamePadKey.RIGHT)
        window.release(GamePadKey.RIGHT)
        window.release(GamePadKey.TOP)

        self.assertEqual(
            window.controller.pressed,
            [GamePadKey.TOP, GamePadKey.TOP_RIGHT, GamePadKey.TOP],
        )
        self.assertEqual(window.controller.released, [GamePadKey.TOP])
        self.assertEqual(window.pressed_var.value, "无")

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
