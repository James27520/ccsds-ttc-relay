"""Ownership, guard and TC cleanup checks using fake process/sysfs state only.

This module does not instantiate a real console or execute a shell command.
"""
from collections import OrderedDict, deque
import re
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from .protocol import MessageTracker
from .terminal_backend import TerminalController
from .terminal_radio import TerminalRadio, ReceiveUnavailable


class BoardState:
    """Small interpreter for emitted ownership checks, never a shell."""
    def __init__(self, radio):
        self.radio = radio
        self.owned = {'reader': ['101', '1001'], 'decoder': ['102', '1002'],
                      'guard': ['103', '1003']}
        self.processes = {p: (ticks, 'S') for p, ticks in self.owned.values()}
        self.mask = ['0', '0', '1', '1']
        self.buffer = '1'
        self.killed = []
        self.commands = []
        self.max_wire_bytes = 0

    def read(self, path):
        if path.endswith('/buffer/enable'):
            return self.buffer
        if path.endswith('_type'):
            return 'le:S12/16>>0'
        for name in self.owned:
            if path.endswith('/'+name+'.owned'):
                return ' '.join(self.owned[name])
        raise AssertionError('unimplemented fake path: '+path)

    def run(self, command, timeout=8):
        self.commands.append(command)
        # Same fixed-width console framing, without opening any transport.
        wrapper = ("printf '\\nGS_BEGIN_%s\\n'; ( %s ); gs_rc=$?; "
                   "printf '\\nGS_END_%s_%%s\\n' \"$gs_rc\"") % ('0'*12, command, '0'*12)
        self.max_wire_bytes = max(self.max_wire_bytes, len(wrapper.encode('ascii'))+1)
        if command.startswith('cat ') and '/scan_elements/' in command:
            return '\n'.join(self.mask)
        match = re.search(r'/([^/]+)\.owned;', command)
        if command.startswith('if test -f ') and match:
            return ' '.join(self.owned.get(match[1], []))
        process = re.search(r'/proc/(\d+)/stat', command)
        expected = re.search(r'" = (\d+)', command)
        if process and expected:
            pid, ticks = process[1], expected[1]
            current = self.processes.get(pid)
            matches = current and current[0] == ticks
            if 'then echo missing;' in command:
                return 'missing' if not current else current[1] if matches else 'changed'
            if 'then kill -TERM ' in command:
                if matches:
                    self.killed.append(pid)
                    self.processes.pop(pid)
                    if pid == '101':
                        self.buffer = '0'
                return ''
            if 'then awk ' in command:
                return current[1] if matches else ''
            if not matches:
                raise RuntimeError('fake PID/start-time identity mismatch')
            return ''
        # Launch/lease commands are captured only, not executed.
        if command.startswith(('sh -c ', 'mkdir ', 'chmod ', 'echo ')):
            return ''
        raise AssertionError('unimplemented fake command: '+command)


class TerminalRadioSafetyTests(unittest.TestCase):
    def setUp(self):
        self.no_console = patch('sw.ground_station.transport.Console.__init__',
                                side_effect=AssertionError('test attempted hardware'))
        self.no_console.start()
        self.binding = patch('sw.ground_station.terminal_radio._verify_runtime_binding')
        self.binding.start()

    def tearDown(self):
        self.binding.stop()
        self.no_console.stop()

    def radio(self):
        r = object.__new__(TerminalRadio)
        r.stream = '/tmp/terminal_rx_0123456789ab'
        r.stream_owner = ['101', '1001']
        r.stream_owners = {'reader': ['101', '1001'], 'decoder': ['102', '1002'],
                           'guard': ['103', '1003']}
        r.rx_channel, r.business_mode = 2, True
        r.phy, r.tx, r.rx, r.debug = '/fake/phy', '/fake/tx', '/fake/rx', '/fake/debug'
        r.owned, r._closed = True, False
        r.record, r.verify_binding = Mock(), Mock()
        board = BoardState(r)
        r.read, r.run = board.read, board.run
        return r, board

    def test_owned_receive_allows_verified_rx_dma(self):
        radio, _ = self.radio()
        radio.verify_stream()

    def test_changed_reader_decoder_or_guard_record_is_rejected(self):
        for name in ('reader', 'decoder', 'guard'):
            with self.subTest(name=name):
                radio, board = self.radio()
                board.owned[name] = ['900', '9000']
                board.processes['900'] = ('9000', 'S')
                with self.assertRaisesRegex(RuntimeError, '身份'):
                    radio.verify_stream()

    def test_dead_guard_or_reused_pid_invalidates_receive(self):
        for process in (None, ('9999', 'S')):
            with self.subTest(process=process):
                radio, board = self.radio()
                if process:
                    board.processes['103'] = process
                else:
                    board.processes.pop('103')
                with self.assertRaises(RuntimeError):
                    radio.verify_stream()

    def test_changed_channel_mask_or_dma_stop_invalidates_receive(self):
        for mask, buffer in ((['1', '1', '0', '0'], '1'), (['0', '0', '1', '1'], '0')):
            with self.subTest(mask=mask, buffer=buffer):
                radio, board = self.radio()
                board.mask, board.buffer = mask, buffer
                with self.assertRaises(RuntimeError):
                    radio.verify_stream()

    def test_tc_mode_cannot_reuse_active_business_dma(self):
        radio, _ = self.radio()
        radio.business_mode = False
        with self.assertRaisesRegex(RuntimeError, '释放业务接收'):
            radio.require_idle()

    def test_rx_parameters_and_shared_clocks_are_blocked_while_streaming(self):
        radio, _ = self.radio()
        for name, value in [('in_voltage_sampling_frequency', 2500000),
                            ('out_voltage_sampling_frequency', 2500000),
                            ('out_voltage_rf_bandwidth', 3000000),
                            ('in_voltage1_hardwaregain', 30),
                            ('out_altvoltage0_RX_LO_frequency', 2189750000)]:
            with self.subTest(name=name), self.assertRaises((RuntimeError, ValueError)):
                radio.write(radio.phy+'/'+name, value)

    def test_stop_kills_only_matching_pid_start_time_and_waits_for_processes(self):
        radio, board = self.radio()
        # Reader PID now belongs to an unrelated process; old reader has gone.
        board.processes['101'] = ('9999', 'S')
        board.buffer = '0'
        radio.stop_receive()
        self.assertNotIn('101', board.killed)
        self.assertEqual(set(board.killed), {'102', '103'})
        self.assertEqual(board.processes['101'], ('9999', 'S'))
        self.assertIsNone(radio.stream)
        self.assertFalse(radio.stream_owners)

    def test_tampered_cleanup_identity_is_not_signalled(self):
        radio, board = self.radio()
        board.owned['guard'] = ['900', '9000']
        board.processes['900'] = ('9000', 'S')
        with self.assertRaisesRegex(RuntimeError, '身份变化'):
            radio.stop_receive()
        self.assertNotIn('900', board.killed)
        self.assertIsNotNone(radio.stream)

    def test_receive_launch_commands_fit_console_bound_and_never_start_tx(self):
        radio, board = self.radio()
        radio.stream, radio.stream_owner, radio.stream_owners = None, None, {}
        radio.receiver_binary = Mock(return_value=b'\x7fELFfake')
        with patch('sw.ground_station.terminal_radio.AutonomousRadio.require_idle'), \
             patch('sw.ground_station.terminal_radio.Console.upload'), \
             patch('sw.ground_station.terminal_radio.uuid.uuid4', return_value=SimpleNamespace(hex='0'*32)):
            radio.start_receive()
        self.assertEqual(set(radio.stream_owners), {'reader', 'decoder', 'guard'})
        self.assertLessEqual(board.max_wire_bytes, 900)
        launch = '\n'.join(board.commands)
        self.assertIn('iio_readdev ', launch)
        self.assertNotIn('iio_writedev', launch)
        self.assertNotIn('enable_request', launch)
        self.assertIn('+ 90', launch)

    def test_upload_failure_retains_cleanup_path_without_launching_reader(self):
        radio, board = self.radio()
        radio.stream, radio.stream_owner, radio.stream_owners = None, None, {}
        radio.receiver_binary = Mock(return_value=b'\x7fELFfake')
        with patch('sw.ground_station.terminal_radio.AutonomousRadio.require_idle'), \
             patch('sw.ground_station.terminal_radio.Console.upload', side_effect=RuntimeError('fake upload failure')):
            with self.assertRaisesRegex(RuntimeError, 'upload failure'):
                radio.start_receive()
        self.assertTrue(radio.stream.startswith('/tmp/terminal_rx_'))
        self.assertFalse(radio.stream_owners)
        self.assertFalse(any('iio_readdev' in command for command in board.commands))

    def test_cleanup_waits_for_decoder_after_rx_dma_is_disabled(self):
        radio, board = self.radio()
        original = board.run
        decoder_polls = []

        def run(command, timeout=8):
            if 'then kill -TERM 102;' in command:
                return ''  # Decoder takes time to finish its current window.
            if '/proc/102/stat' in command and 'then awk ' in command:
                decoder_polls.append(command)
                return 'S' if len(decoder_polls) < 3 else 'Z'
            return original(command, timeout)

        radio.run = run
        with patch('sw.ground_station.terminal_radio.time.sleep'):
            radio.stop_receive()
        self.assertEqual(board.buffer, '0')
        self.assertEqual(len(decoder_polls), 3)
        self.assertIsNone(radio.stream)

    def test_transmit_monitor_checks_pid_identity_and_deadline(self):
        for guard_alive, remaining, expected in ((False, 10, 'error'), (True, 0, False), (True, 10, True)):
            with self.subTest(guard_alive=guard_alive, remaining=remaining):
                radio, board = self.radio()
                radio.remote = '/fake/transmit'
                board.processes.update({'201': ('2001', 'S'), '202': ('2002', 'S')})
                if not guard_alive:
                    board.processes.pop('201')
                values = {radio.remote+'/guard_state': 'enabled',
                          radio.remote+'/guard_owned': '201 2001',
                          radio.remote+'/owned': '202 2002',
                          radio.phy+'/out_altvoltage1_TX_LO_powerdown': '0',
                          radio.tx+'/buffer/enable': '1'}
                radio.read = lambda path: values[path]
                radio.run = lambda command, timeout=8: str(remaining) if command.startswith('echo $((') else board.run(command, timeout)
                if expected == 'error':
                    with self.assertRaises(RuntimeError):
                        radio.verify_transmit()
                else:
                    self.assertIs(radio.verify_transmit(), expected)


class TerminalCleanupSafetyTests(unittest.TestCase):
    def controller(self):
        c = object.__new__(TerminalController)
        c.radio = Mock()
        c.radio.info = {'model': 'fake'}
        c.role = 'sender'
        c.transaction = Mock()
        c.interrupt = threading.Event()
        c.job_lock = threading.RLock()
        c.jobs, c.send_order = OrderedDict(), deque()
        c.tc_active = c.tx_active = False
        c.rx_active = True
        c.discard_pending = c.discard_pending_sends = c.status = c.state = c.event = Mock()
        c.check_cancel = Mock()
        c._resume_receive = Mock()
        c.lease = Mock()
        return c

    def test_tc_capture_cleanup_failure_still_stops_tx_and_restores_mode(self):
        c = self.controller()
        radio = c.radio
        radio.finish_capture.side_effect = RuntimeError('fake capture cleanup failed')
        with self.assertRaisesRegex(RuntimeError, '清理未确认'):
            c._telecontrol({}, wiring_confirmed=True)
        self.assertGreaterEqual(radio.stop.call_count, 2)
        self.assertTrue(radio.business_mode)
        self.assertEqual(radio.tx_channel, 1)
        self.assertFalse(c.tc_active)
        c._resume_receive.assert_not_called()

    def test_disconnect_attempts_all_cleanup_and_releases_port_after_error(self):
        c = self.controller()
        radio, lease = c.radio, c.lease
        radio.stop_receive.side_effect = RuntimeError('fake RX cleanup failed')
        with self.assertRaisesRegex(RuntimeError, '清理未完全确认'):
            c._disconnect()
        radio.stop.assert_called_once()
        radio.finish_capture.assert_called_once()
        radio.close.assert_called_once()
        lease.close.assert_called_once()
        self.assertIsNone(c.radio)
        self.assertIsNone(c.lease)
        self.assertFalse(c.rx_active or c.tx_active or c.tc_active)

    def polling_controller(self, **status_values):
        c = self.controller()
        c.poll_seconds = 0
        c.last_poll = 0
        c.last_samples = None
        c.last_progress = time.monotonic()
        c.receive_rate_anchor = (0, 0)  # A prior fake snapshot for rate checks.
        c.last_frame_count = c.last_reject_count = 0
        c.tracker = MessageTracker()
        c.settings = {'rx_lo_hz_readback': 2189750000}
        status = dict(samples=2500000, uptime_ms=1000, rms=2, recent_rms=2,
                      clips=0, frames=0, rejects=0, eof=False, stopped=False,
                      input_error=False)
        status.update(status_values)
        c.radio.poll_receive.return_value = status, []
        return c

    def test_tx_guard_failure_is_checked_before_receive_poll(self):
        c = self.polling_controller()
        c.tx_active = True
        c.radio.verify_transmit.side_effect = RuntimeError('fake guard PID disappeared')
        with self.assertRaisesRegex(RuntimeError, 'guard PID'):
            c._poll()
        c.radio.poll_receive.assert_not_called()

    def test_recent_overload_cannot_be_hidden_by_cumulative_rms(self):
        c = self.polling_controller(rms=2, recent_rms=1500)
        with self.assertRaisesRegex(RuntimeError, '电平'):
            c._poll()

    def test_stopped_input_or_insufficient_throughput_invalidates_receive(self):
        for values in ({'eof': True}, {'stopped': True}, {'input_error': True},
                       {'samples': 6_000_000, 'uptime_ms': 6000}):
            with self.subTest(values=values):
                with self.assertRaises(RuntimeError):
                    self.polling_controller(**values)._poll()


if __name__ == '__main__':
    unittest.main()
