import threading
import time
from typing import Optional, List

import serial
import serial.tools.list_ports

from .protocol import GamePadKey, Direction, SwitchButton, SwitchHAT, SwitchStick, SwitchReport
from .serial_transport import EzDvCommand, Reply
from .serial_connection import open_handshaken_port, ordered_ports


def sleep(seconds: float, end: Optional[float] = None) -> None:
    start = time.time()
    if end is None:
        mid = start + seconds - 0.1
        end = start + seconds
    else:
        mid = end - 0.1
    while True:
        if time.time() >= mid:
            if time.time() >= end:
                return
        else:
            time.sleep(0.05)


class EasyConController:
    MINIMAL_INTERVAL = 30

    KEY_TO_BUTTON = {
        GamePadKey.Y: SwitchButton.Y,
        GamePadKey.B: SwitchButton.B,
        GamePadKey.A: SwitchButton.A,
        GamePadKey.X: SwitchButton.X,
        GamePadKey.L: SwitchButton.L,
        GamePadKey.R: SwitchButton.R,
        GamePadKey.ZL: SwitchButton.ZL,
        GamePadKey.ZR: SwitchButton.ZR,
        GamePadKey.MINUS: SwitchButton.MINUS,
        GamePadKey.PLUS: SwitchButton.PLUS,
        GamePadKey.LCLICK: SwitchButton.LCLICK,
        GamePadKey.RCLICK: SwitchButton.RCLICK,
        GamePadKey.HOME: SwitchButton.HOME,
        GamePadKey.CAPTURE: SwitchButton.CAPTURE,
    }

    KEY_TO_HAT = {
        GamePadKey.TOP: SwitchHAT.TOP,
        GamePadKey.TOP_RIGHT: SwitchHAT.TOP_RIGHT,
        GamePadKey.RIGHT: SwitchHAT.RIGHT,
        GamePadKey.DOWN_RIGHT: SwitchHAT.BOTTOM_RIGHT,
        GamePadKey.DOWN: SwitchHAT.BOTTOM,
        GamePadKey.DOWN_LEFT: SwitchHAT.BOTTOM_LEFT,
        GamePadKey.LEFT: SwitchHAT.LEFT,
        GamePadKey.TOP_LEFT: SwitchHAT.TOP_LEFT,
    }

    def __init__(self):
        self.serial_dev: Optional[serial.Serial] = None
        self.port_name: Optional[str] = None
        self.baudrate = 115200
        self.baudrate_fallbacks = [9600]  # 与固定 EasyCon 164a 的 TryConnect 一致
        self.connection_error = ""
        self._connection_generation = 0
        self._connection_lock = threading.RLock()
        self._connect_gate = threading.Lock()
        self.connected_flag = False
        self.io_lock = threading.Lock()
        self.debug_flag = False
        self.report_state = SwitchReport()
        self.report_state_dirty = False
        self.io_cond = threading.Condition()
        self.io_thread: Optional[threading.Thread] = None
        self.io_running = False

    @property
    def is_connected(self) -> bool:
        return self.connected_flag and self.serial_dev is not None and self.serial_dev.is_open

    def setdebug_flag(self, enabled: bool):
        self.debug_flag = enabled

    def list_ports(self) -> List[str]:
        return [p.device for p in serial.tools.list_ports.comports()]

    def connect(self, port: Optional[str] = None, timeout: float = 1.0, *,
                preferred_port=None, cancel_check=lambda: False, progress=lambda _text: None) -> bool:
        """Only adopt a verified device; explicit ports never scan other ports."""
        if not self._connect_gate.acquire(blocking=False):
            self.connection_error = "连接正在进行，请勿重复连接"
            return False
        try:
            self.disconnect()
            generation = self._connection_generation
            cancelled = lambda: cancel_check() or generation != self._connection_generation
            ports = [port] if port else ordered_ports(preferred_port)
            if not ports:
                self.connection_error = "未发现串口，请检查 USB 线、串口驱动和单片机供电"
                return False
            for candidate in ports:
                for baudrate in (115200, *self.baudrate_fallbacks):
                    if baudrate == 9600:
                        # Fixed 164a leaves 100 ms before reopening at 9600.
                        retry_at = time.monotonic() + .1
                        while time.monotonic() < retry_at:
                            if cancelled():
                                self.connection_error = "连接已取消"
                                return False
                            time.sleep(.01)
                    if cancelled():
                        self.connection_error = "连接已取消"
                        return False
                    progress(f"正在握手 {candidate} · {baudrate}……")
                    if self.try_connect_port(candidate, baudrate, timeout, cancel_check=cancelled):
                        return True
                    progress(f"{candidate} · {baudrate}：{self.connection_error}")
            return False
        finally:
            self._connect_gate.release()

    def try_connect_port(self, port: str, baudrate: int, timeout: float, *, cancel_check=lambda: False) -> bool:
        generation = self._connection_generation
        cancelled = lambda: cancel_check() or generation != self._connection_generation
        connection = None
        try:
            connection = open_handshaken_port(port, baudrate, timeout, cancelled=cancelled)
            with self._connection_lock:
                if cancelled():
                    raise RuntimeError("连接已取消")
                if self.serial_dev is not None:
                    raise RuntimeError("已有连接，请先断开")
                self.serial_dev = connection
                self.port_name = port
                self.baudrate = baudrate
                self.connected_flag = True
                self.connection_error = ""
                self.startio_thread()
                connection = None
            return True
        except Exception as exc:
            with self._connection_lock:
                if connection is not None and self.serial_dev is connection:
                    try:
                        self.disconnect()
                    finally:
                        connection = None
            self.connection_error = str(exc)
            if self.debug_flag:
                print(f"Failed to connect {port}: {exc}")
            return False
        finally:
            if connection is not None:
                connection.close()

    def _try_connect_with_timeout(self, port: str, baudrate: int, timeout: float) -> bool:
        return self.try_connect_port(port, baudrate, timeout)

    def disconnect(self):
        with self._connection_lock:
            self._connection_generation += 1
            self.connected_flag = False
            self.io_running = False
            with self.io_cond:
                self.report_state.reset()
                self.report_state_dirty = False
                self.io_cond.notify()
            if self.io_thread and self.io_thread.is_alive():
                self.io_thread.join(timeout=2.0)
            connection, self.serial_dev = self.serial_dev, None
            self.port_name = None
            if connection:
                connection.close()

    def startio_thread(self):
        if self.io_thread and self.io_thread.is_alive():
            return
        self.io_running = True
        self.io_thread = threading.Thread(target=self.io_loop, daemon=True)
        self.io_thread.start()

    def io_loop(self):
        last_send = 0.0
        while self.io_running:
            with self.io_cond:
                while self.io_running and not self.report_state_dirty:
                    self.io_cond.wait(timeout=0.1)
                if not self.io_running:
                    return

                now = time.time() * 1000
                dt = now - last_send
                if dt < self.MINIMAL_INTERVAL:
                    self.io_cond.wait(timeout=(self.MINIMAL_INTERVAL - dt) / 1000.0)
                    if not self.io_running:
                        return
                    continue

                report_bytes = self.report_state.get_bytes()
                self.report_state_dirty = False

            if self.is_connected:
                with self.io_lock:
                    try:
                        if self.debug_flag:
                            print(f"[{self.port_name}] >> {' '.join(f'{b:02X}' for b in report_bytes)} | {self.report_to_str()}")
                        self.serial_dev.write(report_bytes)
                        last_send = time.time() * 1000
                    except Exception:
                        self.connected_flag = False

    def send_report(self):
        if not self.connected_flag:
            return
        with self.io_cond:
            self.report_state_dirty = True
            self.io_cond.notify()

    def report_to_str(self) -> str:
        buttons = []
        for key, btn in self.KEY_TO_BUTTON.items():
            if self.report_state.button & btn:
                buttons.append(key.name)
        if self.report_state.hat != SwitchHAT.CENTER:
            buttons.append(f"HAT.{SwitchHAT(self.report_state.hat).name}")
        return f"Btn:{buttons} LX:{self.report_state.lx} LY:{self.report_state.ly} RX:{self.report_state.rx} RY:{self.report_state.ry}"

    def press(self, key: GamePadKey):
        if key in self.KEY_TO_BUTTON:
            self.report_state.button |= self.KEY_TO_BUTTON[key]
        elif key in self.KEY_TO_HAT:
            self.report_state.hat = self.KEY_TO_HAT[key]
        elif key == GamePadKey.LS:
            pass
        elif key == GamePadKey.RS:
            pass
        self.send_report()

    def release(self, key: GamePadKey):
        if key in self.KEY_TO_BUTTON:
            self.report_state.button &= ~self.KEY_TO_BUTTON[key]
        elif key in self.KEY_TO_HAT:
            self.report_state.hat = SwitchHAT.CENTER
        elif key == GamePadKey.LS:
            self.report_state.lx = SwitchStick.STICK_CENTER
            self.report_state.ly = SwitchStick.STICK_CENTER
        elif key == GamePadKey.RS:
            self.report_state.rx = SwitchStick.STICK_CENTER
            self.report_state.ry = SwitchStick.STICK_CENTER
        self.send_report()

    def release_all(self):
        self.report_state.reset()
        self.send_report()

    def click(self, key: GamePadKey, duration_ms: int = 50):
        self.press(key)
        sleep(duration_ms / 1000)
        self.release(key)

    def set_stick(self, stick: GamePadKey, x: int, y: int):
        if stick not in (GamePadKey.LS, GamePadKey.RS):
            raise ValueError("stick must be LS or RS")

        x = max(0, min(255, x))
        y = max(0, min(255, y))

        if stick == GamePadKey.LS:
            self.report_state.lx = x
            self.report_state.ly = y
        else:
            self.report_state.rx = x
            self.report_state.ry = y
        self.send_report()

    def click_stick(self, stick: GamePadKey, x: int, y: int, duration_ms: int = 50):
        self.set_stick(stick, x, y)
        sleep(duration_ms / 1000)
        self.set_stick(stick, SwitchStick.STICK_CENTER, SwitchStick.STICK_CENTER)

    def push_direction(self, direction: Direction, duration_ms: int = 50):
        self.click(GamePadKey(direction), duration_ms)

    def reset(self):
        self.release_all()

    def a(self, duration_ms: int = 50): self.click(GamePadKey.A, duration_ms)
    def b(self, duration_ms: int = 50): self.click(GamePadKey.B, duration_ms)
    def x(self, duration_ms: int = 50): self.click(GamePadKey.X, duration_ms)
    def y(self, duration_ms: int = 50): self.click(GamePadKey.Y, duration_ms)

    def l(self, duration_ms: int = 50): self.click(GamePadKey.L, duration_ms)
    def r(self, duration_ms: int = 50): self.click(GamePadKey.R, duration_ms)
    def zl(self, duration_ms: int = 50): self.click(GamePadKey.ZL, duration_ms)
    def zr(self, duration_ms: int = 50): self.click(GamePadKey.ZR, duration_ms)

    def minus(self, duration_ms: int = 50): self.click(GamePadKey.MINUS, duration_ms)
    def plus(self, duration_ms: int = 50): self.click(GamePadKey.PLUS, duration_ms)
    def home(self, duration_ms: int = 50): self.click(GamePadKey.HOME, duration_ms)
    def capture(self, duration_ms: int = 50): self.click(GamePadKey.CAPTURE, duration_ms)

    def up(self, duration_ms: int = 50): self.click(GamePadKey.TOP, duration_ms)
    def down(self, duration_ms: int = 50): self.click(GamePadKey.DOWN, duration_ms)
    def left(self, duration_ms: int = 50): self.click(GamePadKey.LEFT, duration_ms)
    def right(self, duration_ms: int = 50): self.click(GamePadKey.RIGHT, duration_ms)

    def lstick(self, x: int, y: int, duration_ms: int = 50):
        self.click_stick(GamePadKey.LS, x, y, duration_ms)

    def rstick(self, x: int, y: int, duration_ms: int = 50):
        self.click_stick(GamePadKey.RS, x, y, duration_ms)

    # ============== 高级控制器命令 ==============

    def recv_byte(self, timeout: float = 0.2) -> Optional[int]:
        """等待并读取单字节响应"""
        if not self.serial_dev:
            return None
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.serial_dev.in_waiting:
                return self.serial_dev.read(1)[0]
            time.sleep(0.01)
        return None

    def send_command(self, *cmd_bytes: int, timeout: float = 0.2) -> Optional[int]:
        """发送 EzDv 命令并等待单字节响应"""
        if not self.connected_flag or not self.serial_dev:
            return None
        with self.io_lock:
            try:
                self.serial_dev.reset_input_buffer()
                self.serial_dev.write(bytes(cmd_bytes))
                return self.recv_byte(timeout)
            except Exception:
                return None

    def change_controller_mode(self, mode: int) -> bool:
        """切换控制器模式: 1=JoyCon-L, 2=JoyCon-R, 3=Pro"""
        reply = self.send_command(
            EzDvCommand.Ready, mode, EzDvCommand.ChangeControllerMode
        )
        return reply == Reply.Ack

    def change_controller_color(self, body_rgb: tuple, button_rgb: tuple,
                                grip_l_rgb: tuple, grip_r_rgb: tuple) -> bool:
        """设置手柄颜色 (各 3 字节 RGB)。
        颜色数据内联在命令中一并发送，与 C# 版 SendSync 行为一致。"""
        if not self.connected_flag or not self.serial_dev:
            return False
        cmd = bytes([
            EzDvCommand.Ready, 0, 0, 12, 0,
            EzDvCommand.ChangeControllerColor,
            *body_rgb, *button_rgb, *grip_l_rgb, *grip_r_rgb,
        ])
        with self.io_lock:
            try:
                self.serial_dev.reset_input_buffer()
                self.serial_dev.write(cmd)
                reply = self.recv_byte(timeout=1.0)
                return reply == Reply.Ack
            except Exception:
                return False

    def unpair(self) -> bool:
        """取消配对（断开与主机的蓝牙连接）"""
        reply = self.send_command(EzDvCommand.Ready, EzDvCommand.UnPair)
        return reply == Reply.Ack

    def trigger_led(self) -> bool:
        """触发 LED 闪烁"""
        reply = self.send_command(EzDvCommand.Ready, EzDvCommand.LED)
        return reply == 0

    def get_version(self) -> int:
        """获取固件版本号"""
        reply = self.send_command(EzDvCommand.Ready, EzDvCommand.Version, timeout=0.5)
        if reply is not None and 0x40 <= reply <= 0x80:
            return reply
        return -1

    def flash(self, data: bytes) -> bool:
        """烧录固件（分片发送）"""
        if not self.connected_flag or not self.serial_dev:
            return False
        packet_size = 20
        with self.io_lock:
            for i in range(0, len(data), packet_size):
                chunk = data[i:i + packet_size]
                chunk_len = len(chunk)
                while True:
                    header = bytes([
                        EzDvCommand.Ready,
                        i & 0x7F, (i >> 7) & 0x7F,
                        chunk_len & 0x7F, (chunk_len >> 7) & 0x7F,
                        EzDvCommand.Flash,
                    ])
                    self.serial_dev.reset_input_buffer()
                    self.serial_dev.write(header)
                    reply = self.recv_byte(timeout=1.0)
                    if reply != Reply.FlashStart:
                        if not self.handshake():
                            return False
                        continue
                    self.serial_dev.reset_input_buffer()
                    self.serial_dev.write(chunk)
                    reply = self.recv_byte(timeout=1.0)
                    if reply == Reply.FlashEnd:
                        break
                    if not self.handshake():
                        return False
        return True

    def handshake(self) -> bool:
        """发送握手包恢复通信"""
        if not self.serial_dev:
            return False
        try:
            for _ in range(3):
                self.serial_dev.write(
                    bytes([EzDvCommand.Ready, EzDvCommand.Hello])
                )
            reply = self.recv_byte(timeout=0.2)
            return reply == Reply.Hello
        except Exception:
            return False

    def remote_start(self) -> bool:
        """远程启动板载脚本"""
        reply = self.send_command(EzDvCommand.Ready, EzDvCommand.ScriptStart)
        return reply == Reply.ScriptAck

    def remote_stop(self) -> bool:
        """远程停止板载脚本"""
        reply = self.send_command(EzDvCommand.Ready, EzDvCommand.ScriptStop)
        return reply == Reply.ScriptAck

    def save_amiibo(self, index: int, amiibo_data: bytes) -> bool:
        """保存 Amiibo 数据到指定索引"""
        if not self.connected_flag or not self.serial_dev:
            return False
        packet_size = 20
        with self.io_lock:
            for i in range(0, len(amiibo_data), packet_size):
                chunk = amiibo_data[i:i + packet_size]
                chunk_len = len(chunk)
                while True:
                    header = bytes([
                        EzDvCommand.Ready,
                        i & 0x7F, (i >> 7) & 0x7F,
                        chunk_len & 0x7F, (chunk_len >> 7) & 0x7F,
                        index,
                        EzDvCommand.SaveAmiibo,
                    ])
                    self.serial_dev.reset_input_buffer()
                    self.serial_dev.write(header)
                    reply = self.recv_byte(timeout=1.0)
                    if reply != Reply.Ack:
                        if not self.handshake():
                            return False
                        continue
                    self.serial_dev.reset_input_buffer()
                    self.serial_dev.write(chunk)
                    reply = self.recv_byte(timeout=1.0)
                    if reply == Reply.Ack:
                        break
                    if not self.handshake():
                        return False
        return True

    def change_amiibo_index(self, index: int) -> bool:
        """切换当前使用的 Amiibo 索引"""
        reply = self.send_command(
            EzDvCommand.Ready, index, EzDvCommand.ChangeAmiiboIndex
        )
        return reply == Reply.Ack
