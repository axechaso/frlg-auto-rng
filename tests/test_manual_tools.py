import base64
import hashlib
import json
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from manual_tools import (
    CaptureMonitorWindow,
    CONTROLLER_OVERLAY_ASSET_DIR,
    CONTROLLER_OVERLAY_BUTTON_LAYOUT,
    CONTROLLER_OVERLAY_HEIGHT,
    CONTROLLER_OVERLAY_SHOULDER_ASSETS,
    CONTROLLER_OVERLAY_WIDTH,
    DEFAULT_GAMEPAD_KEYBOARD_MAP,
    GamePadKey,
    KEYBOARD_GAMEPAD_MAP,
    ManualToolsManager,
    assign_keyboard_key,
    clamp_overlay_position,
    encode_tk_png,
    fit_monitor_frame_size,
    load_key_mapping,
    mapping_button_text,
    next_monitor_zoom_size,
    parse_video_device,
    pressed_keys_text,
    save_key_mapping,
    set_window_topmost,
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
        self.assertEqual(parse_video_device("[3] OBS Virtual Camera"), 3)
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

    def test_controller_overlay_layout_covers_every_supported_control(self):
        self.assertEqual(
            set(CONTROLLER_OVERLAY_BUTTON_LAYOUT)
            | set(CONTROLLER_OVERLAY_SHOULDER_ASSETS),
            set(DEFAULT_GAMEPAD_KEYBOARD_MAP),
        )
        self.assertEqual(
            (CONTROLLER_OVERLAY_WIDTH, CONTROLLER_OVERLAY_HEIGHT),
            (100, 100),
        )

    def test_controller_overlay_position_is_clamped_to_the_visible_screen(self):
        self.assertEqual(clamp_overlay_position(-20, -5, 1920, 1080), (0, 0))
        self.assertEqual(clamp_overlay_position(1900, 1060, 1920, 1080), (1820, 980))
        self.assertEqual(clamp_overlay_position(500, 400, 1920, 1080), (500, 400))

    def test_controller_overlay_uses_exact_easycon_vpad_assets(self):
        expected_hashes = {
            "JoyCon.png": "4083937e39ef7b9fb4fc87f3aa530541c721dee63a2c3fdf25dd58c76ce1b6dc",
            "JoyCon_L_0.png": "f3fa8da10079d514870513e6bcc4d78550ad288d75b7c37c00c79091b328a323",
            "JoyCon_L_1.png": "1efa7b11eb1b872e038d13a3eb18256e1b7e2becab0ecb2e44e8accb50abd7d5",
            "JoyCon_R_0.png": "e87d70d201989b5a2a95d5cf363a645b30b6618a473e3cba33bf183b4f411f52",
            "JoyCon_R_1.png": "94624a2e4499078630005e69b7f8789dfa29ef65541678a6b9a9e88beaa96b60",
            "JoyCon_ZL_0.png": "0e61927e1979e17608367bfbe659b691556a3d402af7c833c32fbc1da13d8cbf",
            "JoyCon_ZL_1.png": "ee86e92769142f9b3ac41991b408b3fef41aadbd3a3ed4837d0a3d68343e6608",
            "JoyCon_ZR_0.png": "5932e692efdcd4461dfcaa043ab84b9fd783dd68625043928367de055b33571c",
            "JoyCon_ZR_1.png": "2378ba72ce1faca8f44c15f63152bff9720e5cefbdf691ef8233590dbf9debd7",
        }
        for filename, expected_hash in expected_hashes.items():
            data = (CONTROLLER_OVERLAY_ASSET_DIR / filename).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), expected_hash)
            self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
            self.assertEqual(struct.unpack(">II", data[16:24]), (100, 100))

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

    def test_monitor_frame_size_preserves_sixteen_by_nine(self):
        self.assertEqual(fit_monitor_frame_size(800, 600), (800, 450))
        self.assertEqual(fit_monitor_frame_size(400, 100), (178, 100))
        self.assertEqual(fit_monitor_frame_size(320, 180), (320, 180))
        self.assertEqual(fit_monitor_frame_size(1920, 1080), (1280, 720))

    def test_monitor_mouse_wheel_uses_bounded_zoom_steps(self):
        self.assertEqual(next_monitor_zoom_size(640, 360, 1), (800, 450))
        self.assertEqual(next_monitor_zoom_size(640, 360, -1), (480, 270))
        self.assertEqual(next_monitor_zoom_size(1280, 720, 1), (1280, 720))
        self.assertEqual(next_monitor_zoom_size(320, 180, -1), (320, 180))

    def test_monitor_pauses_expensive_rendering_during_window_move(self):
        class FakeWindow:
            def __init__(self):
                self.geometry = (100, 120, 650, 420)

            def winfo_x(self):
                return self.geometry[0]

            def winfo_y(self):
                return self.geometry[1]

            def winfo_width(self):
                return self.geometry[2]

            def winfo_height(self):
                return self.geometry[3]

        monitor = object.__new__(CaptureMonitorWindow)
        monitor.window = FakeWindow()
        monitor.root = FakeWindow()
        monitor._closed = False
        monitor._last_window_geometry = None
        monitor._last_host_geometry = None
        monitor._render_paused_until = 0.0

        with patch("manual_tools.time.monotonic", return_value=10.0):
            monitor._on_window_configure()
            self.assertFalse(monitor._render_is_paused())
            monitor.window.geometry = (101, 120, 650, 420)
            monitor._on_window_configure()
            self.assertTrue(monitor._render_is_paused())
            self.assertGreaterEqual(
                monitor._render_paused_until,
                10.0 + CaptureMonitorWindow.DRAG_PAUSE_MS / 1000,
            )

            monitor._render_paused_until = 0.0
            monitor._on_host_window_configure()
            self.assertFalse(monitor._render_is_paused())
            monitor.root.geometry = (100, 121, 650, 420)
            monitor._on_host_window_configure()
            self.assertTrue(monitor._render_is_paused())

    def test_monitor_processing_and_rendering_are_bounded_to_live_preview_rate(self):
        self.assertEqual(CaptureMonitorWindow.RENDER_INTERVAL_MS, 33)
        self.assertEqual(
            CaptureMonitorWindow.FRAME_PROCESS_INTERVAL_MS,
            CaptureMonitorWindow.RENDER_INTERVAL_MS,
        )

    def test_topmost_option_uses_window_attribute(self):
        class FakeWindow:
            def __init__(self):
                self.calls = []

            def attributes(self, *arguments):
                self.calls.append(arguments)

        window = FakeWindow()
        set_window_topmost(window, True)
        set_window_topmost(window, False)
        self.assertEqual(
            window.calls,
            [("-topmost", True), ("-topmost", False)],
        )

    def test_monitor_double_click_toggles_image_only_view(self):
        class FakeWidget:
            def __init__(self):
                self.calls = []

            def pack(self, **kwargs):
                self.calls.append(("pack", kwargs))

            def pack_forget(self):
                self.calls.append(("forget", {}))

        class FakeWindow:
            def __init__(self):
                self.focused = 0

            def focus_force(self):
                self.focused += 1

        from manual_tools import CaptureMonitorWindow

        monitor = object.__new__(CaptureMonitorWindow)
        monitor.canvas = FakeWidget()
        monitor.toolbar = FakeWidget()
        monitor.window = FakeWindow()
        monitor._image_only = False

        self.assertEqual(monitor.toggle_image_only(), "break")
        self.assertTrue(monitor._image_only)
        self.assertEqual(monitor.toolbar.calls[-1][0], "forget")

        self.assertEqual(monitor.toggle_image_only(), "break")
        self.assertFalse(monitor._image_only)
        self.assertEqual(monitor.toolbar.calls[-1][0], "pack")

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
        window.overlay = None
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
    def test_controller_does_not_open_while_easycon_is_running(self, window_type, showerror):
        manager = ManualToolsManager(
            object(),
            port_provider=lambda: "COM4",
            video_provider=lambda: "0",
            process_running=lambda: True,
        )

        manager.open_virtual_controller()

        window_type.assert_not_called()
        showerror.assert_called_once()

    @patch("manual_tools.messagebox.showerror")
    @patch("manual_tools.CaptureMonitorWindow")
    def test_monitor_does_not_open_while_easycon_is_running(self, window_type, showerror):
        manager = ManualToolsManager(
            object(),
            port_provider=lambda: "COM4",
            video_provider=lambda: "[3] Capture Card",
            process_running=lambda: True,
        )

        manager.open_monitor()

        window_type.assert_not_called()
        showerror.assert_called_once()

    @patch("manual_tools.CaptureMonitorWindow")
    def test_monitor_can_open_while_compat_runner_shares_a_preview(self, window_type):
        preview_url = "http://127.0.0.1:43123/mjpeg"
        manager = ManualToolsManager(
            object(),
            port_provider=lambda: "COM4",
            video_provider=lambda: "[3] Capture Card",
            process_running=lambda: True,
            preview_url_provider=lambda: preview_url,
        )

        manager.open_monitor()

        window_type.assert_called_once()
        self.assertIs(window_type.call_args.args[-1], manager.preview_url_provider)

    @patch("manual_tools.CaptureMonitorWindow")
    def test_close_monitor_releases_only_the_monitor(self, window_type):
        monitor = window_type.return_value
        monitor.is_open = True
        manager = ManualToolsManager(
            object(),
            port_provider=lambda: "COM4",
            video_provider=lambda: "0",
            process_running=lambda: False,
        )

        manager.open_monitor()
        manager.close_monitor()

        monitor.close.assert_called_once()
        self.assertIsNone(manager.monitor_window)

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
