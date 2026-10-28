"""Offline protocol/evidence checks, not physical RF acceptance evidence."""
import binascii
import struct
import unittest
from unittest.mock import Mock

from sw.tools.telecontrol_waveform import build_body, command_iq, OPERATIONS
from sw.tools.telemetry_downlink import parse_payload, parse_frame, report_format
from .tc_live import assess_rf_reply
from .tc_hardware import CommandSource
from .test_tc_evidence import evidence, atm1_frame


def extended_fixture(operation='enable', *, rc=0, mode=None, gains=None, atten=None,
                     flags=None, remaining=None, actual_rx=900000123):
    request, _, state, _, _, _ = evidence()
    state.update(network=1, a_rc=rc, a_rx_hz=actual_rx)
    p = bytearray.fromhex(atm1_frame(state)['payload_hex']) + bytearray(16)
    p[:5] = b'ATM2\x02'
    p[6] = p[7] = p[55] = OPERATIONS[operation]
    active = operation == 'enable'
    struct.pack_into('>4B4I', p, 92,
        (1 if active else 2) if mode is None else mode,
        *(([30, 30] if active else [0, 0]) if gains is None else gains),
        (3 if active else 1) if flags is None else flags,
        *(([50000, 50000] if active else [89000, 89000]) if atten is None else atten),
        (299000 if active else 0) if remaining is None else remaining, 100000)
    request['operation'] = operation
    return request, dict(frames=[dict(payload_hex=p.hex(), crc16=binascii.crc_hqx(p, 0xffff))])


class RemoteRelayTests(unittest.TestCase):
    def test_atm2_report_can_be_rechecked_by_file_viewer(self):
        from .rf_telemetry_window import validated_snapshots
        _, report = extended_fixture()
        frame = report['frames'][0]
        frame['crc_valid'] = True
        snapshot = parse_payload(bytes.fromhex(frame['payload_hex']))
        report['format'] = report_format([snapshot])
        self.assertEqual(report['format'], 'EXPERIMENTAL_ATM2_RF')
        self.assertEqual(len(validated_snapshots(report)), 1)
        frame['crc16'] ^= 1
        self.assertEqual(validated_snapshots(report), [])

    def test_matching_source_settings_do_not_restart_calibration(self):
        source = CommandSource.__new__(CommandSource)
        source.owned=True; source._closed=False; source.phy='/phy'
        source.record=Mock(); source.write=Mock(); source.mute=Mock()
        for name, current, value, tolerance in (
            ('out_voltage_sampling_frequency', '2500000', 2500000, 0),
            ('out_altvoltage1_TX_LO_frequency', '900999998', 901000000, 10),
            ('out_voltage_rf_bandwidth', '3000000', 3000000, 0),
            ('out_voltage0_rf_port_select', 'A', 'A', 0)):
            source.read=Mock(return_value=current)
            self.assertEqual(source.configure_if_changed(name, value, tolerance), current)
        source.write.assert_not_called()
        source.read=Mock(side_effect=['5000000', '1'])
        source.write.return_value='2500000'
        self.assertEqual(source.configure_if_changed('out_voltage_sampling_frequency', 2500000), '2500000')
        source.write.assert_called_once_with('/phy/out_voltage_sampling_frequency', 2500000, 0)
        source.read=Mock(side_effect=['5000000', '0'])
        with self.assertRaises(RuntimeError):
            source.configure_if_changed('out_voltage_sampling_frequency', 2500000)
        source.mute.assert_called_once()

    def test_new_commands_keep_legacy_frame_size_and_old_golden(self):
        from sw.tools.telecontrol_waveform import build_cadu
        import numpy as np
        self.assertEqual(np.packbits(build_cadu(build_body(100, 2450, 0))[0]).tobytes().hex(),
                         '1acffc1dbcd9014c82bf4b2c0b3894c10ddfdc50')
        for operation, version in OPERATIONS.items():
            body = build_body(901, 1000, 8, operation)
            self.assertEqual(len(body), 8)
            self.assertEqual(body[0], version)
            self.assertEqual(int.from_bytes(body[-2:], 'big'), binascii.crc_hqx(body[:-2], 0xffff))
            self.assertEqual(command_iq(901, 1000, 8, operation=operation).shape, (4000, 2))

    def test_enable_requires_actual_both_channels_and_active_lease(self):
        request, report = extended_fixture()
        result = assess_rf_reply(request, report)
        self.assertTrue(result['passed'])
        self.assertEqual(result['relay']['rx_gain_db'], [30, 30])
        self.assertFalse(result['independent_spi'])
        for changes in (dict(mode=2), dict(gains=[30, 0]), dict(atten=[50000, 89000]),
                        dict(flags=1, remaining=0), dict(flags=2), dict(actual_rx=901000000)):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                assess_rf_reply(*extended_fixture(**changes))

    def test_stop_query_do_not_mistake_request_frequency_for_a_tune(self):
        for op in ('stop', 'status'):
            result = assess_rf_reply(*extended_fixture(op, actual_rx=901000000))
            self.assertTrue(result['passed'])
            self.assertEqual(result['ack']['rx_hz'], 901000000)
        with self.assertRaises(ValueError):
            assess_rf_reply(*extended_fixture('stop', gains=[0, 30]))

    def test_negative_ack_is_an_associated_failure_not_success(self):
        request, report = extended_fixture('enable', rc=-5, mode=2, gains=[0, 0],
                                           atten=[89000, 89000], flags=1, remaining=0)
        result = assess_rf_reply(request, report)
        self.assertFalse(result['passed'])
        self.assertTrue(result['matched'])
        self.assertEqual(result['remote_rc'], -5)

    def test_wrong_opcode_crc_stale_and_legacy_substitution_rejected(self):
        request, report = extended_fixture()
        request['operation'] = 'status'
        with self.assertRaises(ValueError):
            assess_rf_reply(request, report)
        request, report = extended_fixture()
        baseline = assess_rf_reply(request, report)['snapshot']
        with self.assertRaises(ValueError):
            assess_rf_reply(request, report, baseline)
        report['frames'][0]['crc16'] ^= 1
        with self.assertRaises(ValueError):
            assess_rf_reply(request, report)
        legacy, _, state, _, _, _ = evidence()
        state['network'] = 1
        with self.assertRaises(ValueError):
            assess_rf_reply(dict(legacy, operation='enable'), dict(frames=[atm1_frame(state)]))

    def test_lengths_and_reserved_bits_are_strict(self):
        _, report = extended_fixture()
        p = bytes.fromhex(report['frames'][0]['payload_hex'])
        for damaged in (p[:-1], p+b'\0', b'ATM1\x01'+p[5:], p[:95]+b'\x80'+p[96:]):
            with self.assertRaises(ValueError):
                parse_payload(damaged)
        with self.assertRaises(ValueError):
            parse_frame(b'\xaa\xaa\x60'+p+b'\0\0')


if __name__ == '__main__':
    unittest.main()
