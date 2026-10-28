"""Fault injection for DEBUG transport; never opens or enumerates serial ports."""
import hashlib
import types
import unittest
from unittest.mock import Mock, patch

from .transport import Console, _board_identity


class FragmentedPort:
    def __init__(self, response):
        self.response = bytearray(response)
        self.writes = []
        self.clock = 0

    @property
    def in_waiting(self):
        return min(3, len(self.response))

    def write(self, data):
        self.writes.append(data)
        return len(data)

    def read(self, size):
        self.clock += .001
        # Every marker and CRLF is split over several reads.
        result = bytes(self.response[:min(size, 3)])
        del self.response[:len(result)]
        return result


def console_without_serial():
    console = Console.__new__(Console)
    console.record = Mock()
    console.phy, console.tx, console.rx = '/phy', '/tx', '/rx'
    return console


class ConsoleRunTests(unittest.TestCase):
    token = '123456abcdef'

    def run_response(self, response, **kwargs):
        console = console_without_serial()
        console.port = FragmentedPort(response)
        with patch('sw.ground_station.transport.uuid.uuid4', return_value=types.SimpleNamespace(hex=self.token)), \
                patch('sw.ground_station.transport.time.monotonic', side_effect=lambda: console.port.clock), \
                patch('sw.ground_station.transport.time.sleep'):
            return console, console.run('echo example', timeout=.5, **kwargs)

    def test_arbitrary_serial_fragments_echo_and_stale_markers(self):
        response = (b"echo GS_BEGIN_123456abcdef echoed command\r\n"
                    b"GS_END_deadbeef0000_0\r\n"
                    b"GS_BEGIN_123456abcdef\r\n"
                    b"example\r\nGS_END_123456abcdef_0\r\n")
        console, output = self.run_response(response)
        self.assertEqual(output, 'example')
        self.assertEqual(console.record.call_args.kwargs['rc'], 0)

    def test_failure_status_is_not_treated_as_success(self):
        with self.assertRaisesRegex(RuntimeError, 'rc=17'):
            self.run_response(b'\nGS_BEGIN_123456abcdef\nfailed\nGS_END_123456abcdef_17\n')

    def test_unicode_response_uses_byte_marker_boundaries(self):
        _, output = self.run_response(('启动\nGS_BEGIN_123456abcdef\n状态正常\n'
                                       'GS_END_123456abcdef_0\n').encode('utf-8'))
        self.assertEqual(output, '状态正常')

    def test_short_write_and_oversized_reply_abort(self):
        console = console_without_serial()
        console.port = FragmentedPort(b'')
        console.port.write = Mock(return_value=1)
        with self.assertRaisesRegex(RuntimeError, '未完整写入'):
            console.run('true')
        self.assertEqual(console.port.write.call_args.args, (b'\x03\n',))
        console.port = FragmentedPort(b'x' * 300)
        with patch('sw.ground_station.transport.MAX_RESPONSE_BYTES', 32), \
                patch('sw.ground_station.transport.time.monotonic', side_effect=lambda: console.port.clock):
            with self.assertRaisesRegex(RuntimeError, '上限'):
                console.run('true')
        self.assertEqual(console.port.writes[-1], b'\x03\n')

    def test_timeout_and_missing_begin_abort_with_ctrl_c(self):
        for response in [b'partial output', b'\nGS_END_123456abcdef_0\n']:
            console = console_without_serial()
            console.port = FragmentedPort(response)
            with patch('sw.ground_station.transport.uuid.uuid4', return_value=types.SimpleNamespace(hex=self.token)), \
                    patch('sw.ground_station.transport.time.monotonic', side_effect=lambda: console.port.clock), \
                    patch('sw.ground_station.transport.time.sleep'):
                with self.assertRaises(TimeoutError):
                    console.run('true', timeout=.01)
            self.assertEqual(console.port.writes[-1], b'\x03\n')


class FastPort:
    """A UART transaction fake that exposes binary only after host changes rate."""
    token = '123456abcdef'

    def __init__(self, data, fault=None):
        self.data, self.fault = data, fault
        self.response = bytearray()
        self.writes, self.rates = [], [115200]
        self.clock = 0.
        self.phase = 'idle'
        self._baudrate = 115200
        self.resets = 0

    @property
    def baudrate(self):
        return self._baudrate

    @baudrate.setter
    def baudrate(self, rate):
        self._baudrate = rate
        self.rates.append(rate)
        if rate == 921600 and self.fault == 'baud_failure':
            raise OSError('host rejected fast baud')
        if rate == 921600 and self.phase == 'ready':
            self.phase = 'binary'
            if self.fault == 'begin_timeout':
                return
            self.response.extend(b'\nFAST_BEGIN_' + self.token.encode() + b'\n')
            if self.fault == 'short':
                self.response.extend(self.data[:-100])
                return
            data = self.data
            if self.fault == 'hash':
                data = bytes([data[0] ^ 1]) + data[1:]
            self.response.extend(data)
            if self.fault == 'tail':
                self.response.extend(b'\nFAST_END_badtoken0000_0\n')
            elif self.fault == 'rc':
                self.response.extend(b'\nFAST_END_' + self.token.encode() + b'_17\n')
            else:
                self.response.extend(b'\nFAST_END_' + self.token.encode() + b'_0\n')

    @property
    def in_waiting(self):
        return min(137, len(self.response))

    def read(self, size):
        self.clock += .0001 if self.response else .05
        result = bytes(self.response[:size])
        del self.response[:len(result)]
        return result

    def write(self, data):
        self.writes.append(data)
        if data.startswith(b'( gs_stty='):
            self.phase = 'ready'
            if self.fault != 'ready_timeout':
                self.response.extend(b'echoed command\r\n\nFAST_READY_' + self.token.encode() + b'\n')
            if self.fault == 'short_write':
                return len(data)-1
        if data.startswith(b'\x03'):
            self.response.clear()
            self.phase = 'aborted'
        return len(data)

    def reset_input_buffer(self):
        self.resets += 1
        self.response.clear()


class FastDownloadTests(unittest.TestCase):
    def transaction(self, data, fault=None, restore_failures=0):
        console = console_without_serial()
        console.port = FastPort(data, fault)
        digest = hashlib.sha256(data).hexdigest()
        failures = [restore_failures]
        def run(command, **kwargs):
            if command.startswith('wc -c'):
                return f'{len(data)}\n{digest}  /tmp/capture.bin'
            if 'GS_RESTORED_' in command:
                if failures[0]:
                    failures[0] -= 1
                    raise TimeoutError('restore confirmation timeout')
                self.assertEqual(console.port.baudrate, 115200)
                return 'GS_RESTORED_' + FastPort.token
            self.fail('Unexpected text command: ' + command)
        console.run = Mock(side_effect=run)
        return console

    def execute(self, console, data):
        with patch('sw.ground_station.transport.uuid.uuid4',
                   return_value=types.SimpleNamespace(hex=FastPort.token)), \
                patch('sw.ground_station.transport.time.monotonic', side_effect=lambda: console.port.clock), \
                patch('sw.ground_station.transport.time.sleep'):
            return console.download('/tmp/capture.bin', len(data))

    def test_all_control_bytes_and_payload_markers_are_exact_data(self):
        data = bytes(range(256))*512 + b'\nFAST_END_123456abcdef_0\n\nFAST_BEGIN_123456abcdef\n'
        console = self.transaction(data)
        self.assertEqual(self.execute(console, data), data)
        self.assertEqual(console.port.baudrate, 115200)
        self.assertIn(921600, console.port.rates)
        self.assertIn(b'trap', console.port.writes[0])
        self.assertIn(b'EXIT HUP INT TERM', console.port.writes[0])
        self.assertTrue(console.record.call_args.kwargs['success'])
        self.assertEqual(console.record.call_args.kwargs['restored_baudrate'], 115200)
        self.assertFalse(any('xxd' in call.args[0] for call in console.run.call_args_list))

    def test_bad_tail_returncode_and_hash_reject_and_restore(self):
        data = bytes(range(256))*8
        for fault in ['tail', 'rc', 'hash']:
            with self.subTest(fault=fault):
                console = self.transaction(data, fault)
                with self.assertRaises(RuntimeError):
                    self.execute(console, data)
                self.assertEqual(console.port.baudrate, 115200)
                self.assertTrue(any(value.startswith(b'\x03') for value in console.port.writes))
                self.assertFalse(console.record.call_args.kwargs['success'])
                self.assertEqual(console.record.call_args.kwargs['restored_baudrate'], 115200)

    def test_short_ready_and_begin_timeout_reject_restore_without_fallback(self):
        data = bytes(range(256))*8
        for fault in ['short', 'ready_timeout', 'begin_timeout']:
            with self.subTest(fault=fault):
                console = self.transaction(data, fault)
                with self.assertRaises(TimeoutError):
                    self.execute(console, data)
                self.assertEqual(console.port.baudrate, 115200)
                self.assertFalse(any('xxd' in call.args[0] for call in console.run.call_args_list))

    def test_short_command_write_still_attempts_default_rate_recovery(self):
        data = b'bytes' * 100
        console = self.transaction(data, 'short_write')
        with self.assertRaisesRegex(RuntimeError, '未完整写入'):
            self.execute(console, data)
        self.assertEqual(console.port.baudrate, 115200)
        self.assertGreater(console.port.resets, 0)

    def test_host_baud_configuration_failure_still_sets_default_in_finally(self):
        data = b'bytes' * 100
        console = self.transaction(data, 'baud_failure')
        with self.assertRaisesRegex(RuntimeError, 'host rejected fast baud'):
            self.execute(console, data)
        self.assertEqual(console.port.baudrate, 115200)
        self.assertFalse(console.record.call_args.kwargs['success'])

    def test_restore_gets_one_retry_and_unconfirmed_restore_is_failure(self):
        data = bytes(range(256))*8
        console = self.transaction(data, restore_failures=1)
        self.assertEqual(self.execute(console, data), data)
        self.assertIn(b'\x03\nstty 115200\n', console.port.writes)
        console = self.transaction(data, restore_failures=2)
        with self.assertRaisesRegex(RuntimeError, '恢复115200未确认'):
            self.execute(console, data)
        self.assertEqual(console.port.baudrate, 115200)
        self.assertIsNone(console.record.call_args.kwargs['restored_baudrate'])
        writes = len(console.port.writes)
        with self.assertRaisesRegex(RuntimeError, '禁止继续发送命令'):
            Console.run(console, 'echo unsafe-after-unconfirmed-download-recovery')
        self.assertEqual(len(console.port.writes), writes)

    def test_interrupt_while_reading_fast_data_still_restores_default_rate(self):
        data = bytes(range(256))*8
        console = self.transaction(data)
        read = console.port.read
        def interrupt_fast_read(size):
            if console.port.phase == 'binary':
                raise KeyboardInterrupt()
            return read(size)
        console.port.read = interrupt_fast_read
        with self.assertRaises(KeyboardInterrupt):
            self.execute(console, data)
        self.assertEqual(console.port.baudrate, 115200)
        self.assertTrue(getattr(console, '_console_synchronized', False))
        self.assertFalse(console.record.call_args.kwargs['success'])

    def test_invalid_mode_or_size_is_rejected_before_commands(self):
        console = console_without_serial()
        console.run = Mock()
        for size, mode in [(1, 'unknown'), (0, 'fast'), (True, 'fast'), (1048577, 'fast')]:
            with self.assertRaises(ValueError):
                console.download('/tmp/capture.bin', size, mode=mode)
        console.run.assert_not_called()


class FastUploadPort:
    token = '123456abcdef'

    def __init__(self, size, fault=None):
        self.size, self.fault = size, fault
        self.response, self.received = bytearray(), bytearray()
        self.writes, self.rates = [], [115200]
        self.clock, self.last_input = 0., 0.
        self.phase, self._baudrate = 'idle', 115200
        self.write_timeout = 3
        self.purged = 0

    @property
    def baudrate(self):
        return self._baudrate

    @baudrate.setter
    def baudrate(self, rate):
        self._baudrate = rate
        self.rates.append(rate)
        if rate == 921600 and self.phase == 'ready':
            self.phase = 'binary'
            self.last_input = self.clock
            if self.fault != 'begin_timeout':
                self.response.extend(b'\nUP_BEGIN_' + self.token.encode() + b'\n')
            if self.fault == 'stale_begin':
                # Simulate a host driver/thread stall after the board's marker
                # was queued: head has timed out before the host resumes.
                self.advance(3.2)

    @property
    def in_waiting(self):
        return min(37, len(self.response))

    def finish(self):
        if self.fault != 'end_timeout':
            code = b'17' if self.fault == 'rc' else b'0'
            self.response.extend(b'\nUP_END_' + self.token.encode() + b'_' + code + b'\n')
        self.phase = 'ended'

    def advance(self, duration):
        self.clock += duration
        if self.phase == 'binary' and self.clock-self.last_input >= 3:
            self.finish()
        if self.phase == 'ended' and duration >= .3:
            self.phase = 'restored'
        if self.phase == 'ready' and self.fault == 'ready_timeout' and self.clock >= 3.6:
            self.phase = 'restored'

    def read(self, size):
        self.advance(.0001 if self.response else .05)
        result = bytes(self.response[:size])
        del self.response[:len(result)]
        return result

    def write(self, data):
        self.writes.append((self.clock, data))
        if data.startswith(b'( gs_stty='):
            self.phase = 'ready'
            if self.fault != 'ready_timeout':
                self.response.extend(b'\nUP_READY_' + self.token.encode() + b'\n')
            return len(data)
        if self.phase != 'binary':
            raise AssertionError('Attempt to write bytes after raw reader has exited')
        self.last_input = self.clock
        if self.fault in ('short_write', 'write_timeout'):
            self.received.extend(data[:17])
            if self.fault == 'write_timeout':
                raise TimeoutError('injected raw write timeout')
            return 17
        self.received.extend(data[:-17] if self.fault == 'short_board' else data)
        if len(self.received) >= self.size:
            if self.fault == 'hash':
                self.received[0] ^= 1
            self.finish()
        return len(data)

    def reset_output_buffer(self):
        self.purged += 1

    def reset_input_buffer(self):
        self.response.clear()


class FastUploadTests(unittest.TestCase):
    def transaction(self, data, fault=None, restore_failure=False):
        console = console_without_serial()
        console.port = FastUploadPort(len(data), fault)
        def run(command, **kwargs):
            if command.startswith('test ! -e'):
                return ''
            if 'GS_RESTORED_' in command:
                self.assertEqual(console.port.baudrate, 115200)
                if restore_failure:
                    raise TimeoutError('upload restore confirmation failed')
                return 'GS_RESTORED_' + FastUploadPort.token
            if command.startswith('wc -c'):
                board = bytes(console.port.received)
                return f'{len(board)}\n{hashlib.sha256(board).hexdigest()}  /tmp/message.iq'
            self.fail('Unexpected command: ' + command)
        console.run = Mock(side_effect=run)
        return console

    def execute(self, console, data, progress=None):
        with patch('sw.ground_station.transport.uuid.uuid4',
                   return_value=types.SimpleNamespace(hex=FastUploadPort.token)), \
                patch('sw.ground_station.transport.time.monotonic', side_effect=lambda: console.port.clock), \
                patch('sw.ground_station.transport.time.sleep', side_effect=console.port.advance) as sleep:
            return console.upload('/tmp/message.iq', data, progress), sleep

    def assert_no_post_failure_control_bytes(self, console):
        # Only the initial shell command and 4096-byte raw chunks may be written.
        # Restoration confirmation is exercised through the separately mocked run.
        for _, payload in console.port.writes[1:]:
            self.assertLessEqual(len(payload), 4096)
            self.assertNotEqual(payload, b'\x03\n')
            self.assertNotEqual(payload, b'\x03\nstty 115200\n')
        self.assertEqual(console.port.baudrate, 115200)
        self.assertEqual(console.port.write_timeout, 3)

    def test_control_bytes_chunk_progress_digest_and_default_restore(self):
        data = bytes(range(256))*169 + b'\nUP_END_123456abcdef_0\n'
        console = self.transaction(data)
        progress = Mock()
        digest, sleep = self.execute(console, data, progress)
        self.assertEqual(digest, hashlib.sha256(data).hexdigest())
        self.assertEqual(console.port.received, data)
        self.assertEqual(len(console.port.writes)-1, (len(data)+4095)//4096)
        self.assertEqual(progress.call_args_list[0].args, (0.,))
        self.assertEqual(progress.call_args.args, (1.,))
        self.assertEqual(progress.call_count, (len(data)+4095)//4096+1)
        self.assertIn(b'raw -echo min 0 time 30', console.port.writes[0][1])
        self.assertIn(b'head -c ', console.port.writes[0][1])
        self.assert_no_post_failure_control_bytes(console)
        sleep.assert_called_once_with(.5)

    def test_cancel_waits_for_raw_timeout_without_more_input(self):
        data = bytes(range(256))*40
        for cancel_before_first in (False, True):
            console = self.transaction(data)
            def progress(fraction):
                if fraction or cancel_before_first:
                    raise RuntimeError('upload cancelled')
            with self.subTest(before_first=cancel_before_first), self.assertRaisesRegex(RuntimeError, 'cancelled'):
                self.execute(console, data, progress)
            self.assertEqual(len(console.port.received), 0 if cancel_before_first else 4096)
            self.assertGreaterEqual(console.port.clock-console.port.writes[-1][0], 3.6)
            self.assertEqual(console.port.purged, 1)
            self.assert_no_post_failure_control_bytes(console)
            self.assertFalse(any(call.args[0].startswith('wc -c') for call in console.run.call_args_list))

    def test_short_write_write_timeout_and_handshake_timeouts_restore(self):
        data = bytes(range(256))*40
        for fault in ['short_write', 'write_timeout', 'ready_timeout', 'begin_timeout', 'end_timeout', 'rc']:
            with self.subTest(fault=fault):
                console = self.transaction(data, fault)
                with self.assertRaises((RuntimeError, TimeoutError)):
                    self.execute(console, data)
                self.assertGreaterEqual(console.port.clock-console.port.writes[-1][0], 3.6)
                self.assert_no_post_failure_control_bytes(console)

    def test_board_short_data_or_corrupt_hash_rejected_after_head_returns_zero(self):
        data = bytes(range(256))*40
        for fault in ['short_board', 'hash']:
            with self.subTest(fault=fault):
                console = self.transaction(data, fault)
                with self.assertRaisesRegex(RuntimeError, '长度或SHA256'):
                    self.execute(console, data)
                self.assert_no_post_failure_control_bytes(console)
                self.assertFalse(console.record.call_args.kwargs['success'])

    def test_blocked_progress_never_resumes_input_after_tty_timeout(self):
        data = bytes(range(256))*40
        console = self.transaction(data)
        def progress(fraction):
            if fraction:
                console.port.advance(3.2)
        with self.assertRaisesRegex(TimeoutError, '包间隔'):
            self.execute(console, data, progress)
        self.assertEqual(len(console.port.received), 4096)
        self.assert_no_post_failure_control_bytes(console)

    def test_stale_begin_cannot_grant_a_new_raw_input_deadline(self):
        data = bytes(range(256))*40
        console = self.transaction(data, 'stale_begin')
        with self.assertRaisesRegex(TimeoutError, '包间隔'):
            self.execute(console, data)
        self.assertEqual(len(console.port.writes), 1)  # Initial shell command only.
        self.assertEqual(console.port.received, b'')
        self.assert_no_post_failure_control_bytes(console)

    def test_restore_confirmation_failure_rejects_successful_payload(self):
        data = bytes(range(256))*40
        console = self.transaction(data, restore_failure=True)
        with self.assertRaisesRegex(RuntimeError, '恢复115200未确认'):
            self.execute(console, data)
        self.assert_no_post_failure_control_bytes(console)
        self.assertIsNone(console.record.call_args.kwargs['restored_baudrate'])
        self.assertFalse(any(call.args[0].startswith('wc -c') for call in console.run.call_args_list))
        writes = len(console.port.writes)
        with self.assertRaisesRegex(RuntimeError, '禁止继续发送命令'):
            Console.run(console, 'echo unsafe-after-unconfirmed-raw-recovery')
        self.assertEqual(len(console.port.writes), writes)

    def test_interrupt_during_progress_still_waits_before_console_commands(self):
        data = bytes(range(256))*40
        console = self.transaction(data)
        with self.assertRaises(KeyboardInterrupt):
            self.execute(console, data, Mock(side_effect=KeyboardInterrupt()))
        self.assertEqual(console.port.received, b'')
        self.assertGreaterEqual(console.port.clock-console.port.writes[-1][0], 3.6)
        self.assert_no_post_failure_control_bytes(console)

    def test_invalid_upload_mode_type_or_byte_size_cannot_create_remote_file(self):
        console = console_without_serial()
        console.run = Mock()
        for data, mode in [(b'x', 'unknown'), (b'', 'fast'), (17, 'fast'),
                           (b'x'*1048577, 'fast'), ('text', 'fast')]:
            with self.assertRaises(ValueError):
                console.upload('/tmp/message.iq', data, mode=mode)
        console.run.assert_not_called()


class ReadbackAndTransferTests(unittest.TestCase):
    def test_empty_hw_serial_cannot_consume_next_line_and_usb_is_explicit(self):
        info = 'hw_model: Pluto\r\n\thw_serial: \t\r\n\tfw_version: v0.38\r\n'
        self.assertEqual(_board_identity(info, '00000000ABC123'), ('00000000ABC123', 'usb'))
        self.assertEqual(_board_identity('hw_serial: RX104412345\nfw_version: v0.38', 'OTHERUSB12'),
                         ('RX104412345', 'iio'))
        for usb in [None, '', 'short', 'space serial', 'line\nserial']:
            with self.subTest(usb=usb), self.assertRaises(RuntimeError):
                _board_identity(info, usb)

    def test_finite_numeric_readback_and_documented_gain_unit(self):
        console = console_without_serial()
        console.run = Mock(return_value='')
        for value, readback, tolerance in [(900000000, '900000009', 10),
                                           (30, '30.000000 dB', 0),
                                           (.01, '1e-2', 0)]:
            console.read = Mock(return_value=readback)
            self.assertEqual(console.write('/phy/in_voltage0_hardwaregain', value, tolerance), readback)
        for readback in ['nan', 'NaN dB', 'inf', '1e999', '30 junk', '30.0 dBm', '31.0 dB', '']:
            console.read = Mock(return_value=readback)
            with self.subTest(readback=readback), self.assertRaises(RuntimeError):
                console.write('/phy/in_voltage0_hardwaregain', 30)
        console.read = Mock(return_value='2500000 dB')
        with self.assertRaises(RuntimeError):
            console.write('/phy/out_voltage_sampling_frequency', 2500000)
        console.read = Mock(return_value='manual extra')
        with self.assertRaises(RuntimeError):
            console.write('/phy/in_voltage0_gain_control_mode', 'manual')

    def test_nonfinite_write_and_invalid_tolerance_rejected_before_write(self):
        console = console_without_serial()
        console.run = Mock()
        for value in [float('nan'), float('inf'), -float('inf'), '1e999']:
            with self.assertRaises(ValueError):
                console.write('/phy/in_voltage0_hardwaregain', value)
        for tolerance in [-1, float('nan'), float('inf')]:
            with self.assertRaises(ValueError):
                console.write('/phy/in_voltage0_hardwaregain', 1, tolerance)
        console.run.assert_not_called()

    def test_download_length_hex_and_hash_must_all_match(self):
        data = b'raw ADC data\0' * 200
        digest = hashlib.sha256(data).hexdigest()
        info = f'{len(data)}\n{digest}  /tmp/capture.bin'
        encoded = '\n'.join(data.hex()[start:start+60] for start in range(0, len(data)*2, 60))
        console = console_without_serial()
        console.run = Mock(side_effect=[info, encoded])
        self.assertEqual(console.download('/tmp/capture.bin', len(data), mode='legacy'), data)
        console.run.assert_called_with('xxd -p /tmp/capture.bin', timeout=max(12, 2*len(data)/6000+8))
        for metadata, body, error in [
                (f'{len(data)-4}\n{digest} x', encoded, RuntimeError),
                (info, encoded[:-8], (ValueError, RuntimeError)),
                (info, '!!!!', ValueError),
                (info, '0' * (len(data)*2), RuntimeError),
                (info, encoded.replace('0', '\ufffd', 1), ValueError),
                (f'{len(data)}\n' + '0' * 64 + ' x', encoded, RuntimeError)]:
            console.run = Mock(side_effect=[metadata, body])
            with self.subTest(metadata=metadata[:12], body=body[:12]), self.assertRaises(error):
                console.download('/tmp/capture.bin', len(data), mode='legacy')

    def test_upload_chunk_bound_digest_and_cancellation(self):
        data = bytes(range(256)) * 4
        digest = hashlib.sha256(data).hexdigest()
        console = console_without_serial()
        metadata = f'{len(data)}\n{digest}  /tmp/message.iq'
        console.run = Mock(side_effect=['', '', '', '', '', metadata])
        progress = Mock()
        self.assertEqual(console.upload('/tmp/message.iq', data, progress, mode='legacy'), digest)
        chunks = [call.args[0] for call in console.run.call_args_list if 'xxd -r -p' in call.args[0]]
        self.assertEqual(len(chunks), 4)
        self.assertTrue(all(len(command.split("'")[1]) <= 512 for command in chunks))
        self.assertEqual(bytes.fromhex(''.join(command.split("'")[1] for command in chunks)), data)
        self.assertEqual(progress.call_args.args, (1.,))
        console.run = Mock(side_effect=['', '', '', '', '', metadata.replace(digest, '0' * 64)])
        with self.assertRaisesRegex(RuntimeError, '校验失败'):
            console.upload('/tmp/message.iq', data, mode='legacy')
        console.run = Mock(return_value='')
        with self.assertRaisesRegex(RuntimeError, 'cancel'):
            console.upload('/tmp/message.iq', data, Mock(side_effect=RuntimeError('cancel')), mode='legacy')
        self.assertEqual(console.run.call_count, 2)

    def test_mute_attempts_other_shutdowns_after_lo_write_failure(self):
        console = console_without_serial()
        console.write = Mock(side_effect=[RuntimeError('LO failure'), '-89.000000 dB', '-89.000000 dB'])
        console.run = Mock(side_effect=['', '0 0 0 0'])
        with self.assertRaisesRegex(RuntimeError, 'LO failure'):
            console.mute()
        self.assertEqual(console.write.call_count, 3)
        self.assertEqual(console.run.call_count, 2)


if __name__ == '__main__':
    unittest.main()
