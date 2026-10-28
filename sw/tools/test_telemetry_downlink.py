"""Synthetic/offline protocol tests; never radio acceptance evidence."""
import struct
import unittest
import numpy as np
try:
    from . import telemetry_downlink as tm
except ImportError:
    import telemetry_downlink as tm


def payload():
    p = bytearray(96)
    p[:6] = b'ATM1\x01\x3f'
    struct.pack_into('>6I', p, 8, 7, 1234, 9, 4, 2, 1)
    struct.pack_into('>IBBHH', p, 32, 9, 3, 201, 900, 1000)
    struct.pack_into('>IBBHHHBxi', p, 42, 7, 1, 199, 800, 950, 0x1234, 3, -2)
    struct.pack_into('>IBBHHHiQQ', p, 60, 8, 4, 198, 700, 900, 0xabcd, 0, 700000001, 899999998)
    return bytes(p)


def frame():
    p = payload()
    return b'\xaa\xaa\x60'+p+struct.pack('>H', tm.phy.crc16(p))


class TelemetryTests(unittest.TestCase):
    def test_three_independent_sources_and_exact_hz(self):
        value = tm.parse_frame(frame())
        self.assertEqual([value[k]['origin'] for k in ('decoded_record', 'send_record', 'ack_record')], [3, 1, 4])
        self.assertEqual(value['ack_record']['tx_hz'], 899999998)
        self.assertEqual(value['send_record']['rc'], -2)
        self.assertEqual(value['sequence'], 7)
        self.assertIsNone(value['boot_identity'])

    def test_reject_corruption_and_semantics(self):
        p = bytearray(payload())
        for index, value in [(4, 2), (5, 0xff), (6, 1), (36, 0), (55, 1), (75, 1), (92, 1)]:
            bad = p.copy(); bad[index] = value
            with self.assertRaises(ValueError): tm.parse_payload(bytes(bad))
        bad = bytearray(frame()); bad[-1] ^= 1
        with self.assertRaises(ValueError): tm.parse_frame(bytes(bad))
        with self.assertRaises(ValueError): tm.parse_payload(payload()[:-1])
        bad = p.copy(); bad[5] &= ~8
        with self.assertRaises(ValueError): tm.parse_payload(bytes(bad))

    def test_synthetic_blind_iq_roundtrip_and_no_expected_state(self):
        # Synthetic verification only: periodic reference shaping, unknown CFO,
        # phase and arbitrary sample start. Raw receiver representation is 12bit.
        bits = np.unpackbits(np.frombuffer(frame(), dtype=np.uint8))
        sps = 25
        up = np.zeros(len(bits)*sps*6)
        up[::sps] = np.tile(1-2*bits.astype(float), 6)
        shaped = np.convolve(up, tm.phy.srrc(.35, sps, span=8), 'same')
        z = shaped*np.exp(1j*(.71+2*np.pi*503123*np.arange(len(up))/2500000))
        z = z[127:127+65536]
        raw = np.rint(np.column_stack((z.real, z.imag))*1000).astype('<i2').tobytes()
        report = tm.decode_capture(raw)
        self.assertGreaterEqual(report['valid_telemetry_count'], 2)
        self.assertTrue(all(s['sequence'] == 7 for s in report['telemetry']))
        self.assertEqual(report['ber'], None)
        quiet = bytes(65536*4)
        self.assertEqual(tm.decode_capture(quiet)['valid_telemetry_count'], 0)

    def test_synthetic_finite_rectangular_pl_burst(self):
        # Matches proposed PL bit scheduling (rectangular BPSK, not SRRC).
        # This tests a chosen aligned receive window, never acquisition timing
        # or DAC analog behavior. A one-shot burst requires receiver coordination.
        burst = b'\xaa'*8+frame()*4+b'\xaa'*8
        self.assertEqual(len(burst), 420)
        symbols = 1-2*np.unpackbits(np.frombuffer(burst, dtype=np.uint8)).astype(float)
        baseband = np.repeat(symbols, 25)
        self.assertEqual(len(baseband), 84000)  # 33.6ms @ 2.5MSPS
        for polarity in (-1, 1):
            z = polarity*baseband*np.exp(1j*(1.12+2*np.pi*(-247931)*np.arange(len(baseband))/2500000))
            window = z[531:531+65536]
            raw = np.rint(np.column_stack((window.real, window.imag))*500).astype('<i2').tobytes()
            report = tm.decode_capture(raw, expected_offset_hz=-250000)
            self.assertGreaterEqual(report['valid_telemetry_count'], 2)
            self.assertTrue(all(s['ack_record']['origin'] == 4 for s in report['telemetry']))


if __name__ == '__main__':
    unittest.main()
