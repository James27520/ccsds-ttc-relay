"""Exact user frequency -> request -> air bytes -> terminal register contract."""
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock, patch
import unittest

from .rf_profiles import business_center_hz, business_lo_allowed, is_demo_request
from .ui_v2_model import command_request, business_frequency_plan
from .terminal_backend import _Transaction
from .terminal_radio import TerminalRadio
from sw.tools.telecontrol_waveform import build_body
from sw.tools.telecontrol_protocol import frequency_fields, wire_fields


class FrequencyKHzTests(unittest.TestCase):
    def test_extreme_exponents_and_nonfinite_inputs_are_validation_errors(self):
        for text in ('1e99999999', '1e-99999999', 'NaN', 'sNaN', 'Infinity', '-Infinity'):
            for role in ('sender', 'receiver'):
                with self.subTest(text=text, role=role), self.assertRaises(ValueError):
                    business_center_hz(role, text)

    def test_every_grid_point_roundtrips_independently_without_rounding(self):
        for offset in range(100, 29901):
            other = 30000-offset  # Opposite ends, deliberately not a fixed shift.
            rx_center, tx_center = 1980000000+offset*1000, 2170000000+other*1000
            rx_text, tx_text = str(Decimal(rx_center)/1000000), str(Decimal(tx_center)/1000000)
            request = command_request(rx_text, tx_text, 7, encoding='n256_khz_v1')
            version, a, b, seq = wire_fields(request)
            self.assertEqual((version, a, b, seq), (0x81, offset, other, 7))
            fields = frequency_fields(version, a, b)
            self.assertEqual(fields['rx_hz'], rx_center-500000)
            self.assertEqual(fields['tx_hz'], tx_center-500000)
            self.assertEqual(business_frequency_plan('sender', rx_text)['lo_hz'], rx_center-500000)
            self.assertEqual(business_frequency_plan('receiver', tx_text)['lo_hz'], tx_center+250000)
        self.assertTrue(is_demo_request(request))

    def test_sub_khz_and_band_edge_inputs_are_not_rounded_or_clamped(self):
        for role, values in [('sender', ('1980.099', '2009.901', '1988.123001')),
                             ('receiver', ('2170.099', '2199.901', '2184.5671'))]:
            for value in (*values, 'NaN', 'sNaN', 'Infinity', True, ''):
                with self.subTest(role=role, value=value), self.assertRaises(ValueError):
                    business_center_hz(role, value)

    def test_nonpreset_register_write_keeps_binding_and_other_guards(self):
        radio = TerminalRadio.__new__(TerminalRadio)
        radio.business_mode, radio.owned, radio._closed, radio.stream = True, True, False, None
        radio.phy = '/test/phy'
        with patch('sw.ground_station.terminal_radio._verify_runtime_binding') as binding, \
             patch('sw.ground_station.terminal_radio.Console.write', return_value='ok') as write:
            self.assertEqual(radio.write('/test/phy/out_altvoltage1_TX_LO_frequency', 1987623000), 'ok')
            self.assertEqual(radio.write('/test/phy/out_altvoltage0_RX_LO_frequency', 2184817000), 'ok')
            self.assertEqual(binding.call_count, 2)
            for path, value in [('/test/phy/out_altvoltage1_TX_LO_frequency',1987623001),
                                ('/test/phy/out_altvoltage1_TX_LO_frequency',2009401000),
                                ('/test/phy/out_voltage1_hardwaregain',-50),
                                ('/other/phy/out_altvoltage1_TX_LO_frequency',1987623000)]:
                with self.assertRaises(ValueError): radio.write(path, value)
            self.assertEqual(write.call_count, 2)

    def test_confirmed_request_keeps_exact_ack_without_changing_local_plan(self):
        owner = SimpleNamespace(tc_result=None, set_plan=Mock(), event=Mock(),
                                tx_center='1988.123', rx_center='2184.567')
        transaction = _Transaction.__new__(_Transaction)
        transaction.owner = owner
        request = command_request('1988.123', '2184.567', 9, encoding='n256_khz_v1')
        transaction.event('result', passed=True, requested=request,
                          ack=dict(rx_hz=1987623000, tx_hz=2184067000))
        owner.set_plan.assert_not_called()


if __name__ == '__main__':
    unittest.main()
