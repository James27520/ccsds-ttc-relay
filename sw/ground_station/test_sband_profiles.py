"""S-band configuration and RF-return checks; no hardware is opened."""
import binascii
import copy
import unittest
from unittest.mock import Mock

from .rf_profiles import DEMO_RELAY_PAIRS, is_demo_request
from .ui_v2_model import command_request, business_frequency_plan
from .tc_hardware import request_values
from .tc_live import assess_rf_reply
from .test_tc_live import fixture
from .test_tc_evidence import atm1_frame
from .business_live import BusinessSource
from sw.tools.telecontrol_waveform import build_body


class SBandTests(unittest.TestCase):
    def test_exact_signal_centers_local_los_and_command_bytes(self):
        for rx, tx in DEMO_RELAY_PAIRS:
            request = command_request(str(rx)+'.5', str(tx)+'.5', 37)
            self.assertTrue(is_demo_request(request))
            self.assertEqual(request_values(**request), request)
            self.assertEqual(business_frequency_plan('sender', rx+.5)['lo_hz'], rx*1000000)
            self.assertEqual(business_frequency_plan('receiver', tx+.5)['lo_hz'], tx*1000000+750000)
            body = build_body(rx, tx, 37)
            self.assertEqual(body[:6], b'\x01'+rx.to_bytes(2,'little')+tx.to_bytes(2,'little')+b'\x25')
            self.assertEqual(int.from_bytes(body[6:],'big'), binascii.crc_hqx(body[:6], 0xffff))

    def test_no_cross_pair_or_full_band_authorization(self):
        for rx, tx in ((1989,2180),(1990,2179),(900,2179),(1989,1000),(1980,2170),(2450,2900)):
            with self.assertRaises(ValueError):
                request_values(rx,tx,1)
            self.assertFalse(is_demo_request(dict(rx_mhz=rx,tx_mhz=tx)))
        for rx, tx in ((True,2179),(1989.0,2179),(1989,'2179')):
            with self.assertRaises(ValueError):
                request_values(rx,tx,1)

    def test_current_adc_rf_return_matches_high_frequency_and_rejects_wrong_ack(self):
        for rx,tx in DEMO_RELAY_PAIRS:
            request,state,_ = fixture()
            request.update(rx_mhz=rx,tx_mhz=tx)
            for prefix in ('d','s','a'):
                state[prefix+'_rx_mhz'], state[prefix+'_tx_mhz'] = rx,tx
            state['a_rx_hz'],state['a_tx_hz'] = rx*1000000-2,tx*1000000-2
            report=dict(frames=[atm1_frame(state)])
            good=assess_rf_reply(request,report)
            self.assertTrue(good['passed'])
            self.assertFalse(good['independent_spi'])
            wrong=copy.deepcopy(state);wrong['a_tx_hz']-=1000000
            with self.assertRaises(ValueError):
                assess_rf_reply(request,dict(frames=[atm1_frame(wrong)]))
            wrong=copy.deepcopy(state);wrong['d_origin']=4
            with self.assertRaises(ValueError):
                assess_rf_reply(request,dict(frames=[atm1_frame(wrong)]))

    def test_business_waveform_keeps_guarded_profile_and_new_frequency(self):
        source=BusinessSource.__new__(BusinessSource)
        source._prepare_waveform=Mock()
        for seq,(rx,_) in enumerate(DEMO_RELAY_PAIRS):
            manifest=source.prepare_message('S-band text','abcdef01',seq,60,lambda:None,tx_rf_mhz=rx+.5)
            self.assertEqual(manifest['business_lo_hz'],rx*1000000)
            self.assertEqual(source._prepare_waveform.call_args.kwargs['attenuation_db'],60)


if __name__ == '__main__':
    unittest.main()
