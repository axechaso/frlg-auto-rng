"""Qt controller and capture windows; share the formal serial transport."""
import json
import threading
import time
import urllib.request
from pathlib import Path

from PySide6.QtCore import QEvent, QPoint, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QImage, QKeySequence, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QGridLayout, QHBoxLayout, QKeySequenceEdit, QLabel, QMessageBox, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from app_paths import DATA_ROOT, RESOURCE_ROOT, USER_DATA_ROOT
from tid_session import write_json_atomic
from .jobs import Job

DEFAULT_KEYS = dict(zip(("A", "B", "X", "Y", "L", "R", "ZL", "ZR", "PLUS", "MINUS", "CAPTURE", "HOME", "LCLICK", "RCLICK", "TOP", "DOWN", "LEFT", "RIGHT"),
                        ("y", "u", "i", "h", "g", "t", "f", "r", "k", "j", "z", "c", "q", "e", "w", "s", "a", "d")))
DIRECTIONS = {(0, -1): "TOP", (0, 1): "DOWN", (-1, 0): "LEFT", (1, 0): "RIGHT",
              (-1, -1): "TOP_LEFT", (1, -1): "TOP_RIGHT", (-1, 1): "DOWN_LEFT", (1, 1): "DOWN_RIGHT"}
TOOL_STYLE = """
QDialog { background: #f3f6fb; }
QLabel { color: #17314d; }
QPushButton { background: white; color: #45618a; border: 1px solid #d7e0ef;
    border-radius: 8px; padding: 8px 12px; min-height: 20px; }
QPushButton:hover { background: #edf1ff; border-color: #adb9ef; }
QPushButton:pressed { background: #e1e6ff; color: #5260d9; }
QPushButton:disabled { background: #edf0f5; color: #95a3b8; }
QKeySequenceEdit { background: white; border: 1px solid #d7e0ef; border-radius: 7px; padding: 8px; }
"""


def validate_mapping(mapping):
    if not isinstance(mapping, dict) or set(mapping) != set(DEFAULT_KEYS):
        raise ValueError("键位配置不完整")
    values = {key: str(value).strip().casefold() for key, value in mapping.items()}
    if any(not value or QKeySequence.fromString(value).isEmpty() for value in values.values()) or len(set(values.values())) != len(values):
        raise ValueError("每个手柄按键都需要不同的有效键盘按键")
    return values


class ControllerWindow(QDialog):
    def __init__(self, host):
        super().__init__(host)
        self.host = host
        self.setWindowTitle("虚拟手柄")
        self.setStyleSheet(TOOL_STYLE)
        self.resize(660, 340)
        self.controller = self.native = self.job = None
        self.pressed = set()
        self.keyboard_pressed = {}
        self.shutting_down = False
        self.mapping_path = host.paths.user / "manual_controller_keymap.json"
        self.mapping = dict(DEFAULT_KEYS)
        self.layout_box = QVBoxLayout(self)
        self.layout_box.setContentsMargins(18, 16, 18, 18)
        self.layout_box.setSpacing(12)
        self.status = QLabel("上行为手柄键，下行为键盘键。\n选择主界面的串口后连接；失去焦点会释放全部按键。")
        self.status.setWordWrap(True)
        self.status.setFixedHeight(44)
        self.layout_box.addWidget(self.status)
        row = QHBoxLayout()
        self.connect_button = QPushButton("连接")
        self.connect_button.clicked.connect(self.toggle_connection)
        row.addWidget(self.connect_button)
        for title, callback in (("释放全部", self.release_all), ("键位设置", self.edit_mapping), ("手柄浮窗", self.toggle_overlay)):
            button = QPushButton(title)
            button.clicked.connect(callback)
            row.addWidget(button)
        topmost = QPushButton("置顶")
        topmost.setCheckable(True)
        topmost.toggled.connect(self.set_topmost)
        row.addWidget(topmost)
        self.layout_box.addLayout(row)
        grid = QGridLayout()
        grid.setSpacing(8)
        self.buttons = {}
        for i, key in enumerate(DEFAULT_KEYS):
            button = QPushButton(key)
            button.setMinimumHeight(44)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.pressed.connect(lambda key=key: self.press(key))
            button.released.connect(lambda key=key: self.release(key))
            grid.addWidget(button, i // 6, i % 6)
            self.buttons[key] = button
        self.layout_box.addLayout(grid)
        self.overlay = ControllerOverlay(self)
        try:
            mapping_source = self.mapping_path
            if not mapping_source.is_file() and host.paths.user == USER_DATA_ROOT:
                mapping_source = DATA_ROOT / "runtime/manual_controller_keymap.json"
            if mapping_source.is_file():
                self.mapping = validate_mapping(json.loads(mapping_source.read_text(encoding="utf-8")))
        except (ValueError, OSError) as exc:
            self.status.setText(f"键位配置未载入：{exc}；暂用默认键位。")
        self.refresh_keys()
        QApplication.instance().installEventFilter(self)

    def refresh_keys(self):
        for key, button in self.buttons.items():
            button.setText(f"{key}\n{self.mapping[key].upper()}")
            button.setProperty("active", key in self.pressed)
            button.setStyleSheet("background:#e7ebff;color:#4f5fd4;" if key in self.pressed else "")
        self.overlay.update()

    def set_topmost(self, enabled):
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, enabled)
        self.show()

    def toggle_connection(self):
        if self.controller:
            self.disconnect()
            return
        if self.job:
            return
        port = self.host.fields["port"].currentData()
        if not port or self.host.running or self.host.job:
            self.status.setText("请先选择串口，并停止当前自动运行或预检。")
            return
        self.connect_button.setEnabled(False)
        self.status.setText(f"正在连接 {port}……")
        def connect(cancel, progress):
            from easycon import EasyConController, GamePadKey
            controller = EasyConController()
            try:
                if not controller.try_connect_port(port, controller.baudrate, timeout=1.0):
                    raise ValueError(f"无法连接 {port}")
                return controller, GamePadKey
            except Exception:
                controller.disconnect()
                raise
        self.job = Job(connect)
        self.job_result = None
        self.job_error = ""
        self.job.succeeded.connect(lambda result: setattr(self, "job_result", result))
        self.job.failed.connect(lambda error: setattr(self, "job_error", error))
        self.job.finished.connect(self.connected)
        self.job.start()

    def connected(self):
        job, self.job = self.job, None
        self.connect_button.setEnabled(True)
        if self.job_error:
            self.status.setText(f"连接失败：{self.job_error}")
        else:
            self.controller, self.native = self.job_result
            self.connect_button.setText("断开")
            self.status.setText(f"已连接 {self.controller.port_name}")
        job.deleteLater()
        if self.shutting_down:
            self.disconnect()
            self.close()

    def disconnect(self):
        self.release_all()
        if self.controller:
            try:
                self.controller.disconnect()
            except Exception as exc:
                self.status.setText(f"串口断开时返回错误：{exc}")
        self.controller = self.native = None
        self.connect_button.setText("连接")
        self.status.setText("未连接")
        self.overlay.update()

    def sync_direction(self):
        x = int("RIGHT" in self.pressed) - int("LEFT" in self.pressed)
        y = int("DOWN" in self.pressed) - int("TOP" in self.pressed)
        direction = DIRECTIONS.get((x, y))
        if direction:
            self.controller.press(getattr(self.native, direction))
        else:
            self.controller.release(self.native.TOP)

    def press(self, key):
        if not self.controller or not self.controller.is_connected or key in self.pressed:
            return
        try:
            self.pressed.add(key)
            if key in ("TOP", "DOWN", "LEFT", "RIGHT"):
                self.sync_direction()
            else:
                self.controller.press(getattr(self.native, key))
        except Exception as exc:
            self.release_all()
            self.status.setText(f"按键发送失败：{exc}")
        self.refresh_keys()

    def release(self, key):
        if key not in self.pressed:
            return
        self.pressed.discard(key)
        try:
            if self.controller and self.controller.is_connected:
                if key in ("TOP", "DOWN", "LEFT", "RIGHT"):
                    self.sync_direction()
                else:
                    self.controller.release(getattr(self.native, key))
        except Exception as exc:
            self.status.setText(f"释放失败：{exc}")
        self.refresh_keys()

    def release_all(self):
        self.pressed.clear()
        self.keyboard_pressed.clear()
        try:
            if self.controller and self.controller.is_connected:
                self.controller.release_all()
        except Exception as exc:
            self.status.setText(f"释放失败：{exc}")
        self.refresh_keys()

    def eventFilter(self, obj, event):
        if obj is self and event.type() == QEvent.Type.WindowDeactivate:
            self.release_all()
        if QApplication.activeWindow() is self and event.type() in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
            if event.isAutoRepeat():
                return True
            text = QKeySequence(event.keyCombination()).toString().casefold()
            key = self.keyboard_pressed.pop(event.key(), None) if event.type() == QEvent.Type.KeyRelease else next((key for key, value in self.mapping.items() if value == text), None)
            if key:
                if event.type() == QEvent.Type.KeyPress:
                    self.keyboard_pressed[event.key()] = key
                (self.press if event.type() == QEvent.Type.KeyPress else self.release)(key)
                return True
        return super().eventFilter(obj, event)

    def edit_mapping(self):
        self.release_all()
        dialog = QDialog(self)
        dialog.setWindowTitle("键位设置")
        layout = QVBoxLayout(dialog)
        grid = QGridLayout()
        edits = {}
        for i, (key, value) in enumerate(self.mapping.items()):
            grid.addWidget(QLabel(key), i // 3, i % 3 * 2)
            edit = QKeySequenceEdit(QKeySequence(value))
            edit.setMaximumSequenceLength(1)
            edits[key] = edit
            grid.addWidget(edit, i // 3, i % 3 * 2 + 1)
        layout.addLayout(grid)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.RestoreDefaults)
        buttons.rejected.connect(dialog.reject)
        buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults).clicked.connect(lambda: [edits[key].setKeySequence(QKeySequence(value)) for key, value in DEFAULT_KEYS.items()])
        def save():
            try:
                mapping = validate_mapping({key: edit.keySequence().toString() for key, edit in edits.items()})
                write_json_atomic(self.mapping_path, mapping)
                self.mapping = mapping
                self.refresh_keys()
                dialog.accept()
            except (ValueError, OSError) as exc:
                QMessageBox.warning(dialog, "键位未保存", str(exc))
        buttons.accepted.connect(save)
        layout.addWidget(buttons)
        dialog.exec()

    def toggle_overlay(self):
        self.overlay.setVisible(not self.overlay.isVisible())

    def closeEvent(self, event):
        self.shutting_down = True
        self.disconnect()
        self.overlay.hide()
        if self.job:
            self.job.cancelled.set()
            event.ignore()
        else:
            event.accept()


class ControllerOverlay(QWidget):
    def __init__(self, controller):
        super().__init__(controller, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.controller = controller
        self.setFixedSize(100, 100)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.assets = {path.stem: QPixmap(str(path)) for path in (RESOURCE_ROOT / "assets/easycon_vpad").glob("*.png")}
        self.drag = None
        self.setToolTip("右键拖动；左键显示手柄；中键隐藏。")

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.drawPixmap(0, 0, self.assets.get("JoyCon", QPixmap()))
        pressed = self.controller.pressed
        for key in ("ZL", "ZR", "L", "R"):
            painter.drawPixmap(0, 0, self.assets.get(f"JoyCon_{key}_{int(key in pressed)}", QPixmap()))
        positions = {"A": (83, 33), "B": (75, 42), "X": (75, 25), "Y": (67, 33), "TOP": (24, 58),
            "DOWN": (24, 70), "LEFT": (18, 64), "RIGHT": (30, 64), "LCLICK": (24, 33), "RCLICK": (75, 64),
            "PLUS": (67, 14), "MINUS": (31, 14), "HOME": (69, 84), "CAPTURE": (29, 84)}
        painter.setPen(Qt.PenStyle.NoPen)
        for key, (x, y) in positions.items():
            painter.setBrush(QColor("#22c58b" if key in pressed else "#323232"))
            painter.drawEllipse(QPoint(x, y), 4, 4)
        painter.setBrush(QColor("white" if self.controller.controller else "#444444"))
        painter.drawRect(47, 42, 5, 15)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            self.drag = event.globalPosition().toPoint() - self.pos()
        elif event.button() == Qt.MouseButton.MiddleButton:
            self.hide()
        else:
            self.controller.show()
            self.controller.activateWindow()

    def mouseMoveEvent(self, event):
        if self.drag is not None:
            target = event.globalPosition().toPoint() - self.drag
            bounds = self.screen().availableGeometry()
            self.move(max(bounds.left(), min(target.x(), bounds.right() - 99)), max(bounds.top(), min(target.y(), bounds.bottom() - 99)))

    def mouseReleaseEvent(self, event):
        self.drag = None


class FrameReader:
    """Latest-frame mailbox; no UI objects are touched by capture threads."""
    def __init__(self, source):
        self.source = source
        self.stop = threading.Event()
        self.frame = None
        self.status = "正在连接画面……"
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self):
        capture = None
        try:
            if isinstance(self.source, str):
                while not self.stop.is_set():
                    try:
                        with urllib.request.urlopen(self.source, timeout=1) as response:
                            buffer = b""
                            while not self.stop.is_set():
                                chunk = response.read(4096)
                                if not chunk:
                                    break
                                buffer += chunk
                                start, end = buffer.find(b"\xff\xd8"), buffer.find(b"\xff\xd9")
                                if 0 <= start < end:
                                    frame = QImage.fromData(buffer[start:end + 2])
                                    buffer = buffer[end + 2:]
                                    if not frame.isNull():
                                        self.frame = frame
                                        self.status = "运行器共享画面"
                                if len(buffer) > 8 * 1024 * 1024:
                                    buffer = b""
                    except (OSError, ValueError) as exc:
                        self.status = f"等待运行器画面：{exc}"
                    self.stop.wait(.3)
            else:
                import cv2
                capture = cv2.VideoCapture(self.source, cv2.CAP_DSHOW)
                if not capture.isOpened():
                    raise ValueError("采集卡打开失败，请确认未被其他程序占用")
                while not self.stop.is_set():
                    ok, frame = capture.read()
                    if ok:
                        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                        self.frame = QImage(rgb.data, rgb.shape[1], rgb.shape[0], rgb.strides[0], QImage.Format.Format_RGB888).copy()
                        self.status = "采集卡实时画面"
                    else:
                        self.status = "没有收到画面，请重连"
                    self.stop.wait(.01)
        except Exception as exc:
            self.status = f"画面连接失败：{exc}"
        finally:
            if capture:
                capture.release()


class MonitorWindow(QDialog):
    def __init__(self, host):
        super().__init__(host)
        self.host = host
        self.reader = None
        self.old_readers = []
        self.setWindowTitle("监视窗口")
        self.setStyleSheet(TOOL_STYLE)
        self.resize(720, 490)
        layout = QVBoxLayout(self)
        self.toolbar = QWidget()
        tools = QHBoxLayout(self.toolbar)
        self.status = QLabel("等待连接")
        self.status.setWordWrap(True)
        self.status.setMinimumWidth(0)
        self.status.setMaximumHeight(48)
        self.status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        tools.addWidget(self.status, 1)
        for text, callback in (("重连", self.restart), ("置顶", self.toggle_topmost)):
            button = QPushButton(text)
            button.clicked.connect(callback)
            tools.addWidget(button)
        layout.addWidget(self.toolbar)
        self.picture = QLabel("双击仅显示画面；滚轮缩放窗口")
        self.picture.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.picture.setMinimumSize(240, 160)
        self.picture.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.picture.setStyleSheet("background:#142038;color:#c7d4e9;border-radius:8px")
        self.picture.installEventFilter(self)
        layout.addWidget(self.picture, 1)
        self.render_after = 0
        self.timer = QTimer(self)
        self.timer.setInterval(33)
        self.timer.timeout.connect(self.render)
        self.timer.start()

    def current_source(self):
        if self.host.running:
            url = self.host.run_command.preview_url if self.host.run_command else ""
            if not url:
                raise ValueError("当前原版 CLI 不提供共享画面，请停止后查看采集卡")
            return url
        source = self.host.fields["video"].currentData()
        if source is None:
            raise ValueError("请先选择采集卡")
        return source

    def stop_capture(self):
        if self.reader:
            self.reader.stop.set()
            self.old_readers.append(self.reader)
            self.reader = None
        self.old_readers = [reader for reader in self.old_readers if reader.thread.is_alive()]

    def restart(self):
        self.stop_capture()
        if self.old_readers:
            self.status.setText("正在释放上次采集……")
            QTimer.singleShot(100, self.restart_if_visible)
            return
        try:
            self.reader = FrameReader(self.current_source())
        except ValueError as exc:
            self.status.setText(str(exc))

    def restart_if_visible(self):
        if self.isVisible():
            self.restart()

    def render(self):
        if self.reader:
            self.status.setText(self.reader.status)
            if self.reader.frame is not None and time.monotonic() >= self.render_after:
                self.picture.setPixmap(QPixmap.fromImage(self.reader.frame).scaled(self.picture.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, event):
        self.render_after = time.monotonic() + .12
        super().resizeEvent(event)

    def toggle_topmost(self):
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, not bool(self.windowFlags() & Qt.WindowType.WindowStaysOnTopHint))
        self.show()

    def eventFilter(self, obj, event):
        if obj is self.picture and event.type() == QEvent.Type.MouseButtonDblClick:
            self.toolbar.setVisible(not self.toolbar.isVisible())
            return True
        if obj is self.picture and event.type() == QEvent.Type.Wheel:
            factor = 1.1 if event.angleDelta().y() > 0 else 1 / 1.1
            self.resize(max(320, int(self.width() * factor)), max(240, int(self.height() * factor)))
            return True
        return super().eventFilter(obj, event)

    def closeEvent(self, event):
        self.stop_capture()
        event.accept()
