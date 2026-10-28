"""Fault-oriented checks for the manual capture and bounded source adapters."""
import unittest
from unittest.mock import Mock, patch

from .tc_hardware import CommandSource, ControlAdda, request_values
from .tc_roundtrip import manual_command, execute
from .test_rf_live import good_state


class ManualCommandTests(unittest.TestCase):
    def setUp(self):
        self.a, self.s, self.r = Mock(), Mock(), Mock()
        self.order = Mock()
        for name, value in [('adda',self.a),('source',self.s),('relay',self.r)]:
            self.order.attach_mock(value,name)
        self.before = dict(applied=4, failures=0, d_valid=0,s_valid=1,a_valid=1,
                           s_air_seq=232,a_air_seq=232)
        self.a.acquire_control.return_value = self.before
        self.a.tmstatus.return_value = good_state()
        self.a.capture_status.return_value = dict(state=6,valid=1,consumed=0)
        self.a.query.side_effect = [dict(network=1,pending=0),dict(pending=0,applied=5,failures=0),
                                   dict(network=0,pending=0,armed=0)]
        self.a.control.side_effect = lambda cmd: ['DECODED source=ADC_NORMAL rx=900 tx=1001 air_seq=240 rc=0'] if cmd=='decode' else []
        self.r.diagnostics.return_value = dict(relay_rx_hz_readback=900000000,
                                               relay_tx_hz_readback=1000999998)
        self.request = request_values(900,1001,240)

    def run_command(self):
        return manual_command(self.a,self.s,self.r,self.request,Mock())

    def test_source_stops_before_single_decode_and_spi_precedes_network_off(self):
        self.run_command()
        calls=[str(c) for c in self.order.mock_calls]
        self.assertLess(calls.index('call.source.stop()'),calls.index("call.adda.control('decode')"))
        self.assertLess(calls.index('call.relay.diagnostics(atten=89, gain=0, exact_frequency=False)'),
                        calls.index('call.adda.release_control()'))
        self.assertEqual(sum("control('decode')" in c for c in calls),1)
        self.assertFalse(any('auto on' in c or 'nettest' in c for c in calls))
        self.r.run.assert_not_called()

    def test_stale_sequence_rejected_before_arm_or_source(self):
        self.request['air_seq']=232
        with self.assertRaises(ValueError):self.run_command()
        self.s.start.assert_not_called();self.a.control.assert_not_called()

    def test_bad_capture_never_decodes_or_reads_spi(self):
        self.a.capture_status.return_value=dict(state=7,valid=0,consumed=0)
        with self.assertRaises(RuntimeError):self.run_command()
        self.assertNotIn(('decode',),[c.args for c in self.a.control.call_args_list])
        self.r.diagnostics.assert_not_called()

    def test_non_adc_result_is_rejected(self):
        self.a.control.return_value=[];self.a.control.side_effect=None
        with self.assertRaisesRegex(RuntimeError,'ADC_NORMAL'):self.run_command()
        self.r.diagnostics.assert_not_called()

    def test_extra_application_never_accepted_as_one_transaction(self):
        self.a.query.side_effect=[dict(network=1,pending=0),dict(pending=0,applied=6,failures=0)]
        with self.assertRaisesRegex(RuntimeError,'计数异常'):self.run_command()
        self.r.diagnostics.assert_not_called()

    def test_wrong_spi_is_not_replaced_with_expected_value(self):
        self.r.diagnostics.return_value['relay_tx_hz_readback']=1000000000
        with self.assertRaisesRegex(RuntimeError,'独立SPI'):self.run_command()
        self.a.release_control.assert_not_called()  # Outer finally owns failure cleanup.


class OwnershipTests(unittest.TestCase):
    def test_invalid_parameters_and_missing_wiring_touch_no_port(self):
        with patch('sw.ground_station.tc_roundtrip.CommandSource') as source:
            with self.assertRaises(ValueError):execute('unused','S','A','R',request_values(900,1001,240))
            source.assert_not_called()
        for args in [(True,1001,1),(900,2450,1),(900,1000,256),(900,1000,1.0)]:
            with self.assertRaises(ValueError):request_values(*args)

    def test_busy_source_does_not_become_owned_or_mute(self):
        s=CommandSource.__new__(CommandSource)
        s.owned=False;s.prepared=False;s.verify_binding=Mock();s.require_idle=Mock(side_effect=RuntimeError('busy'))
        s.mute=Mock()
        with self.assertRaisesRegex(RuntimeError,'busy'):
            s.prepare(request_values(900,1000,240),wiring_confirmed=True)
        s.stop();s.mute.assert_not_called();self.assertFalse(s.owned)

    def test_missing_guard_keeps_lo_off(self):
        s=CommandSource.__new__(CommandSource)
        s.prepared=True;s.remote='/tmp/test';s.phy='/phy';s.tx='/tx'
        s.block_samples=4000;s.attenuation_db=30
        s.manifest={'sha256':'abcdef'}
        s.verify_binding=Mock();s.require_idle=Mock();s.run=Mock(return_value='abcdef  /tmp/test/waveform.bin')
        s.read=Mock(side_effect=['1','bad guard identity']);s.write=Mock()
        with self.assertRaisesRegex(RuntimeError,'保护身份'):s.start()
        self.assertFalse(any(c.args[0].endswith('TX_LO_powerdown') for c in s.write.call_args_list))

    def test_host_cannot_enable_lo_after_guard_expired(self):
        s=CommandSource.__new__(CommandSource)
        s.owned=True;s._closed=False;s.phy='/phy';s.verify_binding=Mock()
        with self.assertRaises(ValueError):s.write('/phy/out_altvoltage1_TX_LO_powerdown',0)
        s.verify_binding.assert_not_called()

    def test_failed_mute_keeps_guard_armed(self):
        s=CommandSource.__new__(CommandSource)
        s.owned=True;s.remote='/tmp/test';s.tx='/tx'
        s.verify_binding=Mock()
        s.mute=Mock(side_effect=RuntimeError('mute failed'));s.run=Mock(return_value='')
        s.read=Mock(return_value='0')
        with self.assertRaisesRegex(RuntimeError,'mute failed'):s.stop()
        self.assertFalse(any('/released' in c.args[0] for c in s.run.call_args_list))

    def test_busy_adda_does_not_stop_other_task(self):
        a=ControlAdda.__new__(ControlAdda)
        a.control_owned=False;a.verify_binding=Mock()
        a.capture_status=Mock(return_value=dict(auto=1,state=3))
        a.query=Mock(return_value=dict(network=1,armed=1,pending=0))
        a.control=Mock()
        with self.assertRaises(RuntimeError):a.acquire_control()
        a.release_control();a.control.assert_not_called()

    def test_cleanup_attempts_all_commands_even_if_one_fails(self):
        a=ControlAdda.__new__(ControlAdda);a.control_owned=True
        a.control=Mock(side_effect=[RuntimeError('first failed'),[],[],[]])
        a.query=Mock(return_value=dict(network=0,armed=0,pending=0))
        with self.assertRaisesRegex(RuntimeError,'first failed'):a.release_control()
        self.assertEqual([c.args[0] for c in a.control.call_args_list],
                         ['auto off','arm off','capture cancel','network off'])


if __name__=='__main__':unittest.main()
