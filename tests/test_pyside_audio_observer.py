import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from PySide6.QtCore import QByteArray, QObject, Signal
from PySide6.QtMultimedia import QtAudio
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from audio_observer import LOG_PREFIX, SoundMatch, read_template
from pyside_app.audio_observer import AudioWorker


class FakeInput:
    def id(self):
        return QByteArray(b"capture-card-1")

    def description(self):
        return "采集卡游戏音频"

    def isFormatSupported(self, format):
        return True


class FakeStream(QObject):
    readyRead = Signal()

    def __init__(self):
        super().__init__()
        self.data = b""

    def readAll(self):
        value, self.data = self.data, b""
        return QByteArray(value)

    def push(self, value):
        self.data += value
        self.readyRead.emit()


class FakeSource(QObject):
    stateChanged = Signal(object)

    def __init__(self):
        super().__init__()
        self.stream = FakeStream()
        self.stopped = False
        self.failure = QtAudio.Error.NoError

    def setBufferSize(self, size):
        self.size = size

    def start(self):
        return self.stream

    def stop(self):
        self.stopped = True
        self.stateChanged.emit(QtAudio.State.StoppedState)

    def error(self):
        return self.failure


class PySideAudioObserverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(["audio-observer-tests", "-platform", "offscreen"])

    def setUp(self):
        from pyside_app.migration import CompleteWindow
        from pyside_app.services import AppPaths

        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.window = CompleteWindow(paths=AppPaths(user=self.root, output=self.root / "runtime"), auto_detect=False)
        self.observer = self.window.audio_observer

    def tearDown(self):
        self.window.running = False
        self.observer.close()
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()
        self.temp.cleanup()

    def wait_until(self, predicate):
        for _ in range(150):
            self.app.processEvents()
            if predicate():
                return
            QTest.qWait(10)
        self.fail("audio event was not delivered")

    def select_fake_device(self):
        with patch("pyside_app.audio_observer.QMediaDevices.audioInputs", return_value=[FakeInput()]):
            self.observer.refresh_devices()
        self.observer.dialog.device.setCurrentIndex(1)

    def test_never_opens_default_microphone_and_requires_explicit_selection(self):
        with patch("pyside_app.audio_observer.QAudioSource") as capture:
            self.observer.start()
            capture.assert_not_called()
        self.assertEqual(self.observer.session, "")
        self.assertIn("选择采集卡", self.observer.dialog.status.text())

    def test_observer_remains_accessible_during_automation(self):
        self.window.running = True
        self.window.refresh_state()
        self.assertTrue(self.window.actions["声音判闪试用"].isEnabled())
        self.assertTrue(self.window.settings_button.isEnabled())
        with patch("pyside_app.audio_observer.QMediaDevices.audioInputs", return_value=[]):
            self.window.actions["声音判闪试用"].click()
        self.assertTrue(self.observer.dialog.isVisible())
        self.assertTrue(self.window.running)

    def test_live_pcm_emits_one_observation_without_touching_workflow(self):
        self.select_fake_device()
        source = FakeSource()
        run_log = self.root / "original.log"
        run_log.write_text("original checkpoint\n", encoding="utf-8")
        self.window.run_command = SimpleNamespace(log_path=run_log)
        self.window.running = True
        with patch("pyside_app.audio_observer.QAudioSource", return_value=source), patch.object(self.window, "stop_run") as stop_run:
            self.observer.dialog.start.click()
            template = read_template(self.observer.template_path)
            payload = (np.concatenate((template, np.zeros(3200))) * 32767).astype("<i2").tobytes()
            source.stream.push(payload)
            self.wait_until(lambda: self.observer.hit_count == 1)
            self.assertIn("疑似闪光音效", self.window.log_view.toPlainText())
            self.assertTrue(self.window.running)
            stop_run.assert_not_called()
            self.assertEqual(run_log.read_text(encoding="utf-8"), "original checkpoint\n")
            self.observer.dialog.stop.click()
            self.assertTrue(source.stopped)
            self.assertIsNone(self.observer.worker)

    def test_stale_signals_after_stop_do_not_log_and_preferences_do_not_auto_start(self):
        self.select_fake_device()
        with patch("pyside_app.audio_observer.QAudioSource", return_value=FakeSource()):
            self.observer.start()
        session = self.observer.session
        self.observer.stop()
        before = self.window.log_view.toPlainText()
        self.observer._matched(session, SoundMatch(.95, 0, .77, -20), time.monotonic())
        self.assertEqual(self.window.log_view.toPlainText(), before)
        saved = json.loads((self.root / "audio_observer.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["device_name"], "采集卡游戏音频")
        self.assertNotIn("enabled", saved)

    def test_device_disconnect_and_watchdog_stop_only_audio(self):
        self.select_fake_device()
        source = FakeSource()
        with patch("pyside_app.audio_observer.QAudioSource", return_value=source):
            self.observer.start()
        self.window.running = True
        with patch.object(self.window, "stop_run") as stop_run, patch("pyside_app.audio_observer.QMediaDevices.audioInputs", return_value=[]):
            self.observer.refresh_devices()
            self.assertTrue(source.stopped)
            self.assertTrue(self.window.running)
            stop_run.assert_not_called()
        self.assertIn("断开", self.observer.dialog.status.text())
        self.select_fake_device()
        with patch("pyside_app.audio_observer.QAudioSource", return_value=FakeSource()):
            self.observer.start()
        self.observer.last_received = time.monotonic() - 3
        self.observer._check_stream()
        self.assertIsNone(self.observer.source)
        self.assertTrue(self.window.running)

    def test_observation_preserves_incomplete_stdout_and_bypasses_error_parser(self):
        self.window.log_view.clear()
        self.window._append_log("目标")
        original_pending = self.window.pending_output
        self.window.append_observation_log(LOG_PREFIX + "音源=Unhandled exception 疑似闪光音效")
        self.assertEqual(self.window.pending_output, original_pending)
        self.window._append_log("信息\n", final=True)
        text = self.window.log_view.toPlainText()
        self.assertIn("目标信息", text)
        self.assertIn("疑似闪光音效", text)
        self.assertEqual(self.window.runtime_issues, {})
        from pyside_app.window import FrlgWindow
        with patch.object(self.window, "_read_output"), patch.object(self.window, "_notify_run_finished") as notify:
            FrlgWindow._process_finished(self.window, 0, None)
        self.assertFalse(notify.call_args.kwargs["fatal_output"])

    def test_worker_drops_bounded_backlog_and_does_not_join_discontinuous_sound(self):
        template = read_template(self.observer.template_path)
        worker = AudioWorker("test", template, 16000, 1, "int16", .8)
        data = (template[:6000] * 32767).astype("<i2").tobytes()
        for _ in range(30):
            worker.submit(data, time.monotonic())
        self.assertLessEqual(worker.packets.qsize(), 12)
        self.assertTrue(any(packet[2] for packet in list(worker.packets.queue)))
        worker.stop()
        worker.deleteLater()

    def test_dropped_backlog_keeps_pcm_frame_alignment(self):
        template = read_template(self.observer.template_path)
        worker = AudioWorker("test", template, 11025, 2, "float32", .8)
        samples = np.arange(12000 * 2, dtype="<f4").tobytes()
        worker.submit(samples[:3], time.monotonic())
        worker.submit(samples[3:], time.monotonic())
        payload, _, reset = worker.packets.get_nowait()
        self.assertTrue(reset)
        self.assertEqual(len(payload) % 8, 0)
        self.assertEqual(payload, samples[-(11025 // 4 * 8):])
        worker.stop()
        worker.deleteLater()

    def test_log_write_failure_stops_only_observer_and_stays_visible(self):
        self.select_fake_device()
        source = FakeSource()
        with patch("pyside_app.audio_observer.QAudioSource", return_value=source):
            self.observer.start()
        self.window.running = True
        with patch.object(self.observer.log, "append", side_effect=OSError("disk full")), patch.object(self.window, "stop_run") as stop_run:
            self.observer._matched(self.observer.session, SoundMatch(.95, 0, .77, -20), time.monotonic())
            stop_run.assert_not_called()
        self.assertTrue(self.window.running)
        self.assertTrue(source.stopped)
        self.assertIn("无法保存", self.observer.dialog.status.text())
        self.assertNotIn("已记录 1", self.observer.dialog.status.text())


if __name__ == "__main__":
    unittest.main()
