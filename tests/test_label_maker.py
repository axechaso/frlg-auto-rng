import json
import os
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from pyside_app.label_catalog import label_choices
from pyside_app.label_editor import LabelEditorDialog
from pyside_app.label_testing import verify_preview
from pyside_app.manual import MonitorWindow
from pyside_app.migration import CompleteWindow
from pyside_app.services import AppPaths
from tests.test_device_label_overrides import write_label


class LabelMakerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        backend_patch = patch("pyside_app.label_editor.EASYCON170_TEST", True)
        backend_patch.start()
        self.addCleanup(backend_patch.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "scripts"
        self.source.mkdir()
        self.script = self.source / "main.ecs"
        self.script.write_text("PRINT @目标\n# @注释不能显示\n", encoding="utf-8")
        (self.source / "lib").mkdir()
        (self.source / "lib" / "helpers.ecs").write_text("IF @主页 > 95\nENDIF\n", encoding="utf-8")
        self.label = self.source / "ImgLabel" / "目标.IL"
        write_label(self.label, method=1)
        write_label(self.source / "ImgLabel" / "主页.IL")
        write_label(self.source / "ImgLabel" / "不使用.IL")
        self.w = CompleteWindow(paths=AppPaths(user=self.root / "user", output=self.root / "runtime",
                                              source=self.source, tid_source=self.root / "missing"), auto_detect=False)
        self.w.app_update.auto_timer.stop()
        self.w.fields["sid_source"].setText(str(self.root / "missing"))
        self.w.devices = ({}, {0: "USB Capture", 1: "Other Capture"})
        self.w._fill(self.w.fields["video"], [("USB Capture", 0), ("Other Capture", 1)], 0)
        with patch("pyside_app.label_editor.prepare_compat_runner", side_effect=FileNotFoundError("no CLI")) as prepare:
            self.editor = LabelEditorDialog(self.w)
            prepare.assert_not_called()
        self.editor.label_choice.setCurrentIndex(self.editor.label_choice.findText("目标.IL"))
        self.w.accessories.label_editor = self.editor
        self.editor.finished.connect(self.w.accessories._label_editor_finished)
        self.editor.show()
        self.monitor = MonitorWindow(self.w)
        self.w.accessories.monitor = self.monitor
        self.image = QImage(1280, 720, QImage.Format.Format_RGB32)
        self.image.fill(Qt.GlobalColor.white)
        self.reader = SimpleNamespace(source=0, latest=(1, self.image), frame=self.image,
                                      stop=threading.Event(), status="offline fixture",
                                      thread=Mock(is_alive=Mock(return_value=False)))
        self.monitor.reader = self.reader

    def tearDown(self):
        self.editor.close()
        for _ in range(200):
            if self.editor.native_job is None:
                break
            QTest.qWait(10)
        self.editor.close()
        self.w.close()
        self.editor.deleteLater()
        self.w.deleteLater()
        self.app.processEvents()
        self.temp.cleanup()

    def capture(self):
        self.monitor.capture_button.click()
        self.assertIsNotNone(self.editor.frame_path)
        self.editor.scene_confirm.setChecked(True)

    def test_script_catalog_filters_references_and_prefers_current_device_override(self):
        self.assertEqual({item.name for item in label_choices(self.script)}, {"目标.IL", "主页.IL"})
        profile = self.editor.store.profile("USB Capture")
        replacement = profile.label_dir / "目标.IL"
        write_label(replacement, method=1, image=b"override")
        self.editor._load_script_labels()
        self.editor.label_filter.setText("目标")
        self.assertEqual(self.editor.label_choice.count(), 1)
        self.assertIn("当前设备覆盖", self.editor.label_choice.currentText())
        self.assertEqual(self.editor.original_path, replacement.resolve())
        self.editor.label_filter.setText("没有此项")
        self.assertIsNone(self.editor.original_path)
        self.assertEqual(self.editor.payload, {})
        self.assertFalse(self.editor.apply_button.isEnabled())

    def test_monitor_capture_freezes_normalized_pixels_without_file_dialogs(self):
        with patch("pyside_app.label_editor.QFileDialog.getOpenFileName", side_effect=AssertionError("file picker")):
            self.capture()
        path = self.editor.frame_path
        self.assertEqual(self.editor.canvas.image_size.width(), 1920)
        self.assertEqual(self.editor.canvas.image_size.height(), 1080)
        self.image.fill(Qt.GlobalColor.black)
        self.assertEqual(QImage(str(path)).pixelColor(10, 10).red(), 255)
        self.assertFalse(self.reader.stop.is_set())
        self.assertEqual((self.image.width(), self.image.height()), (1280, 720))

    def test_capture_crop_local_tests_and_device_save_end_to_end(self):
        original = self.label.read_bytes()
        self.capture()
        self.editor._selection_finished("range", QRect(0, 0, 100, 100))
        self.editor._selection_finished("target", QRect(10, 20, 30, 40))
        self.editor.test_same_image()
        self.assertTrue(self.editor._same_image_ok, self.editor.result_text.text())
        self.assertIn("本地匹配", self.editor.result_text.text())
        self.editor.test_fresh_frames()
        self.editor.fresh_timer.stop()
        self.editor._collect_fresh()  # The cached frame isn't a new frame.
        self.assertEqual(self.editor._fresh_paths, [])
        for sequence in (2, 3, 4):
            self.reader.latest = sequence, self.image
            self.editor._collect_fresh()
        for _ in range(200):
            if self.editor.native_job is None:
                break
            QTest.qWait(10)
        self.assertTrue(self.editor._fresh_frames_ok, self.editor.result_text.text())
        self.assertTrue(self.editor.apply_button.isEnabled())
        self.assertEqual([r["monitor_sequence"] for r in self.editor._fresh_frame_results], [2, 3, 4])
        with patch("pyside_app.label_editor.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes), \
             patch("pyside_app.label_editor.QFileDialog.getSaveFileName", side_effect=AssertionError("save picker")):
            self.editor.save_draft()
            self.editor.save_and_apply()
        self.assertEqual(self.label.read_bytes(), original)
        metadata = self.editor.store.list_overrides("USB Capture")
        self.assertEqual(len(metadata), 1)
        profile = self.editor.store.profile("USB Capture")
        manifest = json.loads(profile.manifest_path.read_text(encoding="utf-8"))
        self.assertFalse(manifest["files"][self.label.name]["verification"]["native_verified"])
        saved = profile.label_dir / self.label.name
        payload = json.loads(saved.read_text(encoding="utf-8"))
        self.assertEqual(payload["TargetWidth"], 30)
        self.assertEqual(payload["RangeWidth"], 100)

    def test_adjacent_page_is_captured_and_tested_without_replacing_source(self):
        self.capture()
        source = self.editor.frame_path
        black = self.image.copy()
        black.fill(Qt.GlobalColor.black)
        self.reader.latest = 2, black
        with patch("pyside_app.label_editor.QFileDialog.getOpenFileName", side_effect=AssertionError("file picker")):
            self.editor.test_adjacent_state()
        self.assertTrue(self.editor._adjacent_ok, self.editor.adjacent_state.text())
        self.assertEqual(self.editor.frame_path, source)
        self.assertNotEqual(source, self.editor._adjacent_frame_path)

    def test_changed_device_or_stopped_monitor_cannot_supply_stale_capture(self):
        self.capture()
        source = self.editor.frame_path
        self.reader.stop.set()
        with patch.object(self.editor, "open_monitor"):
            self.editor.capture_monitor_frame()
        self.assertEqual(self.editor.frame_path, source)
        self.assertIn("截图失败", self.editor.result_text.text())
        self.w.fields["video"].setCurrentIndex(1)
        self.assertIsNone(self.editor.frame_path)
        self.assertFalse(self.editor.scene_confirm.isChecked())
        self.assertFalse(self.editor._same_image_ok)
        self.assertFalse(self.editor._fresh_frames_ok)

    def test_missing_labels_are_visible_and_unavailable(self):
        self.label.unlink()
        self.editor._load_script_labels()
        index = next(i for i in range(self.editor.label_choice.count()) if "目标.IL" in self.editor.label_choice.itemText(i))
        self.assertIn("文件缺失", self.editor.label_choice.itemText(index))
        self.assertFalse(self.editor.label_choice.model().item(index).isEnabled())

    def test_long_label_dropdown_has_visible_draggable_scrollbar(self):
        combo = self.editor.label_choice
        with patch.object(self.editor, "_load_selected_label"):
            for number in range(200):
                combo.addItem(f"标签{number:03}.IL", str(self.label))
            combo.setCurrentIndex(0)
            combo.showPopup()
            self.app.processEvents()
            scrollbar = combo.view().verticalScrollBar()
            self.assertTrue(scrollbar.isVisible())
            self.assertGreater(scrollbar.maximum(), 0)
            self.assertGreaterEqual(scrollbar.width(), 14)
            QTest.mousePress(scrollbar, Qt.MouseButton.LeftButton, pos=QPoint(scrollbar.width() // 2, 12))
            QTest.mouseMove(scrollbar, QPoint(scrollbar.width() // 2, scrollbar.height() // 2), 30)
            QTest.mouseRelease(scrollbar, Qt.MouseButton.LeftButton, pos=QPoint(scrollbar.width() // 2, scrollbar.height() // 2))
            self.assertGreater(scrollbar.value(), 0)
            scrollbar.setValue(scrollbar.maximum())
            self.app.processEvents()
            self.assertGreater(combo.view().indexAt(combo.view().viewport().rect().center()).row(), 100)
            combo.hidePopup()

    def test_menu_opens_editor_and_monitor_without_open_file_dialogs(self):
        self.editor.close()
        with patch("pyside_app.accessories.QFileDialog.getOpenFileName", side_effect=AssertionError("file picker")), \
             patch("pyside_app.label_editor.LabelEditorDialog.open_monitor") as monitor:
            self.w.accessories.open_label_editor()
            other = self.w.accessories.label_editor
            self.assertIsNotNone(other)
            self.assertGreater(other.label_choice.count(), 0)
            monitor.assert_called_once()
            other.close()


class LocalLabelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_supported_image_methods_and_alpha_masks(self):
        import cv2
        import numpy as np
        import base64
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            pixels = np.random.default_rng(42).integers(10, 240, (108, 192, 3), dtype=np.uint8)
            ok, encoded = cv2.imencode(".png", pixels)
            self.assertTrue(ok)
            frame = root / "frame.png"
            frame.write_bytes(encoded.tobytes())
            for method in (1, 3, 5, 11, 14):
                label = root / f"method{method}.IL"
                write_label(label, method=method)
                payload = json.loads(label.read_text())
                target = pixels[20:60, 10:40].copy()
                if method == 14:
                    target = cv2.cvtColor(target, cv2.COLOR_BGR2BGRA)
                    target[:10, :10, 3] = 0
                _, png = cv2.imencode(".png", target)
                payload.update(ImgBase64=base64.b64encode(png).decode("ascii"), RangeWidth=192, RangeHeight=108)
                label.write_text(json.dumps(payload))
                with self.subTest(method=method):
                    result = verify_preview(label, frame=frame)[0]
                    self.assertTrue(result["passed"])
                    self.assertFalse(result["native_verified"])
                    self.assertEqual(result["location"], [10, 20])
            payload["UseGrayscale"] = True
            label.write_text(json.dumps(payload))
            with self.assertRaisesRegex(ValueError, "额外预处理"):
                verify_preview(label, frame=frame)
