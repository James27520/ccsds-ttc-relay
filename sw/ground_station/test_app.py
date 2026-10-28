"""UI integration checks with a fake controller; no serial or hardware imports."""
import threading
import tkinter as tk
import unittest

from .app import StationApp


class FakeController:
    def __init__(self, role, emit, log_dir=None):
        self.role, self.emit, self.calls = role, emit, []

    def submit(self, action, **kwargs):
        self.calls.append((action, kwargs))


class StationAppTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = None

    def tearDown(self):
        try:
            for callback in self.root.tk.call("after", "info"):
                self.root.after_cancel(callback)
            self.root.destroy()
        except tk.TclError:
            pass

    def make_app(self, role):
        self.app = StationApp(self.root, role, controller_factory=FakeController)
        self.root.update()
        return self.app

    def ready(self, app):
        app._handle_event(dict(type="devices", devices=[dict(port="FAKE_PORT", label="测试设备"),
                                                        dict(port="FAKE_RELAY", label="转发测试设备")]))
        app.port_var.set("测试设备")
        if app.role == "sender":
            app.relay_port_var.set("转发测试设备")
        app._connect()
        app._handle_event(dict(type="status", state="ready", message="测试连接"))

    def test_startup_discovers_without_connecting_or_transmitting(self):
        app = self.make_app("sender")
        self.assertEqual(app.controller.calls, [("discover", {})])
        self.assertFalse(app.connected)
        self.assertEqual(app.history.get_children(), ())

    def test_sender_requires_two_distinct_debug_ports(self):
        app = self.make_app("sender")
        app._handle_event(dict(type="devices", devices=[dict(port="FAKE_PORT", label="测试设备")]))
        self.assertEqual(app.port_var.get(), "")
        app.port_var.set("测试设备")
        app.relay_port_var.set("测试设备")
        app._connect()
        self.assertEqual(app.controller.calls, [("discover", {})])
        self.ready(app)
        self.assertEqual(app.controller.calls[-1], ("connect", {"port": "FAKE_PORT", "relay_port": "FAKE_RELAY"}))

    def test_utf8_limit_and_send_payload(self):
        app = self.make_app("sender")
        self.ready(app)
        app.message_input.insert("1.0", "全国嵌入式")
        self.root.update()
        self.assertTrue(app.byte_var.get().startswith("15 / 32"))
        app._send()
        self.assertEqual(app.controller.calls[-1], ("send", {"text": "全国嵌入式"}))
        app.message_input.insert("end", "a" * 33)
        self.root.update()
        self.assertEqual(str(app.send_button.cget("state")), "disabled")
        calls = len(app.controller.calls)
        app._send()
        self.assertEqual(len(app.controller.calls), calls)

    def test_settings_reject_unsafe_range_and_distinguish_readbacks(self):
        app = self.make_app("sender")
        self.ready(app)
        app.requested["tx_atten_db"].set("49")
        calls = len(app.controller.calls)
        app._configure()
        self.assertEqual(len(app.controller.calls), calls)
        app._handle_event(dict(type="settings", values={"tx_lo_mhz_requested": 900,
                              "tx_lo_hz_readback": 900000000, "tx_atten_db_requested": 50}))
        self.assertEqual(app.readbacks["tx_lo_mhz"].get(), "900")
        self.assertEqual(app.readbacks["tx_atten_db"].get(), "未提供回读")

    def test_worker_callback_waits_for_tk_queue_consumption(self):
        app = self.make_app("sender")
        worker = threading.Thread(target=lambda: app.controller.emit(
            dict(type="status", state="ready", message="来自工作线程")))
        worker.start()
        worker.join()
        self.assertFalse(app.connected)
        app._drain_events()
        self.assertTrue(app.connected)

    def test_receiver_uses_only_independent_capture_messages(self):
        app = self.make_app("receiver")
        self.ready(app)
        self.assertEqual(app.spectrum.points, [])
        app._receive()
        app._handle_event(dict(type="rx", messages=[dict(message_id="session:1", text="实测内容",
            payload_bytes=12, duplicate=False)], valid_frames=1, crc_rejected=2, rms_codes=45.2,
            carrier_hz=1000500000, spectrum=dict(freq_mhz=[1000.4, 1000.5, 1000.6], dbfs=[-80, -35, -81]),
            capture_seconds=15.8, received_at="2026-10-28T10:00:00+08:00"))
        self.assertEqual(app.metric_vars["valid"].get(), "1")
        self.assertEqual(len(app.history.get_children()), 1)
        self.assertEqual(len(app.spectrum.points), 3)
        self.assertIn("1000.500000 MHz", app.carrier_var.get())
        self.assertEqual(sum(action == "receive" for action, _ in app.controller.calls), 1)
        app._stop()
        self.assertEqual(app.controller.calls[-1], ("stop", {}))

    def test_close_keeps_window_until_cleanup_acknowledgement(self):
        app = self.make_app("receiver")
        app.close()
        self.assertEqual(app.controller.calls[-1], ("close", {}))
        self.assertTrue(self.root.winfo_exists())
        app._close_wait_notice()
        self.assertTrue(self.root.winfo_exists())
        self.assertIn("仍在等待", app.log_text.get("1.0", "end"))
        app._handle_event(dict(type="closed"))
        self.assertTrue(app.closed)

    def test_receiver_text_row_visible_at_minimum_window_size(self):
        app = self.make_app("receiver")
        self.root.geometry("1000x840")
        self.root.deiconify()
        app._append_message(dict(message_id="12345678:0001", text="布局验收", payload_bytes=12), "已解码")
        self.root.update()
        row = app.history.get_children()[0]
        bounds = app.history.bbox(row)
        self.assertTrue(bounds, "a decoded row must remain visible at minimum window size")
        self.assertGreaterEqual(app.history.winfo_height(), bounds[1] + bounds[3])

    def test_compact_spectrum_level_labels_do_not_overlap(self):
        app = self.make_app("receiver")
        self.root.geometry("1000x840")
        self.root.deiconify()
        app.spectrum.set_spectrum(dict(freq_mhz=[1000.4, 1000.5, 1000.6], dbfs=[-110, -65, -100]))
        self.root.update()
        bounds = sorted((app.spectrum.bbox(item) for item in app.spectrum.find_withtag("level_tick")),
                        key=lambda box: box[1])
        self.assertGreaterEqual(len(bounds), 2)
        for upper, lower in zip(bounds, bounds[1:]):
            self.assertLess(upper[3], lower[1])


if __name__ == "__main__":
    unittest.main()
