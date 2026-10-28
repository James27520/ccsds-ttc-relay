"""Controller fault tests with in-memory consoles; no hardware or serial use."""
from pathlib import Path
import queue
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from . import controller
from .protocol import MessageTracker, encode_message, parse_message
from .test_relay import GOOD_DIAGNOSTICS, GOOD_STATUS, relay_without_serial


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


class ReadRelayWorkerTests(unittest.TestCase):
    """Exercise action dispatch, real diagnostic parsing, and the existing fault stop."""

    def wait_for(self, messages, kind, state=None):
        deadline = time.monotonic() + 3
        seen = []
        while time.monotonic() < deadline:
            try:
                event = messages.get(timeout=max(.01, deadline - time.monotonic()))
            except queue.Empty:
                break
            seen.append(event)
            if event['type'] == kind and (state is None or event.get('state') == state):
                return event, seen
        self.fail(f'No {kind}/{state} event; received {seen}')

    def fake_source(self):
        source = Mock()
        source.phy, source.tx, source.rx = '/phy', '/tx', '/rx'
        source.read.return_value = '0'
        source.run.return_value = ''
        return source

    def test_read_relay_uses_only_status_and_rfdiag_and_preserves_running_settings(self):
        messages = queue.Queue()
        relay = relay_without_serial()
        relay.close = Mock()
        status = GOOD_STATUS.replace('rxgain=0', 'rxgain=30')
        diagnostics = GOOD_DIAGNOSTICS.replace('tx_hz=1000000000', 'tx_hz=1001000000')
        relay.run.side_effect = lambda command: {'status': status, 'rfdiag': diagnostics}[command]
        source = self.fake_source()
        with tempfile.TemporaryDirectory() as directory:
            station = controller.StationController('sender', messages.put, Path(directory) / 'session')
            try:
                station.console, station.relay = source, relay
                station.settings = {'unchanged_setting': 123}
                station.configured = station.active = True
                station.last_lease = time.monotonic()
                station.submit('read_relay')
                event, _ = self.wait_for(messages, 'relay_telemetry')
                self.assertEqual([call.args[0] for call in relay.run.call_args_list], ['status', 'rfdiag'])
                self.assertEqual(source.mock_calls, [])
                self.assertEqual(station.settings, {'unchanged_setting': 123})
                self.assertTrue(station.active)
                self.assertTrue(station.configured)
                self.assertEqual(event['values']['relay_tx_hz_readback'], 1001000000)
                self.assertEqual(event['values']['relay_mode'], 2)
                self.assertGreater(event['received_at'], 0)
            finally:
                station.submit('close')
                station.worker.join(3)
                self.assertFalse(station.worker.is_alive())

    def test_missing_relay_and_read_failures_stop_source_and_attempt_relay_mute(self):
        for fault in ('missing', 'status', 'diagnostics'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as directory:
                messages = queue.Queue()
                source = self.fake_source()
                relay = Mock()
                relay.status.return_value = dict(txatt='50', rxgain='30', mode='1')
                relay.mute.return_value = {'relay_mode': 2}
                if fault in ('status', 'diagnostics'):
                    getattr(relay, fault).side_effect = OSError('USB lost during ' + fault)
                station = controller.StationController('sender', messages.put, Path(directory) / 'session')
                try:
                    station.console, station.relay = source, None if fault == 'missing' else relay
                    station.configured = station.active = True
                    station.last_lease = time.monotonic()
                    station.writer = (123, '456')
                    station.submit('read_relay')
                    event, seen = self.wait_for(messages, 'status', 'error')
                    self.assertFalse(any(item['type'] == 'relay_telemetry' for item in seen))
                    self.assertFalse(station.active)
                    self.assertFalse(station.configured)
                    self.assertIsNone(station.writer)
                    source.mute.assert_called_once()
                    self.assertTrue(any('kill -INT 123' in call.args[0] and '456' in call.args[0]
                                        for call in source.run.call_args_list))
                    if fault != 'missing':
                        relay.mute.assert_called_once()
                        relay.start.assert_not_called()
                        relay.prepare.assert_not_called()
                        self.assertIn('USB lost', event['message'])
                finally:
                    station.submit('close')
                    station.worker.join(3)
                    self.assertFalse(station.worker.is_alive())


if __name__ == '__main__':
    unittest.main()
