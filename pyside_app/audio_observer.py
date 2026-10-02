"""Opt-in capture-card audio observer. It has no access to workflow controls."""

from __future__ import annotations

import json
import math
import queue
import threading
import time
import uuid

import numpy as np
from PySide6.QtCore import QObject, QThread, QTimer, Signal
from PySide6.QtMultimedia import QAudioFormat, QAudioSource, QMediaDevices, QtAudio
from PySide6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel,
    QProgressBar, QPushButton, QVBoxLayout,
)

from app_paths import RESOURCE_ROOT
from pyside_chrome import ThemedDialog as QDialog
from audio_observer import (
    DEFAULT_THRESHOLD, TEMPLATE_NAME, ObservationLog, PcmStream,
    ShinySoundDetector, read_template, template_digest,
)
from tid_session import write_json_atomic


class AudioWorker(QThread):
    matched = Signal(str, object, float)
    level = Signal(str, float)
    gap = Signal(str, str)
    failed = Signal(str, str)

    def __init__(self, session, template, sample_rate, channels, sample_format, threshold, parent=None):
        super().__init__(parent)
        self.session = session
        self.decoder = PcmStream(sample_rate, channels, sample_format)
        self.detector = ShinySoundDetector(template, threshold)
        self.bytes_per_second = sample_rate * self.decoder.frame_bytes
        self.pending_bytes = b""
        self.packets = queue.Queue(maxsize=12)
        self.stopping = threading.Event()

    def submit(self, data: bytes, received: float):
        if self.stopping.is_set():
            return
        data = self.pending_bytes + data
        size = len(data) // self.decoder.frame_bytes * self.decoder.frame_bytes
        self.pending_bytes = data[size:]
        data = data[:size]
        if not data:
            return
        reset = False
        if len(data) > self.bytes_per_second:
            # Discard stale backlog instead of detecting old sounds as new.
            keep = self.bytes_per_second // (4 * self.decoder.frame_bytes) * self.decoder.frame_bytes
            data = data[-keep:]
            reset = True
        if self.packets.full():
            while True:
                try:
                    self.packets.get_nowait()
                except queue.Empty:
                    break
            reset = True
        self.packets.put_nowait((data, received, reset))

    def stop(self):
        self.stopping.set()

    def run(self):
        last_received = None
        segment_start = 0.0
        last_level = last_gap = 0.0
        try:
            while not self.stopping.is_set():
                try:
                    data, received, reset = self.packets.get(timeout=0.1)
                except queue.Empty:
                    continue
                duration = len(data) / self.bytes_per_second
                if time.monotonic() - received > 0.75:
                    reset = True
                    data = b""
                if last_received is not None and received - last_received > duration + 0.75:
                    reset = True
                if reset or last_received is None:
                    self.decoder.reset()
                    self.detector.reset()
                    segment_start = received - duration
                    if reset and received - last_gap > 1.0:
                        self.gap.emit(self.session, "音频不连续，已清空比对窗口；本段不作声音结论。")
                        last_gap = received
                last_received = received
                if not data:
                    last_received = None
                    continue
                samples = self.decoder.feed(data)
                if len(samples) and received - last_level >= 0.1:
                    dbfs = 10 * math.log10(max(float(np.mean(samples * samples)), 1e-12))
                    self.level.emit(self.session, dbfs)
                    last_level = received
                matches = self.detector.feed(samples)
                for match in matches:
                    if not self.stopping.is_set() and time.monotonic() - received < 0.75:
                        self.matched.emit(self.session, match, segment_start + match.end_seconds)
        except Exception as exc:
            self.failed.emit(self.session, str(exc))


class AudioObserverDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("声音判闪试用")
        self.resize(650, 460)
        self.setMinimumWidth(530)
        self.setStyleSheet("""
            QDialog { background: #f3f6fb; }
            QDoubleSpinBox { background: white; color: #17314d; border: 1px solid #d7e0ef;
                border-radius: 7px; padding: 8px; padding-right: 27px; }
            QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
                subcontrol-origin: border; width: 24px; background: #edf1fa;
                border-left: 1px solid #d7e0ef; }
            QDoubleSpinBox::up-button { subcontrol-position: top right; border-top-right-radius: 7px; }
            QDoubleSpinBox::down-button { subcontrol-position: bottom right; border-bottom-right-radius: 7px; }
            QDoubleSpinBox::up-arrow { image: url("@UP@"); width: 12px; height: 12px; }
            QDoubleSpinBox::down-arrow { image: url("@DOWN@"); width: 12px; height: 12px; }
            QProgressBar { border: 1px solid #d7e0ef; border-radius: 7px; background: white;
                text-align: center; min-height: 28px; color: #17314d; }
            QProgressBar::chunk { background: #b5d9cf; border-radius: 7px; }
        """.replace("@UP@", (RESOURCE_ROOT / "assets/pyside_preview/chevron-up.svg").as_posix())
            .replace("@DOWN@", (RESOURCE_ROOT / "assets/pyside_preview/chevron-down.svg").as_posix()))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        intro = QLabel("选择采集卡的音频输入后开始监听。识别到疑似闪光音效时，仅在日志中记录，供人工对照。")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        form = QFormLayout()
        self.device = QComboBox()
        self.device.setMinimumContentsLength(20)
        self.device.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.device.addItem("请刷新并选择采集卡音频输入", "")
        self.refresh = QPushButton("刷新音频设备")
        self.refresh.setProperty("kind", "ghost")
        device_row = QHBoxLayout()
        device_row.addWidget(self.device, 1)
        device_row.addWidget(self.refresh)
        form.addRow("音频输入", device_row)
        form.setVerticalSpacing(12)
        self.threshold = QDoubleSpinBox()
        self.threshold.setRange(0.50, 0.99)
        self.threshold.setSingleStep(0.01)
        self.threshold.setDecimals(2)
        self.threshold.setValue(DEFAULT_THRESHOLD)
        self.threshold.setToolTip("数值越高越严格；这是与样本的相似度，不是识别准确率。")
        form.addRow("相似度阈值", self.threshold)
        form.addRow("识别样本", QLabel("火红 / 叶绿出场音效 v1"))
        self.meter = QProgressBar()
        self.meter.setRange(0, 100)
        self.meter.setValue(0)
        self.meter.setFormat("未监听")
        form.addRow("输入电平", self.meter)
        layout.addLayout(form)
        self.status = QLabel("未监听。开始前请确认所选设备是采集卡的游戏音频。")
        self.status.setWordWrap(True)
        self.status.setMinimumHeight(52)
        layout.addWidget(self.status)
        note = QLabel("试验样本含背景音乐，可能误报或漏报，也无法仅凭声音区分敌我。不会停止任务、操作手柄或改变现有判闪结果。")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.location = QLabel("观察记录会保存在用户目录，之后可在“历史日志”中查看。")
        self.location.setWordWrap(True)
        layout.addWidget(self.location)
        layout.addStretch()
        buttons = QHBoxLayout()
        self.start = QPushButton("开始监听")
        self.start.setProperty("kind", "primary")
        self.stop = QPushButton("停止监听")
        self.stop.setProperty("kind", "ghost")
        self.stop.setEnabled(False)
        hide = QPushButton("收起窗口")
        hide.setProperty("kind", "ghost")
        hide.clicked.connect(self.hide)
        buttons.addWidget(self.start)
        buttons.addWidget(self.stop)
        buttons.addStretch()
        buttons.addWidget(hide)
        layout.addLayout(buttons)


class AudioObserverController(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.w = window
        self.dialog = AudioObserverDialog(window)
        self.config_path = window.paths.user / "audio_observer.json"
        self.template_path = RESOURCE_ROOT / "assets" / "audio" / TEMPLATE_NAME
        self.log = ObservationLog(window.paths.user)
        self.dialog.location.setText(f"观察日志：{self.log.root}\n收起窗口会继续监听，退出程序会停止。")
        self.source = self.stream = self.worker = None
        self.retired_workers = []
        self.session = ""
        self.device_id = self.device_name = ""
        self.devices = {}
        self.last_received = 0.0
        self.hit_count = 0
        self._load_settings()
        self.media = QMediaDevices(self)
        self.media.audioInputsChanged.connect(self.refresh_devices)
        self.watchdog = QTimer(self)
        self.watchdog.setInterval(500)
        self.watchdog.timeout.connect(self._check_stream)
        self.dialog.refresh.clicked.connect(self.refresh_devices)
        self.dialog.start.clicked.connect(self.start)
        self.dialog.stop.clicked.connect(self.stop)
        window._bind("声音判闪试用", self.show)

    @staticmethod
    def _device_id(device):
        return bytes(device.id().toHex()).decode("ascii")

    def _load_settings(self):
        try:
            data = json.loads(self.config_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return
            self.device_id = str(data.get("device_id", ""))
            self.device_name = str(data.get("device_name", ""))
            threshold = data.get("threshold", DEFAULT_THRESHOLD)
            if type(threshold) in (int, float) and math.isfinite(threshold) and 0.5 <= threshold <= 0.99:
                self.dialog.threshold.setValue(threshold)
        except (OSError, ValueError):
            pass

    def _save_settings(self):
        write_json_atomic(self.config_path, {
            "device_id": self.device_id, "device_name": self.device_name,
            "threshold": self.dialog.threshold.value(),
        })

    def show(self):
        self.refresh_devices()
        self.dialog.show()
        self.dialog.raise_()

    def refresh_devices(self):
        selected = self.dialog.device.currentData() or self.device_id
        self.devices = {self._device_id(device): device for device in QMediaDevices.audioInputs()}
        if self.source is not None and self.device_id not in self.devices:
            self._fault(self.session, "所选音频设备已断开，请重新选择并开始监听。")
        self.dialog.device.clear()
        self.dialog.device.addItem("请选择采集卡音频输入", "")
        for identity, device in self.devices.items():
            self.dialog.device.addItem(device.description(), identity)
        if selected and selected not in self.devices:
            self.dialog.device.addItem(f"未连接：{self.device_name or '已保存的音频设备'}", selected)
        self.dialog.device.setCurrentIndex(max(0, self.dialog.device.findData(selected)))

    def _record(self, message):
        try:
            line = self.log.append(message)
        except OSError as exc:
            self.stop(silent=True)
            self.dialog.status.setText(f"观察日志无法保存，已停止声音监听：{exc}")
            return False
        self.w.append_observation_log(line)
        return True

    def start(self):
        if self.source is not None or self.worker is not None:
            return
        identity = self.dialog.device.currentData()
        device = self.devices.get(identity)
        if device is None:
            self.dialog.status.setText("请先刷新并明确选择采集卡音频输入，不会自动连接默认麦克风。")
            return
        try:
            template = read_template(self.template_path)
            format = QAudioFormat()
            format.setSampleRate(16000)
            format.setChannelCount(1)
            format.setSampleFormat(QAudioFormat.SampleFormat.Int16)
            if not device.isFormatSupported(format):
                format = device.preferredFormat()
            formats = {
                QAudioFormat.SampleFormat.Int16: "int16",
                QAudioFormat.SampleFormat.Int32: "int32",
                QAudioFormat.SampleFormat.UInt8: "uint8",
                QAudioFormat.SampleFormat.Float: "float32",
            }
            sample_format = formats.get(format.sampleFormat())
            if sample_format is None:
                raise ValueError("音频设备未提供支持的 PCM 格式")
            self.device_id, self.device_name = identity, device.description()
            self._save_settings()
            self.session = uuid.uuid4().hex
            self.hit_count = 0
            self.worker = AudioWorker(
                self.session, template, format.sampleRate(), format.channelCount(),
                sample_format, self.dialog.threshold.value(), self,
            )
            self.worker.matched.connect(self._matched)
            self.worker.level.connect(self._level)
            self.worker.gap.connect(self._gap)
            self.worker.failed.connect(self._fault)
            self.worker.start()
            self.source = QAudioSource(device, format, self)
            source = self.source
            source.setBufferSize(format.bytesForDuration(250000))
            source.stateChanged.connect(lambda state: self._state_changed(source, state))
            self.last_received = time.monotonic()
            self.stream = source.start()
            if self.source is not source or self.stream is None or source.error() != QtAudio.Error.NoError:
                raise RuntimeError("音频输入无法启动，请检查设备占用和 Windows 音频权限")
            stream = self.stream
            stream.readyRead.connect(lambda: self._read(source, stream))
            self.watchdog.start()
            self._set_active(True)
            self.dialog.status.setText(f"正在监听 {self.device_name}；{format.sampleRate()} Hz / {format.channelCount()} 声道。仅记录声音观察。")
            if not self._record(
                f"开始监听；音源={self.device_name}；阈值={self.dialog.threshold.value():.2f}；"
                f"样本={TEMPLATE_NAME}；样本SHA256={template_digest(self.template_path)}；仅记录，不参与流程判断。"
            ):
                return
            self._read(source, stream)
        except Exception as exc:
            self.stop(silent=True)
            self.dialog.status.setText(f"声音监听未启动：{exc}")

    def _set_active(self, active):
        self.dialog.start.setEnabled(not active)
        self.dialog.stop.setEnabled(active)
        self.dialog.device.setEnabled(not active)
        self.dialog.threshold.setEnabled(not active)
        self.dialog.refresh.setEnabled(not active)

    def _read(self, source, stream):
        if source is not self.source or self.worker is None:
            return
        data = bytes(stream.readAll())
        if data:
            self.last_received = time.monotonic()
            self.worker.submit(data, self.last_received)

    def _level(self, session, dbfs):
        if session != self.session:
            return
        self.dialog.meter.setValue(max(0, min(100, round((dbfs + 60) / 60 * 100))))
        self.dialog.meter.setFormat("接近静音" if dbfs < -65 else f"{dbfs:.1f} dBFS")

    def _matched(self, session, match, captured_at):
        if session != self.session or not self.session:
            return
        self.hit_count += 1
        delay = max(0, time.monotonic() - captured_at)
        run = getattr(self.w, "run_command", None)
        context = str(run.log_path) if getattr(self.w, "running", False) and run else "未运行自动流程"
        saved = self._record(
            f"疑似闪光音效；相似度={match.score:.3f}；阈值={self.dialog.threshold.value():.2f}；"
            f"音源={self.device_name}；第{self.hit_count}次；声音窗口结束距今约{delay:.2f}秒；"
            f"运行日志={context}；仅记录，不参与流程判断。"
        )
        if saved:
            self.dialog.status.setText(f"监听中 · 已记录 {self.hit_count} 次疑似闪光音效，最近相似度 {match.score:.3f}。")

    def _gap(self, session, message):
        if session == self.session and self.session:
            if self._record(message):
                self.dialog.status.setText(message)

    def _fault(self, session, message):
        if session != self.session or not self.session:
            return
        if self._record(f"音频不可用：{message}；不作声音结论，现有流程继续。"):
            self.stop(silent=True)
            self.dialog.status.setText(f"监听已停止：{message}")

    def _state_changed(self, source, state):
        if source is self.source and state == QtAudio.State.StoppedState and source.error() != QtAudio.Error.NoError:
            self._fault(self.session, f"音频采集异常（{source.error().name}），请重新连接。")

    def _check_stream(self):
        if self.source is not None and time.monotonic() - self.last_received > 2.5:
            self._fault(self.session, "超过 2.5 秒未收到音频数据；静音与断流不同，请检查输入。")

    def stop(self, *, silent=False):
        was_active = bool(self.session)
        self.session = ""  # Ignore queued signals from the previous session.
        self.watchdog.stop()
        source, self.source = self.source, None
        self.stream = None
        if source is not None:
            source.stop()
            source.deleteLater()
        worker, self.worker = self.worker, None
        if worker is not None:
            worker.stop()
            if worker.wait(1500):
                worker.deleteLater()
            else:
                self.retired_workers.append(worker)
        self._set_active(False)
        self.dialog.meter.setValue(0)
        self.dialog.meter.setFormat("未监听")
        self.dialog.status.setText("已停止监听。")
        if was_active and not silent:
            self._record("停止监听。")

    def close(self):
        self.stop()
        for worker in list(self.retired_workers):
            worker.stop()
            if not worker.wait(100):
                return False
            worker.deleteLater()
            self.retired_workers.remove(worker)
        self.dialog.hide()
        return True
