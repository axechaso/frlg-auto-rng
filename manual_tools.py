"""Manual controller and capture monitor windows for the auto RNG GUI."""

from __future__ import annotations

import base64
import json
import re
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any, Callable

from app_paths import DATA_ROOT, RESOURCE_ROOT


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


GAMEPAD_KEY_ORDER = (
    GamePadKey.A,
    GamePadKey.B,
    GamePadKey.X,
    GamePadKey.Y,
    GamePadKey.L,
    GamePadKey.R,
    GamePadKey.ZL,
    GamePadKey.ZR,
    GamePadKey.PLUS,
    GamePadKey.MINUS,
    GamePadKey.HOME,
    GamePadKey.CAPTURE,
    GamePadKey.LCLICK,
    GamePadKey.RCLICK,
    GamePadKey.TOP,
    GamePadKey.DOWN,
    GamePadKey.LEFT,
    GamePadKey.RIGHT,
)

GAMEPAD_KEY_LABELS = {
    GamePadKey.TOP: "↑",
    GamePadKey.DOWN: "↓",
    GamePadKey.LEFT: "←",
    GamePadKey.RIGHT: "→",
    GamePadKey.PLUS: "+",
    GamePadKey.MINUS: "−",
    GamePadKey.CAPTURE: "截图",
}

DEFAULT_GAMEPAD_KEYBOARD_MAP = {
    GamePadKey.A: "y",
    GamePadKey.B: "u",
    GamePadKey.X: "i",
    GamePadKey.Y: "h",
    GamePadKey.L: "g",
    GamePadKey.R: "t",
    GamePadKey.ZL: "f",
    GamePadKey.ZR: "r",
    GamePadKey.PLUS: "k",
    GamePadKey.MINUS: "j",
    GamePadKey.CAPTURE: "z",
    GamePadKey.HOME: "c",
    GamePadKey.LCLICK: "q",
    GamePadKey.RCLICK: "e",
    GamePadKey.TOP: "w",
    GamePadKey.DOWN: "s",
    GamePadKey.LEFT: "a",
    GamePadKey.RIGHT: "d",
}

KEY_MAPPING_PATH = (
    DATA_ROOT / "runtime" / "manual_controller_keymap.json"
)


def normalize_keysym(value: str) -> str:
    return value.strip().casefold()


def build_keyboard_gamepad_map(mapping) -> dict[str, str]:
    return {
        normalize_keysym(keyboard_key): gamepad_key
        for gamepad_key, keyboard_key in mapping.items()
        if normalize_keysym(keyboard_key)
    }


KEYBOARD_GAMEPAD_MAP = build_keyboard_gamepad_map(DEFAULT_GAMEPAD_KEYBOARD_MAP)

CONTROLLER_OVERLAY_WIDTH = 100
CONTROLLER_OVERLAY_HEIGHT = 100
CONTROLLER_OVERLAY_IDLE_FILL = "#323232"
CONTROLLER_OVERLAY_ACTIVE_FILL = "#00ff00"
CONTROLLER_OVERLAY_ASSET_DIR = RESOURCE_ROOT / "assets" / "easycon_vpad"
CONTROLLER_OVERLAY_SHOULDER_ASSETS = {
    GamePadKey.ZL: "JoyCon_ZL",
    GamePadKey.ZR: "JoyCon_ZR",
    GamePadKey.L: "JoyCon_L",
    GamePadKey.R: "JoyCon_R",
}
CONTROLLER_OVERLAY_BUTTON_LAYOUT = {
    GamePadKey.LCLICK: ("oval", (16, 26, 31, 41)),
    GamePadKey.TOP: ("round", (21, 55, 27, 61)),
    GamePadKey.DOWN: ("round", (21, 67, 27, 73)),
    GamePadKey.LEFT: ("round", (15, 61, 21, 67)),
    GamePadKey.RIGHT: ("round", (27, 61, 33, 67)),
    GamePadKey.X: ("oval", (71, 21, 80, 30)),
    GamePadKey.Y: ("oval", (63, 29, 72, 38)),
    GamePadKey.A: ("oval", (79, 29, 88, 38)),
    GamePadKey.B: ("oval", (71, 37, 80, 46)),
    GamePadKey.RCLICK: ("oval", (68, 57, 83, 72)),
    GamePadKey.MINUS: ("round", (29, 12, 34, 17)),
    GamePadKey.PLUS: ("round", (65, 12, 70, 17)),
    GamePadKey.CAPTURE: ("round", (27, 82, 32, 87)),
    GamePadKey.HOME: ("round", (67, 82, 72, 87)),
}


def clamp_overlay_position(
    x: int,
    y: int,
    screen_width: int,
    screen_height: int,
) -> tuple[int, int]:
    return (
        max(0, min(int(x), max(0, int(screen_width) - CONTROLLER_OVERLAY_WIDTH))),
        max(0, min(int(y), max(0, int(screen_height) - CONTROLLER_OVERLAY_HEIGHT))),
    )


def load_key_mapping(path: Path = KEY_MAPPING_PATH) -> dict[str, str]:
    mapping = dict(DEFAULT_GAMEPAD_KEYBOARD_MAP)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError, TypeError):
        return mapping
    if not isinstance(payload, dict):
        return mapping

    candidate = {}
    used_keys = set()
    for gamepad_key in GAMEPAD_KEY_ORDER:
        keyboard_key = normalize_keysym(str(payload.get(gamepad_key, "")))
        if not keyboard_key or keyboard_key in used_keys:
            return mapping
        candidate[gamepad_key] = keyboard_key
        used_keys.add(keyboard_key)
    return candidate


def save_key_mapping(mapping, path: Path = KEY_MAPPING_PATH) -> None:
    payload = {
        gamepad_key: normalize_keysym(mapping[gamepad_key])
        for gamepad_key in GAMEPAD_KEY_ORDER
    }
    if len(set(payload.values())) != len(payload):
        raise ValueError("键盘按键不能重复映射")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def assign_keyboard_key(mapping, gamepad_key: str, keyboard_key: str) -> None:
    keyboard_key = normalize_keysym(keyboard_key)
    if not keyboard_key:
        raise ValueError("键盘按键不能为空")
    old_key = mapping[gamepad_key]
    conflicting_gamepad = next(
        (
            mapped_gamepad
            for mapped_gamepad, mapped_key in mapping.items()
            if mapped_gamepad != gamepad_key
            and normalize_keysym(mapped_key) == keyboard_key
        ),
        None,
    )
    mapping[gamepad_key] = keyboard_key
    if conflicting_gamepad is not None:
        mapping[conflicting_gamepad] = old_key


def display_keyboard_key(keysym: str) -> str:
    labels = {
        "space": "Space",
        "return": "Enter",
        "tab": "Tab",
        "backspace": "Backspace",
        "up": "↑",
        "down": "↓",
        "left": "←",
        "right": "→",
        "shift_l": "左 Shift",
        "shift_r": "右 Shift",
        "control_l": "左 Ctrl",
        "control_r": "右 Ctrl",
        "alt_l": "左 Alt",
        "alt_r": "右 Alt",
    }
    normalized = normalize_keysym(keysym)
    return labels.get(normalized, normalized.upper())


def mapping_button_text(gamepad_key: str, keyboard_key: str) -> str:
    gamepad_label = GAMEPAD_KEY_LABELS.get(gamepad_key, gamepad_key)
    return f"{gamepad_label}\n[{display_keyboard_key(keyboard_key)}]"


def pressed_keys_text(pressed) -> str:
    pressed_set = set(pressed)
    labels = [
        GAMEPAD_KEY_LABELS.get(key, key)
        for key in GAMEPAD_KEY_ORDER
        if key in pressed_set
    ]
    return " + ".join(labels) if labels else "无"


def set_window_topmost(window, enabled: bool) -> None:
    window.attributes("-topmost", bool(enabled))


def encode_tk_png(frame, cv2_module) -> str:
    encoded, png = cv2_module.imencode(
        ".png",
        frame,
        [cv2_module.IMWRITE_PNG_COMPRESSION, 1],
    )
    if not encoded:
        raise ValueError("OpenCV 无法编码监视画面")
    return base64.b64encode(png.tobytes()).decode("ascii")


def fit_monitor_frame_size(
    width: int,
    height: int,
    max_width: int = 1280,
    max_height: int = 720,
) -> tuple[int, int]:
    width = min(max(1, int(width)), max_width)
    height = min(max(1, int(height)), max_height)
    aspect_ratio = 16 / 9
    if width / height > aspect_ratio:
        return max(1, round(height * aspect_ratio)), height
    return width, max(1, round(width / aspect_ratio))


MONITOR_ZOOM_SIZES = (
    (320, 180),
    (480, 270),
    (640, 360),
    (800, 450),
    (960, 540),
    (1120, 630),
    (1280, 720),
)


def next_monitor_zoom_size(width: int, height: int, direction: int) -> tuple[int, int]:
    fitted_width, fitted_height = fit_monitor_frame_size(width, height)
    nearest_index = min(
        range(len(MONITOR_ZOOM_SIZES)),
        key=lambda index: (
            abs(MONITOR_ZOOM_SIZES[index][0] - fitted_width)
            + abs(MONITOR_ZOOM_SIZES[index][1] - fitted_height)
        ),
    )
    step = 1 if direction > 0 else -1
    target_index = max(0, min(len(MONITOR_ZOOM_SIZES) - 1, nearest_index + step))
    return MONITOR_ZOOM_SIZES[target_index]


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
    display_match = re.match(r"^\s*\[(\d+)\]", value)
    try:
        device = int(display_match.group(1)) if display_match else int(value.strip())
    except ValueError as exc:
        raise ValueError("请选择有效的采集卡") from exc
    if device < 0:
        raise ValueError("请选择有效的采集卡")
    return device


class KeyMappingWindow:
    def __init__(
        self,
        parent: tk.Misc,
        mapping,
        on_saved: Callable[[dict[str, str]], None],
        on_closed: Callable[[], None],
    ):
        self.mapping = dict(mapping)
        self.on_saved = on_saved
        self.on_closed = on_closed
        self._closed = False
        self._capturing: str | None = None

        self.window = tk.Toplevel(parent)
        self.window.title("按键映射")
        self.window.resizable(False, False)
        self.window.transient(parent)
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.window.bind("<KeyPress>", self._on_key_press, add="+")

        body = ttk.Frame(self.window, padding=10)
        body.pack(fill="both", expand=True)
        self.mapping_buttons: dict[str, ttk.Button] = {}

        shoulders = ttk.Frame(body)
        shoulders.pack(fill="x", pady=(0, 8))
        for column, gamepad_key in enumerate(
            (GamePadKey.ZL, GamePadKey.L, GamePadKey.R, GamePadKey.ZR)
        ):
            shoulders.columnconfigure(column, weight=1, uniform="shoulders")
            self._add_mapping_button(shoulders, gamepad_key, 0, column, width=9)

        controls = ttk.Frame(body)
        controls.pack()

        dpad = ttk.LabelFrame(controls, text="方向键", padding=7)
        dpad.grid(row=0, column=0, padx=(0, 10), sticky="ns")
        self._add_mapping_button(dpad, GamePadKey.TOP, 0, 1)
        self._add_mapping_button(dpad, GamePadKey.LEFT, 1, 0)
        self._add_mapping_button(dpad, GamePadKey.RIGHT, 1, 2)
        self._add_mapping_button(dpad, GamePadKey.DOWN, 2, 1)

        system = ttk.LabelFrame(controls, text="系统键", padding=7)
        system.grid(row=0, column=1, padx=(0, 10), sticky="ns")
        self._add_mapping_button(system, GamePadKey.MINUS, 0, 0)
        self._add_mapping_button(system, GamePadKey.PLUS, 0, 1)
        self._add_mapping_button(system, GamePadKey.HOME, 1, 0, colspan=2)
        self._add_mapping_button(system, GamePadKey.CAPTURE, 2, 0, colspan=2)
        self._add_mapping_button(system, GamePadKey.LCLICK, 3, 0)
        self._add_mapping_button(system, GamePadKey.RCLICK, 3, 1)

        face = ttk.LabelFrame(controls, text="ABXY", padding=7)
        face.grid(row=0, column=2, sticky="ns")
        self._add_mapping_button(face, GamePadKey.X, 0, 1)
        self._add_mapping_button(face, GamePadKey.Y, 1, 0)
        self._add_mapping_button(face, GamePadKey.A, 1, 2)
        self._add_mapping_button(face, GamePadKey.B, 2, 1)

        self.status_var = tk.StringVar(value="点击手柄位置后，按新的键盘键")
        ttk.Label(body, textvariable=self.status_var, anchor="center").pack(
            fill="x", pady=(8, 6)
        )

        actions = ttk.Frame(body)
        actions.pack(fill="x")
        ttk.Button(actions, text="恢复默认", command=self.restore_defaults).pack(
            side="left"
        )
        ttk.Button(actions, text="保存", command=self.save).pack(side="right")

        self._refresh_buttons()

    @property
    def is_open(self) -> bool:
        return not self._closed and bool(self.window.winfo_exists())

    def show(self) -> None:
        self.window.deiconify()
        self.window.lift()
        self.window.focus_force()

    def _add_mapping_button(
        self,
        parent,
        gamepad_key: str,
        row: int,
        column: int,
        *,
        width: int = 7,
        colspan: int = 1,
    ) -> None:
        button = ttk.Button(
            parent,
            width=width,
            command=lambda key=gamepad_key: self.begin_capture(key),
        )
        button.grid(
            row=row,
            column=column,
            columnspan=colspan,
            padx=2,
            pady=2,
            sticky="nsew",
        )
        self.mapping_buttons[gamepad_key] = button

    def _refresh_buttons(self) -> None:
        for gamepad_key, button in self.mapping_buttons.items():
            button.configure(
                text=mapping_button_text(
                    gamepad_key,
                    self.mapping[gamepad_key],
                )
            )

    def begin_capture(self, gamepad_key: str) -> None:
        self._capturing = gamepad_key
        self._refresh_buttons()
        button = self.mapping_buttons[gamepad_key]
        label = GAMEPAD_KEY_LABELS.get(gamepad_key, gamepad_key)
        button.configure(text=f"{label}\n[按新键]")
        button.focus_set()
        self.status_var.set(f"请按 {label} 的新键，Esc 取消")
        self.window.focus_force()

    def _on_key_press(self, event):
        if self._capturing is None:
            return None
        keyboard_key = normalize_keysym(event.keysym)
        if keyboard_key == "escape":
            self._capturing = None
            self._refresh_buttons()
            self.status_var.set("已取消修改")
            return "break"
        gamepad_key = self._capturing
        assign_keyboard_key(self.mapping, gamepad_key, keyboard_key)
        self._capturing = None
        self._refresh_buttons()
        label = GAMEPAD_KEY_LABELS.get(gamepad_key, gamepad_key)
        self.status_var.set(f"{label} = {display_keyboard_key(keyboard_key)}")
        return "break"

    def restore_defaults(self) -> None:
        self.mapping = dict(DEFAULT_GAMEPAD_KEYBOARD_MAP)
        self._capturing = None
        self._refresh_buttons()
        self.status_var.set("已恢复默认，点击保存后生效")

    def save(self) -> None:
        try:
            save_key_mapping(self.mapping)
        except (OSError, ValueError) as exc:
            messagebox.showerror("保存失败", str(exc), parent=self.window)
            return
        self.on_saved(dict(self.mapping))
        self.close()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self.window.destroy()
        finally:
            self.on_closed()


class ControllerStateOverlay:
    """Compact EasyCon-style controller state overlay for the Tk GUI."""

    TRANSPARENT_COLOR = "#010203"

    def __init__(
        self,
        root: tk.Misc,
        pressed_provider: Callable[[], set[str]],
        connected_provider: Callable[[], bool],
        activate_controller: Callable[[], None],
        on_hidden: Callable[[], None],
    ):
        self.root = root
        self.pressed_provider = pressed_provider
        self.connected_provider = connected_provider
        self.activate_controller = activate_controller
        self.on_hidden = on_hidden
        self._closed = False
        self._position_initialized = False
        self._right_press_root: tuple[int, int] | None = None
        self._right_press_window: tuple[int, int] | None = None
        self._right_dragged = False
        self._button_items: dict[str, int] = {}
        self._asset_images: dict[str, tk.PhotoImage] = {}
        self._shoulder_items: dict[str, int] = {}

        self.window = tk.Toplevel(root)
        self.window.title("手柄状态浮窗")
        self.window.overrideredirect(True)
        self.window.resizable(False, False)
        self.window.configure(background=self.TRANSPARENT_COLOR)
        self.window.attributes("-topmost", True)
        try:
            self.window.wm_attributes("-transparentcolor", self.TRANSPARENT_COLOR)
        except tk.TclError:
            pass
        self.window.protocol("WM_DELETE_WINDOW", self.hide)

        self.canvas = tk.Canvas(
            self.window,
            width=CONTROLLER_OVERLAY_WIDTH,
            height=CONTROLLER_OVERLAY_HEIGHT,
            background=self.TRANSPARENT_COLOR,
            highlightthickness=0,
            cursor="hand2",
        )
        self.canvas.pack()
        self._draw_background()
        self._draw_state_items()

        # The canvas fills the whole frameless window. Bind only once here:
        # widget and toplevel bindings both participate in Tk's bind tags, so
        # registering on both can dispatch one physical click twice.
        self.canvas.bind("<ButtonRelease-1>", self._on_left_release, add="+")
        self.canvas.bind("<ButtonRelease-2>", self._on_middle_release, add="+")
        self.canvas.bind("<ButtonPress-3>", self._on_right_press, add="+")
        self.canvas.bind("<B3-Motion>", self._on_right_drag, add="+")
        self.canvas.bind("<ButtonRelease-3>", self._on_right_release, add="+")

        self.window.withdraw()

    @property
    def is_open(self) -> bool:
        return not self._closed and bool(self.window.winfo_exists())

    @property
    def is_visible(self) -> bool:
        return self.is_open and self.window.state() != "withdrawn"

    def _draw_background(self) -> None:
        canvas = self.canvas
        background = self._load_asset("JoyCon.png")
        canvas.create_image(0, 0, image=background, anchor="nw")
        canvas.create_oval(11, 21, 36, 46, fill="#5b596d", outline="#34333e")
        canvas.create_oval(63, 52, 88, 77, fill="#725d63", outline="#42343a")

    def _load_asset(self, filename: str) -> tk.PhotoImage:
        path = CONTROLLER_OVERLAY_ASSET_DIR / filename
        if not path.is_file():
            raise RuntimeError(f"缺少 EasyCon 手柄浮窗资源：{path}")
        image = tk.PhotoImage(master=self.window, file=str(path))
        if image.width() != CONTROLLER_OVERLAY_WIDTH or image.height() != CONTROLLER_OVERLAY_HEIGHT:
            raise RuntimeError(
                f"EasyCon 手柄浮窗资源尺寸错误：{path.name} "
                f"({image.width()}x{image.height()})"
            )
        self._asset_images[filename] = image
        return image

    def _draw_state_items(self) -> None:
        canvas = self.canvas
        for key, (shape, bounds) in CONTROLLER_OVERLAY_BUTTON_LAYOUT.items():
            if shape == "oval":
                item = canvas.create_oval(
                    *bounds,
                    fill=CONTROLLER_OVERLAY_IDLE_FILL,
                    outline="#111111",
                )
            else:
                item = canvas.create_rectangle(
                    *bounds,
                    fill=CONTROLLER_OVERLAY_IDLE_FILL,
                    outline="#111111",
                )
            self._button_items[key] = item

        self._connection_items = tuple(
            canvas.create_rectangle(
                47,
                32 + 10 * index,
                52,
                37 + 10 * index,
                fill="#202020",
                outline="#111111",
            )
            for index in range(4)
        )
        for key, basename in CONTROLLER_OVERLAY_SHOULDER_ASSETS.items():
            idle_image = self._load_asset(f"{basename}_0.png")
            self._load_asset(f"{basename}_1.png")
            self._shoulder_items[key] = canvas.create_image(
                0,
                0,
                image=idle_image,
                anchor="nw",
            )

    def refresh_state(self) -> None:
        if self._closed:
            return
        try:
            pressed = set(self.pressed_provider())
        except Exception:
            pressed = set()
        try:
            connected = bool(self.connected_provider())
        except Exception:
            connected = False

        for key, item in self._button_items.items():
            self.canvas.itemconfigure(
                item,
                fill=(
                    CONTROLLER_OVERLAY_ACTIVE_FILL
                    if connected and key in pressed
                    else CONTROLLER_OVERLAY_IDLE_FILL
                ),
            )
        for key, item in self._shoulder_items.items():
            basename = CONTROLLER_OVERLAY_SHOULDER_ASSETS[key]
            state = 1 if connected and key in pressed else 0
            self.canvas.itemconfigure(
                item,
                image=self._asset_images[f"{basename}_{state}.png"],
            )
        connection_fill = "#ffffff" if connected else "#202020"
        for item in self._connection_items:
            self.canvas.itemconfigure(item, fill=connection_fill)
        self.window.attributes("-alpha", 1.0 if connected else 0.55)

    def show(self) -> None:
        if self._closed:
            return
        if not self._position_initialized:
            self.reset_position()
        else:
            self._clamp_to_screen()
        self.refresh_state()
        self.window.deiconify()
        self.window.lift()

    def hide(self) -> None:
        if self._closed:
            return
        self.window.withdraw()
        self.on_hidden()

    def toggle(self) -> None:
        if self.is_visible:
            self.hide()
        else:
            self.show()

    def reset_position(self) -> None:
        self.root.update_idletasks()
        root_x = self.root.winfo_rootx()
        root_y = self.root.winfo_rooty()
        root_width = max(1, self.root.winfo_width())
        x = root_x + root_width - CONTROLLER_OVERLAY_WIDTH - 20
        y = root_y + 50
        x, y = clamp_overlay_position(
            x,
            y,
            self.window.winfo_screenwidth(),
            self.window.winfo_screenheight(),
        )
        self.window.geometry(f"+{x}+{y}")
        self._position_initialized = True

    def _clamp_to_screen(self) -> None:
        x, y = clamp_overlay_position(
            self.window.winfo_x(),
            self.window.winfo_y(),
            self.window.winfo_screenwidth(),
            self.window.winfo_screenheight(),
        )
        self.window.geometry(f"+{x}+{y}")

    def _on_left_release(self, _event=None):
        self.activate_controller()
        return "break"

    def _on_middle_release(self, _event=None):
        self.hide()
        return "break"

    def _on_right_press(self, event):
        self._right_press_root = (event.x_root, event.y_root)
        self._right_press_window = (self.window.winfo_x(), self.window.winfo_y())
        self._right_dragged = False
        return "break"

    def _on_right_drag(self, event):
        if self._right_press_root is None or self._right_press_window is None:
            return "break"
        dx = event.x_root - self._right_press_root[0]
        dy = event.y_root - self._right_press_root[1]
        if dx or dy:
            self._right_dragged = True
        x, y = clamp_overlay_position(
            self._right_press_window[0] + dx,
            self._right_press_window[1] + dy,
            self.window.winfo_screenwidth(),
            self.window.winfo_screenheight(),
        )
        self.window.geometry(f"+{x}+{y}")
        return "break"

    def _on_right_release(self, _event=None):
        if not self._right_dragged:
            self.reset_position()
        self._right_press_root = None
        self._right_press_window = None
        self._right_dragged = False
        return "break"

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.window.destroy()


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
        self.gamepad_keyboard_map = load_key_mapping()
        self.keyboard_gamepad_map = build_keyboard_gamepad_map(
            self.gamepad_keyboard_map
        )
        self.mapping_window: KeyMappingWindow | None = None
        self.overlay: ControllerStateOverlay | None = None

        self.window = tk.Toplevel(root)
        self.window.title("虚拟手柄")
        self.window.resizable(False, False)
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.window.bind("<KeyPress>", self._on_key_press)
        self.window.bind("<KeyRelease>", self._on_key_release)
        self.window.bind("<FocusOut>", lambda _event: self.release_all())

        header = ttk.Frame(self.window, padding=(10, 10, 10, 6))
        header.pack(fill="x")
        self.status_var = tk.StringVar(value="未连接")
        ttk.Label(
            header,
            textvariable=self.status_var,
            width=26,
            anchor="w",
        ).pack(side="left")
        self.connect_button = ttk.Button(
            header,
            text="连接",
            command=self.toggle_connection,
            width=8,
        )
        self.connect_button.pack(side="right")

        pressed_frame = ttk.LabelFrame(self.window, text="当前按键", padding=(8, 5))
        pressed_frame.pack(fill="x", padx=10)
        self.pressed_var = tk.StringVar(value="无")
        ttk.Label(
            pressed_frame,
            textvariable=self.pressed_var,
            width=28,
            anchor="center",
        ).pack(fill="x")

        footer = ttk.Frame(self.window, padding=(10, 6, 10, 10))
        footer.pack(fill="x")
        self.topmost_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            footer,
            text="置顶",
            variable=self.topmost_var,
            command=self._apply_topmost,
        ).pack(side="left")
        self.overlay_button = ttk.Button(
            footer,
            text="隐藏浮窗",
            command=self.toggle_overlay,
        )
        self.overlay_button.pack(side="left", padx=(8, 0))
        ttk.Button(
            footer,
            text="按键映射",
            command=self.open_key_mapping,
        ).pack(side="right")

        self.overlay = ControllerStateOverlay(
            root,
            pressed_provider=lambda: set(self._pressed),
            connected_provider=self._controller_connected,
            activate_controller=self.show,
            on_hidden=self._overlay_hidden,
        )
        self.overlay.show()
        self.window.after(80, self.connect)

    @property
    def is_open(self) -> bool:
        return not self._closed and bool(self.window.winfo_exists())

    def show(self) -> None:
        if self.overlay is not None:
            self.overlay.show()
            self.overlay_button.configure(text="隐藏浮窗")
        # Keep keyboard events on the full controller window. The overlay is a
        # status surface and must not steal focus merely because it is shown.
        self.window.deiconify()
        self.window.lift()
        self.window.focus_force()

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

    def _apply_topmost(self) -> None:
        set_window_topmost(self.window, self.topmost_var.get())

    def _controller_connected(self) -> bool:
        return bool(self.controller is not None and self.controller.is_connected)

    def toggle_overlay(self) -> None:
        overlay = self.overlay
        if overlay is None:
            return
        overlay.toggle()
        self.overlay_button.configure(
            text="隐藏浮窗" if overlay.is_visible else "显示浮窗"
        )

    def _overlay_hidden(self) -> None:
        if not self._closed:
            self.overlay_button.configure(text="显示浮窗")

    def open_key_mapping(self) -> None:
        self.release_all()
        if self.mapping_window is not None and self.mapping_window.is_open:
            self.mapping_window.show()
            return
        self.mapping_window = KeyMappingWindow(
            self.window,
            self.gamepad_keyboard_map,
            self._apply_key_mapping,
            self._mapping_closed,
        )

    def _apply_key_mapping(self, mapping: dict[str, str]) -> None:
        self.release_all()
        self.gamepad_keyboard_map = dict(mapping)
        self.keyboard_gamepad_map = build_keyboard_gamepad_map(mapping)
        self.window.focus_force()

    def _mapping_closed(self) -> None:
        self.mapping_window = None
        if not self._closed:
            self.window.focus_force()

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
                    self.window.focus_force()
                else:
                    if controller is not None:
                        controller.disconnect()
                    detail = f"：{error}" if error else ""
                    self.status_var.set(f"无法连接 {port}{detail}")
                    self.connect_button.configure(text="重试")
                if self.overlay is not None:
                    self.overlay.refresh_state()

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
        if self.overlay is not None:
            self.overlay.refresh_state()

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
        self._update_pressed_display()
        if self.overlay is not None:
            self.overlay.refresh_state()
        if key in _DIRECTION_KEYS:
            self._sync_direction(controller)
        else:
            controller.press(native_key)

    def release(self, key: str) -> None:
        if key not in self._pressed:
            return
        self._pressed.discard(key)
        self._update_pressed_display()
        if self.overlay is not None:
            self.overlay.refresh_state()
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
        self._update_pressed_display()
        if self.overlay is not None:
            self.overlay.refresh_state()
        controller = self.controller
        if controller is not None and controller.is_connected:
            controller.release_all()

    def _update_pressed_display(self) -> None:
        self.pressed_var.set(pressed_keys_text(self._pressed))

    def _on_key_press(self, event) -> None:
        key = self.keyboard_gamepad_map.get(normalize_keysym(event.keysym))
        if key is not None:
            self.press(key)
            return "break"
        return None

    def _on_key_release(self, event) -> None:
        key = self.keyboard_gamepad_map.get(normalize_keysym(event.keysym))
        if key is not None:
            self.release(key)
            return "break"
        return None

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        mapping_window = self.mapping_window
        self.mapping_window = None
        if mapping_window is not None:
            mapping_window.close()
        self.disconnect()
        overlay = self.overlay
        self.overlay = None
        if overlay is not None:
            overlay.close()
        try:
            self.window.destroy()
        finally:
            self.on_closed()


class CaptureMonitorWindow:
    FRAME_WIDTH = 640
    FRAME_HEIGHT = 360
    # Tk must decode each PhotoImage on its UI thread. Keep both producer and
    # consumer near 30 FPS so an idle monitor does not compete with the GUI
    # (or the running EasyCon worker) for CPU/GIL time.
    RENDER_INTERVAL_MS = 33
    FRAME_PROCESS_INTERVAL_MS = 33
    DRAG_PAUSE_MS = 180

    def __init__(
        self,
        root: tk.Misc,
        video_provider: Callable[[], str],
        on_closed: Callable[[], None],
        preview_url_provider: Callable[[], str | None] | None = None,
    ):
        self.root = root
        self.video_provider = video_provider
        self.preview_url_provider = preview_url_provider
        self.on_closed = on_closed
        self._closed = False
        self._generation = 0
        self._stop_event = threading.Event()
        self._capture = None
        self._stream_response = None
        self._capture_thread: threading.Thread | None = None
        self._frame_lock = threading.Lock()
        self._latest_frame: tuple[int, str, int, int] | None = None
        self._target_size = (self.FRAME_WIDTH, self.FRAME_HEIGHT)
        self._rendered_sequence = -1
        self._render_error_reported = False
        self._image_only = False
        self._photo = None
        self._last_window_geometry: tuple[int, int, int, int] | None = None
        self._last_host_geometry: tuple[int, int, int, int] | None = None
        self._render_paused_until = 0.0
        self._host_configure_bind_id = None

        self.window = tk.Toplevel(root)
        self.window.title("监视窗口")
        self.window.resizable(True, True)
        self.window.minsize(320, 180)
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.window.bind("<Configure>", self._on_window_configure, add="+")
        self._host_configure_bind_id = self.root.bind(
            "<Configure>",
            self._on_host_window_configure,
            add="+",
        )
        self.window.bind("<Escape>", self._restore_normal_view, add="+")

        self.toolbar = ttk.Frame(self.window, padding=(8, 8, 8, 5))
        self.toolbar.pack(fill="x")
        self.status_var = tk.StringVar(value="准备打开采集卡")
        ttk.Label(self.toolbar, textvariable=self.status_var).pack(side="left")
        ttk.Button(self.toolbar, text="重新打开", command=self.restart).pack(
            side="right"
        )
        self.topmost_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            self.toolbar,
            text="置顶",
            variable=self.topmost_var,
            command=self._apply_topmost,
        ).pack(side="right", padx=(0, 8))

        self.canvas = tk.Canvas(
            self.window,
            width=self.FRAME_WIDTH,
            height=self.FRAME_HEIGHT,
            background="black",
            highlightthickness=0,
        )
        self.canvas.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.image_item = self.canvas.create_image(0, 0, anchor="nw")
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind("<Double-Button-1>", self.toggle_image_only)
        self.canvas.bind("<MouseWheel>", self._on_mouse_wheel)
        self.canvas.bind("<Button-4>", lambda _event: self._zoom_monitor(1))
        self.canvas.bind("<Button-5>", lambda _event: self._zoom_monitor(-1))

        self.restart()
        self.window.after(self.RENDER_INTERVAL_MS, self._render)

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

    def _apply_topmost(self) -> None:
        set_window_topmost(self.window, self.topmost_var.get())

    def _on_window_configure(self, _event=None) -> None:
        """Temporarily yield the UI thread while the native window is moving."""
        if self._closed:
            return
        if (
            _event is not None
            and getattr(_event, "widget", self.window) is not self.window
        ):
            return
        try:
            geometry = (
                self.window.winfo_x(),
                self.window.winfo_y(),
                self.window.winfo_width(),
                self.window.winfo_height(),
            )
        except tk.TclError:
            return
        previous = self._last_window_geometry
        self._last_window_geometry = geometry
        if previous is not None and geometry != previous:
            self._pause_rendering()

    def _on_host_window_configure(self, event=None) -> None:
        """Pause preview work when the main application window is moving too."""
        if self._closed:
            return
        if event is not None and getattr(event, "widget", self.root) is not self.root:
            return
        try:
            geometry = (
                self.root.winfo_x(),
                self.root.winfo_y(),
                self.root.winfo_width(),
                self.root.winfo_height(),
            )
        except tk.TclError:
            return
        previous = self._last_host_geometry
        self._last_host_geometry = geometry
        if previous is not None and geometry != previous:
            self._pause_rendering()

    def _pause_rendering(self) -> None:
        pause_until = time.monotonic() + self.DRAG_PAUSE_MS / 1000
        self._render_paused_until = max(
            self._render_paused_until,
            pause_until,
        )

    def _render_is_paused(self) -> bool:
        return time.monotonic() < self._render_paused_until

    def _on_canvas_configure(self, event) -> None:
        if event.width < 16 or event.height < 16:
            return
        target_size = fit_monitor_frame_size(event.width, event.height)
        with self._frame_lock:
            self._target_size = target_size

    def _on_mouse_wheel(self, event):
        if event.delta == 0:
            return None
        return self._zoom_monitor(1 if event.delta > 0 else -1)

    def _zoom_monitor(self, direction: int):
        canvas_width = max(1, self.canvas.winfo_width())
        canvas_height = max(1, self.canvas.winfo_height())
        target_width, target_height = next_monitor_zoom_size(
            canvas_width,
            canvas_height,
            direction,
        )
        extra_width = max(0, self.window.winfo_width() - canvas_width)
        extra_height = max(0, self.window.winfo_height() - canvas_height)
        self.window.geometry(
            f"{target_width + extra_width}x{target_height + extra_height}"
        )
        return "break"

    def toggle_image_only(self, _event=None):
        self.canvas.pack_forget()
        if self._image_only:
            self.toolbar.pack(fill="x")
            self.canvas.pack(fill="both", expand=True, padx=8, pady=(0, 8))
            self._image_only = False
        else:
            self.toolbar.pack_forget()
            self.canvas.pack(fill="both", expand=True)
            self._image_only = True
        self.window.focus_force()
        return "break"

    def _restore_normal_view(self, _event=None):
        if self._image_only:
            return self.toggle_image_only()
        return None

    def restart(self) -> None:
        preview_url = (
            self.preview_url_provider() if self.preview_url_provider is not None else None
        )
        if preview_url:
            self._restart_preview_stream(preview_url)
            return
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

    def _restart_preview_stream(self, preview_url: str) -> None:
        self._stop_capture()
        self._generation += 1
        generation = self._generation
        self._stop_event = threading.Event()
        self.status_var.set("正在连接运行中的 EasyCon 预览…")
        self._capture_thread = threading.Thread(
            target=self._preview_loop,
            args=(preview_url, generation, self._stop_event),
            daemon=True,
        )
        self._capture_thread.start()

    def _preview_loop(
        self,
        preview_url: str,
        generation: int,
        stop_event: threading.Event,
    ) -> None:
        import cv2
        from urllib.request import urlopen

        sequence = 0
        next_process_at = 0.0
        retry_reported = False
        while not stop_event.is_set() and generation == self._generation:
            response = None
            connected = False
            try:
                # The runner starts the HTTP listener after opening the capture
                # device, so the first connection can legitimately race startup.
                response = urlopen(preview_url, timeout=2)
                self._stream_response = response
                connected = True
                retry_reported = False
                self._post_status("已连接 EasyCon 回环预览")
                buffer = bytearray()
                first_frame = True
                while not stop_event.is_set() and generation == self._generation:
                    read_chunk = getattr(response, "read1", response.read)
                    chunk = read_chunk(65536)
                    if not chunk:
                        break
                    buffer.extend(chunk)
                    while not stop_event.is_set():
                        start = buffer.find(b"\xff\xd8")
                        if start < 0:
                            if len(buffer) > 2:
                                del buffer[:-2]
                            break
                        end = buffer.find(b"\xff\xd9", start + 2)
                        if end < 0:
                            if start > 0:
                                del buffer[:start]
                            break
                        jpeg = bytes(buffer[start : end + 2])
                        del buffer[: end + 2]
                        if self._render_is_paused():
                            # Do not drain a live MJPEG stream in a tight loop
                            # while the native window is in a move/resize.
                            buffer.clear()
                            stop_event.wait(0.01)
                            continue
                        now = time.monotonic()
                        if now < next_process_at:
                            # The stream can be faster than Tk can display it;
                            # discard intermediate frames before JPEG decoding.
                            continue
                        next_process_at = now + self.FRAME_PROCESS_INTERVAL_MS / 1000
                        array = __import__("numpy").frombuffer(jpeg, dtype="uint8")
                        frame = cv2.imdecode(array, cv2.IMREAD_COLOR)
                        if frame is None or frame.size == 0:
                            continue
                        with self._frame_lock:
                            target_width, target_height = self._target_size
                        shrinking = (
                            target_width <= frame.shape[1]
                            and target_height <= frame.shape[0]
                        )
                        resized = cv2.resize(
                            frame,
                            (target_width, target_height),
                            interpolation=(
                                cv2.INTER_AREA if shrinking else cv2.INTER_LINEAR
                            ),
                        )
                        encoded = encode_tk_png(resized, cv2)
                        sequence += 1
                        with self._frame_lock:
                            self._latest_frame = (
                                sequence,
                                encoded,
                                target_width,
                                target_height,
                            )
                        if first_frame:
                            first_frame = False
                            self._post_status("EasyCon 回环画面已连接")
            except Exception as exc:
                if not stop_event.is_set() and not retry_reported:
                    self._post_status(f"回环预览连接失败，正在重试：{exc}")
                    retry_reported = True
            finally:
                if response is not None:
                    try:
                        response.close()
                    except Exception:
                        pass
                if self._stream_response is response:
                    self._stream_response = None
            if stop_event.is_set() or generation != self._generation:
                break
            if connected:
                self._post_status("回环预览流已断开，正在重试…")
                retry_reported = True
            if stop_event.wait(0.5):
                break

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
        next_process_at = 0.0
        failed_reads = 0
        first_frame = True
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
                if self._render_is_paused():
                    stop_event.wait(0.01)
                    continue
                now = time.monotonic()
                if now < next_process_at:
                    continue
                next_process_at = now + self.FRAME_PROCESS_INTERVAL_MS / 1000
                with self._frame_lock:
                    target_width, target_height = self._target_size
                shrinking = (
                    target_width <= frame.shape[1]
                    and target_height <= frame.shape[0]
                )
                resized = cv2.resize(
                    frame,
                    (target_width, target_height),
                    interpolation=(
                        cv2.INTER_AREA if shrinking else cv2.INTER_LINEAR
                    ),
                )
                try:
                    encoded = encode_tk_png(resized, cv2)
                except Exception as exc:
                    self._post_status(f"画面编码失败：{exc}")
                    return
                sequence += 1
                with self._frame_lock:
                    self._latest_frame = (
                        sequence,
                        encoded,
                        target_width,
                        target_height,
                    )
                if first_frame:
                    first_frame = False
                    self._post_status(f"采集卡 {device} 画面已连接")
        finally:
            capture.release()
            if self._capture is capture:
                self._capture = None

    def _render(self) -> None:
        if self._closed:
            return
        if self._render_is_paused():
            self.window.after(self.RENDER_INTERVAL_MS, self._render)
            return
        with self._frame_lock:
            frame = self._latest_frame
        if frame is not None and frame[0] != self._rendered_sequence:
            try:
                photo = tk.PhotoImage(master=self.window, data=frame[1], format="png")
                self.canvas.itemconfigure(self.image_item, image=photo)
                canvas_width = max(1, self.canvas.winfo_width())
                canvas_height = max(1, self.canvas.winfo_height())
                self.canvas.coords(
                    self.image_item,
                    max(0, (canvas_width - frame[2]) // 2),
                    max(0, (canvas_height - frame[3]) // 2),
                )
                self._photo = photo
                self._rendered_sequence = frame[0]
                self._render_error_reported = False
            except tk.TclError as exc:
                if not self._render_error_reported:
                    self.status_var.set(f"画面渲染失败：{exc}")
                    self._render_error_reported = True
        self.window.after(self.RENDER_INTERVAL_MS, self._render)

    def _stop_capture(self) -> None:
        self._generation += 1
        self._stop_event.set()
        capture = self._capture
        if capture is not None:
            try:
                capture.release()
            except Exception:
                pass
        response = self._stream_response
        if response is not None:
            try:
                response.close()
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
        bind_id = self._host_configure_bind_id
        self._host_configure_bind_id = None
        if bind_id:
            try:
                self.root.unbind("<Configure>", bind_id)
            except tk.TclError:
                pass
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
        preview_url_provider: Callable[[], str | None] | None = None,
    ):
        self.root = root
        self.port_provider = port_provider
        self.video_provider = video_provider
        self.process_running = process_running
        self.preview_url_provider = preview_url_provider
        self.controller_window: VirtualControllerWindow | None = None
        self.monitor_window: CaptureMonitorWindow | None = None

    def _controller_available(self) -> bool:
        if self.process_running():
            messagebox.showerror(
                "EasyCon 正在运行",
                "请先停止当前自动流程，再打开虚拟手柄。",
                parent=self.root,
            )
            return False
        return True

    def open_virtual_controller(self) -> None:
        if not self._controller_available():
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
        if not self._monitor_available():
            return
        if self.monitor_window is not None and self.monitor_window.is_open:
            self.monitor_window.show()
            return
        self.monitor_window = CaptureMonitorWindow(
            self.root,
            self.video_provider,
            self._monitor_closed,
            self.preview_url_provider,
        )

    def _monitor_available(self) -> bool:
        if self.process_running() and not (
            self.preview_url_provider is not None and self.preview_url_provider()
        ):
            messagebox.showerror(
                "EasyCon 正在运行",
                "当前运行后端没有共享预览，请先停止自动流程，再打开监视窗口。",
                parent=self.root,
            )
            return False
        return True

    def _controller_closed(self) -> None:
        self.controller_window = None

    def _monitor_closed(self) -> None:
        self.monitor_window = None

    def close_monitor(self) -> None:
        monitor_window = self.monitor_window
        self.monitor_window = None
        if monitor_window is not None:
            monitor_window.close()

    def close_all(self) -> None:
        controller_window = self.controller_window
        self.controller_window = None
        if controller_window is not None:
            controller_window.close()
        self.close_monitor()
