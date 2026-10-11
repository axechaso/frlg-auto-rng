"""Bounded EasyCon Hello probes. A timed-out worker never owns a controller."""
from __future__ import annotations

import re
import threading
import time

import serial
import serial.tools.list_ports

from .serial_transport import EzDvCommand, Reply

_pending = set()
_pending_lock = threading.Lock()


def ordered_ports(preferred=None):
    """Prefer the selected live port, then USB/other ports, then Bluetooth."""
    rows = list(serial.tools.list_ports.comports())
    def key(row):
        hardware = (getattr(row, "hwid", "") or "").upper()
        bluetooth = "BTHENUM" in hardware or "RFCOMM" in hardware
        name = row.device.upper()
        number = re.fullmatch(r"COM(\d+)", name)
        return bluetooth, int(number[1]) if number else 0, name
    ports = list(dict.fromkeys(row.device for row in sorted(rows, key=key)))
    selected = next((port for port in ports if preferred and port.casefold() == preferred.casefold()), None)
    if selected:
        ports.remove(selected)
        ports.insert(0, selected)
    return ports


def open_handshaken_port(port, baudrate, timeout, *, cancelled=lambda: False):
    """Open and verify Ready/Ready/Hello, or raise without adopting late results.

    Windows drivers can block inside open/read/write. The caller's deadline and
    cancellation remain bounded; an abandoned daemon closes its own serial
    handle when the driver returns. The same pending port is not reopened.
    """
    if timeout <= 0:
        raise ValueError("连接超时必须大于 0")
    if cancelled():
        raise RuntimeError("连接已取消")
    port_key = port.casefold()
    with _pending_lock:
        if port_key in _pending:
            raise RuntimeError(f"{port} 的上一连接尝试仍在释放，请稍后重试")
        _pending.add(port_key)
    ready, abandoned = threading.Event(), threading.Event()
    lock = threading.Lock()
    result = {"serial": None, "error": None}
    deadline = time.monotonic() + timeout

    def stop():
        return abandoned.is_set() or cancelled() or time.monotonic() >= deadline

    def worker():
        connection = None
        verified = False
        try:
            connection = serial.Serial()
            connection.port = port
            connection.baudrate = baudrate
            connection.timeout = min(.05, timeout)
            connection.write_timeout = min(.2, timeout)
            # Set public flags before open: avoid resetting CH340/Arduino boards.
            connection.dtr = False
            connection.rts = False
            connection.open()
            if not stop():
                connection.reset_input_buffer()
                connection.reset_output_buffer()
                connection.write(bytes((EzDvCommand.Ready, EzDvCommand.Ready, EzDvCommand.Hello)))
                while not stop():
                    count = connection.in_waiting
                    if count:
                        response = connection.read(count)
                        # Match the fixed 164a TTLSerialClient's first-byte test.
                        if response and response[0] == Reply.Hello:
                            verified = True
                            break
                    abandoned.wait(.01)
                if not verified:
                    raise TimeoutError(f"{port} @ {baudrate} 未收到伊机控 Hello 握手")
        except Exception as exc:
            with lock:
                result["error"] = exc
        finally:
            with lock:
                if verified and not stop():
                    result["serial"], connection = connection, None
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass
            with _pending_lock:
                _pending.discard(port_key)
            ready.set()

    def discard():
        with lock:
            abandoned.set()
            connection, result["serial"] = result["serial"], None
        if connection is not None:
            connection.close()

    thread = threading.Thread(target=worker, daemon=True, name=f"easycon-connect-{port}")
    try:
        thread.start()
    except Exception:
        with _pending_lock:
            _pending.discard(port_key)
        raise
    while not ready.wait(min(.02, max(0, deadline - time.monotonic()))):
        if cancelled() or time.monotonic() >= deadline:
            discard()
            if cancelled():
                raise RuntimeError("连接已取消")
            raise TimeoutError(f"{port} @ {baudrate} 连接超时（{timeout:g} 秒）")
    if cancelled() or time.monotonic() >= deadline:
        discard()
        raise RuntimeError("连接已取消") if cancelled() else TimeoutError(f"{port} @ {baudrate} 连接超时")
    with lock:
        connection, result["serial"] = result["serial"], None
        error = result["error"]
    if connection is None:
        raise error or RuntimeError(f"{port} @ {baudrate} 未完成握手")
    return connection
