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
                              rf_telemetry_decoder=decode)
        self.app.open_rf_telemetry()
        self.window = self.app.rf_telemetry_window
        self.window.window.withdraw()
        self.temp = tempfile.TemporaryDirectory()

    def tearDown(self):
        if not self.window.closed:
            self.window.close()
        try:
            for callback in self.root.tk.call("after", "info"):
                self.root.after_cancel(callback)
            self.root.destroy()
        except tk.TclError:
            pass
        self.temp.cleanup()

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
        self.app.open_telemetry()
        self.assertEqual(self.app.telemetry_window.controller.calls, [("discover", {})])
        self.window.close()
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

    def test_main_close_closes_file_viewer_without_waiting_on_worker(self):
        self.app.close()
        self.assertTrue(self.window.closed)
        self.assertEqual(self.app.controller.calls[-1], ("close", {}))
        self.app._handle_event(dict(type="closed"))
        self.assertTrue(self.app.closed)

    def test_unexpected_station_exit_closes_file_window_before_root(self):
        self.app._handle_event(dict(type="closed"))
        self.assertTrue(self.window.closed)
        self.assertTrue(self.app.closed)


if __name__ == "__main__":
    unittest.main()
