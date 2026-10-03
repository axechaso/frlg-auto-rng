import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from pyside_app.migration import CompleteWindow
from pyside_app.services import AppPaths
from pyside_preview import NAV_ITEMS
from assets.pyside_preview.guide_steps import GUIDES


class PageGuideTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.paths=AppPaths(user=self.root,output=self.root/"runtime")
        self.w=CompleteWindow(paths=self.paths,auto_detect=False)
        self.w.show()
        self.app.processEvents()

    def tearDown(self):
        self.w.close()
        for _ in range(100):
            if not self.w.history_controller.busy: break
            QTest.qWait(10)
        self.w.close()
        self.w.deleteLater()
        self.app.processEvents()
        self.temp.cleanup()

    def test_all_nav_pages_have_stable_steps_and_real_anchors_no_device_actions(self):
        guides=self.w.page_guides
        registry=guides.anchors()
        self.w.advanced_check.setChecked(True)
        with patch.object(self.w,"request_start") as start,patch.object(self.w,"search") as search,patch.object(self.w,"detect_devices") as detect:
            for page,title,_ in NAV_ITEMS:
                with self.subTest(page=page):
                    self.assertIn(page,GUIDES)
                    self.assertTrue(4<=len(GUIDES[page])<=7)
                    self.assertEqual(len({s.step_id for s in GUIDES[page]}),len(GUIDES[page]))
                    for step in GUIDES[page]: self.assertIn(step.anchor_id,registry)
                    self.w.select_page(page)
                    self.app.processEvents()
                    guides.start(page,restart=True)
                    self.assertEqual(guides.active_page,page)
                    for _ in range(len(guides.active_steps)-1): guides.move(1)
                    guides.move(-1)
                    step=guides.active_steps[guides.index].step_id
                    guides.minimize()
                    guides.start(page)
                    self.assertEqual(guides.active_steps[guides.index].step_id,step)
                    guides.opt_out()
                    self.assertTrue(guides.state["pages"][page]["opt_out"])
                    guides.start(page,restart=True)
                    self.assertEqual(guides.index,0)
                    guides.minimize()
            start.assert_not_called();search.assert_not_called();detect.assert_not_called()

    def test_progress_resume_corruption_and_unknown_steps_preserve_business_settings(self):
        guides=self.w.page_guides
        guides.start("sid");guides.move(1);guides.minimize()
        path=self.root/"guide_state.json"
        self.assertEqual(json.loads(path.read_text())["pages"]["sid"]["step_id"],"count")
        from pyside_app.page_guides import PageGuides
        second=PageGuides(self.w)
        second.start("sid")
        self.assertEqual(second.index,1)
        second.minimize()
        raw='{"broken":'
        path.write_text(raw,encoding="utf-8")
        corrupt=PageGuides(self.w)
        self.assertTrue(corrupt.error)
        corrupt.start("sid");corrupt.move(1);corrupt.minimize()
        self.assertEqual(path.read_text(encoding="utf-8"),raw)
        self.assertIsNone(self.w.job)
        self.assertFalse(self.w.running)

    def test_hidden_advanced_and_actual_device_state_are_honest(self):
        with patch("pyside_app.page_guides.QMessageBox.information"):
            self.w.page_guides.start("script_test")
        self.assertFalse(self.w.advanced_check.isChecked())
        self.w.page_guides.start("sid")
        self.w.page_guides.index=4
        self.w.page_guides.render()
        self.assertIn("尚未检测",self.w.page_guides.overlay.state.text())
        self.w.running=True
        self.w.page_guides.update_status()
        self.assertIn("参数已冻结",self.w.page_guides.overlay.state.text())
        self.w.running=False

    def test_escape_closes_only_the_tutorial_and_keeps_stop_visible(self):
        self.w.page_guides.start("sid")
        overlay=self.w.page_guides.overlay
        self.assertTrue(self.w.stop_button.isVisible())
        with patch.object(self.w,"stop_run") as stop:
            QTest.keyClick(overlay,Qt.Key.Key_Escape)
            stop.assert_not_called()
        self.assertIsNone(self.w.page_guides.active_page)
        self.assertFalse(overlay.isVisible())
