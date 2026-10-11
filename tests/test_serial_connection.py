import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from easycon import EasyConController
from easycon.serial_connection import open_handshaken_port, ordered_ports
from easycon.serial_transport import EzDvCommand, Reply


class FakeSerial:
    def __init__(self, responses=(), on_open=None):
        self.responses = list(responses)
        self.on_open = on_open
        self.is_open = False
        self.writes = []
        self.closed = threading.Event()
        self.open_flags = None
        self.close_count = 0

    def open(self):
        self.open_flags = self.dtr, self.rts
        if self.on_open:
            self.on_open()
        self.is_open = True

    def reset_input_buffer(self):
        pass

    def reset_output_buffer(self):
        pass

    @property
    def in_waiting(self):
        return len(self.responses[0]) if self.responses else 0

    def read(self, count):
        return self.responses.pop(0)

    def write(self, data):
        self.writes.append(data)

    def close(self):
        self.close_count += 1
        self.is_open = False
        self.closed.set()


class SerialConnectionTests(unittest.TestCase):
    def setUp(self):
        self.port = "FAKE-" + self._testMethodName

    def test_selected_live_port_first_then_natural_usb_then_bluetooth(self):
        rows = [SimpleNamespace(device=p, hwid=h) for p, h in (
            ("COM12", "USB"), ("COM3", "BTHENUM"), ("COM9", "USB"), ("COM2", "USB"))]
        with patch("serial.tools.list_ports.comports", return_value=rows):
            self.assertEqual(ordered_ports(), ["COM2", "COM9", "COM12", "COM3"])
            self.assertEqual(ordered_ports("com9"), ["COM9", "COM2", "COM12", "COM3"])
            self.assertEqual(ordered_ports("COM8"), ["COM2", "COM9", "COM12", "COM3"])

    def test_hello_only_and_public_reset_flags_set_before_open(self):
        device = FakeSerial([bytes((Reply.Hello,))])
        with patch("easycon.serial_connection.serial.Serial", return_value=device):
            result = open_handshaken_port(self.port, 115200, .5)
        self.assertIs(result, device)
        self.assertEqual(device.open_flags, (False, False))
        self.assertEqual(device.writes, [bytes((EzDvCommand.Ready, EzDvCommand.Ready, EzDvCommand.Hello))])
        self.assertFalse(device.closed.is_set())
        device.close()

    def test_first_byte_must_be_hello_not_arbitrary_matching_substring(self):
        device = FakeSerial([bytes((1, Reply.Hello))])
        with patch("easycon.serial_connection.serial.Serial", return_value=device):
            with self.assertRaises(TimeoutError):
                open_handshaken_port(self.port, 115200, .08)
        self.assertTrue(device.closed.wait(.5))

    def test_later_hello_packet_can_follow_noise(self):
        device = FakeSerial([b"\x01", bytes((Reply.Hello,))])
        with patch("easycon.serial_connection.serial.Serial", return_value=device):
            self.assertIs(open_handshaken_port(self.port, 115200, .5), device)
        device.close()

    def test_open_error_closes_temporary_serial(self):
        device = FakeSerial(on_open=Mock(side_effect=PermissionError("port busy")))
        with patch("easycon.serial_connection.serial.Serial", return_value=device):
            with self.assertRaisesRegex(PermissionError, "port busy"):
                open_handshaken_port(self.port, 115200, .5)
        self.assertTrue(device.closed.is_set())
        self.assertEqual(device.close_count, 1)

    def test_blocked_open_returns_on_deadline_and_late_handle_is_closed(self):
        gate, entered = threading.Event(), threading.Event()
        def block():
            entered.set()
            gate.wait(3)
        device = FakeSerial([bytes((Reply.Hello,))], block)
        try:
            with patch("easycon.serial_connection.serial.Serial", return_value=device) as construct:
                start = time.monotonic()
                with self.assertRaises(TimeoutError):
                    open_handshaken_port(self.port, 115200, .08)
                self.assertLess(time.monotonic() - start, .75)
                self.assertTrue(entered.is_set())
                with self.assertRaisesRegex(RuntimeError, "仍在释放"):
                    open_handshaken_port(self.port, 9600, .5)
                self.assertEqual(construct.call_count, 1)
        finally:
            gate.set()
        self.assertTrue(device.closed.wait(.5))
        self.assertEqual(device.writes, [])

    def test_cancelled_probe_does_not_open_serial(self):
        with patch("easycon.serial_connection.serial.Serial") as construct:
            with self.assertRaisesRegex(RuntimeError, "取消"):
                open_handshaken_port(self.port, 115200, .5, cancelled=lambda: True)
        construct.assert_not_called()

    def test_cancellation_during_blocked_open_does_not_adopt_late_result(self):
        gate, entered, cancel = threading.Event(), threading.Event(), threading.Event()
        device = FakeSerial([bytes((Reply.Hello,))], lambda: (entered.set(), gate.wait(3)))
        controller = EasyConController()
        result = []
        try:
            with patch("easycon.serial_connection.serial.Serial", return_value=device), patch.object(controller, "startio_thread") as start_io:
                caller = threading.Thread(target=lambda: result.append(controller.connect(self.port,
                    cancel_check=cancel.is_set)))
                caller.start()
                self.assertTrue(entered.wait(1))
                cancel.set()
                caller.join(.5)
                self.assertFalse(caller.is_alive())
                self.assertEqual(result, [False])
                start_io.assert_not_called()
                self.assertFalse(controller.is_connected)
                self.assertIsNone(controller.serial_dev)
        finally:
            gate.set()
        self.assertTrue(device.closed.wait(.5))

    def test_controller_adopts_only_verified_serial_and_reports_actual_baudrate(self):
        device = FakeSerial([bytes((Reply.Hello,))])
        controller = EasyConController()
        with patch("easycon.serial_connection.serial.Serial", return_value=device), patch.object(controller, "startio_thread") as start_io:
            self.assertTrue(controller.try_connect_port(self.port, 9600, .5))
        self.assertTrue(controller.is_connected)
        self.assertEqual(controller.port_name, self.port)
        self.assertEqual(controller.baudrate, 9600)
        start_io.assert_called_once()
        controller.disconnect()
        self.assertIsNone(controller.port_name)
        self.assertTrue(device.closed.is_set())

    def test_each_port_uses_164a_primary_then_9600_before_next_port(self):
        controller = EasyConController()
        attempts = []
        with patch("easycon.controller.ordered_ports", return_value=["COM7", "COM9"]), patch.object(
            controller, "try_connect_port", side_effect=[False, False, False, True]) as connect:
            self.assertTrue(controller.connect(preferred_port="COM7", progress=attempts.append))
        self.assertEqual([call.args[:2] for call in connect.call_args_list],
                         [("COM7", 115200), ("COM7", 9600), ("COM9", 115200), ("COM9", 9600)])
        self.assertTrue(any("正在握手 COM9" in text for text in attempts))

    def test_manual_connect_does_not_scan_other_ports(self):
        controller = EasyConController()
        with patch("easycon.controller.ordered_ports") as scan, patch.object(controller, "try_connect_port", return_value=False) as connect:
            self.assertFalse(controller.connect("COM7"))
        scan.assert_not_called()
        self.assertEqual([call.args[:2] for call in connect.call_args_list], [("COM7", 115200), ("COM7", 9600)])

    def test_164a_baudrate_retry_pause_can_be_cancelled(self):
        controller = EasyConController()
        cancel = threading.Event()
        with patch.object(controller, "try_connect_port", return_value=False) as connect, patch(
            "easycon.controller.time.sleep", side_effect=lambda _seconds: cancel.set()) as pause:
            self.assertFalse(controller.connect("COM7", cancel_check=cancel.is_set))
        self.assertEqual([call.args[:2] for call in connect.call_args_list], [("COM7", 115200)])
        pause.assert_called_once_with(.01)
        self.assertEqual(controller.connection_error, "连接已取消")

    def test_disconnecting_invalidates_pending_connection(self):
        controller = EasyConController()
        gate, entered = threading.Event(), threading.Event()
        device = FakeSerial([bytes((Reply.Hello,))], lambda: (entered.set(), gate.wait(3)))
        results = []
        try:
            with patch("easycon.serial_connection.serial.Serial", return_value=device), patch.object(controller, "startio_thread") as start_io:
                caller = threading.Thread(target=lambda: results.append(controller.connect(self.port)))
                caller.start()
                self.assertTrue(entered.wait(1))
                controller.disconnect()
                caller.join(.5)
                self.assertEqual(results, [False])
                self.assertFalse(caller.is_alive())
                start_io.assert_not_called()
        finally:
            gate.set()
        self.assertTrue(device.closed.wait(.5))
        self.assertIsNone(controller.serial_dev)

    def test_no_ports_is_actionable_without_opening_any_device(self):
        controller = EasyConController()
        with patch("easycon.controller.ordered_ports", return_value=[]), patch("easycon.serial_connection.serial.Serial") as construct:
            self.assertFalse(controller.connect())
        construct.assert_not_called()
        self.assertIn("串口驱动", controller.connection_error)

    def test_io_thread_start_failure_does_not_leave_a_connected_handle(self):
        controller = EasyConController()
        device = FakeSerial([bytes((Reply.Hello,))])
        with patch("easycon.serial_connection.serial.Serial", return_value=device), patch.object(controller,
            "startio_thread", side_effect=RuntimeError("thread unavailable")):
            self.assertFalse(controller.try_connect_port(self.port, 115200, .5))
        self.assertFalse(controller.is_connected)
        self.assertIsNone(controller.serial_dev)
        self.assertIsNone(controller.port_name)
        self.assertEqual(device.close_count, 1)
        self.assertIn("thread unavailable", controller.connection_error)

    def test_disconnect_discards_unsent_pressed_state(self):
        controller = EasyConController()
        controller.report_state.button = 4
        controller.report_state_dirty = True
        controller.disconnect()
        self.assertFalse(controller.report_state_dirty)
        self.assertEqual(controller.report_state.button, 0)


if __name__ == "__main__":
    unittest.main()
