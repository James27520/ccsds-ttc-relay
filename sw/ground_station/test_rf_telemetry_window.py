"""Offline UI evidence and lifecycle tests. Fixtures are synthetic, never SMA proof."""
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import time
import tkinter as tk
import unittest

from .app import StationApp
from ._tk_test_support import dispose_tk_test
from .rf_telemetry_window import validated_snapshots
from .test_app import FakeController
from .test_telemetry_window import FakeTelemetryController
from sw.tools.test_telemetry_downlink import payload
from sw.tools.telemetry_downlink import phy


def report():
    data = payload()
    return dict(format="EXPERIMENTAL_ATM1_RF", sha256="declared-only", frames=[
        dict(payload_hex=data.hex(), crc16=phy.crc16(data), crc_valid=True,
             first_symbol_sample=123, carrier_offset_hz=503123.25)],
        telemetry=[dict(sequence=9999)], expected=dict(sequence=8888), valid_telemetry_count=9000)


class FakeRFController:
    def __init__(self, emit, log_dir=None):
        self.emit, self.calls, self.log_dir = emit, [], log_dir

    def submit(self, action, **kwargs):
        self.calls.append((action, kwargs))


class RFReportTests(unittest.TestCase):
    def test_only_original_frame_crc_populates_snapshot(self):
        value = validated_snapshots(report())
        self.assertEqual(len(value), 1)
        self.assertEqual(value[0]["sequence"], 7)
        self.assertEqual([value[0][key]["origin"] for key in ("decoded_record", "send_record", "ack_record")], [3, 1, 4])
        bad = report()
        bad["frames"][0]["crc16"] ^= 1
        self.assertEqual(validated_snapshots(bad), [])
        bad["frames"] = []
        self.assertEqual(validated_snapshots(bad), [])

    def test_rejects_usb_or_manifest(self):
        for value in (dict(format="TM1", telemetry=report()["telemetry"]), dict(expected=report())):
            with self.assertRaises(ValueError):
                validated_snapshots(value)


class RFWindowTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.decoder_calls = []
        def decode(raw, **kwargs):
            self.decoder_calls.append((raw, kwargs, threading.get_ident()))
            return report()
        self.app = StationApp(self.root, "sender", controller_factory=FakeController,
                              telemetry_controller_factory=FakeTelemetryController,
                              rf_telemetry_decoder=decode,
                              rf_telemetry_controller_factory=FakeRFController)
        self.app.open_rf_telemetry()
        self.window = self.app.rf_telemetry_window
        self.window.window.withdraw()
        self.temp = tempfile.TemporaryDirectory()

    def tearDown(self):
        if not self.window.closed:
            self.window.close()
            self.window._handle_event(dict(type="closed"))
        self.temp.cleanup()
        dispose_tk_test(self)

    def wait_loaded(self):
        deadline = time.monotonic() + 5
        while self.window._busy and time.monotonic() < deadline:
            self.root.update()
            time.sleep(.01)
        self.assertFalse(self.window._busy)

    def inject(self, value):
        generation = self.window._begin()
        self.window._handle_event(dict(type="loaded", generation=generation,
                                      report=value, mode="json", path="synthetic.json", mtime=100))

    def test_open_and_refresh_are_passive_and_usb_window_stays_independent(self):
        self.app.open_rf_telemetry()
        self.assertIs(self.app.rf_telemetry_window, self.window)
        self.assertEqual(self.app.controller.calls, [("discover", {})])
        self.assertEqual(self.decoder_calls, [])
        self.assertEqual(self.window.controller.calls, [("discover", {})])
        self.app.open_telemetry()
        self.assertEqual(self.app.telemetry_window.controller.calls, [("discover", {})])
        self.window.close()
        self.assertFalse(self.window.closed)
        self.assertEqual(self.window.controller.calls[-1], ("close", {}))
        self.window._handle_event(dict(type="closed"))
        self.assertIsNone(self.app.rf_telemetry_window)
        self.assertFalse(self.app.telemetry_window.closed)

    def test_iq_worker_has_exact_file_sha_and_no_hardware_actions(self):
        raw = b"synthetic offline fixture only"
        path = Path(self.temp.name) / "fixture.iq"
        path.write_bytes(raw)
        self.window.load_iq(str(path))
        self.wait_loaded()
        self.assertEqual(self.decoder_calls[0][0], raw)
        self.assertNotEqual(self.decoder_calls[0][2], threading.get_ident())
        self.assertIn(str(path), self.window.digest_var.get())
        self.assertIn(hashlib.sha256(raw).hexdigest(), self.window.digest_var.get())
        self.assertIn("离线解码", self.window.source_var.get())
        self.assertEqual(self.app.controller.calls, [("discover", {})])

    def test_records_are_independent_and_ack_never_spi(self):
        self.inject(report())
        variables = self.window.record_vars
        self.assertIn("SYNTHETIC", variables["decoded_record"].get())
        self.assertIn("ADC_NORMAL", variables["send_record"].get())
        self.assertIn("UART_NETTEST", variables["ack_record"].get())
        self.assertIn("899999998 Hz", variables["ack_record"].get())
        self.assertIn("非独立 SPI", variables["ack_record"].get())
        self.assertIn("1 帧", self.window.status_var.get())
        self.assertNotIn("9000", self.window.status_var.get())

    def test_corrupt_frame_and_empty_report_clear_old_results(self):
        self.inject(report())
        bad = report()
        bad["frames"][0]["crc16"] ^= 1
        self.inject(bad)
        self.assertEqual(self.window.frames.get_children(), ())
        self.assertIn("0 帧", self.window.status_var.get())
        self.assertTrue(all("未知" in var.get() for var in self.window.record_vars.values()))

    def test_report_import_and_changed_file_refresh_clear_stale_records(self):
        path = Path(self.temp.name) / "report.json"
        path.write_text(json.dumps(report()), encoding="utf-8")
        self.window.load_report(str(path))
        self.wait_loaded()
        self.assertIn("非新采集", self.window.source_var.get())
        self.assertIn("未复核 IQ", self.window.digest_var.get())
        self.assertEqual(len(self.window.snapshots), 1)
        path.write_text('{"format":"EXPERIMENTAL_ATM1_RF","frames":[]}', encoding="utf-8")
        self.window.auto_var.set(True)
        self.window._refresh()
        self.wait_loaded()
        self.assertEqual(self.window.snapshots, [])
        path.unlink()
        self.window._refresh()
        self.assertIn("刷新失败", self.window.status_var.get())

    def test_malformed_file_and_old_worker_event_cannot_restore_results(self):
        self.inject(report())
        path = Path(self.temp.name) / "report.json"
        path.write_text("{bad", encoding="utf-8")
        self.window.load_report(str(path))
        self.wait_loaded()
        self.assertEqual(self.window.snapshots, [])
        self.assertIn("失败", self.window.status_var.get())
        self.window._handle_event(dict(type="loaded", generation=self.window._generation - 1,
                                      report=report(), mode="json", path="old.json", mtime=10))
        self.assertEqual(self.window.snapshots, [])

    def test_main_close_waits_for_rf_worker(self):
        self.app.close()
        self.assertTrue(self.window.closing)
        self.assertFalse(self.window.closed)
        self.assertEqual(self.app.controller.calls[-1], ("close", {}))
        self.app._handle_event(dict(type="closed"))
        self.assertFalse(self.app.closed)
        self.assertIn("RF", self.app.footer_var.get())
        self.window._handle_event(dict(type="closed"))
        self.assertTrue(self.app.closed)

    def test_unexpected_station_exit_closes_file_window_before_root(self):
        self.app._handle_event(dict(type="closed"))
        self.assertTrue(self.window.closing)
        self.assertFalse(self.app.closed)
        self.window._handle_event(dict(type="closed"))
        self.assertTrue(self.window.closed)
        self.assertTrue(self.app.closed)

    def ready(self):
        self.window._handle_event(dict(type="devices", devices=[
            dict(label="接收 SDR", port="FAKE_RX"), dict(label="遥控板", port="FAKE_ADDA"),
            dict(label="备用", port="FAKE_OTHER")]))
        self.window.rx_port_var.set("接收 SDR")
        self.window.adda_port_var.set("遥控板")
        self.window._probe()
        self.probed()
        self.window._connect()
        self.window._handle_event(dict(type="status", state="connected", message="已连接"))

    def probed(self):
        self.window._handle_event(dict(type="probe", binding_token="FAKE_TOKEN", binding={
            "receiver": dict(port="FAKE_RX", description="receiver firmware"),
            "adda": dict(port="FAKE_ADDA", description="ADDA TM1")}))

    def captured(self, value=None, send=True):
        self.window._handle_event(dict(type="capture", report=report() if value is None else value,
            iq_path="FAKE_CAPTURE.iq", report_path="FAKE_REPORT.json", received_at=1793000000,
            capture_seconds=.1048576, send_requested=send))
        self.window._handle_event(dict(type="status", state="connected", message="单次采集完成"))

    def test_two_distinct_ports_probe_then_connect_without_automatic_capture(self):
        self.ready()
        self.assertEqual(self.window.controller.calls, [("discover", {}),
            ("probe", dict(rx_port="FAKE_RX", adda_port="FAKE_ADDA")),
            ("connect", dict(binding_token="FAKE_TOKEN"))])
        self.assertIn("FAKE_ADDA", self.window.binding_var.get())
        self.assertEqual(str(self.window.capture_button.cget("state")), "normal")
        self.assertEqual(self.app.controller.calls, [("discover", {})])

    def test_same_port_and_selection_change_cannot_reuse_binding_token(self):
        self.window._handle_event(dict(type="devices", devices=[dict(label="一个端口", port="FAKE_ONE")]))
        self.window.rx_port_var.set("一个端口")
        self.window.adda_port_var.set("一个端口")
        self.window._probe()
        self.assertEqual(self.window.controller.calls, [("discover", {})])
        self.ready()
        self.window._handle_event(dict(type="status", state="disconnected", message="断开"))
        self.window._probe()
        self.probed()
        self.window.rx_port_var.set("备用")
        self.window._connect()
        self.assertIsNone(self.window.binding_token)
        self.assertEqual(self.window.controller.calls[-1][0], "probe")

    def test_late_probe_after_selection_change_is_rejected_even_if_changed_back(self):
        self.window._handle_event(dict(type="devices", devices=[
            dict(label="接收 SDR", port="FAKE_RX"), dict(label="遥控板", port="FAKE_ADDA")]))
        self.window.rx_port_var.set("接收 SDR")
        self.window.adda_port_var.set("遥控板")
        self.window._probe()
        self.window.rx_port_var.set("遥控板")
        self.window.rx_port_var.set("接收 SDR")
        self.probed()
        self.window._connect()
        self.assertIsNone(self.window.binding_token)
        self.assertEqual(self.window.controller.calls[-1][0], "probe")

    def test_send_once_and_receive_only_are_explicit_and_display_online_evidence(self):
        self.ready()
        for send in (True, False):
            self.window._capture(send)
            self.assertEqual(self.window.controller.calls[-1], ("capture", dict(send=send)))
            self.assertEqual(self.window.snapshots, [])
            self.assertEqual(str(self.window.stop_button.cget("state")), "normal")
            self.window._capture(send)
            self.assertEqual(sum(action == "capture" for action, _ in self.window.controller.calls), 1 if send else 2)
            self.captured(send=send)
            self.assertEqual(len(self.window.snapshots), 1)
            self.assertIn("在线单次 IQ", self.window.source_var.get())
            self.assertIn("在线采集完成时间", self.window.time_var.get())
            self.assertIn("FAKE_CAPTURE.iq", self.window.digest_var.get())
            self.assertIn("接收控制器", self.window.digest_var.get())
            self.assertIn("停发对照" if not send else "请求有限发送", self.window.source_var.get())

    def test_capture_empty_or_bad_crc_never_reuses_old_expected_or_usb_data(self):
        self.ready()
        self.window._capture(True)
        self.captured()
        self.window._capture(False)
        bad = report()
        bad["frames"][0]["crc16"] ^= 1
        self.captured(bad, send=False)
        self.assertEqual(self.window.snapshots, [])
        self.assertIn("0 帧", self.window.status_var.get())
        self.assertTrue(all("未知" in var.get() for var in self.window.record_vars.values()))

    def test_stop_and_error_restore_controls_without_retransmission(self):
        self.ready()
        self.window._capture(True)
        self.window._handle_event(dict(type="status", state="capturing", message="采集中"))
        self.window.stop_button.invoke()
        self.assertEqual(self.window.controller.calls[-1], ("stop", {}))
        self.assertEqual(str(self.window.capture_button.cget("state")), "disabled")
        self.window._handle_event(dict(type="status", state="stopped", message="已停"))
        self.assertEqual(str(self.window.capture_button.cget("state")), "normal")
        self.window._handle_event(dict(type="status", state="error", message="port is busy"))
        self.assertIsNone(self.window.binding_token)
        self.assertIn("关闭", self.window.log_var.get())
        self.assertEqual(str(self.window.connect_button.cget("state")), "disabled")

    def test_stop_remains_pending_when_capture_result_and_connected_status_race(self):
        self.ready()
        self.window._capture(True)
        self.window._stop()
        self.captured()
        self.assertEqual(self.window._pending, "stop")
        self.assertEqual(str(self.window.capture_button.cget("state")), "disabled")
        self.window._handle_event(dict(type="status", state="disconnected", message="已停止并释放"))
        self.assertIsNone(self.window.binding_token)
        self.assertEqual(str(self.window.probe_button.cget("state")), "normal")

    def test_stop_can_interrupt_read_only_probe(self):
        self.window._handle_event(dict(type="devices", devices=[
            dict(label="接收 SDR", port="FAKE_RX"), dict(label="遥控板", port="FAKE_ADDA")]))
        self.window.rx_port_var.set("接收 SDR")
        self.window.adda_port_var.set("遥控板")
        self.window._probe()
        self.assertEqual(str(self.window.stop_button.cget("state")), "normal")
        self.window.stop_button.invoke()
        self.assertEqual(self.window.controller.calls[-1], ("stop", {}))
        self.probed()
        self.window._handle_event(dict(type="status", state="probed", message="旧核验已完成"))
        self.assertIsNone(self.window.binding_token)
        self.assertEqual(self.window._pending, "stop")
        self.window._handle_event(dict(type="status", state="disconnected", message="已停止"))
        self.assertIsNone(self.window.binding_token)

    def test_online_capture_disables_history_refresh_and_ignores_old_worker(self):
        self.ready()
        self.window.report_path = Path(self.temp.name) / "old.json"
        self.window.auto_var.set(True)
        self.window._capture(True)
        self.assertFalse(self.window.auto_var.get())
        self.assertIsNone(self.window.report_path)
        self.window._handle_event(dict(type="loaded", generation=self.window._generation - 1,
                                      report=report(), mode="json", path="old.json", mtime=10))
        self.assertEqual(self.window.snapshots, [])
        self.window.load_report("not_read_during_capture.json")
        self.assertIsNone(self.window.report_path)

    def test_worker_callback_uses_queue_and_close_waits_for_ack(self):
        self.ready()
        self.window._capture(True)
        worker = threading.Thread(target=lambda: self.window.controller.emit(dict(type="capture", report=report(),
            iq_path="FAKE.iq", report_path="FAKE.json", received_at=1793000000, capture_seconds=.1, send_requested=True)))
        worker.start(); worker.join()
        self.assertEqual(self.window.snapshots, [])
        self.window._drain_events()
        self.assertEqual(len(self.window.snapshots), 1)
        self.window.close()
        self.window.close()
        self.assertFalse(self.window.closed)
        self.assertTrue(self.window.window.winfo_exists())
        self.assertEqual(sum(action == "close" for action, _ in self.window.controller.calls), 1)
        self.window._handle_event(dict(type="closed"))
        self.assertIsNone(self.app.rf_telemetry_window)
        self.assertFalse(self.app.closed)

    def test_rf_worker_can_finish_before_station_worker(self):
        self.app.close()
        self.window._handle_event(dict(type="closed"))
        self.assertFalse(self.app.closed)
        self.app._handle_event(dict(type="closed"))
        self.assertTrue(self.app.closed)

    def test_scroll_layout_keeps_all_cards_available_at_minimum_size(self):
        self.inject(report())
        self.window.window.deiconify()
        self.window.window.geometry("950x730")
        self.root.update()
        bounds = self.window.canvas.bbox("all")
        self.assertGreater(bounds[3], self.window.canvas.winfo_height())
        self.window.canvas.yview_moveto(1)
        self.root.update()
        self.assertGreater(self.window.canvas.yview()[0], 0)

    def test_startup_failure_leaves_no_orphan(self):
        self.window.close()
        self.window._handle_event(dict(type="closed"))
        def fail(*args, **kwargs):
            raise RuntimeError("fake RF startup failure")
        self.app.rf_telemetry_controller_factory = fail
        self.app.open_rf_telemetry()
        self.assertIsNone(self.app.rf_telemetry_window)
        self.assertFalse(any(isinstance(widget, tk.Toplevel) for widget in self.root.winfo_children()))
        self.assertIn("fake RF startup failure", self.app.log_text.get("1.0", "end"))


if __name__ == "__main__":
    unittest.main()
