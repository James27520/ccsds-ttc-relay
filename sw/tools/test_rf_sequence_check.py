"""Offline sequence accounting, including decisions rejected by frame CRC."""
import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from rf_sequence_check import generate_sequence, analyze_sequence, _shape, main
from rf_text_link import build_frame, FS


def receive(iq, offset=-250_000, phase=.73, start=0, length=None):
    z = iq[:, 0].astype(float)+1j*iq[:, 1]
    z = np.roll(z, -start)
    if length:
        z = z[:length]
    z *= .25*np.exp(1j*(2*np.pi*(offset-500_000)*np.arange(len(z))/FS+phase))
    return np.rint(np.column_stack((z.real, z.imag))).astype("<i2").tobytes()


class SequenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.iq, cls.manifest = generate_sequence()

    def test_sequence_shape_and_mapping(self):
        self.assertEqual(self.iq.shape, (25600, 2))
        self.assertEqual(self.iq.nbytes, 102400)
        self.assertEqual(self.iq.dtype.str, "<i2")
        self.assertEqual(self.manifest["frames"][0]["text"], "SEQ000:ABCD")
        self.assertEqual(self.manifest["frames"][-1]["text"], "SEQ007:ABCD")
        report = analyze_sequence(receive(self.iq), self.manifest, -250_000)
        self.assertTrue(report["passed"])
        self.assertGreater(report["conditional_compared_bits"], 1000)
        self.assertEqual(report["conditional_bit_errors"], 0)
        json.dumps(report, allow_nan=False)

    def test_wrap_truncated_start_and_positive_branch(self):
        # Start partway through frame 6; accepted frames include 7 -> 0.
        raw = receive(self.iq, 750_731, phase=2.8, start=6*3200+537, length=12000)
        report = analyze_sequence(raw, self.manifest, 750_000)
        self.assertTrue(report["passed"])
        self.assertEqual(report["conditional_bit_errors"], 0)
        self.assertTrue(any(t["from_seq"] == 7 and t["to_seq"] == 0
                            and t["sample_delta"] == 3200 and t["consistent"]
                            for t in report["sequence_transitions"]))
        self.assertAlmostEqual(report["blind_decode"]["carrier_offset_hz"], 750_731, delta=20)

    def test_whole_sequence_cyclic_filter_boundary(self):
        frames = [bytes.fromhex(f["frame_hex"]) for f in self.manifest["frames"]]
        # An independently expanded two-period block must have the same shaped
        # first/last frame boundaries as looping the one-period output.
        expanded = _shape(frames*2, .1)
        np.testing.assert_array_equal(expanded, np.tile(self.iq, (2, 1)))
        self.assertGreater(np.linalg.norm(self.iq[0]), 0)
        self.assertGreater(np.linalg.norm(self.iq[-1]), 0)

    def test_wrong_order_and_payload(self):
        frames = [bytes.fromhex(f["frame_hex"]) for f in self.manifest["frames"]]
        frames[2], frames[3] = frames[3], frames[2]
        report = analyze_sequence(receive(_shape(frames, .1)), self.manifest, -250_000)
        self.assertFalse(report["passed"])
        self.assertGreater(report["conditional_bit_errors"], 0)
        self.assertTrue(any(not t["consistent"] for t in report["sequence_transitions"]))
        frames[2] = build_frame("SEQ002:WXYZ")
        report = analyze_sequence(receive(_shape(frames, .1)), self.manifest, -250_000)
        self.assertGreater(report["unexpected_payload_frames"], 0)
        self.assertFalse(report["passed"])

    def test_single_bit_error_survives_crc_filtering(self):
        frames = [bytes.fromhex(f["frame_hex"]) for f in self.manifest["frames"]]
        damaged = bytearray(frames[3])
        damaged[9] ^= 1  # Payload bit only; retain the original CRC.
        frames[3] = bytes(damaged)
        report = analyze_sequence(receive(_shape(frames, .1)), self.manifest, -250_000)
        self.assertFalse(report["acquisition_failed"])
        self.assertFalse(report["passed"])
        self.assertEqual(report["conditional_bit_errors"], 1)
        self.assertEqual(report["conditional_compared_bits"], 1016)
        self.assertGreater(report["blind_decode"]["crc_rejected_frames"], 0)
        self.assertTrue(any(t["frame_steps"] == 2 and t["unaccepted_frame_slots"] == 1
                            for t in report["sequence_transitions"]))

    def test_no_anchor_keeps_window_explicit(self):
        rng = np.random.default_rng(9)
        for iq in [rng.integers(-10, 11, size=(8192, 2), dtype=np.int16),
                   np.zeros((8192, 2), dtype=np.int16)]:
            report = analyze_sequence(iq.astype("<i2").tobytes(), self.manifest, -250_000)
            self.assertTrue(report["acquisition_failed"])
            self.assertFalse(report["passed"])
            self.assertGreater(report["decision_bits"], 300)
            self.assertEqual(report["conditional_compared_bits"], 0)
            self.assertIsNone(report["ber"])

    def test_invalid_inputs(self):
        for count in [0, 1001, True, 1.5]:
            with self.assertRaises(ValueError):
                generate_sequence(count)
        for amp in [0, -1, 1.01, float("nan")]:
            with self.assertRaises(ValueError):
                generate_sequence(amplitude=amp)
        for key, value in [("count", 7), ("frame_bits", 127), ("sample_rate_hz", 1),
                           ("sha256", "z"*64), ("frames", [])]:
            manifest = copy.deepcopy(self.manifest)
            manifest[key] = value
            with self.assertRaises(ValueError):
                analyze_sequence(receive(self.iq), manifest, -250_000)
        manifest = copy.deepcopy(self.manifest)
        manifest["frames"][3]["seq"] = 1
        with self.assertRaises(ValueError):
            analyze_sequence(receive(self.iq), manifest, -250_000)
        with self.assertRaises(ValueError):
            analyze_sequence(np.full((8192, 2), 2048, dtype="<i2").tobytes(), self.manifest, -250_000)

    def test_cli_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)/"sequence"
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["generate", "--out", str(out)]), 0)
            before = (out/"iq_s16le.bin").read_bytes()
            with self.assertRaises(FileExistsError):
                main(["generate", "--out", str(out)])
            self.assertEqual((out/"iq_s16le.bin").read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
