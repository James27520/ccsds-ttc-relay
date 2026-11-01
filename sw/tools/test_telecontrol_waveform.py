"""Offline protocol, periodic waveform and file contract tests."""
import contextlib
import binascii
import hashlib
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest

import numpy as np

try:
    from . import telecontrol_waveform as w
except ImportError:
    import telecontrol_waveform as w


class WaveformTests(unittest.TestCase):
    def test_khz_golden_vector_crc_frame_and_legacy_operation_vectors(self):
        body = w.build_body(rx_hz=1991845000, tx_hz=2192956000, seq=37)
        self.assertEqual(body.hex(), '813930a05b250cf5')
        self.assertEqual(int.from_bytes(body[-2:], 'big'), binascii.crc_hqx(body[:6], 0xffff))
        bits, _ = w.build_cadu(body)
        self.assertEqual(len(bits), 160)
        self.assertEqual(np.packbits(bits).tobytes().hex(), '1acffc1d6f35361c647e3550724117084338067e')
        for op, golden in [('frequency', '018403e80307579e'), ('enable', '218403e803076296'),
                           ('stop', '228403e80307ac76'), ('status', '238403e80307e9d6')]:
            self.assertEqual(w.build_body(900, 1000, 7, op).hex(), golden)

    def test_khz_edges_independent_pair_and_stop_ignored_fields(self):
        for rx_offset, tx_offset in [(100, 29900), (29900, 100), (101, 12345)]:
            body = w.build_body(rx_hz=1979500000+rx_offset*1000,
                                tx_hz=2169500000+tx_offset*1000, seq=255, operation='enable')
            self.assertEqual(struct.unpack('<BHHB', body[:6]), (0xa1, rx_offset, tx_offset, 255))
        for operation, version in [('stop', 0xa2), ('status', 0xa3)]:
            body = w.build_body(seq=0, operation=operation, encoding='n256_khz_v1',
                                rx_hz='invalid draft', tx_hz=float('nan'))
            self.assertEqual(struct.unpack('<BHHB', body[:6]), (version, 0, 0, 0))
        for bad in (1979599000, 2009401000, 1991845001, 1991845000.0, True):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                w.build_body(rx_hz=bad, tx_hz=2192956000, seq=1)
        for changes in (dict(encoding='unknown'), dict(rx=900), dict(seq=True)):
            values = dict(rx_hz=1991845000, tx_hz=2192956000, seq=1)
            values.update(changes)
            with self.assertRaises(ValueError):
                w.build_body(**values)

    def test_khz_cli_manifest_retains_exact_hz_and_no_mhz_offsets(self):
        with tempfile.TemporaryDirectory() as root:
            out = Path(root)/'khz'
            with contextlib.redirect_stdout(io.StringIO()):
                w.main(['--mode', 'cmd', '--rx-hz', '1991845000', '--tx-hz', '2192956000',
                        '--seq', '37', '--out', str(out)])
            manifest = json.loads((out/'manifest.json').read_text())
            self.assertEqual(manifest['body_hex'], '813930a05b250cf5')
            self.assertEqual(manifest['encoding'], 'n256_khz_v1')
            self.assertEqual(manifest['rx_hz'], 1991845000)
            self.assertEqual(manifest['tx_offset_khz'], 23456)
            self.assertNotIn('rx_mhz', manifest)
            self.assertEqual(len((out/'iq_s16le.bin').read_bytes()), 16000)

    def test_golden_vectors(self):
        vectors = [
            (100, 2450, 0, "01640092090077ab", "1acffc1dbcd9014c82bf4b2c0b3894c10ddfdc50"),
            (120, 1000, 1, "017800e8030118f9", "1acffc1dbcd902e425bf7178a92646027b434d99"),
            (2400, 2450, 7, "0160099209077d3d", "1acffc1dbcd90178796fe89c0b3894fb8771de0a"),
        ]
        for rx, tx, seq, body_hex, frame_hex in vectors:
            with self.subTest(seq=seq):
                body = w.build_body(rx, tx, seq)
                self.assertEqual(body.hex(), body_hex)
                bits, _ = w.build_cadu(body)
                self.assertEqual(len(bits), 160)
                self.assertEqual(np.packbits(bits).tobytes().hex(), frame_hex)

    def test_invalid_values_do_not_wrap(self):
        for args in [(69, 1000, 0), (6001, 1000, 0), (900, 65536, 0),
                     (900, 1000, -1), (900, 1000, 256), (900.0, 1000, 0),
                     (True, 1000, 0), (900, 1000, 1.5)]:
            with self.subTest(args=args), self.assertRaises(ValueError):
                w.build_body(*args)
        for amplitude in (0, -0.1, 1.01, float("nan"), float("inf"), True):
            with self.subTest(amplitude=amplitude), self.assertRaises(ValueError):
                w.command_iq(900, 1000, 1, amplitude)

    def test_tone_is_positive_single_side(self):
        iq = w.tone_iq()
        signal = iq[:, 0].astype(float) + 1j * iq[:, 1]
        spectrum = abs(np.fft.fft(signal)) ** 2
        self.assertEqual(int(spectrum.argmax()), 800)
        self.assertGreater(spectrum[800] / max(spectrum[-800], 1), 1e8)
        self.assertLess(abs(np.max(abs(signal)) / 32767 - 0.1), 3e-5)

    def test_periodic_shaping_matches_two_period_interior(self):
        bits, _ = w.build_cadu(w.build_body(900, 1000, 5))
        up = np.zeros(4 * w.FRAME_SAMPLES)
        up[::w.SPS] = np.tile(np.where(bits == 0, 1.0, -1.0), 4)
        filtered = np.convolve(up, w.srrc(w.BETA, w.SPS, span=w.SPAN), "same")
        bb = filtered[w.FRAME_SAMPLES:3 * w.FRAME_SAMPLES]
        phase = np.exp(2j * np.pi * w.OFFSET_HZ * np.arange(len(bb)) / w.FS)
        expected = w._quantize(bb * phase, 0.1)
        actual = np.tile(w.command_iq(900, 1000, 5), (2, 1))
        np.testing.assert_array_equal(actual, expected)
        # A zero-padded single frame has different boundary samples.
        single = up[:w.FRAME_SAMPLES]
        padded = np.convolve(single, w.srrc(w.BETA, w.SPS, span=w.SPAN), "same")
        self.assertGreater(np.max(abs(padded[:100] - bb[:100])), 1e-3)
        self.assertTrue(np.any(actual[:25]))
        self.assertTrue(np.any(actual[-25:]))

    def test_cli_files_endian_hash_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as root:
            out = Path(root) / "reference"
            argv = ["--mode", "cmd", "--rx", "900", "--tx", "1000",
                    "--seq", "9", "--out", str(out)]
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(w.main(argv), 0)
            raw = (out / "iq_s16le.bin").read_bytes()
            manifest = json.loads((out / "manifest.json").read_text())
            self.assertEqual(len(raw), 16000)
            iq = w.command_iq(900, 1000, 9)
            self.assertEqual(iq.shape, (4000, 2))
            self.assertEqual(iq.dtype, np.dtype("<i2"))
            self.assertEqual(raw[:80], struct.pack("<40h", *iq.ravel()[:40]))
            self.assertEqual(manifest["complex_samples"], 4000)
            self.assertEqual(manifest["byte_count"], len(raw))
            self.assertEqual(manifest["sha256"], hashlib.sha256(raw).hexdigest())
            self.assertEqual(manifest["source"], "OFFLINE_REFERENCE")
            self.assertEqual(manifest["frame_bits"], 160)
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                w.main(argv)
            self.assertEqual((out / "iq_s16le.bin").read_bytes(), raw)

    def test_cli_rejects_missing_or_invalid_without_output(self):
        with tempfile.TemporaryDirectory() as root:
            out = Path(root) / "absent"
            cases = [["--mode", "cmd", "--rx", "900", "--tx", "1000"],
                     ["--mode", "cmd", "--rx", "65536", "--tx", "1000", "--seq", "0"],
                     ["--mode", "tone", "--amplitude", "nan"],
                     ["--mode", "tone", "--seq", "0"]]
            for args in cases:
                with self.subTest(args=args), contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit):
                        w.main(args + ["--out", str(out)])
                    self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
