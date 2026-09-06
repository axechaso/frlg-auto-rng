"""Qt controller and capture windows; share the formal serial transport."""
import json
import threading
import time
import urllib.request
from pathlib import Path

from PySide6.QtCore import QEvent, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QImage, QKeySequence, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QHBoxLayout, QLabel, QMessageBox, QPushButton, QSizePolicy, QVBoxLayout, QWidget
from pyside_chrome import ThemedDialog as QDialog

from app_paths import DATA_ROOT, RESOURCE_ROOT, USER_DATA_ROOT
from tid_session import write_json_atomic
from .jobs import Job
from .controller_layout import ControllerLayout, DEFAULT_KEYS, LABELS, load_mapping_values, validate_mapping
from .controller_keyboard import ControllerKeyboard
from .monitor_view import VideoSurface, ZOOM_WIDTHS, video_rect

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
QPushButton[padKey="true"] { padding:2px; min-height:0; font-size:11px; border-radius:7px; }
QPushButton[padKey="true"][active="true"] { background:#6177f2; border-color:#5369e4; color:white; }
QPushButton:checked { background:#e9edff; border-color:#aebaff; color:#485cc7; }
"""


class ControllerWindow(QDialog):
    def __init__(self, host):
        super().__init__(host)
        self.host = host
        self.setWindowTitle("虚拟手柄")
        self.setStyleSheet(TOOL_STYLE)
        self.resize(820, 660)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled, False)
        self.controller = self.native = self.job = None
        self.pressed = set()
        self.keyboard_pressed = {}
        self.mouse_pressed = set()
        self.shutting_down = False
        self.overlay_only = False
        self.overlay_requested = False
        self.keyboard_active = True
        self.mapping_path = host.paths.user / "pyside6_controller_keymap.json"
        self.mapping = dict(DEFAULT_KEYS)
        self.layout_box = QVBoxLayout(self)
        self.layout_box.setContentsMargins(18, 16, 18, 18)
        self.layout_box.setSpacing(12)
        self.status = QLabel("选择主界面的串口后连接。按手柄位置操作，下方小字为键盘映射。")
        self.status.setWordWrap(True)
        self.layout_box.addWidget(self.status)
        self.key_status = QLabel("键盘：点击手柄或监视画面后操作；开启浮窗可在其他窗口控制。")
        self.key_status.setWordWrap(True)
        self.layout_box.addWidget(self.key_status)
        row = QHBoxLayout()
        self.connect_button = QPushButton("连接")
        self.connect_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.connect_button.setAutoDefault(False)
        self.connect_button.clicked.connect(self.toggle_connection)
        row.addWidget(self.connect_button)
        for title, callback in (("释放全部", self.release_all), ("键位设置", self.edit_mapping), ("手柄浮窗", self.toggle_overlay)):
            button = QPushButton(title)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.setAutoDefault(False)
            button.clicked.connect(callback)
            row.addWidget(button)
        topmost = QPushButton("置顶")
        topmost.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        topmost.setAutoDefault(False)
        topmost.setCheckable(True)
        topmost.toggled.connect(self.set_topmost)
        row.addWidget(topmost)
        self.layout_box.addLayout(row)
        self.pad = ControllerLayout(self.mapping, self)
        self.buttons = self.pad.controls
        for key, button in self.buttons.items():
            button.pressed.connect(lambda key=key: self.mouse_press(key))
            button.released.connect(lambda key=key: self.mouse_release(key))
        self.layout_box.addWidget(self.pad, 1)
        self.overlay = ControllerOverlay(self)
        self.keyboard = ControllerKeyboard(self)
        try:
            mapping_source = self.mapping_path
            if not mapping_source.is_file():
                mapping_source = host.paths.user / "manual_controller_keymap.json"
            if not mapping_source.is_file() and host.paths.user == USER_DATA_ROOT:
                mapping_source = DATA_ROOT / "runtime/manual_controller_keymap.json"
            if mapping_source.is_file():
                self.mapping = load_mapping_values(json.loads(mapping_source.read_text(encoding="utf-8")))
                if mapping_source != self.mapping_path:
                    self.key_status.setText("已保留原键位并补充摇杆方向；可在键位设置恢复图示键位。")
            self.keyboard.update_mapping(self.mapping)
        except (ValueError, OSError) as exc:
            self.mapping = dict(DEFAULT_KEYS)
            self.keyboard.update_mapping(self.mapping)
            self.status.setText(f"键位配置未载入：{exc}；暂用默认键位。")
        self.refresh_keys()
        QApplication.instance().installEventFilter(self)
        QApplication.instance().aboutToQuit.connect(self.keyboard.stop)
        QApplication.instance().aboutToQuit.connect(self.release_all)

    def refresh_keys(self):
        self.pad.refresh(self.mapping, self.pressed)
        self.overlay.update()

    def showEvent(self, event):
        super().showEvent(event)
        if self.shutting_down:
            self.shutting_down = False
            self.keyboard_active = True
        self.start_keyboard()
        QTimer.singleShot(0, self.pad.setFocus)

    def start_keyboard(self):
        try:
            self.keyboard.start()
        except OSError as exc:
            self.key_status.setText(f"{exc}；暂用窗口内键盘输入。")
            if self.overlay_only:
                self.host.set_status(f"手柄键盘监听未启动：{exc}")

    def report_status(self, text):
        self.status.setText(text)
        if self.overlay_only:
            self.host.set_status(text)

    def open_overlay(self):
        if self.host.running or self.host.job:
            self.host.set_status("请先停止自动运行或等待当前任务完成，再打开手柄浮窗。")
            return
        self.overlay_only = True
        self.overlay_requested = True
        self.shutting_down = False
        self.hide()
        self.start_keyboard()
        self.overlay.show_control()
        self.overlay.raise_()
        port = self.host.fields["port"].currentData()
        if self.controller and (not self.controller.is_connected or self.controller.port_name != port):
            self.disconnect()
        if not self.controller and not self.job:
            self.toggle_connection()

    def mouse_press(self, key):
        self.pad.setFocus()
        self.mouse_pressed.add(key)
        self.press(key)

    def mouse_release(self, key):
        self.mouse_pressed.discard(key)
        if key not in self.keyboard_pressed.values():
            self.release(key)

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
            self.report_status("请先在顶部选择串口，并停止当前自动运行或预检。")
            return
        self.connect_button.setEnabled(False)
        self.report_status(f"正在连接 {port}……")
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
        stale = self.overlay_only and (not self.overlay_requested or (self.job_result and self.job_result[0].port_name != self.host.fields["port"].currentData()))
        if stale:
            if self.job_result:
                try:
                    self.job_result[0].disconnect()
                except Exception as exc:
                    self.report_status(f"旧串口连接释放失败：{exc}")
            if self.overlay_requested:
                QTimer.singleShot(0, self.retry_overlay_connection)
        elif self.job_error:
            self.report_status(f"连接失败：{self.job_error}")
        else:
            self.controller, self.native = self.job_result
            self.connect_button.setText("断开")
            self.report_status(f"手柄已连接 {self.controller.port_name}")
            if not self.overlay_only:
                self.pad.setFocus()
        job.deleteLater()
        if self.shutting_down:
            self.disconnect()
            self.close()

    def retry_overlay_connection(self):
        if self.overlay_requested and not self.shutting_down:
            self.toggle_connection()

    def disconnect(self):
        self.release_all()
        if self.controller:
            try:
                self.controller.disconnect()
            except Exception as exc:
                self.status.setText(f"串口断开时返回错误：{exc}")
        self.controller = self.native = None
        self.connect_button.setText("连接")
        self.report_status("手柄未连接")
        self.overlay.update()

    def sync_direction(self):
        x, y = self.direction_vector()
        direction = DIRECTIONS.get((x, y))
        if direction:
            self.controller.press(getattr(self.native, direction))
        else:
            self.controller.release(self.native.TOP)

    def direction_vector(self):
        directions = {"TOP": (0, -1), "DOWN": (0, 1), "LEFT": (-1, 0), "RIGHT": (1, 0),
                      "TOP_LEFT": (-1, -1), "TOP_RIGHT": (1, -1), "DOWN_LEFT": (-1, 1), "DOWN_RIGHT": (1, 1)}
        vectors = [vector for key, vector in directions.items() if key in self.pressed]
        clamp = lambda value: max(-1, min(1, value))
        return clamp(sum(v[0] for v in vectors)), clamp(sum(v[1] for v in vectors))

    def sync_stick(self, prefix):
        x = int(prefix + "_RIGHT" in self.pressed) - int(prefix + "_LEFT" in self.pressed)
        y = int(prefix + "_DOWN" in self.pressed) - int(prefix + "_UP" in self.pressed)
        axis = lambda value: 0 if value < 0 else 255 if value > 0 else 128
        self.controller.set_stick(getattr(self.native, prefix), axis(x), axis(y))

    def press(self, key):
        if not self.controller or not self.controller.is_connected or key in self.pressed:
            return
        try:
            self.pressed.add(key)
            if key.startswith(("LS_", "RS_")):
                self.sync_stick(key[:2])
            elif key in DIRECTIONS.values():
                self.sync_direction()
            else:
                self.controller.press(getattr(self.native, key))
        except Exception as exc:
            self.release_all()
            self.report_status(f"按键发送失败：{exc}")
        self.refresh_keys()

    def release(self, key):
        if key not in self.pressed:
            return
        self.pressed.discard(key)
        try:
            if self.controller and self.controller.is_connected:
                if key.startswith(("LS_", "RS_")):
                    self.sync_stick(key[:2])
                elif key in DIRECTIONS.values():
                    self.sync_direction()
                else:
                    self.controller.release(getattr(self.native, key))
        except Exception as exc:
            self.status.setText(f"释放失败：{exc}")
        self.refresh_keys()

    def release_all(self):
        self.keyboard.reset()
        self.pressed.clear()
        self.keyboard_pressed.clear()
        self.mouse_pressed.clear()
        try:
            if self.controller and self.controller.is_connected:
                self.controller.release_all()
        except Exception as exc:
            self.status.setText(f"释放失败：{exc}")
        self.refresh_keys()

    def keyboard_windows(self):
        monitor = getattr(getattr(self.host, "accessories", None), "monitor", None)
        return tuple(window for window in (self, self.overlay, monitor) if window is not None)

    def keyboard_allowed(self, receiver=None):
        if self.shutting_down or not self.keyboard_active or self.host.running or self.host.job:
            return False
        if self.overlay_only and (not self.controller or not self.controller.is_connected):
            return False
        windows = self.keyboard_windows()
        modal = QApplication.activeModalWidget()
        if modal is not None and modal not in windows:
            return False
        if self.overlay.isVisible() and self.controller and self.controller.is_connected:
            return True
        active = QApplication.activeWindow()
        return active in windows or (active is None and receiver in windows)

    def keyboard_transition(self, token, key, down):
        if down:
            self.keyboard_pressed[token] = key
            self.press(key)
        else:
            self.keyboard_pressed.pop(token, None)
            if key not in self.mouse_pressed and key not in self.keyboard_pressed.values():
                self.release(key)
        state = "按下" if down else "已松开"
        self.key_status.setText(f"键盘 {self.mapping[key].upper()} → {LABELS.get(key, key)}（{state}）" if self.controller else f"已收到键盘 {self.mapping[key].upper()}；手柄尚未连接。")

    def eventFilter(self, obj, event):
        windows = self.keyboard_windows()
        if not self.overlay.isVisible() and ((obj in windows and event.type() in (QEvent.Type.WindowDeactivate, QEvent.Type.Hide)) or event.type() == QEvent.Type.ApplicationDeactivate):
            self.release_all()
        receiver = obj.window() if isinstance(obj, QWidget) else None
        if receiver is self.overlay and self.overlay.isVisible() and event.type() in (QEvent.Type.ShortcutOverride, QEvent.Type.KeyPress, QEvent.Type.KeyRelease) and event.key() == Qt.Key.Key_Escape:
            if event.type() == QEvent.Type.KeyPress:
                self.overlay.exit_control()
            event.accept()
            return True
        if self.keyboard_allowed(receiver) and event.type() in (QEvent.Type.ShortcutOverride, QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
            if event.key() == Qt.Key.Key_Escape and self.overlay.isVisible():
                if event.type() == QEvent.Type.KeyPress:
                    self.overlay.exit_control()
                event.accept()
                return True
            token = ("scan", event.nativeScanCode()) if event.nativeScanCode() else ("key", event.key())
            text = QKeySequence(event.keyCombination()).toString(QKeySequence.SequenceFormat.PortableText).casefold()
            key = self.keyboard_pressed.get(token) if event.type() == QEvent.Type.KeyRelease else next((key for key, value in self.mapping.items() if value == text), None)
            if key is None and event.type() != QEvent.Type.KeyRelease and not (event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.MetaModifier)):
                bare = QKeySequence(event.key()).toString(QKeySequence.SequenceFormat.PortableText).casefold()
                key = next((key for key, value in self.mapping.items() if value == bare), None)
            if not key:
                return super().eventFilter(obj, event)
            if event.type() == QEvent.Type.ShortcutOverride:
                event.accept()
                return True
            if event.isAutoRepeat():
                return True
            self.keyboard_transition(token, key, event.type() == QEvent.Type.KeyPress)
            return True
        return super().eventFilter(obj, event)

    def edit_mapping(self):
        self.release_all()
        dialog = QDialog(self)
        dialog.setWindowTitle("键位设置")
        dialog.resize(820, 620)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("点击对应位置后按键，Esc 清空；左右摇杆与十字键分别设置。"))
        pad = ControllerLayout(self.mapping, dialog, editing=True)
        edits = pad.controls
        layout.addWidget(pad, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.RestoreDefaults)
        buttons.rejected.connect(dialog.reject)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("保存")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults).setText("恢复图示键位")
        buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults).clicked.connect(lambda: [edits[key].setKeySequence(QKeySequence(value)) for key, value in DEFAULT_KEYS.items()])
        def save():
            try:
                mapping = validate_mapping({key: edit.keySequence().toString() for key, edit in edits.items()})
                self.keyboard.build_bindings(mapping)
                write_json_atomic(self.mapping_path, mapping)
                self.keyboard.update_mapping(mapping)
                self.mapping = mapping
                self.refresh_keys()
                dialog.accept()
            except (ValueError, OSError) as exc:
                QMessageBox.warning(dialog, "键位未保存", str(exc))
        buttons.accepted.connect(save)
        layout.addWidget(buttons)
        dialog.exec()

    def toggle_overlay(self):
        if self.overlay.isVisible():
            self.overlay.exit_control()
        else:
            self.overlay.show_control()

    def closeEvent(self, event):
        self.shutting_down = True
        self.overlay_requested = False
        self.keyboard.stop()
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
        self.setAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled, False)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.assets = {path.stem: QPixmap(str(path)) for path in (RESOURCE_ROOT / "assets/easycon_vpad").glob("*.png")}
        self.drag = None
        self.moved = False
        self.setToolTip("左键：启用 / 暂停键盘控制\n中键或 Esc：关闭浮窗并释放按键\n右键拖动：移动；右键单击：位置复位\n亮起：按键 / 摇杆状态；中间指示灯：脚本运行状态")
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.update)
        self.script_started = None
        self.reset_location()

    def reset_location(self):
        screen = QApplication.primaryScreen()
        if screen:
            bounds = screen.availableGeometry()
            self.move(bounds.x() + bounds.width() // 2, bounds.y() + (bounds.height() - 100) // 2)

    def set_active(self, active):
        self.controller.release_all()
        self.controller.keyboard_active = active
        self.setWindowOpacity(1.0 if active else 0.5)
        self.controller.key_status.setText("浮窗键盘已启用：可切换到其他窗口操作；左键暂停，Esc 退出。" if active else "浮窗键盘已暂停，所有按键已释放；左键浮窗可重新启用。")
        self.update()

    def show_control(self):
        self.set_active(True)
        self.show()

    def exit_control(self):
        self.set_active(False)
        self.hide()
        self.controller.key_status.setText("浮窗已关闭，键盘控制已停止；点击“手柄浮窗”可重新启用。")
        if self.controller.overlay_only:
            self.controller.overlay_requested = False
            if self.controller.job:
                self.controller.job.cancelled.set()
            self.controller.disconnect()
            self.controller.keyboard.stop()

    def showEvent(self, event):
        self.timer.start()
        super().showEvent(event)

    def hideEvent(self, event):
        self.timer.stop()
        super().hideEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.drawPixmap(0, 0, self.assets.get("JoyCon", QPixmap()))
        pressed = self.controller.pressed
        # Coordinates, shapes, colors and layers follow EasyCon 1.6.4-a's
        # JCPainter, using its original JoyCon images without modification.
        for prefix, x, y, click in (("LS", 11, 21, "LCLICK"), ("RS", 63, 52, "RCLICK")):
            sx = int(prefix + "_RIGHT" in pressed) - int(prefix + "_LEFT" in pressed)
            sy = int(prefix + "_DOWN" in pressed) - int(prefix + "_UP" in pressed)
            painter.setPen(QPen(QColor("black"), 1))
            painter.setBrush(QColor(0, 255, 0, 200) if sx or sy else QColor(0, 0, 0, 50))
            painter.drawEllipse(QRectF(x + 2, y + 2, 21, 21))
            painter.setPen(QPen(QColor("black"), 1))
            painter.setBrush(QColor("#00ff00" if click in pressed else "#323232"))
            painter.drawEllipse(QRectF(x + (0 if sx < 0 else 10 if sx > 0 else 5), y + (0 if sy < 0 else 10 if sy > 0 else 5), 15, 15))
        dx, dy = self.controller.direction_vector()
        painter.setPen(QPen(QColor("black"), 1))
        for active, x, y in ((dy < 0, 21, 55), (dy > 0, 21, 67), (dx < 0, 15, 61), (dx > 0, 27, 61)):
            painter.setBrush(QColor("#00ff00" if active else "#323232"))
            painter.drawRoundedRect(QRectF(x, y, 6, 6), 2, 2)
        for key in ("ZL", "ZR", "L", "R"):
            painter.drawPixmap(0, 0, self.assets.get(f"JoyCon_{key}_{int(key in pressed)}", QPixmap()))
        for key, (x, y) in {"A": (79, 29), "B": (71, 37), "X": (71, 21), "Y": (63, 29)}.items():
            painter.setBrush(QColor("#00ff00" if key in pressed else "#323232"))
            painter.drawEllipse(QRectF(x, y, 9, 9))
        for key, (x, y) in {"MINUS": (29, 12), "PLUS": (65, 12), "CAPTURE": (27, 82), "HOME": (67, 82)}.items():
            painter.setBrush(QColor("#00ff00" if key in pressed else "#323232"))
            painter.drawRoundedRect(QRectF(x, y, 5, 5), 1, 1)
        if self.controller.host.running:
            if self.script_started is None:
                self.script_started = time.monotonic()
            led = abs(3 - (int((time.monotonic() - self.script_started) / .15) % 6))
        else:
            self.script_started = None
            led = -1
        for i in range(4):
            painter.setBrush(QColor("white") if i == led else QColor(255, 255, 255, 130) if led >= 0 else QColor(0, 0, 0, 130))
            painter.drawRect(QRectF(47, 32 + 10 * i, 5, 5))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            self.drag = event.globalPosition().toPoint() - self.pos()
            self.moved = False

    def mouseMoveEvent(self, event):
        if self.drag is not None:
            target = event.globalPosition().toPoint() - self.drag
            self.moved |= target != self.pos()
            self.move(target)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            if not self.moved:
                self.reset_location()
            self.drag = None
        elif event.button() == Qt.MouseButton.LeftButton:
            self.set_active(not self.controller.keyboard_active)
        elif event.button() == Qt.MouseButton.MiddleButton:
            self.exit_control()


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
                capture.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
                capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
                capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
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
        self.picture_only = False
        self.wheel_delta = 0
        self.video_layout = layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)
        self.toolbar = QWidget()
        tools = QHBoxLayout(self.toolbar)
        self.status = QLabel("等待连接")
        self.status.setWordWrap(True)
        self.status.setMinimumWidth(0)
        self.status.setMaximumHeight(48)
        self.status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        tools.addWidget(self.status, 1)
        self.zoom_buttons = {}
        for text, callback in (("−", lambda: self.zoom_by(-1)), ("+", lambda: self.zoom_by(1)), ("重连", self.restart), ("置顶", self.toggle_topmost)):
            button = QPushButton(text)
            button.setAutoDefault(False)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            if text in ("−", "+"):
                button.setFixedWidth(36)
                button.setToolTip("缩小画面" if text == "−" else "放大画面")
                self.zoom_buttons[text] = button
            button.clicked.connect(callback)
            tools.addWidget(button)
        layout.addWidget(self.toolbar)
        self.picture = VideoSurface(self)
        self.picture.double_clicked.connect(self.toggle_picture_only)
        self.picture.wheel_scrolled.connect(self.wheel_zoom)
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
                self.picture.set_frame(self.reader.frame)

    def resize_video(self, width):
        if self.isMaximized() or self.isFullScreen():
            self.showNormal()
        # Settle once more after the width changes: a long connection status
        # can wrap and change toolbar height at the smaller zoom levels.
        for _ in range(2):
            self.layout().activate()
            self.window_chrome.shell.layout().activate()
            self.video_layout.activate()
            extra_width = self.width() - self.picture.width()
            extra_height = self.height() - self.picture.height()
            bounds = self.screen().availableGeometry()
            limit = min(1280, bounds.width() - extra_width, (bounds.height() - extra_height) * 16 / 9)
            fitted = max(160, int(min(max(320, width), limit)))
            self.resize(fitted + extra_width, round(fitted * 9 / 16) + extra_height)

    def zoom_by(self, direction):
        width = video_rect(self.picture.width(), self.picture.height()).width()
        candidates = [value for value in ZOOM_WIDTHS if value > width + 2] if direction > 0 else [value for value in ZOOM_WIDTHS if value < width - 2]
        target = min(candidates) if direction > 0 and candidates else max(candidates) if candidates else width
        self.resize_video(target)

    def toggle_picture_only(self):
        width = video_rect(self.picture.width(), self.picture.height()).width()
        self.picture_only = not self.picture_only
        self.picture.content_only = self.picture_only
        self.picture.drag_offset = None
        self.toolbar.setVisible(not self.picture_only)
        self.video_layout.setContentsMargins(*([0] * 4 if self.picture_only else [10] * 4))
        self.video_layout.setSpacing(0 if self.picture_only else 6)
        self.window_chrome.set_content_only(self.picture_only)
        self.resize_video(width)
        self.picture.setFocus()

    def resizeEvent(self, event):
        self.render_after = time.monotonic() + .12
        super().resizeEvent(event)

    def toggle_topmost(self):
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, not bool(self.windowFlags() & Qt.WindowType.WindowStaysOnTopHint))
        self.show()

    def wheel_zoom(self, delta):
        self.wheel_delta += delta
        while abs(self.wheel_delta) >= 120:
            direction = 1 if self.wheel_delta > 0 else -1
            self.zoom_by(direction)
            self.wheel_delta -= direction * 120

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape and self.picture_only:
            self.toggle_picture_only()
            event.accept()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        self.stop_capture()
        event.accept()
