import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from pyside_app.migration import CompleteWindow
from pyside_app.services import AppPaths
from tests.test_label_incidents import incident_payload
from pyside_app.label_repair_prompt import incident_summary


class LabelRepairPromptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.w=CompleteWindow(paths=AppPaths(user=self.root,output=self.root/"runtime"),auto_detect=False)
        self.w.show()
        self.p=self.w.accessories.repair_prompts
    def tearDown(self):
        self.w.close()
        for _ in range(100):
            if self.p.job is None: break
            QTest.qWait(10)
        self.w.close();self.w.deleteLater();self.app.processEvents();self.temp.cleanup()
    def wait_job(self):
        for _ in range(100):
            QTest.qWait(10)
            if self.p.job is None and self.p.dialog: return
        self.fail("prompt did not arrive")

    def test_current_complete_incident_once_not_old_or_other_run(self):
        old=incident_payload("old");old["run_id"]="old-run"
        self.w.accessories.incidents.write_completed(old)
        self.w.accessories.poll_incidents()
        self.assertIsNone(self.p.dialog)
        self.p.after_exit(20,"run-1")
        QTest.qWait(100)
        self.assertIsNone(self.p.dialog)
        self.w.accessories.incidents.write_completed(incident_payload("current"))
        self.wait_job()
        first=self.p.dialog
        first.close()
        self.p.after_exit(20,"run-1")
        QTest.qWait(350)
        self.assertIs(self.p.dialog,first)
        self.assertFalse(first.isVisible())

    def test_normal_exit_low_score_cancel_and_disabled_prompt_are_silent(self):
        self.w.accessories.incidents.write_completed(incident_payload())
        for code in (0,): self.p.after_exit(code,"run-1",text="普通低分重试")
        self.p.after_exit(20,"run-1",cancelled=True)
        self.w.label_repair_prompt_check.setChecked(False)
        self.p.after_exit(20,"run-1")
        QTest.qWait(50)
        self.assertIsNone(self.p.dialog)

    def test_exit_zero_does_not_resolve_and_missing_values_are_not_zero(self):
        self.w.accessories.incidents.write_completed(incident_payload())
        self.w.accessories.loaded_incidents.add("fault-1")
        self.w.accessories.finish_loaded_incidents(0)
        self.assertEqual(self.w.accessories.incidents.read("fault-1")["resolution"]["status"],"loaded")
        record=incident_payload();record["labels"][0]["score"]=None
        record["predicate"]={"group_operator":"OR"}
        summary=incident_summary(record)
        self.assertIn("未采集，要求 >95",summary)
        self.assertIn("OR",summary)

    def test_preflight_and_capture_fault_are_diagnostics_without_label_claim(self):
        self.assertTrue(self.p.preflight("标签 JSON 损坏"))
        self.assertFalse(self.w.running)
        self.p.dialog.close()
        self.p.after_exit(1,"capture-run",text="采集卡打开失败")
        self.assertIn(("capture-run","prompt"),self.p.seen)

    def test_reported_release_failure_requires_actual_manual_confirmation(self):
        record=incident_payload();record["input_released"]=False
        self.w.accessories.incidents.write_completed(record)
        self.p.after_exit(20,"run-1")
        self.wait_job()
        self.assertFalse(self.p.dialog.repair_button.isEnabled())
        self.p.dialog.release_confirm.setChecked(True)
        self.assertTrue(self.p.dialog.repair_button.isEnabled())
