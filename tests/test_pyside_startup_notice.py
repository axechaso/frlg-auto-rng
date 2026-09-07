"""PySide6 startup notice content and opt-out persistence."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


@unittest.skipUnless(importlib.util.find_spec("PySide6"), "PySide6 is optional")
class StartupNoticeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication(
            ["startup-notice-tests", "-platform", "offscreen"]
        )

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.user_dir = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def module(self):
        spec = importlib.util.find_spec("pyside_app.startup_notice")
        self.assertIsNotNone(spec, "PySide6 启动公告模块尚未实现")
        from pyside_app import startup_notice

        return startup_notice

    def test_dialog_contains_function_summary_credits_links_and_both_qr_images(self):
        from PySide6.QtWidgets import QCheckBox, QLabel, QPushButton

        module = self.module()
        dialog = module.StartupNoticeDialog(self.user_dir)
        self.addCleanup(dialog.deleteLater)

        self.assertEqual(dialog.windowTitle(), "本工具完全开源免费！！！但是钱包空了求打赏...")
        summary = dialog.findChild(QLabel, "startupNoticeSummary")
        self.assertIn("SID 查找", summary.text())
        self.assertIn("孵蛋", summary.text())
        credits = dialog.findChild(QLabel, "startupNoticeCredits")
        self.assertTrue(credits.openExternalLinks())
        for expected in (
            "https://github.com/EasyConNS/EasyCon",
            "https://github.com/nukieberry",
            "https://github.com/ca1e",
            "https://github.com/elmagnificogi",
            "https://github.com/zhangjf-nlp/PyEasyCon",
            "https://github.com/zhangjf-nlp",
            "冰与路飞数字君",
        ):
            self.assertIn(expected, credits.text())
        for name in ("alipayDonationImage", "wechatDonationImage"):
            image = dialog.findChild(QLabel, name)
            self.assertIsNotNone(image)
            self.assertIsNotNone(image.pixmap())
            self.assertFalse(image.pixmap().isNull())
        self.assertEqual(
            dialog.findChild(QCheckBox, "hideStartupNotice").text(),
            "下次启动不再显示",
        )
        self.assertEqual(
            dialog.findChild(QPushButton, "enterToolButton").text(),
            "进入工具",
        )

    def test_checked_opt_out_is_saved_and_automated_launches_are_always_suppressed(self):
        module = self.module()
        self.assertTrue(module.should_show_startup_notice(self.user_dir))

        dialog = module.StartupNoticeDialog(self.user_dir)
        self.addCleanup(dialog.deleteLater)
        dialog.hide_checkbox.setChecked(True)
        dialog.accept()

        self.assertFalse(module.should_show_startup_notice(self.user_dir))
        self.assertFalse(
            module.should_show_startup_notice(self.user_dir, automated=True)
        )
        payload = json.loads(
            (self.user_dir / "startup_notice.json").read_text(encoding="utf-8")
        )
        self.assertEqual(payload, {"schema": 1, "hidden": True})


if __name__ == "__main__":
    unittest.main()
