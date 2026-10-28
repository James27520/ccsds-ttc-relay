"""Monitor evidence separation and lifecycle checks with fake controllers only."""
import threading
import time
import tkinter as tk
import unittest

from .app import StationApp
from .test_app import FakeController


class FakeTelemetryController:
    def __init__(self, emit, log_dir=None):
        self.emit, self.calls = emit, []

    def submit(self, action, **kwargs):
        self.calls.append((action, kwargs))


class TelemetryWindowTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = StationApp(self.root, "sender", controller_factory=FakeController,
                              telemetry_controller_factory=FakeTelemetryController)
        self.app.open_telemetry()
        self.monitor = self.app.telemetry_window
        self.monitor.window.withdraw()
        self.root.update()

    def tearDown(self):
        try:
            for callback in self.root.tk.call("after", "info"):
                self.root.after_cancel(callback)
            self.root.destroy()
        except tk.TclError:
            pass

    def snapshot(self, **values):
        self.monitor._handle_event(dict(type="telemetry", received_at=time.time(), snapshot=values))

    def test_monitor_actions_are_read_only_and_never_use_station_port(self):
        controller = self.monitor.controller
        self.assertEqual(controller.calls, [("discover", {})])
        self.monitor._handle_event(dict(type="devices", devices=[dict(port="FAKE_ADDA", label="遥控板")]))
        self.assertEqual(self.monitor.port_var.get(), "")
        self.monitor.port_var.set("遥控板")
        self.monitor._connect()
        self.monitor._handle_event(dict(type="status", state="connected", message="连接成功"))
        self.monitor.query_button.invoke()
        self.assertEqual(controller.calls[-2:], [("connect", {"port": "FAKE_ADDA"}), ("query", {})])
        self.assertEqual(self.app.controller.calls, [("discover", {})])

    def test_invalid_stage_cannot_reuse_origin_or_values_as_evidence(self):
        self.snapshot(d_valid=1, d_origin=1, d_event=7, d_air_seq=4, d_rx_mhz=900, d_tx_mhz=1000)
        self.assertIn("ADC_NORMAL", self.monitor.origin_labels["d"].cget("text"))
        self.snapshot(d_valid=0, d_origin=1, d_event=7, d_rx_mhz=900, d_tx_mhz=1000)
        self.assertIn("未知", self.monitor.stage_vars["d"]["state"].get())
        self.assertIn("UNKNOWN", self.monitor.origin_labels["d"].cget("text"))
        self.assertEqual(self.monitor.stage_vars["d"]["frequency"].get(), "—")

    def test_uart_test_and_ack_never_become_adc_or_spi_proof(self):
        self.snapshot(d_valid=1, d_origin=4, a_valid=1, a_origin=4, a_rx_hz=900000000,
                      a_tx_hz=1000000000, a_rc=0, spi_valid=0)
        self.assertIn("UART_NETTEST", self.monitor.origin_labels["d"].cget("text"))
        self.assertIn("测试来源", self.monitor.stage_vars["d"]["state"].get())
        self.assertIsNone(self.monitor.relay_received_at)
        self.assertIn("未知", self.monitor.spi_var.get())
        self.app.connected = True
        self.monitor._request_relay()
        self.assertEqual(self.app.controller.calls[-1], ("read_relay", {}))
        self.assertEqual(self.monitor.controller.calls, [("discover", {})])
        self.app._handle_event(dict(type="relay_telemetry", received_at=time.time(), values={
            "relay_rx_hz_readback": 901000000, "relay_tx_hz_readback": 1001000000,
            "relay_tx_atten_db_readback": 50, "relay_rx_gain_db_readback": 30, "relay_mode": 1}))
        self.assertIn("RX 901 MHz", self.monitor.spi_details_var.get())
        self.snapshot(a_valid=1, a_origin=1, a_rx_hz=900000000, a_tx_hz=1000000000, spi_valid=0)
        self.assertIn("RX 901 MHz", self.monitor.spi_details_var.get())

    def test_worker_callback_and_stale_indicator(self):
        worker = threading.Thread(target=lambda: self.monitor.controller.emit(dict(
            type="telemetry", received_at=100.0, snapshot=dict(d_valid=1, d_origin=1))))
        worker.start()
        worker.join()
        self.assertEqual(self.monitor.snapshot, {})
        self.monitor._drain_events()
        self.monitor._refresh_freshness(now=106.1)
        self.assertIn("已过期", self.monitor.freshness_var.get())
        self.assertIn("历史状态", self.monitor.freshness_var.get())

    def test_closing_monitor_waits_and_releases_reference_without_closing_station(self):
        self.monitor.close()
        self.assertEqual(self.monitor.controller.calls[-1], ("close", {}))
        self.assertTrue(self.monitor.window.winfo_exists())
        self.monitor._close_wait_notice()
        self.assertTrue(self.monitor.window.winfo_exists())
        self.monitor._handle_event(dict(type="closed"))
        self.assertIsNone(self.app.telemetry_window)
        self.assertFalse(self.app.closed)
        self.assertTrue(self.root.winfo_exists())

    def test_main_close_waits_when_station_worker_finishes_first(self):
        self.app.close()
        self.app._handle_event(dict(type="closed"))
        self.assertFalse(self.app.closed)
        self.assertTrue(self.root.winfo_exists())
        self.assertEqual(self.monitor.controller.calls[-1], ("close", {}))
        self.monitor._handle_event(dict(type="closed"))
        self.assertTrue(self.app.closed)

    def test_main_close_waits_when_monitor_worker_finishes_first(self):
        self.app.close()
        self.monitor._handle_event(dict(type="closed"))
        self.assertFalse(self.app.closed)
        self.assertTrue(self.root.winfo_exists())
        self.app._handle_event(dict(type="closed"))
        self.assertTrue(self.app.closed)

    def test_monitor_error_releases_connection_controls_and_marks_history(self):
        self.monitor._handle_event(dict(type="devices", devices=[dict(port="FAKE_ADDA", label="遥控板")]))
        self.monitor.port_var.set("遥控板")
        self.monitor._handle_event(dict(type="status", state="connected", message="已连接"))
        self.snapshot(d_valid=1, d_origin=1)
        self.monitor._handle_event(dict(type="status", state="error", message="CRC mismatch; port closed"))
        self.assertFalse(self.monitor.connected)
        self.assertEqual(str(self.monitor.connect_button.cget("state")), "normal")
        self.assertEqual(str(self.monitor.port_combo.cget("state")), "readonly")
        self.assertIn("已断开，保留历史", self.monitor.freshness_var.get())
        self.assertEqual(str(self.monitor.query_button.cget("state")), "disabled")

    def test_unexpected_station_worker_exit_closes_monitor_before_root(self):
        self.app._handle_event(dict(type="closed"))
        self.assertTrue(self.app.closing)
        self.assertTrue(self.monitor.closing)
        self.assertFalse(self.app.closed)
        self.assertEqual(self.monitor.controller.calls[-1], ("close", {}))
        self.assertTrue(self.root.winfo_exists())
        self.monitor._handle_event(dict(type="closed"))
        self.assertTrue(self.app.closed)

    def test_monitor_startup_failure_leaves_no_orphan_window(self):
        self.monitor.close()
        self.monitor._handle_event(dict(type="closed"))
        def failing_factory(*args, **kwargs):
            raise RuntimeError("fake startup failure")
        self.app.telemetry_controller_factory = failing_factory
        self.app.open_telemetry()
        self.assertIsNone(self.app.telemetry_window)
        self.assertFalse(any(isinstance(widget, tk.Toplevel) for widget in self.root.winfo_children()))
        self.assertIn("fake startup failure", self.app.log_text.get("1.0", "end"))


if __name__ == "__main__":
    unittest.main()
