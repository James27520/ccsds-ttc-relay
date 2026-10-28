"""Offline G1 envelope/duplicate/blind-IQ tests; no device access."""
import json
from pathlib import Path
import subprocess
import sys
import unittest

import numpy as np

try:
    from . import protocol
except ImportError:  # Also support unittest discovery directly in this directory.
    import protocol


def receiver_capture(iq, *, transmit_offset=500_000, receive_offset=-250_000,
                     frequency_error=0, phase=0, start=0, noise=3, seed=4):
    """Simulate the RX ADC, not TX's full-scale signed-16 DAC representation."""
    base = iq[:, 0].astype(float) + 1j * iq[:, 1]
    n = protocol.CAPTURE_SAMPLES
    signal = np.tile(base, (n + start) // len(base) + 2)[start:start + n]
    time = (np.arange(n) + start) / 2_500_000
    signal *= np.exp(2j * np.pi *
                     (receive_offset - transmit_offset + frequency_error) * time + 1j * phase)
    signal *= 450 / max(abs(base))
    rng = np.random.default_rng(seed)
    signal += noise * (rng.normal(size=n) + 1j * rng.normal(size=n)) + 3 - 2j
    adc = np.rint(np.column_stack((signal.real, signal.imag)))
    assert adc.min() >= -2048 and adc.max() <= 2047
    return adc.astype("<i2").tobytes()


class EnvelopeTests(unittest.TestCase):
    def test_exact_wire_and_utf8_byte_boundaries(self):
        for body, size in [("a", 1), ("x" * 32, 32), ("测" * 10 + "ab", 32),
                           ("😀" * 8, 32), (" :\n\x00", 4)]:
            with self.subTest(body=body):
                wire = protocol.encode_message(body, "0123abcd", 65535)
                self.assertEqual(wire, "G1:0123abcd:ffff:" + body)
                message = protocol.parse_message(wire)
                self.assertEqual(message, dict(message_id="0123abcd:ffff",
                                               session_id="0123abcd", sequence=65535,
                                               text=body, payload_bytes=size))
        self.assertEqual(protocol.parse_message("G1:00000000:0000:x")["sequence"], 0)

    def test_bad_body_id_sequence_and_strict_utf8(self):
        for body in ["", "a" * 33, "测" * 11, "😀" * 9, "\ud800", b"ok", None]:
            with self.subTest(body=repr(body)), self.assertRaises(ValueError):
                protocol.encode_message(body, "0123abcd", 0)
        for session in ["0123ABCd", "0123abc", "0123abcd0", " 123abcd", "0123abcg", 12, None]:
            with self.subTest(session=session), self.assertRaises(ValueError):
                protocol.encode_message("x", session, 0)
        for sequence in [-1, 65536, True, 1.0, "0001", None]:
            with self.subTest(sequence=sequence), self.assertRaises(ValueError):
                protocol.encode_message("x", "0123abcd", sequence)

    def test_old_text_and_noncanonical_envelopes_are_not_messages(self):
        for payload in ["hello world", "relay test1", "relay test2", "G1:0123abcd:0001:",
                        "G0:0123abcd:0001:x", " G1:0123abcd:0001:x",
                        "G1:0123abcd:001:x", "G1:0123abcd:00001:x",
                        "G1:0123ABCD:0001:x", "G1:0123abcd:000A:x",
                        "G1:0123abcd:０００１:x", "G1:0123abcd:0001:" + "测" * 11,
                        "G1:0123abcd:0001:\udfff", b"G1:0123abcd:0001:x", None]:
            with self.subTest(payload=repr(payload)), self.assertRaises(ValueError):
                protocol.parse_message(payload)

    def test_random_session_and_import_has_no_path_side_effects(self):
        sessions = [protocol.new_session_id() for _ in range(64)]
        self.assertEqual(len(set(sessions)), len(sessions))
        for session in sessions:
            self.assertRegex(session, r"\A[0-9a-f]{8}\Z")
        script = ("import sys; before=sys.path[:]; "
                  "from sw.ground_station import protocol; "
                  "assert sys.path == before; "
                  "assert protocol.parse_message('G1:1234abcd:0000:x')['text']=='x'")
        result = subprocess.run([sys.executable, "-c", script],
                                cwd=Path(__file__).resolve().parents[2],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


class TrackerTests(unittest.TestCase):
    @staticmethod
    def message(body="x", session="0123abcd", sequence=0):
        return protocol.parse_message(protocol.encode_message(body, session, sequence))

    def test_repeat_conflict_and_independent_sessions(self):
        tracker = protocol.MessageTracker()
        original = self.message()
        self.assertEqual(tracker.observe(original), "new")
        self.assertEqual(tracker.observe(original), "duplicate")
        self.assertEqual(tracker.observe(self.message("changed")), "conflict")
        self.assertEqual(tracker.observe(original), "duplicate")
        self.assertEqual(tracker.observe(self.message(session="1123abcd")), "new")
        self.assertEqual(tracker.observe(self.message(sequence=1)), "new")
        self.assertEqual(len(tracker), 3)

    def test_lru_bounded_and_invalid_tracker_inputs(self):
        tracker = protocol.MessageTracker(capacity=2)
        first, second, third = (self.message(sequence=k) for k in range(3))
        self.assertEqual(tracker.observe(first), "new")
        self.assertEqual(tracker.observe(second), "new")
        self.assertEqual(tracker.observe(first), "duplicate")
        self.assertEqual(tracker.observe(third), "new")
        self.assertEqual(len(tracker), 2)
        self.assertEqual(tracker.observe(second), "new")
        for capacity in [0, -1, True, 1.5]:
            with self.assertRaises(ValueError):
                protocol.MessageTracker(capacity)
        invalid = dict(first, message_id="forged")
        with self.assertRaises(ValueError):
            tracker.observe(invalid)


class BlindCaptureTests(unittest.TestCase):
    def test_unknown_body_phase_offset_and_maximum_utf8_body(self):
        cases = [("first message", 1234.5, 1.13, 417, -250_000),
                 ("测试成功", -1791.2, -2.1, 1729, -250_000),
                 ("😀" * 8, 6999.0, 2.8, 3107, 750_000)]
        for sequence, (body, cfo, phase, start, offset) in enumerate(cases):
            with self.subTest(body=body):
                iq, manifest = protocol.generate_message_iq(body, "0123abcd", sequence)
                self.assertEqual(manifest["application"]["text"], body)
                self.assertEqual(manifest["text"], protocol.encode_message(body, "0123abcd", sequence))
                # No manifest/body is supplied to the receiver, only raw ADC IQ.
                raw = receiver_capture(iq, frequency_error=cfo, phase=phase,
                                       start=start, receive_offset=offset, seed=sequence)
                report = protocol.decode_capture(raw, expected_offset_hz=offset)
                self.assertEqual(report["samples"], 32768)
                self.assertGreaterEqual(len(report["messages"]), 1)
                self.assertEqual(report["valid_message_count"], report["valid_frame_count"])
                self.assertTrue(all(message["text"] == body for message in report["messages"]))
                self.assertTrue(all(message["message_id"] == f"0123abcd:{sequence:04x}"
                                    for message in report["messages"]))
                self.assertLess(abs(report["carrier_offset_hz"] - (offset + cfo)), 30)
                self.assertIsNone(report["ber"])
                json.dumps(report, ensure_ascii=True, allow_nan=False)

    def test_crc_damage_rejected_before_application_parse(self):
        iq, manifest = protocol.generate_message_iq("damaged", "0123abcd", 7, corrupt_crc=True)
        self.assertTrue(manifest["test_only"])
        report = protocol.decode_capture(receiver_capture(iq, phase=.7, start=811, noise=0))
        self.assertEqual(report["messages"], [])
        self.assertEqual(report["valid_frame_count"], 0)
        self.assertGreater(report["crc_rejected_frames"], 0)

    def test_crc_valid_legacy_and_malformed_application_frames_stay_out(self):
        for text in ["hello world", "relay test1", "G1:0123ABCD:0001:hi"]:
            with self.subTest(text=text):
                iq, _ = protocol._link.generate_iq(text)
                report = protocol.decode_capture(receiver_capture(iq, phase=1.2, start=232))
                self.assertGreater(report["valid_frame_count"], 0)
                self.assertEqual(report["messages"], [])

    def test_receiver_rejects_dac_codes_and_incomplete_raw_groups(self):
        iq, _ = protocol.generate_message_iq("x", "0123abcd", 0)
        for raw in [iq.tobytes(), b"", b"abc"]:
            with self.assertRaises(ValueError):
                protocol.decode_capture(raw)


if __name__ == "__main__":
    unittest.main()
