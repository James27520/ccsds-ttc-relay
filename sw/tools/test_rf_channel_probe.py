"""Offline channel separation and ownership failure tests; never opens hardware."""
import unittest
from unittest.mock import Mock, patch

import numpy as np

from sw.tools.rf_channel_probe import (
    ChannelProbeReceiver, RAW_BYTES, SAMPLES, split_iq_channels, decode_iq_channels)


def receiver():
    c = ChannelProbeReceiver.__new__(ChannelProbeReceiver)
    c.phy, c.rx, c.tx, c.debug = '/phy', '/rx', '/tx', '/debug'
    c._writable = False
    c._closed = False
    c.info = {'linux_boot_id': 'mock boot'}
    c.settings = None
    c.verify_binding = Mock()
    c.require_idle = Mock()
    c.run = Mock(return_value='0')

    def read(path):
        if path.endswith('/owned'):
            return '123 456'
        if path.endswith('TX_LO_powerdown') or path.endswith('adi,2rx-2tx-mode-enable'):
            return '1'
        if path.endswith('_type'):
            return 'le:S12/16>>0'
        if path.endswith('_index'):
            return path.split('in_voltage')[1][0]
        if path.endswith('/buffer/enable'):
            return '0'
        if path.endswith('RX_LO_frequency'):
            return '901749998'
        if path.endswith('in_voltage_sampling_frequency'):
            return '2500000'
        if path.endswith('in_voltage_rf_bandwidth'):
            return '3000000'
        if path.endswith('_gain_control_mode'):
            return 'manual'
        if path.endswith('_hardwaregain'):
            return '30 dB'
        if path.endswith('_rf_port_select'):
            return 'A_BALANCED'
        raise AssertionError('Unexpected read: '+path)

    c.read = Mock(side_effect=read)
    return c


class ChannelTests(unittest.TestCase):
    def test_pairs_and_signs_preserved_without_swapping_or_ranking(self):
        samples = np.tile(np.array([-2048, 2047, -7, 11], dtype='<i2'), (SAMPLES, 1))
        samples[-1] = [1, -2, 3, -4]
        ch1, ch2 = split_iq_channels(samples.tobytes())
        self.assertEqual((len(ch1), len(ch2)), (131072, 131072))
        self.assertEqual(ch1[:4], b'\x00\xf8\xff\x07')
        self.assertEqual(ch2[:4], b'\xf9\xff\x0b\x00')
        self.assertEqual(ch1[-4:], b'\x01\x00\xfe\xff')
        self.assertEqual(ch2[-4:], b'\x03\x00\xfc\xff')

    def test_rejects_wrong_size_type_and_non_sign_extended_codes(self):
        for raw in ('text', bytes(RAW_BYTES-2), bytes(RAW_BYTES+8),
                    b'\x00\x08'+bytes(RAW_BYTES-2), b'\xff\xf7'+bytes(RAW_BYTES-2)):
            with self.subTest(size=len(raw)), self.assertRaises(ValueError):
                split_iq_channels(raw)

    def test_decoder_receives_only_each_independent_pair(self):
        raw = np.tile(np.array([1, 2, 10, 20], dtype='<i2'), (SAMPLES, 1)).tobytes()
        with patch('sw.tools.rf_channel_probe.decode_capture', side_effect=[{'a': 1}, {'b': 2}]) as decoder:
            self.assertEqual(decode_iq_channels(raw), ({'a': 1}, {'b': 2}))
        self.assertEqual(decoder.call_args_list[0].args[0], split_iq_channels(raw)[0])
        self.assertEqual(decoder.call_args_list[1].args[0], split_iq_channels(raw)[1])


class GateTests(unittest.TestCase):
    def test_invalid_configuration_never_reaches_board(self):
        c = receiver()
        for lo, gain in [(900000000, 30), (901750000, 50), (True, 30), (901750000, True)]:
            with self.assertRaises(ValueError):
                c.configure(lo, gain)
        c.verify_binding.assert_not_called()
        c.run.assert_not_called()

    def test_live_tx_and_busy_dma_are_refused_before_writes(self):
        c = receiver()
        original = c.read.side_effect
        c.read.side_effect = lambda path: '0' if path.endswith('TX_LO_powerdown') else original(path)
        with self.assertRaisesRegex(RuntimeError, 'powerdown'):
            c.configure(901750000)
        c.run.assert_not_called()
        c = receiver()
        c.require_idle.side_effect = RuntimeError('busy DMA')
        with self.assertRaisesRegex(RuntimeError, 'busy DMA'):
            c.configure(901750000)
        c.run.assert_not_called()

    def test_unsupported_mode_or_scan_refused_before_writes(self):
        for suffix, bad in [('adi,2rx-2tx-mode-enable', '0'), ('in_voltage3_index', '2'),
                            ('in_voltage2_type', 'le:u12/16>>0')]:
            c = receiver()
            original = c.read.side_effect
            c.read.side_effect = lambda path, suffix=suffix, bad=bad: bad if path.endswith(suffix) else original(path)
            with self.assertRaises(RuntimeError):
                c.configure(1000750000, 20)
            c.run.assert_not_called()

    def test_configuration_reads_back_both_rx_paths_and_disallows_tx(self):
        c = receiver()
        with patch('sw.tools.rf_channel_probe.Console.write', side_effect=lambda _, p, v, t=0: str(v), autospec=True) as write:
            config = c.configure(901750000, 20)
        paths = [call.args[1] for call in write.call_args_list]
        self.assertIn('/phy/in_voltage1_rf_port_select', paths)
        self.assertIn('/phy/in_voltage1_hardwaregain', paths)
        self.assertEqual(config['rx_gain_db_readback'], [20, 20])
        self.assertFalse(c._writable)
        c._writable = True
        for name, value in [('out_altvoltage1_TX_LO_frequency', 901000000),
                            ('out_altvoltage1_TX_LO_powerdown', 0),
                            ('out_voltage0_hardwaregain', -89)]:
            with self.assertRaises(ValueError):
                c.write('/phy/'+name, value)


class CleanupTests(unittest.TestCase):
    def configured(self):
        c = receiver()
        c.settings = {'rx_lo_hz_requested': 901750000, 'rx_lo_hz_readback': 901750000,
                      'rx_gain_db_readback': [30, 30]}
        return c

    def test_failed_capture_stops_only_owned_pid_then_checks_idle(self):
        c = self.configured()
        c.run.side_effect = ['0', '1\nread error', '0']
        with self.assertRaisesRegex(RuntimeError, 'capture failed'):
            c.capture()
        cleanup = c.run.call_args_list[-1].args[0]
        self.assertIn('/proc/123/stat', cleanup)
        self.assertIn('= 456', cleanup)
        self.assertIn('kill -INT 123', cleanup)
        self.assertNotIn('killall', cleanup)
        self.assertIsNone(c._capture_directory)

    def test_malformed_owner_never_kills_or_disables_any_dma(self):
        c = self.configured()
        original = c.read.side_effect
        c.read.side_effect = lambda path: '123;killall 0' if path.endswith('/owned') else original(path)
        c._capture_directory = '/tmp/channel_probe_mock'
        with self.assertRaisesRegex(RuntimeError, 'identity is incomplete'):
            c._finish_capture()
        c.run.assert_not_called()
        self.assertIsNotNone(c._capture_directory)

    def test_dma_not_released_is_reported_without_forcing_buffer(self):
        c = self.configured()
        c._capture_directory = '/tmp/channel_probe_mock'
        original = c.read.side_effect
        c.read.side_effect = lambda path: '1' if path == '/rx/buffer/enable' else original(path)
        with patch('sw.tools.rf_channel_probe.time.monotonic', side_effect=[0, 4]):
            with self.assertRaisesRegex(RuntimeError, 'DMA release'):
                c._finish_capture()
        self.assertEqual(c.run.call_count, 1)
        self.assertNotIn('buffer', c.run.call_args.args[0])

    def test_success_returns_full_raw_hash_and_download_size(self):
        c = self.configured()
        c.download = Mock(return_value=bytes(RAW_BYTES))
        raw, meta = c.capture()
        self.assertEqual(len(raw), RAW_BYTES)
        self.assertEqual(meta['bytes'], RAW_BYTES)
        self.assertEqual(len(meta['sha256']), 64)
        self.assertEqual(meta['rx_lo_hz_readback'], 901749998)
        self.assertEqual(c.download.call_args.args[1], RAW_BYTES)
        self.assertGreaterEqual(c.verify_binding.call_count, 4)
        self.assertIn('voltage0 voltage1 voltage2 voltage3', c.run.call_args_list[1].args[0])

    def test_frequency_drift_refuses_capture_before_starting_dma(self):
        c = self.configured()
        original = c.read.side_effect
        c.read.side_effect = lambda path: '1000750000' if path.endswith('RX_LO_frequency') else original(path)
        with self.assertRaisesRegex(RuntimeError, 'LO changed'):
            c.capture()
        c.run.assert_not_called()

    def test_tx_enabled_during_download_cannot_return_a_valid_snapshot(self):
        c = self.configured()
        original = c.read.side_effect

        def download(*args):
            c.read.side_effect = lambda path: '0' if path.endswith('TX_LO_powerdown') else original(path)
            return bytes(RAW_BYTES)

        c.download = Mock(side_effect=download)
        with self.assertRaisesRegex(RuntimeError, 'powerdown'):
            c.capture()
        self.assertIsNone(c._capture_directory)
        self.assertEqual(sum('kill -INT' in call.args[0] for call in c.run.call_args_list), 1)


if __name__ == '__main__':
    unittest.main()
