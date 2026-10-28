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
        self.assertEqual(console.download('/tmp/capture.bin', len(data)), data)
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
                console.download('/tmp/capture.bin', len(data))

    def test_upload_chunk_bound_digest_and_cancellation(self):
        data = bytes(range(256)) * 4
        digest = hashlib.sha256(data).hexdigest()
        console = console_without_serial()
        metadata = f'{len(data)}\n{digest}  /tmp/message.iq'
        console.run = Mock(side_effect=['', '', '', '', '', metadata])
        progress = Mock()
        self.assertEqual(console.upload('/tmp/message.iq', data, progress), digest)
        chunks = [call.args[0] for call in console.run.call_args_list if 'xxd -r -p' in call.args[0]]
        self.assertEqual(len(chunks), 4)
        self.assertTrue(all(len(command.split("'")[1]) <= 512 for command in chunks))
        self.assertEqual(bytes.fromhex(''.join(command.split("'")[1] for command in chunks)), data)
        self.assertEqual(progress.call_args.args, (1.,))
        console.run = Mock(side_effect=['', '', '', '', '', metadata.replace(digest, '0' * 64)])
        with self.assertRaisesRegex(RuntimeError, '校验失败'):
            console.upload('/tmp/message.iq', data)
        console.run = Mock(return_value='')
        with self.assertRaisesRegex(RuntimeError, 'cancel'):
            console.upload('/tmp/message.iq', data, Mock(side_effect=RuntimeError('cancel')))
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
