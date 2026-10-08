"""Check real Windows ownership/minimization without devices or keyboard hooks."""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def verify() -> dict:
    if sys.platform != "win32":
        raise RuntimeError("This acceptance check requires native Windows windows.")

    from PySide6.QtGui import QColor, QImage
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QWidget
    from easycon import GamePadKey
    from pyside_app.manual import ControllerWindow
    from pyside_app.migration import CompleteWindow
    from pyside_app.services import AppPaths

    app = QApplication(["floating-window-check", "-platform", "windows"])
    app.setQuitOnLastWindowClosed(False)
    if app.platformName() != "windows":
        raise AssertionError("An offscreen result is not native Windows acceptance.")
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetWindow.restype = wintypes.HWND
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.IsIconic.restype = wintypes.BOOL
    user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    states = []
    checks = 0

    def require(condition, message):
        nonlocal checks
        checks += 1
        if not condition:
            raise AssertionError(message)

    def inspect(stage, name, widget):
        hwnd = int(widget.winId())
        state = {
            "stage": stage, "window": name,
            "qt_visible": widget.isVisible(),
            "native_visible": bool(user32.IsWindowVisible(hwnd)),
            "native_owner": int(user32.GetWindow(hwnd, 4) or 0),
            "native_topmost": bool(user32.GetWindowLongPtrW(hwnd, -20) & 8),
            "qt_transient_parent": widget.windowHandle().transientParent() is not None,
        }
        states.append(state)
        return state

    def a_button_color(overlay):
        image = overlay.grab().toImage()
        ratio = image.devicePixelRatio()
        return image.pixelColor(round(83 * ratio), round(33 * ratio)).name()

    class OfflineReader:
        instances = []

        def __init__(self, source):
            self.source = source
            self.stop = threading.Event()
            self.thread = SimpleNamespace(is_alive=lambda: False)
            self.frame = QImage(640, 360, QImage.Format.Format_RGB32)
            self.frame.fill(QColor("#17465e"))
            self.latest = (1, self.frame)
            self.status = "offline generated frame"
            self.instances.append(self)

    with tempfile.TemporaryDirectory(prefix="frlg-floating-check-") as directory, \
            patch("pyside_app.manual.FrameReader", OfflineReader), \
            patch("pyside_app.controller_keyboard.ControllerKeyboard.start") as keyboard_start, \
            patch("easycon.EasyConController") as serial_constructor:
        root = Path(directory)
        window = CompleteWindow(paths=AppPaths(user=root, output=root / "runtime"), auto_detect=False)
        window.app_update.auto_timer.stop()
        probe = QWidget()
        probe.setWindowTitle("Offline ordinary window")
        try:
            window.show()
            window.fields["port"].clear()
            window.fields["port"].addItem("Offline fake port", "OFFLINE")
            window.fields["port"].setCurrentIndex(0)
            window.fields["video"].clear()
            window.fields["video"].addItem("Offline generated image", 0)
            window.fields["video"].setCurrentIndex(0)
            window.devices = ({"OFFLINE"}, {0: "Offline generated image"})
            window.accessories.open_monitor()
            monitor = window.accessories.monitor
            monitor.topmost_button.click()
            controller = window.accessories.controller = ControllerWindow(window)
            transport = Mock(is_connected=True, port_name="OFFLINE")
            controller.controller = transport
            controller.native = GamePadKey
            window.accessories.open_controller()
            overlay = controller.overlay
            QTest.qWait(200)
            reader = monitor.reader
            require(len(OfflineReader.instances) == 1, f"Preview count={len(OfflineReader.instances)}, status={monitor.status.text()!r}, source={window.fields['video'].currentData()!r}.")
            require(not controller.isVisible(), "Floating pad opened the large controller.")
            for name, widget in (("monitor", monitor), ("overlay", overlay)):
                state = inspect("initial", name, widget)
                require(state["native_owner"] == 0, f"{name} still has a native owner.")
                require(not state["qt_transient_parent"], f"{name} has a Qt transient parent.")
                require(state["native_topmost"], f"{name} is not natively topmost.")
                require(state["native_visible"], f"{name} is not natively visible.")

            # Use the real application's caption button, not a fake hide signal.
            window.window_chrome.titlebar.buttons["minimize"].click()
            QTest.qWait(250)
            require(user32.IsIconic(int(window.winId())), "Main window was not minimized.")
            for name, widget in (("monitor", monitor), ("overlay", overlay)):
                state = inspect("main_minimized", name, widget)
                require(state["native_visible"], f"Minimizing main hid {name}.")
                require(state["native_topmost"], f"Minimizing main removed {name} topmost.")
                require(state["native_owner"] == 0, f"Minimizing main re-owned {name}.")
            require(controller.keyboard_allowed(), "Minimizing main disabled floating input.")
            require(controller.keyboard.feed(0x43, True), "Fake A press was rejected.")
            app.processEvents()
            require("A" in controller.pressed, "Fake input did not reach the pad.")
            controller.keyboard.feed(0x43, False)
            app.processEvents()
            require(not controller.pressed, "Fake A release was lost.")
            require(monitor.reader is reader and not reader.stop.is_set(), "Minimize restarted preview.")
            require(monitor.timer.isActive() and overlay.timer.isActive(), "Minimize stopped render timers.")

            # A normal, separately created window must not remove the pin state.
            probe.show()
            probe.raise_()
            probe.activateWindow()
            QTest.qWait(100)
            for name, widget in (("monitor", monitor), ("overlay", overlay)):
                state = inspect("ordinary_window_active", name, widget)
                require(state["native_visible"] and state["native_topmost"], f"{name} lost pin state.")
            require(not (user32.GetWindowLongPtrW(int(probe.winId()), -20) & 8), "Probe is not a normal window.")
            for enabled in (False, True):
                monitor.topmost_button.click()
                QTest.qWait(80)
                state = inspect("pin_on" if enabled else "pin_off", "monitor", monitor)
                require(state["native_topmost"] == enabled, "Pin control and native flag disagree.")
                require(state["native_visible"] and state["native_owner"] == 0, "Pin toggle hid/re-owned monitor.")
                require(user32.IsIconic(int(window.winId())), "Pin toggle restored main unexpectedly.")
                require(monitor.reader is reader and not reader.stop.is_set(), "Pin toggle restarted capture.")
            require(len(OfflineReader.instances) == 1, "Minimize/pin changes reconnected capture.")

            monitor.toggle_picture_only()
            QTest.qWait(100)
            state = inspect("picture_only", "monitor", monitor)
            require(state["native_visible"] and state["native_topmost"], "Picture-only mode lost topmost.")
            require(not monitor.toolbar.isVisible(), "Picture-only mode left its toolbar visible.")
            monitor.toggle_picture_only()
            controller.show()
            controller.set_topmost(True)
            controller.showMinimized()
            QTest.qWait(150)
            require(user32.IsIconic(int(controller.winId())), "Large controller was not minimized.")
            require(inspect("controller_minimized", "overlay", overlay)["native_visible"], "Minimizing controller hid overlay.")
            controller.hide()
            window.showNormal()
            QTest.qWait(100)
            require(inspect("restored", "monitor", monitor)["native_visible"], "Restore hid monitor.")
            require(inspect("restored", "overlay", overlay)["native_visible"], "Restore hid overlay.")

            # Exercise the existing shared-preview / read-only-script mode too.
            controller.press("A")
            require(window.accessories.release_for_run(), "Manual devices were not released for the script.")
            window.running = True
            window.run_command = SimpleNamespace(preview_url="http://127.0.0.1/offline-preview")
            snapshot = {"buttons": ("A",), "hat": "CENTER", "left_stick": (128, 128), "right_stick": (128, 128)}
            view = SimpleNamespace(snapshot=snapshot, message="offline scripted input")
            window.accessories.input_view = view
            window.accessories.run_started()
            window.accessories.open_controller()
            window.window_chrome.titlebar.buttons["minimize"].click()
            QTest.qWait(150)
            for name, widget in (("monitor", monitor), ("overlay", overlay)):
                state = inspect("script_main_minimized", name, widget)
                require(state["native_visible"] and state["native_topmost"], f"Script mode hid/unpinned {name}.")
            # Supply a new script snapshot after the window-state transition.
            controller.set_script_observation(view)
            require(controller.observing and not controller.keyboard_allowed(), "Script overlay is not read-only.")
            require(not controller.keyboard.feed(0x43, True), "Script mode accepted manual input.")
            require(a_button_color(overlay) == "#00ff00", "Script A press did not light up the overlay.")
            snapshot["buttons"] = ()
            controller.set_script_observation(view)
            app.processEvents()
            require(a_button_color(overlay) != "#00ff00", "Script release did not clear the overlay.")
            require(monitor.reader.source == window.run_command.preview_url, "Script monitor did not use shared preview.")
            require(len(OfflineReader.instances) == 2, "Script mode opened extra readers.")
            window.running = False
            window.run_command = None
            controller.set_script_observation(None)
            window.showNormal()
            QTest.qWait(100)
            probe.close()
            require(window.close(), "Normal application close was not accepted.")
            QTest.qWait(100)
            for name, widget in (("monitor", monitor), ("controller", controller), ("overlay", overlay)):
                require(not inspect("closed", name, widget)["native_visible"], f"Application close left {name} visible.")
            require(all(item.stop.is_set() for item in OfflineReader.instances), "Application close did not stop every preview.")
            require(not monitor.timer.isActive() and not overlay.timer.isActive(), "Application close left render timers running.")
            require(not controller.pressed and controller.controller is None, "Application close left manual input connected.")
            transport.disconnect.assert_called_once()
            require(controller.keyboard.handle is None, "Keyboard hook was not stopped.")
            require(not serial_constructor.called, "Native check attempted a real serial connection.")
            require(bool(keyboard_start.call_count), "Keyboard hook interception was not exercised.")
        finally:
            probe.close()
            window.running = False
            if window.accessories.monitor:
                window.accessories.monitor.close()
            if window.accessories.controller:
                window.accessories.controller.close()
            window.close()
            app.processEvents()
    return {"platform": app.platformName(), "checks": checks, "hardware_connected": False, "states": states}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    report = verify()
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
