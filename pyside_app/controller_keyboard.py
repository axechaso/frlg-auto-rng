"""Windows virtual-key input, independent of Qt focus and IME composition.

Only mapped keys are handled, while the controller explicitly allows input.
The hook posts to Qt; serial I/O never runs inside the Windows hook callback.
"""
import ctypes
import sys
from ctypes import wintypes

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QKeySequence


def virtual_binding(text):
    if not text:
        return None
    combination = QKeySequence.fromString(text, QKeySequence.SequenceFormat.PortableText)[0]
    key = int(combination.key())
    modifiers = combination.keyboardModifiers()
    named = {
        Qt.Key.Key_Backspace: 8, Qt.Key.Key_Tab: 9, Qt.Key.Key_Return: 13,
        Qt.Key.Key_Enter: 13, Qt.Key.Key_Pause: 19, Qt.Key.Key_CapsLock: 20,
        Qt.Key.Key_Space: 32, Qt.Key.Key_PageUp: 33, Qt.Key.Key_PageDown: 34,
        Qt.Key.Key_End: 35, Qt.Key.Key_Home: 36, Qt.Key.Key_Left: 37,
        Qt.Key.Key_Up: 38, Qt.Key.Key_Right: 39, Qt.Key.Key_Down: 40,
        Qt.Key.Key_Print: 44, Qt.Key.Key_Insert: 45, Qt.Key.Key_Delete: 46,
        Qt.Key.Key_NumLock: 144, Qt.Key.Key_ScrollLock: 145,
        Qt.Key.Key_Semicolon: 186, Qt.Key.Key_Equal: 187, Qt.Key.Key_Comma: 188,
        Qt.Key.Key_Minus: 189, Qt.Key.Key_Period: 190, Qt.Key.Key_Slash: 191,
        Qt.Key.Key_QuoteLeft: 192, Qt.Key.Key_BracketLeft: 219,
        Qt.Key.Key_Backslash: 220, Qt.Key.Key_BracketRight: 221, Qt.Key.Key_Apostrophe: 222,
    }
    shifted = {ord(char): vk for char, vk in zip('!@#$%^&*()_+{}|:"<>?~', (49, 50, 51, 52, 53, 54, 55, 56, 57, 48, 189, 187, 219, 221, 220, 186, 222, 188, 190, 191, 192))}
    implicit_shift = False
    if modifiers & Qt.KeyboardModifier.KeypadModifier:
        vk = key - 48 + 96 if 48 <= key <= 57 else {
            Qt.Key.Key_Asterisk: 106, Qt.Key.Key_Plus: 107, Qt.Key.Key_Minus: 109,
            Qt.Key.Key_Period: 110, Qt.Key.Key_Slash: 111, Qt.Key.Key_Enter: 13,
            Qt.Key.Key_Return: 13,
        }.get(key)
    elif 48 <= key <= 57 or 65 <= key <= 90:
        vk = key
    elif Qt.Key.Key_F1 <= key <= Qt.Key.Key_F24:
        vk = key - int(Qt.Key.Key_F1) + 112
    elif key in shifted:
        vk = shifted[key]
        implicit_shift = True
    else:
        vk = named.get(key)
    if vk is None:
        raise ValueError(f"Windows 手柄输入暂不支持按键 {text}，请选择字母、数字、方向键或功能键")
    mask = sum(bit for modifier, bit in (
        (Qt.KeyboardModifier.ShiftModifier, 1), (Qt.KeyboardModifier.ControlModifier, 2),
        (Qt.KeyboardModifier.AltModifier, 4), (Qt.KeyboardModifier.MetaModifier, 8),
    ) if modifiers & modifier)
    if implicit_shift:
        mask |= 1
    return int(vk), mask


class ControllerKeyboard(QObject):
    changed = Signal(int, str, int, bool)

    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.handle = None
        self.callback = None
        self.held = {}
        self.bindings = {}
        self.generation = 0
        self.changed.connect(self.deliver, Qt.ConnectionType.QueuedConnection)
        self.user32 = None
        if sys.platform == "win32":
            self.user32 = ctypes.WinDLL("user32", use_last_error=True)
            self.user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
            self.user32.CallNextHookEx.restype = ctypes.c_ssize_t
            self.user32.SetWindowsHookExW.argtypes = [ctypes.c_int, ctypes.c_void_p, wintypes.HINSTANCE, wintypes.DWORD]
            self.user32.SetWindowsHookExW.restype = wintypes.HHOOK
            self.user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
            self.user32.UnhookWindowsHookEx.restype = wintypes.BOOL
            self.user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
            self.user32.GetAsyncKeyState.restype = ctypes.c_short

    @staticmethod
    def build_bindings(mapping):
        bindings = {}
        for key, text in mapping.items():
            binding = virtual_binding(text)
            if binding is not None:
                if binding in bindings:
                    raise ValueError(f"{text} 与另一项使用同一个 Windows 按键")
                bindings[binding] = key
        return bindings

    def update_mapping(self, mapping):
        bindings = self.build_bindings(mapping)
        self.reset()
        self.bindings = bindings

    def start(self):
        if self.handle or self.user32 is None:
            return

        class KeyboardData(ctypes.Structure):
            _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD),
                        ("flags", wintypes.DWORD), ("time", wintypes.DWORD),
                        ("extra", ctypes.c_size_t)]

        callback_type = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)

        def callback(code, message, pointer):
            if code >= 0 and message in (0x100, 0x101, 0x104, 0x105):
                data = ctypes.cast(pointer, ctypes.POINTER(KeyboardData)).contents
                down = message in (0x100, 0x104)
                # Letters use virtual keys, so a Chinese IME cannot consume the
                # controller key before the tool sees it.
                modifiers = sum(bit for keys, bit in (((16,), 1), ((17,), 2), ((18,), 4), ((91, 92), 8))
                                if any(self.user32.GetAsyncKeyState(vk) & 0x8000 for vk in keys))
                if self.feed(data.vkCode, down, modifiers):
                    return 1
            return self.user32.CallNextHookEx(self.handle, code, message, pointer)

        self.callback = callback_type(callback)
        self.handle = self.user32.SetWindowsHookExW(13, self.callback, None, 0)
        if not self.handle:
            raise OSError(ctypes.get_last_error(), "Windows 键盘监听启动失败")

    def feed(self, vk, down, modifiers=0):
        """Process a native transition; also usable with an isolated fake pad."""
        if not down and vk in self.held:
            key = self.held.pop(vk)
        else:
            if not self.owner.keyboard_allowed():
                return False
            if vk == 27 and self.owner.overlay.isVisible():
                key = "EXIT_OVERLAY"
            else:
                key = self.bindings.get((vk, modifiers))
                if key is None and modifiers in (0, 1):
                    key = self.bindings.get((vk, 0))
            if key is None or not down:
                return False
            if vk in self.held:
                return True
            self.held[vk] = key
        self.changed.emit(self.generation, key, vk, down)
        return True

    def deliver(self, generation, key, vk, down):
        if generation != self.generation:
            return
        if key == "EXIT_OVERLAY":
            if down:
                self.owner.overlay.exit_control()
            return
        if down and not self.owner.keyboard_allowed():
            self.held.pop(vk, None)
            return
        self.owner.keyboard_transition(("native", vk), key, down)

    def reset(self):
        self.generation += 1
        self.held.clear()

    def stop(self):
        self.reset()
        if self.handle:
            self.user32.UnhookWindowsHookEx(self.handle)
            self.handle = None
