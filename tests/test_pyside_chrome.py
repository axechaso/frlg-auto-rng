"""Window decoration must retain close guards and modal dialog contracts."""
import importlib.util
import unittest


@unittest.skipUnless(importlib.util.find_spec("PySide6"), "PySide6 is optional")
class WindowChromeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(["chrome-tests", "-platform", "offscreen"])

    def test_caption_close_respects_running_window_guard(self):
        from PySide6.QtWidgets import QMainWindow, QWidget
        from pyside_chrome import decorate_window

        class GuardedWindow(QMainWindow):
            busy = True

            def closeEvent(self, event):
                if self.busy:
                    event.ignore()
                else:
                    super().closeEvent(event)

        window = GuardedWindow()
        window.setCentralWidget(QWidget())
        chrome = decorate_window(window, dark=True)
        window.show()
        chrome.titlebar.buttons["close"].click()
        self.assertTrue(window.isVisible())
        window.busy = False
        chrome.titlebar.buttons["close"].click()
        self.assertFalse(window.isVisible())
        window.deleteLater()
        self.app.processEvents()

    def test_modal_result_and_reopened_form_are_preserved(self):
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QLineEdit, QVBoxLayout
        from pyside_chrome import ThemedDialog, TitleBar

        dialog = ThemedDialog()
        field = QLineEdit("00007")
        QVBoxLayout(dialog).addWidget(field)
        QTimer.singleShot(20, dialog.accept)
        self.assertEqual(dialog.exec(), dialog.DialogCode.Accepted)
        QTimer.singleShot(20, lambda: dialog.window_chrome.titlebar.buttons["close"].click())
        self.assertEqual(dialog.exec(), dialog.DialogCode.Rejected)
        self.assertEqual(field.text(), "00007")
        self.assertEqual(len(dialog.findChildren(TitleBar)), 1)
        dialog.deleteLater()
        self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
