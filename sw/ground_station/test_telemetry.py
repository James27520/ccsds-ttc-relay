"""TM1 corrupt/partial records and read-only connection lifecycle checks."""
import binascii
from pathlib import Path
import queue
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from .telemetry import TM1_FIELDS, TelemetryController, TelemetrySerial, parse_tm1


def wire(**changes):
    values = dict.fromkeys(TM1_FIELDS, 0)
    values.update(changes)
    prefix = 'TM1 '+' '.join(f'{key}={values[key]}' for key in TM1_FIELDS)
    return prefix+f' crc16={binascii.crc_hqx(prefix.encode(), 0xffff):04X}\r\n'


class TelemetryParserTests(unittest.TestCase):
    def test_matches_c_initial_known_crc_and_preserves_zero_validity(self):
        line = wire(uptime_ms=123)
        self.assertTrue(line.endswith('crc16=F8E2\r\n'))
        values = parse_tm1(line)
        self.assertEqual(values['uptime_ms'], 123)
        self.assertEqual(values['a_valid'], 0)

    def test_checksum_truncation_fields_duplicates_and_version_rejected(self):
        line = wire(uptime_ms=123)
        for bad in (line.replace('123', '124'), line[:-9], line.replace('TM1', 'TM2'),
                    line.replace(' events=0', ''), line.replace('events=0', 'uptime_ms=0'),
                    ' '+line, line+'garbage', 'X'*1024):
            with self.subTest(bad=bad[:30]), self.assertRaises(ValueError):
                parse_tm1(bad)

    def test_valid_crc_cannot_smuggle_impossible_semantics_or_ranges(self):
        for changes in ({'spi_valid': 1}, {'a_valid': 1, 'a_origin': 4, 'a_rc': -1},
                        {'d_valid': 1}, {'network': 2}, {'uptime_ms': -1},
                        {'d_air_seq': 256}, {'a_rx_hz': 1 << 64}, {'s_rc': -(1 << 31)-1}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                parse_tm1(wire(**changes))

    def test_independent_stage_sources_and_full_ack_hz_survive(self):
        values = parse_tm1(wire(d_valid=1, d_origin=3, d_rx_mhz=100,
            s_valid=1, s_origin=4, s_udp_seq=22, s_count=2, s_rc=-7,
            a_valid=1, a_origin=1, a_udp_seq=21, a_rx_hz=900000001, a_tx_hz=1000999999))
        self.assertEqual((values['d_origin'], values['s_origin'], values['a_origin']), (3, 4, 1))
        self.assertEqual(values['a_tx_hz'], 1000999999)
        self.assertEqual(values['s_rc'], -7)

    def test_query_requires_one_complete_tm1_and_rejects_rf_commands(self):
        console = TelemetrySerial.__new__(TelemetrySerial)
        with self.assertRaises(ValueError):
            console._command('nettest 900 1000 1 0 89')
        console._command = Mock(return_value=[wire(), wire()])
        with self.assertRaises(RuntimeError):
            console.query()
        console._command.return_value = ['telemetry', wire(), 'CLI_RESULT rc=0']
        self.assertEqual(console.query()['spi_valid'], 0)


class TelemetryWorkerTests(unittest.TestCase):
    def wait(self, messages, kind):
        for _ in range(30):
            event = messages.get(timeout=2)
            if event['type'] == kind:
                return event
        self.fail('Expected event absent: '+kind)

    def test_no_startup_connection_and_read_only_query_disconnect_close(self):
        messages = queue.Queue()
        board = Mock()
        board.query.return_value = parse_tm1(wire())
        factory = Mock(return_value=board)
        with tempfile.TemporaryDirectory() as directory:
            worker = TelemetryController(messages.put, Path(directory)/'session', serial_factory=factory)
            try:
                factory.assert_not_called()
                worker.submit('connect', port='FAKE')
                self.assertEqual(self.wait(messages, 'telemetry')['snapshot']['a_valid'], 0)
                worker.submit('query')
                self.wait(messages, 'telemetry')
                worker.submit('disconnect')
                self.assertEqual(self.wait(messages, 'status')['state'], 'disconnected')
                board.close.assert_called_once()
                self.assertEqual({call[0] for call in board.mock_calls}, {'query', 'close'})
            finally:
                worker.submit('close')
                worker.worker.join(3)
            self.assertFalse(worker.worker.is_alive())
            self.assertEqual(self.wait(messages, 'closed')['type'], 'closed')

    def test_bad_query_never_emits_snapshot_and_releases_port(self):
        messages = queue.Queue()
        board = Mock()
        board.query.side_effect = ValueError('CRC mismatch')
        with tempfile.TemporaryDirectory() as directory:
            worker = TelemetryController(messages.put, Path(directory)/'session', serial_factory=Mock(return_value=board))
            try:
                worker.submit('connect', port='FAKE')
                self.assertEqual(self.wait(messages, 'status')['state'], 'error')
                board.close.assert_called_once()
                self.assertTrue(messages.empty())
            finally:
                worker.submit('close');worker.worker.join(3)

    def test_close_error_still_acknowledges_worker_termination(self):
        messages = queue.Queue()
        board = Mock()
        board.query.return_value = parse_tm1(wire())
        board.close.side_effect = OSError('removed USB')
        with tempfile.TemporaryDirectory() as directory:
            worker = TelemetryController(messages.put, Path(directory)/'session', serial_factory=Mock(return_value=board))
            worker.submit('connect', port='FAKE')
            self.wait(messages, 'telemetry')
            worker.submit('close');worker.worker.join(3)
            self.assertFalse(worker.worker.is_alive())
            self.assertEqual(self.wait(messages, 'closed')['type'], 'closed')

    def test_serial_and_journal_failure_cannot_suppress_cleanup_acknowledgement(self):
        worker = TelemetryController.__new__(TelemetryController)
        worker.closing = threading.Event()
        worker.closing.set()
        worker.serial = Mock()
        connection = worker.serial
        connection.close.side_effect = OSError('USB removed')
        worker.record = Mock(side_effect=OSError('journal unavailable'))
        worker.emit, worker.journal = Mock(), Mock()
        with self.assertRaisesRegex(OSError, 'journal unavailable'):
            worker._work()
        self.assertIsNone(worker.serial)
        connection.close.assert_called_once()
        worker.emit.assert_called_once_with(dict(type='closed'))
        worker.journal.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
