import unittest

from monitor_core import BoardState, LineBuffer, Session, command_bytes, open_serial


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
