import os
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from pyside_app.migration import CompleteWindow
from pyside_app.services import AppPaths
from pyside_app.label_editor import LabelEditorDialog
from tests.test_device_label_overrides import write_label


class LabelEditorFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.w=CompleteWindow(paths=AppPaths(user=self.root/"user",output=self.root/"runtime"),auto_detect=False)
        self.w.devices=({},{0:"USB Capture",1:"Other Capture"})
        self.w._fill(self.w.fields["video"],[("USB Capture",0),("Other Capture",1)],0)
        self.label=self.root/"candidate.IL";write_label(self.label)
        self.frame=self.root/"frame.png"
        self.image=QImage(1920,1080,QImage.Format.Format_RGB32);self.image.fill(Qt.GlobalColor.white);self.image.save(str(self.frame))
        with patch("pyside_app.label_editor.prepare_compat_runner",return_value=self.root/"unused-runner.exe"):
            self.editor=LabelEditorDialog(self.w,label_path=self.label,frame_path=self.frame)
        self.editor.show()
        self.editor.scene_confirm.setChecked(True)
    def tearDown(self):
        self.editor.close()
        for _ in range(100):
            if self.editor.native_job is None: break
            QTest.qWait(10)
        self.editor.close();self.w.close();self.editor.deleteLater();self.w.deleteLater();self.app.processEvents();self.temp.cleanup()

    def test_fresh_frames_use_existing_mailbox_three_distinct_sequences_offline_native(self):
        reader=SimpleNamespace(source="http://127.0.0.1/mock/mjpeg",latest=(0,self.image),stop=threading.Event())
        self.w.accessories.monitor=SimpleNamespace(reader=reader,close=lambda:None)
        record={"frame_index":0,"integer_score":99,"raw_score":98.1,"passed":True,"elapsed_ms":1,"width":1920,"height":1080}
        with patch("pyside_app.label_editor.verify_label",return_value=(record,)) as matcher,patch.object(self.w.accessories,"release_for_run") as release:
            self.editor.test_fresh_frames();self.editor.fresh_timer.stop()
            self.editor._collect_fresh()
            self.assertEqual(self.editor._fresh_paths,[])
            for i in (1,2,3):
                reader.latest=(i,self.image)
                self.editor._collect_fresh()
            for _ in range(200):
                if self.editor.native_job is None: break
                QTest.qWait(10)
            self.assertTrue(self.editor._fresh_frames_ok)
            self.assertEqual(matcher.call_count,3)
            self.assertTrue(all("frame" in c.kwargs for c in matcher.call_args_list))
            self.assertTrue(all("device" not in c.kwargs for c in matcher.call_args_list))
            release.assert_not_called()
            self.assertEqual([r["shared_preview_sequence"] for r in self.editor._fresh_frame_results],[1,2,3])
            self.w.fields["video"].setCurrentIndex(1)
            self.assertFalse(self.editor._fresh_frames_ok)
            self.assertFalse(self.editor.scene_confirm.isChecked())

    def test_missing_channel_does_not_open_capture_or_claim_verification(self):
        with patch("pyside_app.label_editor.verify_label") as matcher,patch.object(self.w.accessories,"release_for_run") as release:
            self.editor.test_fresh_frames()
            self.assertIn("没有可用",self.editor.result_text.text())
            self.assertFalse(self.editor._fresh_frames_ok)
            matcher.assert_not_called();release.assert_not_called()

    def test_changed_source_image_invalidates_pending_fresh_verification(self):
        reader=SimpleNamespace(source="http://127.0.0.1/mock/mjpeg",latest=(0,self.image),stop=threading.Event())
        self.w.accessories.monitor=SimpleNamespace(reader=reader,close=lambda:None)
        with patch("pyside_app.label_editor.verify_label") as matcher:
            self.editor.test_fresh_frames();self.editor.fresh_timer.stop()
            changed=self.image.copy();changed.fill(Qt.GlobalColor.black);changed.save(str(self.frame))
            reader.latest=(1,self.image)
            self.editor._collect_fresh()
            self.assertFalse(self.editor._fresh_frames_ok)
            self.assertIn("原图已变化",self.editor.result_text.text())
            matcher.assert_not_called()

    def test_batch_partial_failure_is_reported_and_no_candidate_marked_verified(self):
        valid=self.root/"other.IL";write_label(valid)
        invalid=self.root/"broken.IL";invalid.write_text("broken")
        self.editor.import_candidates([str(valid),str(invalid)])
        self.assertIn("other.IL：结构通过",self.editor.result_text.text())
        self.assertIn("broken.IL：失败",self.editor.result_text.text())
        self.assertFalse(self.editor._same_image_ok)
        self.assertFalse(self.editor._fresh_frames_ok)
        self.assertFalse(self.editor.apply_button.isEnabled())
