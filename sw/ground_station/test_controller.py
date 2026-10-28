"""Controller fault tests with in-memory consoles; no hardware or serial use."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from . import controller
from .protocol import MessageTracker, encode_message, parse_message


class ControllerFaultTests(unittest.TestCase):
    def test_reconnect_preserves_existing_private_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            station = self.bare(directory)
            station.console = None
            station.record = Mock()
            station.status = Mock()
            board = Mock()
            board.info = {'port': 'TEST'}
            created = set()
            def run(command):
                target = command.split()[-1]
                if target in created and not command.startswith('mkdir -p '):
                    raise RuntimeError('File exists')
                created.add(target)
                return ''
            board.run.side_effect = run
            station.factory = Mock(return_value=board)
            station._connect('TEST')
            station.console = None
            station._connect('TEST')
            self.assertIs(station.console, board)
            self.assertEqual(created, {'/tmp/fake_station'})

    def bare(self, directory, role='receiver'):
        station = controller.StationController.__new__(controller.StationController)
        station.role = role
        station.console = Mock()
        station.console.phy, station.console.tx, station.console.rx = '/phy', '/tx', '/rx'
        station.relay = None
        station.active = True
        station.writer = None
        station.guard = None
        station.pending_guard = None
        station.log_dir = Path(directory)
        station.remote = '/tmp/fake_station'
        station.capture_index = 0
        station.capture_owned = None
        station.tracker = MessageTracker()
        station.settings = {'expected_rf_mhz': 1000.5, 'rx_lo_hz_readback': 1000750000}
        station.interrupt = controller.threading.Event()
        station.event = Mock()
        return station

    def test_stop_attempts_owned_writer_cleanup_despite_mute_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            station = self.bare(directory, 'sender')
            station.writer = (123, '999')
            station.console.mute.side_effect = RuntimeError('mute readback failed')
            station.console.read.return_value = '0'
            station.console.run.return_value = ''
            with self.assertRaises(RuntimeError):
                station._stop()
            commands = [call.args[0] for call in station.console.run.call_args_list]
            self.assertTrue(any('kill -INT 123' in command and '999' in command for command in commands))
            self.assertFalse(station.active)

    def test_stop_recovers_writer_ownership_after_lost_start_reply(self):
        with tempfile.TemporaryDirectory() as directory:
            station = self.bare(directory, 'sender')
            station.console.run.side_effect = ['123 999', '', '']
            station.console.read.return_value = '0'
            station._stop()
            commands = [call.args[0] for call in station.console.run.call_args_list]
            self.assertTrue(any('kill -INT 123' in command and '999' in command for command in commands))
            self.assertIsNone(station.writer)

    def test_known_writer_cleanup_does_not_depend_on_reading_owned_file(self):
        with tempfile.TemporaryDirectory() as directory:
            station = self.bare(directory, 'sender')
            station.writer = (123, '999')
            def run(command):
                if 'cat ' + station.remote + '/owned' in command:
                    raise RuntimeError('owned read unavailable')
                return ''
            station.console.run.side_effect = run
            station.console.read.return_value = '0'
            station._stop()
            self.assertTrue(any('kill -INT 123' in call.args[0]
                                for call in station.console.run.call_args_list))
            self.assertIsNone(station.writer)

    def test_lost_guard_reply_is_disarmed_and_owned_guard_is_terminated(self):
        with tempfile.TemporaryDirectory() as directory:
            station = self.bare(directory, 'sender')
            lease = '/tmp/fake_station/unique.guard.lease'
            guard_owned = '/tmp/fake_station/unique.guard.owned'
            station.pending_guard = (lease, guard_owned)
            station.console.read.return_value = '0'
            station.console.run.side_effect = lambda command: '456 888' if 'cat ' + guard_owned in command else ''
            station._stop()
            commands = [call.args[0] for call in station.console.run.call_args_list]
            self.assertIn('echo 0 > ' + lease, commands)
            self.assertTrue(any('kill -TERM 456' in command and '888' in command for command in commands))
            self.assertIsNone(station.pending_guard)
            self.assertIsNone(station.guard)

    def test_missing_or_dead_guard_prevents_lease_renewal(self):
        with tempfile.TemporaryDirectory() as directory:
            station = self.bare(directory, 'sender')
            station.writer = (123, '999')
            station._set_lease = Mock()
            with self.assertRaisesRegex(RuntimeError, '保护进程'):
                station._renew()
            station._set_lease.assert_not_called()
            station.guard = (456, '888', '/tmp/fake_station/unique.lease')
            station.console.run.side_effect = ['', RuntimeError('guard has exited')]
            with self.assertRaisesRegex(RuntimeError, 'guard has exited'):
                station._renew()
            station._set_lease.assert_not_called()

    def test_guard_remains_armed_when_mute_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            station = self.bare(directory, 'sender')
            station.guard = (456, '888', '/tmp/fake_station/unique.lease')
            station.console.mute.side_effect = RuntimeError('mute failed')
            station.console.run.return_value = ''
            station.console.read.return_value = '0'
            with self.assertRaisesRegex(RuntimeError, 'mute failed'):
                station._stop()
            self.assertIsNotNone(station.guard)
            self.assertFalse(any('echo 0 >' in call.args[0]
                                 for call in station.console.run.call_args_list))

    def test_urgent_stop_and_close_survive_full_action_queue(self):
        with tempfile.TemporaryDirectory() as directory:
            station = self.bare(directory)
            station.closing = False
            station.commands = controller.queue.Queue(maxsize=1)
            station.urgent = controller.queue.Queue()
            station.commands.put(('receive', {}))
            station.submit('stop')
            station.submit('close')
            self.assertTrue(station.interrupt.is_set())
            self.assertEqual(station.urgent.get_nowait(), ('stop', {}))
            self.assertEqual(station.urgent.get_nowait(), ('close', {}))

    def test_out_of_range_configuration_is_not_written(self):
        cases = [('sender', {'tx_lo_mhz': 901}),
                 ('sender', {'tx_atten_db': 49}),
                 ('receiver', {'rx_gain_db': float('nan')}),
                 ('receiver', {'expected_rf_mhz': 1001}),
                 ('receiver', {'rx_gain_db': 31})]
        for role, settings in cases:
            with self.subTest(role=role, settings=settings), tempfile.TemporaryDirectory() as directory:
                station = self.bare(directory, role)
                station.configured = True
                station.console.run.return_value = ''
                station.console.read.return_value = '0'
                with self.assertRaises(ValueError):
                    station._configure(**settings)
                self.assertFalse(station.configured)
                station.console.write.assert_not_called()

    def test_receiver_scan_layout_is_verified_before_ready(self):
        with tempfile.TemporaryDirectory() as directory:
            station = self.bare(directory)
            station.console.write.side_effect = lambda path, value, *args: str(value)
            station.console.read.return_value = 'le:S16/16>>0'
            with self.assertRaisesRegex(RuntimeError, '格式不匹配'):
                station._configure()
            self.assertFalse(station.configured)

    def test_receiver_connect_needs_no_relay_and_sender_rejects_same_port(self):
        with tempfile.TemporaryDirectory() as directory:
            station = self.bare(directory)
            board = station.console
            station.console = None
            station.factory = Mock(return_value=board)
            station.relay_factory = Mock()
            station.record = Mock()
            station.status = Mock()
            station._connect('COM_FAKE_RX')
            station.relay_factory.assert_not_called()
            board.require_idle.assert_called_once()
            self.assertIs(station.console, board)
            station.role = 'sender'
            station.console = None
            station.factory.reset_mock()
            with self.assertRaises(ValueError):
                station._connect('COM_FAKE_TX', relay_port='COM_FAKE_TX')
            station.factory.assert_not_called()

    def test_rejected_clipped_capture_does_not_poison_duplicate_history(self):
        with tempfile.TemporaryDirectory() as directory:
            station = self.bare(directory)
            raw = bytes(controller.CAPTURE_SAMPLES * 4)
            station.console.read.side_effect = ['1', '0']
            station.console.download.return_value = raw
            message = parse_message(encode_message('hello', '0123abcd', 0))
            report = dict(messages=[message], clip_components=1, rms_codes=100,
                          carrier_offset_hz=-250000, crc_rejected_frames=0)
            with patch.object(controller, 'decode_capture', return_value=report) as decoder:
                with self.assertRaises(RuntimeError):
                    station._capture()
            decoder.assert_called_once_with(raw, expected_offset_hz=-250000)
            self.assertEqual(len(station.tracker), 0)
            self.assertFalse(any(call.args[0] == 'rx' for call in station.event.call_args_list))

    def test_receiver_uses_only_raw_iq_local_lo_and_persists_raw_capture(self):
        with tempfile.TemporaryDirectory() as directory:
            station = self.bare(directory)
            raw = bytes(controller.CAPTURE_SAMPLES * 4)
            station.console.read.side_effect = ['1', '0']
            station.console.download.return_value = raw
            message = parse_message(encode_message('independent RX', '0123abcd', 0))
            report = dict(messages=[message, dict(message)], clip_components=0, rms_codes=100,
                          carrier_offset_hz=-249990, crc_rejected_frames=2)
            with patch.object(controller, 'decode_capture', return_value=report) as decoder:
                station._capture()
            decoder.assert_called_once_with(raw, expected_offset_hz=-250000)
            self.assertEqual((Path(directory) / 'rx_000001.bin').read_bytes(), raw)
            rx = next(call for call in station.event.call_args_list if call.args[0] == 'rx')
            self.assertEqual([item['duplicate'] for item in rx.kwargs['messages']], [False, True])
            self.assertEqual(rx.kwargs['carrier_hz'], 1000500010)
            self.assertTrue((Path(directory) / 'rx_000001.json').is_file())


if __name__ == '__main__':
    unittest.main()
