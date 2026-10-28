"""Finite acquisition fault paths; fakes never open serial ports."""
import json
from pathlib import Path
import queue
import tempfile
import threading
import unittest
from unittest.mock import Mock

from .rf_live import RFTelemetryController, Cancelled, idle_dac, SAMPLES


def good_state(seq=4):
    return dict(enabled=1, seq=seq, pending=0, stopping=0, status=0x28,
                diag=0, dac_verified=1, dac_finished=1, dac_diagnostic=0x102a0110)


class LiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        s = self.station = RFTelemetryController.__new__(RFTelemetryController)
        s.receiver = Mock(phy='/phy', rx='/rx', tx='/tx')
        s.adda = Mock()
        s.receiver_owned = s.adda_owned = True
        s.binding = dict(receiver={'port':'RX'}, adda={'port':'ADDA'})
        s.binding_token = 'verified'
        s.capture_directory = None
        s.index = 0
        s.rx_lo = 90000000
        s.log_dir = Path(self.temp.name)
        s.interrupt = threading.Event()
        s.status, s.event, s.record = Mock(), Mock(), Mock()
        s.decoder = Mock(return_value=dict(format='EXPERIMENTAL_ATM1_RF', frames=[],
            telemetry=[], valid_telemetry_count=0, rms_codes=1., clip_components=0))
        self.seq, self.buffered, self.ready = 4, False, True
        self.c, self.a = s.receiver, s.adda
        self.a.tmstatus.side_effect = lambda: good_state(self.seq)
        self.a.query.return_value = dict(armed=0, pending=0, never_decoder_input='USB reference')
        self.a.send.side_effect = self.send
        self.c.read.side_effect = self.read
        self.c.run.side_effect = self.run_console
        self.c.download.return_value = bytes(SAMPLES*4)

    def send(self):
        self.seq += 1

    def read(self, path):
        if path.endswith('TX_LO_powerdown'):
            return '1'
        if path.endswith('/buffer/enable'):
            value, self.buffered = self.buffered, False
            return '1' if value else '0'
        if path.endswith('_type'):
            return 'le:S12/16>>0'
        if path.endswith('_index'):
            return '0' if 'voltage0' in path else '1'
        raise AssertionError(path)

    def run_console(self, command, **kwargs):
        if 'CAPTURE_READY' in command:
            self.buffered = self.ready
            return 'CAPTURE_READY' if self.ready else ''
        if '/rc;' in command:
            self.buffered = False
            return '0'
        return ''

    def test_quiet_capture_does_not_send_or_clear_and_uses_only_raw_iq(self):
        self.station._capture(False)
        self.a.send.assert_not_called()
        self.a.clear.assert_not_called()
        self.a.stop.assert_not_called()
        args, kwargs = self.station.decoder.call_args
        self.assertEqual(args, (bytes(SAMPLES*4),))
        self.assertEqual(set(kwargs), {'sample_rate_hz','symbol_rate','expected_offset_hz'})
        capture = next(call for call in self.station.event.call_args_list if call.args[0] == 'capture')
        self.assertFalse(capture.kwargs['send_requested'])

    def test_send_is_single_and_cleanup_confirmed_before_result(self):
        self.station._capture(True)
        self.a.send.assert_called_once()
        self.a.stop.assert_called_once()
        saved = json.loads((self.station.log_dir/'rf_000001.capture.json').read_text())
        self.assertEqual(saved['before']['seq']+1, saved['after']['seq'])
        self.assertLessEqual(saved['timing']['buffer_ready_at'], saved['timing']['send_requested_at'])
        self.assertTrue((self.station.log_dir/'rf_000001.bin').exists())

    def test_ready_failure_never_sends_and_still_stops_and_releases_reader(self):
        self.ready = False
        with self.assertRaisesRegex(RuntimeError, '未就绪'):
            self.station._capture(True)
        self.a.send.assert_not_called()
        self.a.stop.assert_called_once()
        self.c.download.assert_not_called()
        self.assertIsNone(self.station.capture_directory)

    def test_lost_send_reply_does_not_retry_and_no_result_is_published(self):
        self.a.send.side_effect = TimeoutError('lost reply')
        with self.assertRaises(TimeoutError):
            self.station._capture(True)
        self.a.send.assert_called_once()
        self.a.stop.assert_called_once()
        self.assertFalse(any(c.args[0]=='capture' for c in self.station.event.call_args_list))

    def test_changed_identity_prevents_any_capture_or_tx_command(self):
        self.c.verify_binding.side_effect = RuntimeError('changed boot')
        with self.assertRaisesRegex(RuntimeError, 'changed boot'):
            self.station._capture(True)
        self.a.send.assert_not_called()
        self.a.clear.assert_not_called()
        self.c.run.assert_not_called()

    def test_cancel_during_transfer_keeps_raw_evidence_but_publishes_no_result(self):
        def transfer(*args):
            self.station.interrupt.set()
            return bytes(SAMPLES*4)
        self.c.download.side_effect = transfer
        with self.assertRaises(Cancelled):
            self.station._capture(True)
        self.assertTrue((self.station.log_dir/'rf_000001.bin').exists())
        self.station.decoder.assert_not_called()
        self.a.stop.assert_called_once()

    def test_idle_precheck_failure_closes_without_muting_foreign_task(self):
        s = self.station
        c,a = self.c,self.a
        s.receiver=s.adda=None
        s.receiver_owned=s.adda_owned=False
        s.opener=Mock(return_value=(c,a))
        c.require_idle.side_effect=RuntimeError('existing capture')
        with self.assertRaisesRegex(RuntimeError,'existing capture'):
            s._connect('verified')
        s._disconnect()
        c.mute.assert_not_called()
        a.stop.assert_not_called()
        c.close.assert_called_once()
        a.close.assert_called_once()

    def test_disconnect_attempts_both_devices_when_dac_stop_fails(self):
        self.a.stop.side_effect=RuntimeError('unplugged')
        with self.assertRaisesRegex(RuntimeError,'unplugged'):
            self.station._disconnect()
        self.c.mute.assert_called_once()
        self.c.close.assert_called_once()
        self.a.close.assert_called_once()
        self.assertIsNone(self.station.binding)

    def test_new_foreign_task_after_connection_is_not_stopped_on_error_cleanup(self):
        self.c.require_idle.side_effect=RuntimeError('foreign task started')
        with self.assertRaisesRegex(RuntimeError,'foreign task'):
            self.station._capture(True)
        self.station._disconnect()
        self.c.mute.assert_not_called()
        self.a.stop.assert_not_called()

    def test_disconnect_does_not_mute_a_foreign_reader_or_writer(self):
        self.station.adda_owned=False
        self.c.require_idle.side_effect=RuntimeError('foreign DMA')
        with self.assertRaisesRegex(RuntimeError,'foreign DMA'):
            self.station._disconnect()
        self.c.mute.assert_not_called()
        self.c.close.assert_called_once()

    def test_busy_fault_reset_and_unverified_dac_rejected(self):
        for bit in [1,4,16,64,128]:
            with self.subTest(bit=bit), self.assertRaises(RuntimeError):
                idle_dac(dict(good_state(),status=bit))
        with self.assertRaises(RuntimeError):
            idle_dac(dict(good_state(),dac_verified=0))

    def test_urgent_close_discards_queued_capture(self):
        s=self.station
        s.commands=queue.Queue();s.urgent=queue.Queue();s.closing=False
        s.journal=Mock();s.emit=Mock()
        s.commands.put(('capture',{'send':True}))
        s.submit('close')
        s._work()
        self.a.send.assert_not_called()
        s.emit.assert_called_with({'type':'closed'})


if __name__ == '__main__':
    unittest.main()
