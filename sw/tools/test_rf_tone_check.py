"""Numerical checks for the conducted-tone measurement, without hardware."""
import unittest

import numpy as np

from rf_tone_check import analyze


class ToneAnalysisTests(unittest.TestCase):
    def test_positive_and_negative_off_bin_tones(self):
        fs, n, amplitude = 2500000, 8192, 200
        for frequency in (-250075, 749937):
            with self.subTest(frequency=frequency):
                tone = amplitude*np.exp(2j*np.pi*frequency*np.arange(n)/fs)
                raw = np.rint(np.column_stack((tone.real, tone.imag))).astype('<i2').tobytes()
                got = analyze(raw, fs, frequency)
                self.assertLess(abs(got['peak_offset_hz']-frequency), 10)
                self.assertAlmostEqual(got['band_power_dbfs'], 20*np.log10(amplitude/2048), delta=.1)
                self.assertEqual(got['clip_components'], 0)

    def test_silence_is_not_positive_evidence(self):
        got = analyze(bytes(8192*4), 2500000, -250000)
        self.assertEqual(got['rms_codes'], 0)
        self.assertLess(got['band_to_median_noise_db'], 0)
        self.assertLess(got['band_power_dbfs'], -200)

    def test_invalid_capture_and_format(self):
        for raw in (b'', b'abc', bytes(31*4), np.array([2048, 0]*32, dtype='<i2').tobytes()):
            with self.subTest(size=len(raw)), self.assertRaises(ValueError):
                analyze(raw, 2500000, -250000)

    def test_invalid_frequency_plan(self):
        for fs, offset, width in [(0, 0, 20000), (float('nan'), 0, 20000),
                                  (2500000, float('inf'), 20000), (2500000, 1240000, 20000),
                                  (2500000, -250000, 1), (2500000, 0, -1)]:
            with self.subTest(fs=fs, offset=offset, width=width), self.assertRaises(ValueError):
                analyze(bytes(8192*4), fs, offset, search_hz=width)

    def test_adc_rails_are_counted(self):
        raw = np.zeros((8192, 2), dtype='<i2')
        raw[10] = [-2048, 2047]
        got = analyze(raw.tobytes(), 2500000, -250000)
        self.assertEqual(got['clip_components'], 2)


if __name__ == '__main__':
    unittest.main()
