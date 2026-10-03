import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
from PySide6.QtCore import QThread
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from pyside_app.migration import CompleteWindow
from pyside_app.services import AppPaths
from pyside_app.log_history import discover_logs, read_log_preview


class HistoryAsyncTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.w = CompleteWindow(paths=AppPaths(user=self.root/"user",output=self.root/"runtime"/"pyside6"),auto_detect=False)
        self.w.show()

    def wait_idle(self):
        deadline = time.monotonic()+10
        while self.w.history_controller.busy:
            if time.monotonic()>deadline:
                self.fail("history workers did not finish")
            QTest.qWait(10)

    def tearDown(self):
        self.w.close()
        self.wait_idle()
        self.w.close()
        self.w.deleteLater()
        self.app.processEvents()
        self.temp.cleanup()

    def test_scan_and_filter_workers_batches_cache_and_selection(self):
        folder=self.root/"runtime"/"pyside6"
        folder.mkdir(parents=True)
        for i in range(600):
            (folder/f"egg-{i:04}.log").write_text(f"test {i}\n",encoding="utf-8")
        threads=[]
        real=discover_logs
        def scanned(*args,**kwargs):
            threads.append(QThread.currentThread() is self.app.thread())
            return real(*args,**kwargs)
        with patch("pyside_app.history_controller.discover_logs",side_effect=scanned) as scan:
            self.w.select_page("history_logs")
            self.assertIsNone(self.w.job)
            self.wait_idle()
            self.assertEqual(self.w.history_table.model().rowCount(),600)
            self.assertEqual(threads,[False])
            selected=self.w._selected_history_log().path
            self.w.select_page("sid")
            self.w.select_page("history_logs")
            self.wait_idle()
            self.assertEqual(scan.call_count,1)
            self.assertEqual(self.w._selected_history_log().path,selected)
            for value in ("no", "egg-001", "egg-002", "egg-0599"):
                self.w.fields["history_search"].setText(value)
            self.wait_idle()
            self.assertEqual(len(self.w.history_rows),1)
            self.assertEqual(self.w.history_rows[0].path.name,"egg-0599.log")
            self.w.fields["history_search"].clear()
            self.wait_idle()
            selected.unlink()
            self.w.history_controller.refresh(force=True)
            self.wait_idle()
            self.assertIsNone(self.w._selected_history_log())
            self.assertIn("未选择其他",self.w.history_log_view.toPlainText())

    def test_large_tail_and_load_more_are_bounded_and_original_unchanged(self):
        path=self.root/"runtime"/"pyside6"/"big.log"
        path.parent.mkdir(parents=True)
        with path.open("wb") as stream:
            stream.seek(100*1024*1024)
            stream.write(b"tail\n"*4000)
        before=(path.stat().st_mtime_ns,path.stat().st_size)
        self.w.select_page("history_logs")
        self.wait_idle()
        self.assertIn("仅显示末尾",self.w.history_log_view.toPlainText())
        self.assertLessEqual(len(self.w.history_log_view.toPlainText().splitlines()),3002)
        for _ in range(6):
            self.w.history_controller.more()
            self.wait_idle()
        self.assertEqual(self.w.history_controller.budget,1024*1024)
        self.assertFalse(self.w.history_more_button.isEnabled())
        self.assertEqual(before,(path.stat().st_mtime_ns,path.stat().st_size))

    def test_scanner_skips_resources_and_cooperates_with_cancel(self):
        runtime=self.root/"runtime"
        (runtime/"ImgLabel").mkdir(parents=True)
        (runtime/"ImgLabel"/"fake.log").write_text("resource")
        (runtime/"real.log").write_text("real")
        self.assertEqual(len(discover_logs(runtime,self.root/"user")),1)
        self.assertEqual(discover_logs(runtime,self.root/"user",cancelled=lambda:True),())

    def test_stream_read_always_has_a_limit(self):
        path=self.root/"trace.log"
        path.write_bytes(b"x"*1024)
        real=Path.open
        reads=[]
        class Stream:
            def __init__(self,stream): self.stream=stream
            def __enter__(self): return self
            def __exit__(self,*args): self.stream.close()
            def __getattr__(self,name): return getattr(self.stream,name)
            def read(self,size=-1):
                reads.append(size)
                self.assert_limit = size
                if size<0: raise AssertionError("unbounded read")
                return self.stream.read(size)
        with patch.object(Path,"open",lambda p,*args,**kwargs:Stream(real(p,*args,**kwargs))):
            read_log_preview(path,max_bytes=200)
        self.assertEqual(reads,[200])
