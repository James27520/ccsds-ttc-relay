"""Offline ATM1 byte fixtures; not physical acquisition acceptance evidence."""
import binascii
import copy
import json
import struct
import unittest

from .tc_evidence import assess_transaction
from .telemetry import TM1_FIELDS


def atm1_frame(frozen, sequence=17, uptime=2200):
    """Real 96-byte wire layout from adda_telemetry_tx.c, including outer CRC."""
    payload = bytearray(96)
    flags = (frozen['network'] | frozen['armed'] << 1 | frozen['pending'] << 2 |
             frozen['d_valid'] << 3 | frozen['s_valid'] << 4 | frozen['a_valid'] << 5)
    payload[:6] = b'ATM1'+bytes([1, flags])
    struct.pack_into('>6I', payload, 8, sequence, uptime, frozen['events'], frozen['decoded'],
                     frozen['applied'], frozen['failures'])
    for prefix, offset in [('d', 32), ('s', 42), ('a', 60)]:
        struct.pack_into('>IBBHH', payload, offset, frozen[prefix+'_event'],
                         frozen[prefix+'_origin'], frozen[prefix+'_air_seq'],
                         frozen[prefix+'_rx_mhz'], frozen[prefix+'_tx_mhz'])
    struct.pack_into('>HBxi', payload, 52, frozen['s_udp_seq'], frozen['s_count'], frozen['s_rc'])
    struct.pack_into('>HiQQ', payload, 70, frozen['a_udp_seq'], frozen['a_rc'],
                     frozen['a_rx_hz'], frozen['a_tx_hz'])
    return dict(payload_hex=payload.hex(), crc16=binascii.crc_hqx(payload, 0xffff),
                crc_valid=True)


def evidence():
    request = dict(rx_mhz=900, tx_mhz=1001, air_seq=164)
    before = dict.fromkeys(TM1_FIELDS, 0)
    before.update(uptime_ms=1000, events=20, decoded=3, applied=2)
    frozen = dict(before, uptime_ms=2000, events=23, decoded=4, applied=3,
                  s_udp_seq=87, s_count=1, s_rc=0, a_udp_seq=87, a_rc=0,
                  a_rx_hz=900_000_123, a_tx_hz=1_000_999_999)
    for prefix, event in [('d', 21), ('s', 22), ('a', 23)]:
        frozen.update({prefix+'_valid': 1, prefix+'_event': event, prefix+'_origin': 1})
        frozen.update({prefix+'_'+key: value for key, value in request.items()})
    spi = dict(relay_rx_hz_readback=900_000_124, relay_tx_hz_readback=1_001_000_000,
               relay_tx_atten_db_readback=89, relay_rx_gain_db_readback=0)
    frame = atm1_frame(frozen)
    report = dict(frames=[dict(frame, first_symbol_sample=1000+i*20200) for i in range(4)],
                  telemetry=[], valid_telemetry_count=0, unique_snapshot_count=999)
    return [request, before, frozen, spi, report, 17]


class TransactionEvidenceTests(unittest.TestCase):
    def test_real_atm1_layout_duplicate_physical_frames_are_one_transaction(self):
        values = evidence()
        result = assess_transaction(*values)
        self.assertEqual(result['passed'], True)
        self.assertEqual(result['rf_source'], 'actual_iq_crc_checked')
        self.assertEqual(result['physical_frame_count'], 4)
        self.assertEqual(result['unique_snapshot_count'], 1)
        self.assertEqual(result['transaction']['air_seq'], 164)
        self.assertEqual(result['transaction']['udp_seq'], 87)
        self.assertEqual(result['ack']['rx_hz'], 900_000_123)
        self.assertEqual(result['spi']['rx_hz'], 900_000_124)
        self.assertEqual(json.loads(json.dumps(result, allow_nan=False)), result)

    def test_inputs_are_not_mutated(self):
        values = evidence()
        saved = copy.deepcopy(values)
        assess_transaction(*values)
        self.assertEqual(values, saved)

    def test_fake_summary_cannot_replace_frames_or_hide_bad_crc(self):
        for frames in ([], [dict(atm1_frame(evidence()[2]), crc16=0)]):
            values = evidence()
            values[4].update(frames=frames, telemetry=[{'passed': True, 'origin': 1}],
                             valid_telemetry_count=999, unique_snapshot_count=1)
            with self.assertRaises(ValueError):
                assess_transaction(*values)

    def test_crc_is_recomputed_even_with_true_crc_valid_flag(self):
        values = evidence()
        frame = values[4]['frames'][0]
        payload = bytearray.fromhex(frame['payload_hex'])
        payload[40] ^= 1
        frame['payload_hex'] = payload.hex()
        with self.assertRaisesRegex(ValueError, 'CRC'):
            assess_transaction(*values)

    def test_wrong_origin_commands_udp_and_receipts_rejected(self):
        changes = [('d_origin', 2), ('s_origin', 3), ('a_origin', 4), ('d_valid', 0),
                   ('s_valid', 0), ('a_valid', 0), ('d_air_seq', 163),
                   ('s_rx_mhz', 901), ('a_tx_mhz', 900), ('a_udp_seq', 88),
                   ('s_rc', -1), ('a_rc', -1), ('s_count', 0), ('s_count', 256)]
        for key, value in changes:
            with self.subTest(key=key, value=value):
                values = evidence()
                values[2][key] = value
                with self.assertRaises(ValueError):
                    assess_transaction(*values)

    def test_stale_reordered_or_multiple_applied_transactions_rejected(self):
        changes = [('d_event', 20), ('s_event', 21), ('a_event', 22), ('events', 24),
                   ('applied', 2), ('applied', 4), ('decoded', 3), ('failures', 1),
                   ('network', 1), ('armed', 1), ('pending', 1), ('uptime_ms', 999)]
        for key, value in changes:
            with self.subTest(key=key, value=value):
                values = evidence()
                values[2][key] = value
                with self.assertRaises(ValueError):
                    assess_transaction(*values)

    def test_rf_fields_must_match_frozen_state_even_when_crc_is_valid(self):
        changes = [('events', 24), ('decoded', 5), ('applied', 4), ('failures', 1),
                   ('network', 1), ('armed', 1), ('pending', 1), ('d_event', 20),
                   ('s_event', 20), ('a_event', 22), ('d_origin', 2), ('s_air_seq', 163),
                   ('a_rx_mhz', 1001), ('s_udp_seq', 88), ('s_count', 2),
                   ('s_rc', -2), ('a_rx_hz', 900_000_124)]
        for key, value in changes:
            with self.subTest(key=key, value=value):
                values = evidence()
                altered = dict(values[2], **{key: value})
                values[4]['frames'] = [atm1_frame(altered)]
                with self.assertRaises(ValueError):
                    assess_transaction(*values)

    def test_rf_sequence_and_uptime_bounds(self):
        for sequence, uptime, accepted in [(17, 1999, False), (17, 2000, True),
                                           (17, 122000, True), (17, 122001, False),
                                           (16, 2200, False), (18, 2200, False)]:
            with self.subTest(sequence=sequence, uptime=uptime):
                values = evidence()
                values[4]['frames'] = [atm1_frame(values[2], sequence, uptime)]
                if accepted:
                    self.assertTrue(assess_transaction(*values)['passed'])
                else:
                    with self.assertRaises(ValueError):
                        assess_transaction(*values)
        values = evidence()
        values[5] = 0xffffffff
        values[4]['frames'] = [atm1_frame(values[2], 0xffffffff)]
        self.assertTrue(assess_transaction(*values)['passed'])

    def test_two_distinct_snapshots_do_not_count_as_one_finite_send(self):
        values = evidence()
        values[4]['frames'].append(atm1_frame(values[2], uptime=2201))
        with self.assertRaisesRegex(ValueError, 'one unique'):
            assess_transaction(*values)

    def test_independent_spi_and_ack_must_match_target_and_each_other(self):
        for ack_offset, spi_offset, accepted in [(10000, 10000, True), (0, -10000, True),
                                                (10001, 0, False), (0, -10001, False),
                                                (10000, -10000, False)]:
            with self.subTest(ack_offset=ack_offset, spi_offset=spi_offset):
                values = evidence()
                values[2]['a_rx_hz'] = 900_000_000+ack_offset
                values[3]['relay_rx_hz_readback'] = 900_000_000+spi_offset
                values[4]['frames'] = [atm1_frame(values[2])]
                if accepted:
                    self.assertTrue(assess_transaction(*values)['passed'])
                else:
                    with self.assertRaises(ValueError):
                        assess_transaction(*values)
        values = evidence()
        values[3]['relay_rx_hz_readback'], values[3]['relay_tx_hz_readback'] = (
            values[3]['relay_tx_hz_readback'], values[3]['relay_rx_hz_readback'])
        with self.assertRaises(ValueError):
            assess_transaction(*values)

    def test_udp_storage_width_does_not_relax_actual_protocol_range(self):
        for seq, accepted in [(0, True), (0x3fff, True), (0x4000, False), (0xffff, False)]:
            with self.subTest(seq=seq):
                values = evidence()
                values[2].update(s_udp_seq=seq, a_udp_seq=seq)
                values[4]['frames'] = [atm1_frame(values[2])]
                if accepted:
                    self.assertTrue(assess_transaction(*values)['passed'])
                else:
                    with self.assertRaises(ValueError):
                        assess_transaction(*values)

    def test_bad_types_nonfinite_and_overflow_are_never_coerced(self):
        for bad in (True, False, '900', 900.0, float('nan'), float('inf'), -1, 6001):
            with self.subTest(bad=bad):
                values = evidence()
                values[0]['rx_mhz'] = bad
                with self.assertRaises(ValueError):
                    assess_transaction(*values)
        for index, key, bad in [(1, 'events', True), (2, 'applied', 3.0),
                                (2, 'uptime_ms', 1 << 32), (2, 'a_rx_hz', 1 << 64),
                                (3, 'relay_rx_hz_readback', '900000124'),
                                (3, 'relay_rx_hz_readback', True), (4, 'rms_codes', float('nan'))]:
            with self.subTest(index=index, key=key):
                values = evidence()
                values[index][key] = bad
                with self.assertRaises(ValueError):
                    assess_transaction(*values)
        for bad in (True, '17', 17.0, -1, 1 << 32):
            values = evidence()
            values[5] = bad
            with self.assertRaises(ValueError):
                assess_transaction(*values)

    def test_malformed_frame_evidence_and_missing_required_fields(self):
        for frame in (None, {}, {'payload_hex': '00', 'crc16': 0},
                      dict(atm1_frame(evidence()[2]), payload_hex='xx'*96),
                      dict(atm1_frame(evidence()[2]), crc16=True),
                      dict(atm1_frame(evidence()[2]), crc16=65536)):
            values = evidence()
            values[4]['frames'] = [frame]
            with self.assertRaises(ValueError):
                assess_transaction(*values)
        for index, key in [(0, 'air_seq'), (1, 'events'), (2, 's_count'),
                           (3, 'relay_rx_hz_readback'), (4, 'frames')]:
            values = evidence()
            del values[index][key]
            with self.assertRaises(ValueError):
                assess_transaction(*values)


if __name__ == '__main__':
    unittest.main()
