"""Offline frequency and ownership checks; never opens a board."""
import unittest
from unittest.mock import Mock, patch

from sw.tools.rf_frequency_probe import (
    POINTS, FrequencyPoint, FrequencyProbeSource, FrequencyProbeReceiver)
from sw.tools.test_rf_channel_probe import receiver


class FrequencyTests(unittest.TestCase):
    def source(self):
        s = FrequencyProbeSource.__new__(FrequencyProbeSource)
        s.phy = '/phy'
        s.owned, s._closed, s.prepared = True, False, False
        s.verify_binding = Mock()
        s.require_idle = Mock()
        s.read = Mock(return_value='1')
        s.mute = Mock()
        s.configure_if_changed = Mock(return_value='1989000000')
        s._prepare_waveform = Mock()
        return s

    def test_translation_and_decoder_offset(self):
        for p in POINTS:
            self.assertEqual(p.output_center_hz-p.input_center_hz,
                             (p.relay_tx_mhz-p.relay_rx_mhz)*1000000)
            self.assertEqual(p.output_center_hz-p.receiver_lo_hz, -250000)
            self.assertLess(p.receiver_lo_hz, 3000000000)

    def test_unknown_point_and_strong_output_rejected_without_board_access(self):
        s = self.source()
        for point, att in [(FrequencyPoint('unknown', 4000, 5000), 60),
                           (POINTS[1], 49), (POINTS[1], True)]:
            with self.assertRaises(ValueError):
                s.prepare_message(point, 'test', '1234abcd', 1, att)
        s._prepare_waveform.assert_not_called()
        s.verify_binding.assert_not_called()

    def test_retune_requires_idle_and_powerdown(self):
        s = self.source()
        s.read.return_value = '0'
        with self.assertRaises(RuntimeError):
            s.tune_muted(POINTS[2])
        s.configure_if_changed.assert_not_called()
        s.read.return_value = '1'
        self.assertEqual(s.tune_muted(POINTS[2]), 1989000000)
        s.configure_if_changed.assert_called_once_with('out_altvoltage1_TX_LO_frequency', 1989000000, 10)

    def test_write_cannot_enable_tx_or_modify_second_tx_or_expand_band(self):
        s = self.source()
        with patch('sw.tools.rf_frequency_probe._verify_runtime_binding'), \
             patch('sw.tools.rf_frequency_probe.Console.write', return_value='2450000000') as write:
            for name, value in [('out_altvoltage1_TX_LO_powerdown', 0),
                                ('out_voltage1_hardwaregain', -50),
                                ('out_altvoltage1_TX_LO_frequency', 5800000000)]:
                with self.assertRaises(ValueError):
                    s.write('/phy/'+name, value)
            write.assert_not_called()
            s.write('/phy/out_altvoltage1_TX_LO_frequency', 2450000000, 10)
            self.assertEqual(write.call_count, 1)
            s.owned = False
            with self.assertRaises(RuntimeError):
                s.write('/phy/out_altvoltage1_TX_LO_frequency', 2450000000, 10)

    def test_receiver_extension_does_not_expand_base_probe(self):
        c = receiver()
        with self.assertRaises(ValueError):
            c.configure(2900750000)
        c.__class__ = FrequencyProbeReceiver
        with patch('sw.tools.rf_channel_probe.Console.write', side_effect=lambda _, p, v, t=0: str(v), autospec=True):
            self.assertEqual(c.configure(2900750000)['rx_lo_hz_readback'], 2900750000)
        # A changed actual LO must be caught before any capture, not normalized.
        with self.assertRaisesRegex(RuntimeError, 'LO changed'):
            c._read_configuration()
        with self.assertRaises(ValueError):
            c.configure(5800750000)

    def test_manifest_frequency_is_not_used_as_received_text(self):
        s = self.source()
        m = s.prepare_message(POINTS[2], '高频验证', '1234abcd', 7)
        self.assertEqual(m['application']['text'], '高频验证')
        self.assertEqual(m['output_center_hz'], 2179500000)
        call = s._prepare_waveform.call_args
        self.assertEqual(call.kwargs['lo_hz'], 1989000000)
        self.assertEqual(call.kwargs['attenuation_db'], 60)
        self.assertEqual(len(call.args[0]), call.kwargs['block_samples']*4)


if __name__ == '__main__':
    unittest.main()
