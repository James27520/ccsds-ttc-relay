import unittest
from pathlib import Path
import tempfile

from monitor_core import BoardState, CommandRecord, LineBuffer, Session, command_bytes, open_serial


class FakeSerial:
    """Offline only: accepts no OS handles and never enumerates devices."""
    def __init__(self, **options):
        self.options = options
        self.port = options["port"]
        self.dtr = True
        self.rts = True
        self.opened = False
        self.writes = []
        self.incoming = bytearray()
        self.partial = False

    def open(self):
        assert self.options["port"] is None
        assert self.dtr is False and self.rts is False
        assert not self.options["rtscts"] and not self.options["dsrdtr"]
        assert (self.options["bytesize"], self.options["parity"], self.options["stopbits"]) == (8, "N", 1)
        self.opened = True

    def close(self):
        self.opened = False

    def write(self, packet):
        assert self.opened
        self.writes.append(packet)
        return len(packet) - 1 if self.partial else len(packet)

    def read(self, count):
        result = bytes(self.incoming[:count])
        del self.incoming[:count]
        return result


class ProtocolTests(unittest.TestCase):
    def test_real_adc_trace_preserves_decode_and_confirmation(self):
        board = BoardState()
        # Exact lines from closed_loop_run1/adda.txt, including duplicate frames.
        lines = [
            "WAVEFORM_DECODE source=ADC_NORMAL epoch=16 rc=1 elapsed_ms=277",
            "DECODED source=ADC_NORMAL rx=900 tx=1000 air_seq=80 rc=0",
            "COMMAND source=ADC_NORMAL rx=900 tx=1000 air_seq=80 rc=0",
            "UDP_SEND_ATTEMPT source=ADC_NORMAL rx=900 tx=1000 air_seq=80 rc=0",
        ]
        for line in lines:
            board.receive(line)
        self.assertEqual(board.last_decoded, CommandRecord("ADC_NORMAL", 900, 1000, 80))
        self.assertIsNone(board.last_ack)
        board.receive("ACK source=ADC_NORMAL rx=900 tx=1000 air_seq=80 rc=0")
        confirmed = board.last_ack
        self.assertEqual(confirmed, board.last_decoded)
        self.assertIsNone(confirmed.udp_seq)
        for line in [
            "CAPTURE state=1 valid=0 error=OK epoch=17 copied_words=65536",
            "WAVEFORM_DECODE source=ADC_NORMAL epoch=17 rc=1 elapsed_ms=278",
            "DECODED source=ADC_NORMAL rx=900 tx=1000 air_seq=80 rc=0",
            "COMMAND source=ADC_NORMAL rx=900 tx=1000 air_seq=80 rc=1",
            "CAPTURE state=6 valid=1 error=OK epoch=17 copied_words=65536",
        ]:
            board.receive(line)
        self.assertIs(board.last_ack, confirmed)
        board.receive("DECODED source=ADC_NORMAL rx=901 tx=1000 air_seq=81 rc=0")
        self.assertEqual(board.last_decoded.air_seq, 81)
        self.assertEqual(board.last_ack.air_seq, 80)

    def test_only_complete_successful_ack_updates_confirmation(self):
        board = BoardState()
        good = "ACK source=UART_NETTEST rx=100 tx=2450 air_seq=0 rc=0"
        board.receive(good)
        confirmed = board.last_ack
        self.assertEqual(confirmed, CommandRecord("UART_NETTEST", 100, 2450, 0))
        for line in [
            good.replace("rc=0", "rc=-4"), good.replace("rc=0", "rc=1"),
            "ACK rc=0", good.replace("air_seq=0 ", ""),
            good.replace("rx=100", "rx=6001"), good.replace("air_seq=0", "air_seq=256"),
            good.replace("UART_NETTEST", "SYNTHETIC"), good + " garbage",
            "ACK_TIMEOUT not marked applied; remote state not confirmed",
        ]:
            with self.subTest(line=line):
                board.receive(line)
                self.assertIs(board.last_ack, confirmed)
        board.receive(good)
        self.assertEqual(board.last_ack, confirmed)  # duplicate contains no new transaction ID
        board.receive("DECODED source=ADC_NORMAL rx=901 tx=1000 air_seq=81 rc=-4")
        self.assertIsNone(board.last_decoded)
        self.assertNotIn("解出有效帧", board.last_result)
        board.receive("DECODED source=ADC_NORMAL rx=901 rc=0")
        self.assertIsNone(board.last_decoded)
        self.assertNotIn("解出有效帧", board.last_result)

    def test_history_reset_and_restart(self):
        board = BoardState()
        for restart in (None,
                        "BOOT ADDA M2 candidate UART115200/8N1 capture=ENABLED",
                        "ADDA PS control core: network=OFF armed=OFF; selftest is local only"):
            board.receive("DECODED source=ADC_NORMAL rx=900 tx=1000 air_seq=80 rc=0")
            board.receive("ACK source=ADC_NORMAL rx=900 tx=1000 air_seq=80 rc=0")
            if restart is None:
                board.reset()  # GUI uses the same reset on disconnect.
            else:
                board.receive(restart)
            self.assertIsNone(board.last_decoded)
            self.assertIsNone(board.last_ack)

    def test_nettest_boundaries_and_defaults(self):
        self.assertEqual(command_bytes("nettest", ("100", "2450", "0", "0", "89")), b"nettest 100 2450 0 0 89\r\n")
        self.assertEqual(command_bytes("nettest", ("70", "6000", "255", "76", "89")), b"nettest 70 6000 255 76 89\r\n")

    def test_injection_unicode_and_illegal_ranges_rejected(self):
        defaults = ["100", "2450", "0", "0", "89"]
        bad_values = ((0, "69"), (0, "6001"), (0, "100\r\narm on"), (0, "100\n"),
                      (0, "１００"), (0, "+100"), (0, "1e2"), (0, "100.5"),
                      (0, " 100"), (1, "0"), (2, "256"), (3, "77"), (4, "90"), (4, "-1"))
        for index, value in bad_values:
            fields = defaults.copy()
            fields[index] = value
            with self.subTest(index=index, value=value), self.assertRaises(ValueError):
                command_bytes("nettest", fields)
        for command in ("network restart", "capture", "status\narm on"):
            with self.assertRaises(ValueError):
                command_bytes(command)

    def test_platform_capture_commands_and_argument_validation(self):
        for command in ("network on", "network off", "waveformtest", "capture cancel", "decode", "auto on", "auto off"):
            self.assertEqual(command_bytes(command), (command+"\r\n").encode("ascii"))
        for mode in ("training", "normal"):
            for channel in ("0", "1"):
                for k in ("0", "1", "2", "3"):
                    self.assertEqual(command_bytes("capture", (mode, channel, k)), f"capture {mode} {channel} {k}\r\n".encode("ascii"))
        for values in (("training\narm on", "0", "0"), ("training", "2", "0"),
                       ("normal", "0", "4"), ("normal", "0", "-1"),
                       ("normal", "１", "0"), ("normal", "0\r", "0")):
            with self.assertRaises(ValueError):
                command_bytes("capture", values)

    def test_open_quiet_dtr_rts_before_open(self):
        session = Session()
        session.connect(FakeSerial, "COM99", 115200)
        port = session.serial
        self.assertEqual(port.writes, [])
        self.assertTrue(port.opened)
        session.send("status")
        self.assertEqual(port.writes, [b"status\r\n"])
        session.close()
        self.assertFalse(port.opened)
        self.assertEqual(port.writes, [b"status\r\n"])

    def test_partial_write_disconnects_and_invalid_input_never_writes(self):
        session = Session()
        session.connect(FakeSerial, "COM99", 115200)
        port = session.serial
        with self.assertRaises(ValueError):
            session.send("nettest", ("100\n", "2450", "0", "0", "89"))
        self.assertEqual(port.writes, [])
        port.partial = True
        with self.assertRaises(OSError):
            session.send("status")
        self.assertIsNone(session.serial)
        self.assertFalse(port.opened)

    def test_non_com_ports_rejected_before_factory(self):
        def forbidden(**_):
            self.fail("factory must not be called")
        for port in ("COM0", "COM1\n", "socket://host", "COM1;arm on", ""):
            with self.assertRaises(ValueError):
                open_serial(forbidden, port)

    def test_chunking_and_overlength_not_interpreted_as_status(self):
        buffer = LineBuffer(limit=32)
        self.assertEqual(buffer.feed(b"SELFTEST_"), [])
        self.assertEqual(buffer.feed(b"PASS\r\nDISARMED\n"), ["SELFTEST_PASS", "DISARMED"])
        lines = buffer.feed(b"x" * 40 + b"STATUS network=1\nDISARMED\n")
        self.assertTrue(lines[0].startswith("[HOST]"))
        self.assertEqual(lines[1:], ["DISARMED"])

    def test_confirmations_and_source_separation(self):
        board = BoardState()
        self.assertIsNone(board.network)
        self.assertIsNone(board.armed)
        board.receive("STATUS network=1 armed=0 decoded=3 applied=0 pending=0 retries=0 failures=0 gain=0 att=89")
        self.assertEqual((board.network, board.armed), (1, 0))
        board.receive("SELFTEST_PASS 3 external digital-frame vectors source=SYNTHETIC no UDP attempted")
        self.assertEqual(board.origin, "SYNTHETIC")
        self.assertIn("不代表真实ADC", board.last_result)
        board.receive("UDP_SEND_ATTEMPT source=UART_NETTEST rx=100 tx=2450 air_seq=0 rc=0")
        self.assertEqual(board.origin, "UART_NETTEST")
        self.assertIn("等待匹配ACK", board.last_result)
        self.assertEqual(board.counters["applied"], 0)
        board.receive("ACK source=UART_NETTEST rx=100 tx=2450 air_seq=0 rc=-4")
        self.assertIn("未通过", board.last_result)
        board.receive("ACK source=UART_NETTEST rx=100 tx=2450 air_seq=0 rc=0")
        self.assertIn("已确认", board.last_result)
        board.receive("DECODED source=ADC_NORMAL rx=100 tx=2450 air_seq=0 rc=0")
        self.assertEqual(board.origin, "ADC_NORMAL")
        board.receive("DECODED source=ADC_TEST rx=100 tx=2450 air_seq=0 rc=0")
        self.assertEqual(board.origin, "ADC_TEST")
        board.receive("DISARMED")
        self.assertEqual(board.armed, 0)

    def test_platform_status_is_reported_not_optimistic(self):
        board = BoardState()
        board.receive("BOOT ADDA PS candidate UART115200/8N1 capture=DISABLED; selftest/waveformtest local SYNTHETIC")
        self.assertFalse(board.capture_enabled)
        board.receive("NETWORK_ON local=169.254.9.11:5006 peer=169.254.9.10:5005 MAC=02:00:00:00:09:11; no RF_SET requested")
        self.assertIsNone(board.network)  # network initialization != PHY ready
        board.receive("CONTROLLER auto=0 capture_state=4 capture_valid=0 consumed=0")
        self.assertEqual((board.automatic, board.capture_state, board.capture_valid), (0, 4, 0))
        board.receive("CAPTURE state=6 valid=1 error=OK epoch=4 copied_words=65536")
        self.assertEqual((board.capture_state, board.capture_valid), (6, 1))
        board.receive("PATTERN_PASS source=ADC_TEST count=131072 transitions=131071 errors=0 zero_states=0 invalid=0 toggle=0x3fff first=0x1234 last=0x2345")
        self.assertEqual(board.origin, "ADC_TEST")
        self.assertIn("不代表模拟", board.last_result)
        board.receive("WAVEFORMTEST_PASS source=SYNTHETIC samples=131072 rx=100 tx=2450 seq=0 elapsed_ms=30 no_UDP=1")
        self.assertEqual(board.origin, "SYNTHETIC")
        self.assertIn("未发UDP", board.last_result)
        board.receive("AUTO_ON validated ADC_NORMAL captures only")
        self.assertEqual((board.armed, board.automatic), (1, 1))
        board.receive("NETWORK_OFF auto=OFF armed=OFF")
        self.assertEqual((board.network, board.armed, board.automatic), (0, 0, 0))
        board.receive("CLI_RESULT rc=-2")
        self.assertIn("未成功", board.last_result)


class HiddenGuiTests(unittest.TestCase):
    @staticmethod
    def forbidden_enumeration():
        raise AssertionError("Offline GUI tests must not enumerate hardware")

    def test_gui_keeps_confirmation_during_capture_and_resets_on_disconnect(self):
        from adda_monitor import Monitor
        app = Monitor(serial_factory=FakeSerial, enumerate_ports=self.forbidden_enumeration, hidden=True)
        try:
            app.port.set("COM99")
            app.toggle_connection()
            port = app.session.serial

            def receive(*lines):
                port.incoming.extend(("\r\n".join(lines) + "\r\n").encode("ascii"))
                app.after_cancel(app.after_id)
                app._poll()

            receive("DECODED source=ADC_NORMAL rx=900 tx=1000 air_seq=80 rc=0",
                    "ACK source=ADC_NORMAL rx=900 tx=1000 air_seq=80 rc=0")
            confirmed = app.confirmed.get()
            self.assertIn("RX 900 MHz / TX 1000 MHz", confirmed)
            self.assertIn("空口序号 80", confirmed)
            self.assertIn("ADC_NORMAL", confirmed)
            self.assertNotIn("UDP序号", confirmed)
            receive("CAPTURE state=1 valid=0 error=OK epoch=18 copied_words=65536",
                    "DECODED source=ADC_NORMAL rx=901 tx=1000 air_seq=81 rc=0",
                    "ACK source=ADC_NORMAL rx=901 tx=1000 air_seq=81 rc=-4",
                    "COMMAND source=ADC_NORMAL rx=900 tx=1000 air_seq=80 rc=1")
            self.assertEqual(app.confirmed.get(), confirmed)
            self.assertIn("RX 901 MHz / TX 1000 MHz", app.decoded.get())
            self.assertIn("空口序号 81", app.decoded.get())
            app.toggle_connection()
            self.assertIsNone(app.state.last_ack)
            self.assertIsNone(app.state.last_decoded)
            self.assertIn("尚无", app.confirmed.get())
            self.assertIn("尚无", app.decoded.get())
            self.assertEqual(port.writes, [])
            app.toggle_connection()
            self.assertIn("尚无", app.confirmed.get())
            self.assertEqual(app.session.serial.writes, [])
        finally:
            app.shutdown()

    def test_gui_full_session_log_survives_display_trimming(self):
        from adda_monitor import Monitor
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "session.log"
            app = Monitor(serial_factory=FakeSerial, enumerate_ports=self.forbidden_enumeration,
                          hidden=True, log_file=path)
            try:
                app.port.set("COM99")
                app.toggle_connection()
                port = app.session.serial
                app.send("status")
                port.incoming.extend(b"DECODED source=ADC_NORMAL rx=900 tx=1000 air_seq=80 rc=0\r\n")
                app.after_cancel(app.after_id)
                app._poll()
                # The file must retain older lines even when the widget trims.
                for i in range(3005):
                    app.log("HOST", f"offline-log-line-{i:04d}")
                visible = app.logs.get("1.0", "end")
                self.assertNotIn("offline-log-line-0000", visible)
                self.assertIn("offline-log-line-3004", visible)
                # Line-buffered output is available before shutdown as well.
                self.assertIn("offline-log-line-3004", path.read_text(encoding="utf-8"))
                app.toggle_connection()
                self.assertEqual(port.writes, [b"status\r\n"])
            finally:
                app.shutdown()
            saved = path.read_text(encoding="utf-8")
            self.assertIn("[TX] status\n", saved)
            self.assertIn("[RX] DECODED source=ADC_NORMAL rx=900 tx=1000 air_seq=80 rc=0\n", saved)
            self.assertIn("串口已打开", saved)
            self.assertIn("串口已断开", saved)
            for i in range(3005):
                self.assertIn(f"[HOST] offline-log-line-{i:04d}\n", saved)
            with self.assertRaises(FileExistsError):
                Monitor(serial_factory=FakeSerial, enumerate_ports=self.forbidden_enumeration,
                        hidden=True, log_file=path)
            self.assertEqual(path.read_text(encoding="utf-8"), saved)

    def test_gui_fake_connect_has_no_automatic_write(self):
        from adda_monitor import Monitor

        def no_enumeration():
            self.fail("GUI selftest must not enumerate ports")

        app = Monitor(serial_factory=FakeSerial, enumerate_ports=no_enumeration, hidden=True)
        try:
            app.update_idletasks()
            self.assertEqual(app.state.origin, "UNKNOWN")
            self.assertEqual(tuple(v.get() for v in app.fields), ("100", "2450", "0", "0", "89"))
            app.port.set("COM99")
            app.toggle_connection()
            port = app.session.serial
            self.assertEqual(port.writes, [])
            self.assertIsNone(app.state.armed)
            app.send("selftest")
            self.assertEqual(port.writes, [b"selftest\r\n"])
            port.incoming.extend(b"SELFTEST_PASS 3 vectors source=SYNTHETIC no UDP attempted\r\n")
            app.after_cancel(app.after_id)
            app._poll()
            self.assertEqual(app.state.origin, "SYNTHETIC")
            app.nettest_button.invoke()
            self.assertEqual(port.writes[-1], b"nettest 100 2450 0 0 89\r\n")
            app.capture_button.invoke()
            self.assertEqual(port.writes[-1], b"capture training 0 0\r\n")
            app.toggle_connection()
            self.assertIsNone(app.session.serial)
            self.assertEqual(len(port.writes), 3)
            self.assertIn("未知", app.board_status.get())
        finally:
            app.shutdown()


if __name__ == "__main__":
    unittest.main()
