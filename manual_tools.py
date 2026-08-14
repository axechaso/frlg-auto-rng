"""Manual controller and capture monitor windows for the auto RNG GUI."""

from __future__ import annotations

import base64
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any, Callable


class GamePadKey:
    """Dependency-free key names resolved to EasyCon enums after connecting."""

    A = "A"
    B = "B"
    X = "X"
    Y = "Y"
    L = "L"
    R = "R"
    ZL = "ZL"
    ZR = "ZR"
    PLUS = "PLUS"
    MINUS = "MINUS"
    CAPTURE = "CAPTURE"
    HOME = "HOME"
    LCLICK = "LCLICK"
    RCLICK = "RCLICK"
    TOP = "TOP"
    DOWN = "DOWN"
    LEFT = "LEFT"
    RIGHT = "RIGHT"
    TOP_LEFT = "TOP_LEFT"
    TOP_RIGHT = "TOP_RIGHT"
    DOWN_LEFT = "DOWN_LEFT"
    DOWN_RIGHT = "DOWN_RIGHT"


KEYBOARD_GAMEPAD_MAP = {
    "y": GamePadKey.A,
    "u": GamePadKey.B,
    "i": GamePadKey.X,
    "h": GamePadKey.Y,
    "g": GamePadKey.L,
    "t": GamePadKey.R,
    "f": GamePadKey.ZL,
    "r": GamePadKey.ZR,
    "k": GamePadKey.PLUS,
    "j": GamePadKey.MINUS,
    "z": GamePadKey.CAPTURE,
    "c": GamePadKey.HOME,
    "q": GamePadKey.LCLICK,
    "e": GamePadKey.RCLICK,
    "w": GamePadKey.TOP,
    "s": GamePadKey.DOWN,
    "a": GamePadKey.LEFT,
    "d": GamePadKey.RIGHT,
}

_DIRECTION_KEYS = frozenset(
    {GamePadKey.TOP, GamePadKey.DOWN, GamePadKey.LEFT, GamePadKey.RIGHT}
)
_DIRECTION_COMBINATIONS = {
    (-1, -1): GamePadKey.TOP_LEFT,
    (0, -1): GamePadKey.TOP,
    (1, -1): GamePadKey.TOP_RIGHT,
    (-1, 0): GamePadKey.LEFT,
    (1, 0): GamePadKey.RIGHT,
    (-1, 1): GamePadKey.DOWN_LEFT,
    (0, 1): GamePadKey.DOWN,
    (1, 1): GamePadKey.DOWN_RIGHT,
}


def parse_video_device(value: str) -> int:
    try:
        device = int(value.strip())
    except ValueError as exc:
        raise ValueError("采集卡序号必须是大于或等于 0 的整数") from exc
    if device < 0:
        raise ValueError("采集卡序号必须是大于或等于 0 的整数")
    return device


class VirtualControllerWindow:
    def __init__(
        self,
        root: tk.Misc,
        port_provider: Callable[[], str],
        on_closed: Callable[[], None],
    ):
        self.root = root
        self.port_provider = port_provider
        self.on_closed = on_closed
        self.controller: Any | None = None
        self._native_gamepad_key = None
        self._closed = False
        self._connect_generation = 0
        self._pressed: set[str] = set()
        self._gamepad_buttons: list[ttk.Button] = []

        self.window = tk.Toplevel(root)
        self.window.title("虚拟手柄")
        self.window.resizable(False, False)
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.window.bind("<KeyPress>", self._on_key_press)
        self.window.bind("<KeyRelease>", self._on_key_release)
        self.window.bind("<FocusOut>", lambda _event: self.release_all())

        header = ttk.Frame(self.window, padding=(10, 10, 10, 4))
        header.pack(fill="x")
        self.status_var = tk.StringVar(value="未连接")
        ttk.Label(header, textvariable=self.status_var).pack(side="left")
        self.connect_button = ttk.Button(
            header,
            text="连接",
            command=self.toggle_connection,
            width=8,
        )
        self.connect_button.pack(side="right")

        shoulders = ttk.Frame(self.window, padding=(10, 4))
        shoulders.pack(fill="x")
        for column, (label, key) in enumerate(
            (
                ("ZL", GamePadKey.ZL),
                ("L", GamePadKey.L),
                ("R", GamePadKey.R),
                ("ZR", GamePadKey.ZR),
            )
        ):
            shoulders.columnconfigure(column, weight=1, uniform="shoulder")
            self._add_gamepad_button(shoulders, label, key, 0, column, width=7)

        controls = ttk.Frame(self.window, padding=10)
        controls.pack()
        dpad = ttk.LabelFrame(controls, text="方向键", padding=8)
        dpad.grid(row=0, column=0, padx=(0, 12))
        self._add_gamepad_button(dpad, "↑", GamePadKey.TOP, 0, 1)
        self._add_gamepad_button(dpad, "←", GamePadKey.LEFT, 1, 0)
        self._add_gamepad_button(dpad, "→", GamePadKey.RIGHT, 1, 2)
        self._add_gamepad_button(dpad, "↓", GamePadKey.DOWN, 2, 1)

        system = ttk.LabelFrame(controls, text="系统", padding=8)
        system.grid(row=0, column=1, padx=(0, 12), sticky="ns")
        self._add_gamepad_button(system, "−", GamePadKey.MINUS, 0, 0)
        self._add_gamepad_button(system, "+", GamePadKey.PLUS, 0, 1)
        self._add_gamepad_button(system, "HOME", GamePadKey.HOME, 1, 0, colspan=2)
        self._add_gamepad_button(system, "截图", GamePadKey.CAPTURE, 2, 0, colspan=2)
        self._add_gamepad_button(system, "L3", GamePadKey.LCLICK, 3, 0)
        self._add_gamepad_button(system, "R3", GamePadKey.RCLICK, 3, 1)

        face = ttk.LabelFrame(controls, text="按键", padding=8)
        face.grid(row=0, column=2)
        self._add_gamepad_button(face, "X", GamePadKey.X, 0, 1)
        self._add_gamepad_button(face, "Y", GamePadKey.Y, 1, 0)
        self._add_gamepad_button(face, "A", GamePadKey.A, 1, 2)
        self._add_gamepad_button(face, "B", GamePadKey.B, 2, 1)

        self._set_gamepad_enabled(False)
        self.window.after(80, self.connect)

    @property
    def is_open(self) -> bool:
        return not self._closed and bool(self.window.winfo_exists())

    def show(self) -> None:
        self.window.deiconify()
        self.window.lift()
        self.window.focus_force()

    def _add_gamepad_button(
        self,
        parent,
        label: str,
        key: str,
        row: int,
        column: int,
        *,
        width: int = 6,
        colspan: int = 1,
    ) -> None:
        button = ttk.Button(parent, text=label, width=width)
        button.grid(
            row=row,
            column=column,
            columnspan=colspan,
            padx=3,
            pady=3,
            sticky="nsew",
        )
        button.bind("<ButtonPress-1>", lambda _event, item=key: self.press(item))
        button.bind("<ButtonRelease-1>", lambda _event, item=key: self.release(item))
        button.bind("<Leave>", lambda _event, item=key: self.release(item))
        self._gamepad_buttons.append(button)

    def _set_gamepad_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for button in self._gamepad_buttons:
            button.configure(state=state)

    def _post(self, callback: Callable[[], None]) -> None:
        try:
            self.root.after(0, callback)
        except (RuntimeError, tk.TclError):
            pass

    def toggle_connection(self) -> None:
        if self.controller is not None and self.controller.is_connected:
            self.disconnect()
        else:
            self.connect()

    def connect(self) -> None:
        if self._closed:
            return
        port = self.port_provider().strip().upper()
        if not port:
            messagebox.showerror("串口为空", "请先填写或检测 EasyCon 串口。", parent=self.window)
            return

        self._connect_generation += 1
        generation = self._connect_generation
        self.connect_button.configure(state="disabled")
        self.status_var.set(f"正在连接 {port}…")

        def worker() -> None:
            controller = None
            native_gamepad_key = None
            try:
                from easycon import EasyConController, GamePadKey as NativeGamePadKey

                controller = EasyConController()
                native_gamepad_key = NativeGamePadKey
                connected = controller.try_connect_port(
                    port,
                    controller.baudrate,
                    timeout=1.0,
                )
                error = ""
            except ModuleNotFoundError as exc:
                connected = False
                if exc.name == "serial":
                    error = "缺少 pyserial；请用“启动-自动乱数首版.bat”启动"
                else:
                    error = f"缺少 Python 模块 {exc.name}"
            except Exception as exc:
                connected = False
                error = str(exc)

            def finish() -> None:
                if self._closed or generation != self._connect_generation:
                    if controller is not None:
                        controller.disconnect()
                    return
                self.connect_button.configure(state="normal")
                if connected and controller is not None and native_gamepad_key is not None:
                    self.controller = controller
                    self._native_gamepad_key = native_gamepad_key
                    self.status_var.set(f"已连接 {controller.port_name}")
                    self.connect_button.configure(text="断开")
                    self._set_gamepad_enabled(True)
                    self.window.focus_force()
                else:
                    if controller is not None:
                        controller.disconnect()
                    detail = f"：{error}" if error else ""
                    self.status_var.set(f"无法连接 {port}{detail}")
                    self.connect_button.configure(text="重试")
                    self._set_gamepad_enabled(False)

            self._post(finish)

        threading.Thread(target=worker, daemon=True).start()

    def disconnect(self) -> None:
        self._connect_generation += 1
        self.release_all()
        controller = self.controller
        self.controller = None
        if controller is not None:
            if controller.is_connected:
                controller.release_all()
                time.sleep(0.06)
            controller.disconnect()
        self._native_gamepad_key = None
        if not self._closed:
            self.status_var.set("未连接")
            self.connect_button.configure(text="连接", state="normal")
            self._set_gamepad_enabled(False)

    def _resolve_key(self, key: str):
        if self._native_gamepad_key is None:
            return None
        return getattr(self._native_gamepad_key, key)

    def press(self, key: str) -> None:
        if key in self._pressed:
            return
        controller = self.controller
        if controller is None or not controller.is_connected:
            return
        native_key = self._resolve_key(key)
        if native_key is None:
            return
        self._pressed.add(key)
        if key in _DIRECTION_KEYS:
            self._sync_direction(controller)
        else:
            controller.press(native_key)

    def release(self, key: str) -> None:
        if key not in self._pressed:
            return
        self._pressed.discard(key)
        controller = self.controller
        if controller is not None and controller.is_connected:
            if key in _DIRECTION_KEYS:
                self._sync_direction(controller)
            else:
                native_key = self._resolve_key(key)
                if native_key is not None:
                    controller.release(native_key)

    def _sync_direction(self, controller: Any) -> None:
        horizontal = int(GamePadKey.RIGHT in self._pressed) - int(
            GamePadKey.LEFT in self._pressed
        )
        vertical = int(GamePadKey.DOWN in self._pressed) - int(
            GamePadKey.TOP in self._pressed
        )
        direction = _DIRECTION_COMBINATIONS.get((horizontal, vertical))
        if direction is None:
            native_top = self._resolve_key(GamePadKey.TOP)
            if native_top is not None:
                controller.release(native_top)
        else:
            native_direction = self._resolve_key(direction)
            if native_direction is not None:
                controller.press(native_direction)

    def release_all(self) -> None:
        self._pressed.clear()
        controller = self.controller
        if controller is not None and controller.is_connected:
            controller.release_all()

    def _on_key_press(self, event) -> None:
        key = KEYBOARD_GAMEPAD_MAP.get(event.keysym.casefold())
        if key is not None:
            self.press(key)
            return "break"
        return None

    def _on_key_release(self, event) -> None:
        key = KEYBOARD_GAMEPAD_MAP.get(event.keysym.casefold())
        if key is not None:
            self.release(key)
            return "break"
        return None

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.disconnect()
        try:
            self.window.destroy()
        finally:
            self.on_closed()


class CaptureMonitorWindow:
    FRAME_WIDTH = 640
    FRAME_HEIGHT = 360

    def __init__(
        self,
        root: tk.Misc,
        video_provider: Callable[[], str],
        on_closed: Callable[[], None],
    ):
        self.root = root
        self.video_provider = video_provider
        self.on_closed = on_closed
        self._closed = False
        self._generation = 0
        self._stop_event = threading.Event()
        self._capture = None
        self._capture_thread: threading.Thread | None = None
        self._frame_lock = threading.Lock()
        self._latest_frame: tuple[int, str] | None = None
        self._rendered_sequence = -1
        self._photo = None

        self.window = tk.Toplevel(root)
        self.window.title("监视窗口")
        self.window.resizable(False, False)
        self.window.protocol("WM_DELETE_WINDOW", self.close)

        toolbar = ttk.Frame(self.window, padding=(8, 8, 8, 5))
        toolbar.pack(fill="x")
        self.status_var = tk.StringVar(value="准备打开采集卡")
        ttk.Label(toolbar, textvariable=self.status_var).pack(side="left")
        ttk.Button(toolbar, text="重新打开", command=self.restart).pack(side="right")

        self.canvas = tk.Canvas(
            self.window,
            width=self.FRAME_WIDTH,
            height=self.FRAME_HEIGHT,
            background="black",
            highlightthickness=0,
        )
        self.canvas.pack(padx=8, pady=(0, 8))
        self.image_item = self.canvas.create_image(0, 0, anchor="nw")

        self.restart()
        self.window.after(66, self._render)

    @property
    def is_open(self) -> bool:
        return not self._closed and bool(self.window.winfo_exists())

    def show(self) -> None:
        self.window.deiconify()
        self.window.lift()
        self.window.focus_force()

    def _post_status(self, text: str) -> None:
        def update() -> None:
            if not self._closed:
                self.status_var.set(text)

        try:
            self.root.after(0, update)
        except (RuntimeError, tk.TclError):
            pass

    def restart(self) -> None:
        try:
            device = parse_video_device(self.video_provider())
        except ValueError as exc:
            messagebox.showerror("采集卡序号错误", str(exc), parent=self.window)
            return
        self._stop_capture()
        self._generation += 1
        generation = self._generation
        self._stop_event = threading.Event()
        self.status_var.set(f"正在打开采集卡 {device}…")
        self._capture_thread = threading.Thread(
            target=self._capture_loop,
            args=(device, generation, self._stop_event),
            daemon=True,
        )
        self._capture_thread.start()

    def _capture_loop(
        self,
        device: int,
        generation: int,
        stop_event: threading.Event,
    ) -> None:
        import cv2

        capture = cv2.VideoCapture(device, cv2.CAP_DSHOW)
        if not capture.isOpened():
            capture.release()
            capture = cv2.VideoCapture(device)
        if not capture.isOpened():
            capture.release()
            self._post_status(f"无法打开采集卡 {device}")
            return
        self._capture = capture
        capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self._post_status(f"采集卡 {device} 已打开")
        sequence = 0
        failed_reads = 0
        try:
            while not stop_event.is_set() and generation == self._generation:
                ok, frame = capture.read()
                if not ok or frame is None:
                    failed_reads += 1
                    if failed_reads >= 30:
                        self._post_status(f"采集卡 {device} 暂无画面")
                        failed_reads = 0
                    time.sleep(0.03)
                    continue
                failed_reads = 0
                resized = cv2.resize(
                    frame,
                    (self.FRAME_WIDTH, self.FRAME_HEIGHT),
                    interpolation=cv2.INTER_AREA,
                )
                rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
                header = f"P6\n{self.FRAME_WIDTH} {self.FRAME_HEIGHT}\n255\n".encode("ascii")
                encoded = base64.b64encode(header + rgb.tobytes()).decode("ascii")
                sequence += 1
                with self._frame_lock:
                    self._latest_frame = (sequence, encoded)
        finally:
            capture.release()
            if self._capture is capture:
                self._capture = None

    def _render(self) -> None:
        if self._closed:
            return
        with self._frame_lock:
            frame = self._latest_frame
        if frame is not None and frame[0] != self._rendered_sequence:
            try:
                photo = tk.PhotoImage(master=self.window, data=frame[1], format="PPM")
                self.canvas.itemconfigure(self.image_item, image=photo)
                self._photo = photo
                self._rendered_sequence = frame[0]
            except tk.TclError:
                pass
        self.window.after(66, self._render)

    def _stop_capture(self) -> None:
        self._generation += 1
        self._stop_event.set()
        capture = self._capture
        if capture is not None:
            try:
                capture.release()
            except Exception:
                pass
        thread = self._capture_thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.0)
        self._capture_thread = None
        self._capture = None

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._stop_capture()
        try:
            self.window.destroy()
        finally:
            self.on_closed()


class ManualToolsManager:
    def __init__(
        self,
        root: tk.Misc,
        *,
        port_provider: Callable[[], str],
        video_provider: Callable[[], str],
        process_running: Callable[[], bool],
    ):
        self.root = root
        self.port_provider = port_provider
        self.video_provider = video_provider
        self.process_running = process_running
        self.controller_window: VirtualControllerWindow | None = None
        self.monitor_window: CaptureMonitorWindow | None = None

    def _available(self) -> bool:
        if self.process_running():
            messagebox.showerror(
                "EasyCon 正在运行",
                "请先停止当前自动流程，再打开手动工具。",
                parent=self.root,
            )
            return False
        return True

    def open_virtual_controller(self) -> None:
        if not self._available():
            return
        if self.controller_window is not None and self.controller_window.is_open:
            self.controller_window.show()
            return
        self.controller_window = VirtualControllerWindow(
            self.root,
            self.port_provider,
            self._controller_closed,
        )

    def open_monitor(self) -> None:
        if not self._available():
            return
        if self.monitor_window is not None and self.monitor_window.is_open:
            self.monitor_window.show()
            return
        self.monitor_window = CaptureMonitorWindow(
            self.root,
            self.video_provider,
            self._monitor_closed,
        )

    def _controller_closed(self) -> None:
        self.controller_window = None

    def _monitor_closed(self) -> None:
        self.monitor_window = None

    def close_all(self) -> None:
        controller_window = self.controller_window
        monitor_window = self.monitor_window
        self.controller_window = None
        self.monitor_window = None
        if controller_window is not None:
            controller_window.close()
        if monitor_window is not None:
            monitor_window.close()
