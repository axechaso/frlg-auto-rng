import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


@unittest.skipUnless(importlib.util.find_spec("PySide6"), "PySide6 is optional")
class ControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(["controller-tests", "-platform", "offscreen"])

    def setUp(self):
        from PySide6.QtWidgets import QWidget
        from easycon import GamePadKey
        from pyside_app.manual import ControllerWindow
        self.temp = tempfile.TemporaryDirectory()
        self.host = QWidget()
        self.host.paths = SimpleNamespace(user=Path(self.temp.name))
        self.host.running = False
        self.host.job = None
        self.host.accessories = SimpleNamespace(monitor=None)
        self.w = ControllerWindow(self.host)
        self.transport = Mock(is_connected=True, port_name="FAKE")
        self.w.controller = self.transport
        self.w.native = GamePadKey
        self.hook_patch = patch.object(self.w.keyboard, "start")
        self.hook_patch.start()
        self.w.show()
        self.w.activateWindow()
        self.app.processEvents()
        self.transport.reset_mock()

    def tearDown(self):
        self.w.close()
        self.hook_patch.stop()
        self.app.removeEventFilter(self.w)
        self.w.deleteLater()
        self.host.close()
        self.host.deleteLater()
        self.app.processEvents()
        self.temp.cleanup()

    def test_keys_work_on_window_child_and_with_shift(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        for target in (self.w, self.w.connect_button, self.w.buttons["A"], self.w.pad):
            QTest.keyPress(target, Qt.Key.Key_C, Qt.KeyboardModifier.ShiftModifier)
            self.assertIn("A", self.w.pressed)
            QTest.keyRelease(target, Qt.Key.Key_C, Qt.KeyboardModifier.ShiftModifier)
            self.assertNotIn("A", self.w.pressed)
        self.transport.press.assert_called_with(self.w.native.A)
        self.transport.release.assert_called_with(self.w.native.A)
        QTest.keyClick(self.w, Qt.Key.Key_Return)
        self.transport.disconnect.assert_not_called()

    def test_native_virtual_key_and_repeat_release(self):
        hook = self.w.keyboard
        self.assertTrue(hook.feed(0x43, True))
        self.assertTrue(hook.feed(0x43, True))
        self.app.processEvents()
        self.assertIn("A", self.w.pressed)
        self.transport.press.assert_called_once_with(self.w.native.A)
        self.assertTrue(hook.feed(0x43, False, 1))
        self.app.processEvents()
        self.assertFalse(self.w.pressed)
        self.transport.release.assert_called_once_with(self.w.native.A)

    def test_sticks_and_hat_diagonals_recenter_independently(self):
        self.w.press("LS_UP")
        self.w.press("LS_RIGHT")
        self.transport.set_stick.assert_called_with(self.w.native.LS, 255, 0)
        self.w.press("LS_DOWN")
        self.transport.set_stick.assert_called_with(self.w.native.LS, 255, 128)
        self.w.release("LS_DOWN")
        self.transport.set_stick.assert_called_with(self.w.native.LS, 255, 0)
        self.w.press("RS_LEFT")
        self.transport.set_stick.assert_called_with(self.w.native.RS, 0, 128)
        self.w.press("TOP_RIGHT")
        self.transport.press.assert_called_with(self.w.native.TOP_RIGHT)
        self.w.press("LEFT")
        self.transport.press.assert_called_with(self.w.native.TOP)
        self.w.release("TOP_RIGHT")
        self.transport.press.assert_called_with(self.w.native.LEFT)
        self.w.release_all()
        self.transport.release_all.assert_called()
        self.assertFalse(self.w.pressed)

    def test_mouse_and_keyboard_can_hold_same_button(self):
        self.w.mouse_press("A")
        self.w.keyboard.feed(0x43, True)
        self.app.processEvents()
        self.w.mouse_release("A")
        self.assertIn("A", self.w.pressed)
        self.w.keyboard.feed(0x43, False)
        self.app.processEvents()
        self.assertNotIn("A", self.w.pressed)
        self.w.keyboard.feed(0x43, True)
        self.app.processEvents()
        self.w.mouse_press("A")
        self.w.keyboard.feed(0x43, False)
        self.app.processEvents()
        self.assertIn("A", self.w.pressed)
        self.w.mouse_release("A")
        self.assertNotIn("A", self.w.pressed)

    def test_overlay_pause_exit_and_escape_drop_queued_keys(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        overlay = self.w.overlay
        overlay.show_control()
        self.app.processEvents()
        self.w.keyboard.feed(0x43, True)
        QTest.mouseClick(overlay, Qt.MouseButton.LeftButton)
        self.app.processEvents()
        self.assertFalse(self.w.keyboard_active)
        self.assertFalse(self.w.pressed)
        self.assertAlmostEqual(overlay.windowOpacity(), .5, delta=.01)
        self.assertFalse(self.w.keyboard.feed(0x43, True))
        QTest.mouseClick(overlay, Qt.MouseButton.LeftButton)
        self.assertTrue(self.w.keyboard_active)
        self.assertEqual(overlay.windowOpacity(), 1)
        self.w.keyboard.feed(0x43, True)
        self.app.processEvents()
        self.assertIn("A", self.w.pressed)
        self.w.keyboard.feed(27, True)
        self.app.processEvents()
        self.assertFalse(overlay.isVisible())
        self.assertFalse(self.w.pressed)
        self.assertFalse(self.w.keyboard_active)
        overlay.show_control()
        QTest.mouseClick(overlay, Qt.MouseButton.MiddleButton)
        self.assertFalse(overlay.isVisible())
        self.assertFalse(self.w.keyboard_active)

    def test_overlay_right_click_resets_and_drag_moves(self):
        from PySide6.QtCore import QPoint, QPointF, QEvent, Qt
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtTest import QTest
        overlay = self.w.overlay
        overlay.show_control()
        self.app.processEvents()
        overlay.move(5, 5)
        QTest.mouseClick(overlay, Qt.MouseButton.RightButton)
        bounds = self.app.primaryScreen().availableGeometry()
        self.assertEqual(overlay.pos(), QPoint(bounds.x() + bounds.width() // 2, bounds.y() + (bounds.height() - 100) // 2))
        start = overlay.pos()
        QTest.mousePress(overlay, Qt.MouseButton.RightButton, pos=QPoint(50, 50))
        movement = QMouseEvent(QEvent.Type.MouseMove, QPointF(70, 60), QPointF(start + QPoint(70, 60)), Qt.MouseButton.NoButton, Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier)
        self.app.sendEvent(overlay, movement)
        QTest.mouseRelease(overlay, Qt.MouseButton.RightButton, pos=QPoint(50, 50))
        self.assertEqual(overlay.pos(), start + QPoint(20, 10))

    def test_only_active_overlay_allows_global_input_and_modal_pauses(self):
        from PySide6.QtWidgets import QDialog
        with patch("pyside_app.manual.QApplication.activeWindow", return_value=self.host):
            self.assertFalse(self.w.keyboard_allowed())
            self.w.overlay.show_control()
            self.assertTrue(self.w.keyboard_allowed())
            dialog = QDialog(self.w)
            with patch("pyside_app.manual.QApplication.activeModalWidget", return_value=dialog):
                self.assertFalse(self.w.keyboard_allowed())
            self.host.running = True
            self.assertFalse(self.w.keyboard_allowed())
            self.host.running = False
            self.w.disconnect()
            self.assertFalse(self.w.keyboard_allowed())

    def test_focus_loss_without_overlay_and_disconnect_release_inputs(self):
        from PySide6.QtCore import QEvent
        self.w.keyboard.feed(0x43, True)
        self.app.processEvents()
        self.w.eventFilter(self.w, QEvent(QEvent.Type.WindowDeactivate))
        self.assertFalse(self.w.pressed)
        self.assertFalse(self.w.keyboard.held)
        self.w.keyboard.feed(0x43, True)
        self.w.disconnect()
        self.app.processEvents()
        self.assertFalse(self.w.pressed)
        self.assertFalse(self.w.keyboard_pressed)

    def test_legacy_mapping_preserved_and_diagonals_can_be_unassigned(self):
        from pyside_app.controller_layout import DEFAULT_KEYS, LEGACY_KEYS, load_mapping_values, validate_mapping
        legacy = {key: value for key, value in DEFAULT_KEYS.items() if key in LEGACY_KEYS}
        legacy.update(TOP="w", DOWN="s", LEFT="a", RIGHT="d", MINUS="j", PLUS="k")
        upgraded = load_mapping_values(legacy)
        self.assertEqual({key: upgraded[key] for key in legacy}, legacy)
        self.assertEqual(upgraded["LS_UP"], "f1")
        self.assertEqual(upgraded["TOP_LEFT"], "")
        self.assertEqual(validate_mapping(upgraded), upgraded)
        upgraded["A"] = upgraded["B"]
        with self.assertRaisesRegex(ValueError, "重复"):
            validate_mapping(upgraded)

    def test_clear_binding_and_save_cancel_do_not_send_or_corrupt_mapping(self):
        from PySide6.QtCore import Qt, QTimer
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QDialogButtonBox
        from pyside_app.controller_layout import ControllerLayout
        original = dict(self.w.mapping)
        def edit(cancel):
            dialog = self.app.activeModalWidget()
            pad = dialog.findChild(ControllerLayout)
            pad.controls["A"].setFocus()
            QTest.keyClick(pad.controls["A"], Qt.Key.Key_Escape)
            self.assertTrue(pad.controls["A"].keySequence().isEmpty())
            buttons = dialog.findChild(QDialogButtonBox)
            QTest.mouseClick(buttons.button(QDialogButtonBox.StandardButton.Cancel if cancel else QDialogButtonBox.StandardButton.Save), Qt.MouseButton.LeftButton)
        QTimer.singleShot(0, lambda: edit(True))
        self.w.edit_mapping()
        self.assertEqual(self.w.mapping, original)
        self.assertFalse(self.w.mapping_path.exists())
        QTimer.singleShot(0, lambda: edit(False))
        self.w.edit_mapping()
        self.assertEqual(self.w.mapping["A"], "")
        self.assertEqual(json.loads(self.w.mapping_path.read_text(encoding="utf-8")), self.w.mapping)
        self.transport.press.assert_not_called()

    def test_overlay_draws_actual_manual_stick_and_button_state(self):
        overlay = self.w.overlay
        overlay.show_control()
        self.app.processEvents()
        neutral = overlay.grab().toImage()
        self.w.press("A")
        self.w.press("LS_RIGHT")
        active = overlay.grab().toImage()
        self.assertNotEqual(neutral.pixelColor(83, 33), active.pixelColor(83, 33))
        self.assertEqual(active.pixelColor(83, 33).name(), "#00ff00")
        self.assertNotEqual(neutral.pixelColor(20, 33), active.pixelColor(20, 33))
        self.w.release_all()
        self.assertEqual(overlay.grab().toImage(), neutral)

    def test_windows_binding_rejects_unsupported_and_alias_duplicates(self):
        from pyside_app.controller_keyboard import ControllerKeyboard, virtual_binding
        self.assertEqual(virtual_binding("Ctrl+F1"), (112, 2))
        self.assertEqual(virtual_binding("Num+1"), (97, 0))
        self.assertEqual(virtual_binding("Shift+!"), (49, 1))
        self.assertEqual(virtual_binding("Num++"), (107, 0))
        with self.assertRaises(ValueError):
            virtual_binding("Volume Up")
        with self.assertRaisesRegex(ValueError, "同一个"):
            ControllerKeyboard.build_bindings({"A": "Return", "B": "Enter"})

    def test_failed_mapping_save_keeps_live_bindings(self):
        from PySide6.QtCore import Qt, QTimer
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QDialogButtonBox
        from pyside_app.controller_layout import ControllerLayout
        original = dict(self.w.mapping)
        bindings = dict(self.w.keyboard.bindings)
        def attempt():
            dialog = self.app.activeModalWidget()
            pad = dialog.findChild(ControllerLayout)
            pad.controls["A"].clear()
            QTest.mouseClick(dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Save), Qt.MouseButton.LeftButton)
            self.assertEqual(self.w.mapping, original)
            self.assertEqual(self.w.keyboard.bindings, bindings)
            dialog.reject()
        with patch("pyside_app.manual.write_json_atomic", side_effect=OSError("read-only")), patch("pyside_app.manual.QMessageBox.warning") as warning:
            QTimer.singleShot(0, attempt)
            self.w.edit_mapping()
            warning.assert_called_once()


if __name__ == "__main__":
    unittest.main()
