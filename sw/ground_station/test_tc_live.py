"""Ground-only TC tests; fixtures are not hardware validation evidence."""
import copy
import json
from pathlib import Path
import queue
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock

from .tc_live import TelecontrolController, assess_rf_reply
from .tc_sequence import SequencePool
from .test_tc_evidence import evidence, atm1_frame


def fixture():
    request, _, state, _, _, _ = evidence()
    state['network'] = 1
    report = dict(frames=[atm1_frame(state)], clip_components=0, rms_codes=20)
    return request, state, report


class RFReplyTests(unittest.TestCase):
    def test_raw_crc_and_records_required_not_cached_summary(self):
        request, _, report = fixture()
        result = assess_rf_reply(request, report)
        self.assertTrue(result['passed'])
        self.assertFalse(result['independent_spi'])
        self.assertEqual(result['ack']['tx_hz'], 1000999999)
        report['frames'][0]['crc16'] ^= 1
        with self.assertRaises(ValueError):
            assess_rf_reply(request, report)
        with self.assertRaises(TimeoutError):
            assess_rf_reply(request, dict(frames=[], passed=True))

    def test_wrong_transaction_status_source_and_frequency_rejected(self):
        for key, value in [('network', 0), ('armed', 1), ('pending', 1), ('d_origin', 3),
                           ('d_air_seq', 163), ('s_count', 4), ('a_udp_seq', 88),
                           ('s_rc', -1), ('a_tx_hz', 1000000000), ('events', 24)]:
            with self.subTest(key=key):
                request, state, report = fixture()
                state[key] = value
                report['frames'] = [atm1_frame(state)]
                with self.assertRaises(ValueError):
                    assess_rf_reply(request, report)

    def test_multiple_snapshots_stale_and_reboot_rejected(self):
        request, state, report = fixture()
        previous = assess_rf_reply(request, report)['snapshot']
        with self.assertRaises(ValueError):
            assess_rf_reply(request, report, previous)
        report['frames'].append(atm1_frame(state, 18, 2201))
        with self.assertRaises(ValueError):
            assess_rf_reply(request, report)
        for value in (None, {}, dict(payload_hex='zz'*96, crc16=0)):
            with self.assertRaises(ValueError):
                assess_rf_reply(request, dict(frames=[value]))


class FakeRadio:
    def __init__(self, port, record):
        self.info = dict(port=port, model='fixture', usb_serial='fixture')
        self.phy = '/phy'
        self.rx_lo = 90000000
        self.calls = []
        self.entered = threading.Event()
    def require_idle(self): self.calls.append('idle')
    def read(self, path): return '1'
    def prepare(self, request, **kwargs): self.calls.append('prepare'); return dict(test_fixture=True)
    def configure_receive(self, check): self.calls.append('rx_setup'); check()
    def start(self): self.calls.append('tx_start'); self.entered.set()
    def stop(self): self.calls.append('stop')
    def finish_capture(self): self.calls.append('finish_capture')
    def close(self): self.calls.append('close')
    def capture_reply(self, check):
        check(); self.calls.append('rx_capture')
        return b'fixture', dict(test_fixture=True)


class GroundWorkerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.events = queue.Queue()
        self.request, _, self.report = fixture()
        self.radio = None
        def factory(port, record):
            self.radio = FakeRadio(port, record)
            return self.radio
        self.controller = TelecontrolController(self.events.put,
            log_dir=Path(self.directory.name)/'session', radio_factory=factory,
            decoder=lambda *_a, **_k: copy.deepcopy(self.report), transmit_seconds=.05,
            quiet_seconds=0, sequence_pool=SequencePool(Path(self.directory.name)/'sequence.json'))
        self.wait('status', 'disconnected')

    def tearDown(self):
        self.controller.submit('close')
        self.controller.worker.join(3)
        self.assertFalse(self.controller.worker.is_alive())
        self.directory.cleanup()

    def wait(self, kind, state=None):
        deadline = time.monotonic()+3
        while True:
            event = self.events.get(timeout=max(.001, deadline-time.monotonic()))
            if event['type'] == kind and (state is None or event.get('state') == state):
                return event

    def connect(self):
        self.controller.submit('connect', source_port='SOURCE')
        self.wait('status', 'connected')

    def test_one_sdr_only_rx_prepared_before_tx_result_from_actual_decoder(self):
        self.connect()
        self.controller.submit('send', requested=self.request, wiring_confirmed=True)
        result = self.wait('result')
        self.assertTrue(result['passed'])
        self.assertLess(self.radio.calls.index('rx_setup'), self.radio.calls.index('tx_start'))
        self.assertLess(self.radio.calls.index('stop'), self.radio.calls.index('rx_capture'))
        self.assertTrue(Path(result['iq_path']).exists())
        self.assertFalse(result['independent_spi'])

    def test_cancel_during_tx_never_emits_success_and_releases_owner(self):
        self.controller.transmit_seconds = 2
        self.connect()
        self.controller.submit('send', requested=self.request, wiring_confirmed=True)
        self.assertTrue(self.radio.entered.wait(1))
        self.controller.submit('stop')
        self.assertEqual(self.wait('status', 'error')['category'], 'cancelled')
        self.wait('status', 'disconnected')
        self.assertIn('stop', self.radio.calls)
        self.assertIn('close', self.radio.calls)
        self.assertNotIn('rx_capture', self.radio.calls)
        self.assertIsNone(self.controller.radio)

    def test_missing_rf_is_timeout_not_filled_from_request(self):
        self.report['frames'] = []
        self.connect()
        self.controller.submit('send', requested=self.request, wiring_confirmed=True)
        self.assertEqual(self.wait('status', 'error')['category'], 'timeout')
        result = json.loads((self.controller.log_dir/'command_0001'/'result.json').read_text(encoding='utf-8'))
        self.assertFalse(result['passed'])
        self.assertNotIn('ack', result)

    def test_no_wiring_and_duplicate_sequences_never_transmit(self):
        self.connect()
        self.controller.used_sequences.add(self.request['air_seq'])
        for confirmed in (False, True):
            if self.controller.radio is None:
                self.connect()
            self.controller.submit('send', requested=self.request, wiring_confirmed=confirmed)
            self.assertEqual(self.wait('status', 'error')['category'], 'validation')
            self.assertNotIn('tx_start', self.radio.calls)

    def test_explicit_reconnect_resets_remote_baseline_but_not_used_sequences(self):
        self.connect()
        self.controller.previous = dict(events=999, uptime_ms=999, sequence=999)
        self.controller.used_sequences.add(123)
        self.controller.submit('disconnect')
        self.wait('status', 'disconnected')
        self.connect()
        self.assertIsNone(self.controller.previous)
        self.assertIn(123, self.controller.used_sequences)

    def test_cleanup_error_does_not_leave_cancellation_latched(self):
        self.connect()
        self.radio.stop = Mock(side_effect=RuntimeError('cleanup fixture failure'))
        self.controller.submit('stop')
        self.assertEqual(self.wait('status', 'error')['category'], 'hardware')
        self.connect()
        self.assertFalse(self.controller.interrupt.is_set())

    def test_cancel_during_old_reply_quiet_window_never_enables_tx(self):
        self.controller.quiet_seconds = 2
        self.connect()
        self.controller.submit('send', requested=self.request, wiring_confirmed=True)
        self.wait('status', 'sending')
        self.controller.submit('stop')
        self.wait('status', 'disconnected')
        self.assertNotIn('tx_start', self.radio.calls)

    def test_closed_event_survives_failed_final_log(self):
        record = self.controller.record
        def fail_close(**values):
            if values.get('state') == 'closed':
                raise OSError('fixture disk failure')
            return record(**values)
        self.controller.record = fail_close
        self.controller.submit('close')
        self.wait('status', 'closed')
        self.assertTrue(self.controller.journal.closed)


if __name__ == '__main__':
    unittest.main()
