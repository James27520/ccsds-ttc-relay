"""Terminal scheduling and payload checks using fake radio/lease only."""
from collections import deque
from pathlib import Path
import json
import queue
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from .protocol import encode_message, _link
from .terminal_backend import TerminalController, _Transaction
from .terminal_radio import ReceiveUnavailable
from .receive_health import ReceiveHealth


class FakeLease:
    def __init__(self, port):
        self.port, self.closed = port, False

    def close(self):
        self.closed = True


class FakeRadio:
    phy, remote = '/fake/phy', '/fake/stream'

    def __init__(self, port, record):
        self.info = dict(port=port, model='fake SDR', usb_serial='fake-serial')
        self.calls = []
        self.call_times = []
        self.fail_prepare_once = False
        self.pending = deque()
        self.samples = 0
        self.business_mode, self.tx_channel = True, 1
        self.stream = False
        self.guard = 'enabled'
        self.status_override = {}
        self.receive_fault = None

    def note(self, name, *values):
        self.calls.append((name, values))
        self.call_times.append((name, time.monotonic()))

    def require_idle(self): self.note('require_idle')
    def read(self, path): return self.guard if path.endswith('/guard_state') else '1'

    def configure_business(self, tx_center, rx_center, rx_channel):
        self.note('configure', tx_center, rx_center, rx_channel)
        return dict(configured=True, tx_lo_hz_readback=int((float(tx_center)-.5)*1e6),
                    rx_lo_hz_readback=int((float(rx_center)+.25)*1e6), expected_rf_mhz=float(rx_center))

    def start_receive(self):
        self.note('start_receive')
        self.stream = True

    def stop_receive(self):
        self.note('stop_receive')
        self.stream = False
        self.pending.clear()

    def stop(self): self.note('stop_tx')
    def start(self): self.note('start_tx')
    def verify_stream(self):
        self.note('verify_stream')
        if self.receive_fault:
            fault, self.receive_fault = self.receive_fault, None
            raise fault

    def verify_transmit(self):
        self.note('verify_transmit')
        if self.guard == 'stopped':
            return False
        if self.guard != 'enabled':
            raise RuntimeError('fake transmit guard invalid')
        return True

    def finish_capture(self): self.note('finish_capture')
    def close(self): self.note('close')

    def prepare_message(self, text, session, sequence, attenuation, check, **values):
        check()
        self.note('prepare', text, session, sequence)
        if self.fail_prepare_once:
            self.fail_prepare_once = False
            raise RuntimeError('fake prepare failed')
        return dict(text=text)

    def poll_receive(self):
        self.verify_stream()
        self.samples += 1024
        frames = self.pending.popleft() if self.pending else []
        status = dict(samples=self.samples, rms=20, clips=0, frames=self.samples//1024, rejects=0)
        status.update(self.status_override)
        return status, frames


class FakeTransaction:
    def __init__(self, owner):
        self.owner = owner
        self.sequence_pool = type('Pool', (), {'next_available': lambda _self: 0})()
        self.entered = threading.Event()
        self.release = threading.Event()
        self.block = False
        self.fail = False
        self.fail_result = False
        self.result_override = {}
        self.requested = []

    def _send(self, requested, **values):
        self.requested.append(requested)
        self.entered.set()
        if self.block:
            while not self.release.wait(.005):
                self.owner.check_cancel()
        self.owner.check_cancel()
        if self.fail:
            raise RuntimeError('fake TC failed')
        result = dict(passed=not self.fail_result, matched=True,
                      requested=dict(operation=requested.get('operation', 'enable')),
                      ack=dict(rx_hz=round(float(self.owner.tx_center)*1e6)-500000,
                               tx_hz=round(float(self.owner.rx_center)*1e6)-500000),
                      relay=dict(valid=True, mode=1, lease_active=True, mute_fault=False,
                                 remaining_lower_bound_ms=60000))
        result.update(self.result_override)
        self.owner.tc_result, self.owner.tc_result_at = result, time.monotonic()


class TerminalBackendTests(unittest.TestCase):
    def test_receive_rate_accepts_measured_startup_trace_but_rejects_sustained_slowdown(self):
        h = ReceiveHealth()
        # Actual startup trace: final cumulative rate was 2.299 MSPS, but
        # progress between these snapshots was 2.401 MSPS.
        for samples, uptime in [(4898816, 2268.749), (7487488, 3328.462),
                                (9912320, 4360.669), (12353536, 5373.890)]:
            result = h.observe(dict(samples=samples, uptime_ms=uptime))
            self.assertFalse(result['recover'])
        result = h.observe(dict(samples=15353536, uptime_ms=8374.890))
        self.assertEqual(result['level'], 'degraded')
        self.assertFalse(result['recover'])
        for n in range(1, 4):
            result = h.observe(dict(samples=15353536+n*3000000, uptime_ms=8374.890+n*3000))
        self.assertTrue(result['recover'])

    def test_receive_rate_rejects_board_clock_reset_and_restarts_baseline(self):
        h = ReceiveHealth()
        h.observe(dict(samples=10000000, uptime_ms=5000))
        with self.assertRaisesRegex(ValueError, '时间回退'):
            h.observe(dict(samples=10000001, uptime_ms=100))
        h = ReceiveHealth()
        h.observe(dict(samples=100000, uptime_ms=500))
        self.assertEqual(h.observe(dict(samples=7600000, uptime_ms=3500))['level'], 'healthy')

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.events = []
        self.controllers = []
        self.serial_patch = patch('sw.ground_station.transport.Console.__init__', side_effect=AssertionError('test accessed hardware'))
        self.serial_patch.start()

    def tearDown(self):
        try:
            for controller in self.controllers:
                if controller.worker.is_alive():
                    controller.submit('close')
                    controller.worker.join(3)
                self.assertFalse(controller.worker.is_alive(), 'fake backend did not close')
        finally:
            self.serial_patch.stop()
            self.tmp.cleanup()

    def wait(self, predicate, message='condition did not complete'):
        deadline = time.monotonic()+3
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(.005)
        self.fail(message)

    def controller(self, role='sender', *, tx_dwell_seconds=.025):
        controller = TerminalController(role, self.events.append,
            log_dir=Path(self.tmp.name)/str(len(self.controllers)),
            radio_factory=FakeRadio, lease_factory=FakeLease,
            transaction_factory=FakeTransaction, poll_seconds=.01,
            tx_dwell_seconds=tx_dwell_seconds)
        self.controllers.append(controller)
        controller.submit('connect', port='FAKE_A' if role == 'sender' else 'FAKE_B')
        self.wait(lambda: controller.rx_active)
        return controller

    @staticmethod
    def count(radio, name):
        return sum(call[0] == name for call in radio.calls)

    def test_connect_auto_receives_on_terminal_specific_channel(self):
        for role, channel in (('sender', 2), ('receiver', 1)):
            controller = self.controller(role)
            self.assertEqual(self.count(controller.radio, 'start_receive'), 1)
            configuration = next(args for name, args in controller.radio.calls if name == 'configure')
            self.assertEqual(configuration[2], channel)
            self.assertTrue(controller.rx_active)
            self.assertFalse(controller.tx_active)
            self.assertFalse(any(event['type'] == 'tx' for event in self.events))

    def test_expired_owned_receiver_recovers_without_resending_previous_text(self):
        c=self.controller(); r=c.radio
        c.submit('send', text='only once')
        self.wait(lambda: c.tx_active)
        r.receive_fault=ReceiveUnavailable('owned guard expired')
        self.wait(lambda: self.count(r,'start_receive')==2)
        self.wait(lambda: c.rx_active and not c.tx_active)
        self.assertEqual(self.count(r,'start_tx'),1)
        self.assertEqual(self.count(r,'prepare'),1)
        self.assertIs(c.radio,r)

    def test_recovery_is_bounded_and_identity_errors_are_not_recovered(self):
        c=self.controller(); r=c.radio
        r.receive_fault=RuntimeError('USB identity changed')
        self.wait(lambda: c.radio is None)
        self.assertEqual(self.count(r,'start_receive'),1)
        c=self.controller(); r=c.radio
        c.receive_recoveries.extend([time.monotonic(), time.monotonic()])
        r.receive_fault=ReceiveUnavailable('expired again')
        self.wait(lambda: c.rx_health == 'suspended')
        self.assertIs(c.radio, r)
        self.assertFalse(c.rx_active)
        self.assertEqual(self.count(r,'start_receive'),1)
        self.assertEqual(self.count(r,'start_tx'),0)
        c.submit('resume_rx')
        self.wait(lambda: c.rx_active)
        self.assertEqual(self.count(r,'start_receive'),2)
        self.assertEqual(self.count(r,'start_tx'),0)
        self.assertEqual(len(c.receive_recoveries),0, 'manual restart must not consume automatic recovery budget')

    def test_new_send_checks_and_recovers_receiver_before_transmit(self):
        c=self.controller(); r=c.radio
        # Hold polling to test the send preflight, not the background poll.
        c.poll_seconds=1000; c.last_poll=time.monotonic()
        r.receive_fault=ReceiveUnavailable('owned reader exited')
        c.submit('send', text='new request')
        self.wait(lambda: c.tx_active)
        self.assertEqual(self.count(r,'start_receive'),2)
        names=[name for name,args in r.calls]
        self.assertLess(max(i for i,n in enumerate(names) if n=='start_receive'),names.index('prepare'))
        self.assertEqual(self.count(r,'start_tx'),1)

    def test_send_and_stop_tx_keep_same_receive_stream(self):
        controller = self.controller()
        radio = controller.radio
        controller.submit('send', text='hello')
        self.wait(lambda: controller.tx_active)
        controller.submit('stop_tx')
        self.wait(lambda: not controller.tx_active and not controller.interrupt.is_set())
        self.assertTrue(controller.rx_active)
        self.assertTrue(radio.stream)
        self.assertEqual(self.count(radio, 'start_receive'), 1)
        self.assertEqual(self.count(radio, 'stop_receive'), 0)
        self.assertEqual(self.count(radio, 'start_tx'), 1)
        self.assertTrue(any(event['type'] == 'tx' and event['text'] == 'hello' for event in self.events))

    def test_owned_rx_exit_during_send_is_recovered_without_replaying_send(self):
        for during_prepare in (True, False):
            with self.subTest(during_prepare=during_prepare):
                c=self.controller(); r=c.radio
                original=r.prepare_message
                def prepare(*args, **kwargs):
                    result=original(*args, **kwargs)
                    if during_prepare:
                        raise ReceiveUnavailable('owned reader exited while preparing')
                    r.receive_fault=ReceiveUnavailable('owned reader exited after TX start')
                    return result
                r.prepare_message=prepare
                request=c.submit('send', text='do not replay')
                self.wait(lambda: self.count(r,'start_receive')==2 and c.rx_active)
                self.assertIs(c.radio, r)
                self.assertFalse(c.tx_active)
                self.assertEqual(c.jobs[request]['state'], 'retry')
                self.assertEqual(self.count(r,'prepare'), 1)
                self.assertEqual(self.count(r,'start_tx'), 0 if during_prepare else 1)
                self.assertFalse(any(e['type']=='tx' and e.get('request_id')==request for e in self.events))
                r.prepare_message=original
                c.submit('send', text='new after recovery')
                self.wait(lambda: c.tx_active)
                self.assertEqual(self.count(r,'prepare'), 2)

    def test_expired_transmit_guard_stops_only_tx_and_keeps_rx(self):
        controller = self.controller()
        radio = controller.radio
        controller.submit('send', text='bounded')
        self.wait(lambda: controller.tx_active)
        radio.guard = 'stopped'
        self.wait(lambda: not controller.tx_active)
        self.assertIs(controller.radio, radio)
        self.assertTrue(controller.rx_active)
        self.assertEqual(self.count(radio, 'start_receive'), 1)
        self.assertEqual(self.count(radio, 'stop_receive'), 0)
        self.assertGreater(self.count(radio, 'verify_transmit'), 0)

    def test_invalid_transmit_guard_fails_closed_and_releases_lease(self):
        controller = self.controller()
        radio, lease = controller.radio, controller.lease
        controller.submit('send', text='bounded')
        self.wait(lambda: controller.tx_active)
        radio.guard = 'unverified'
        self.wait(lambda: any(event.get('state') == 'error' for event in self.events))
        self.assertIsNone(controller.radio)
        self.assertTrue(lease.closed)
        self.assertFalse(controller.rx_active)
        self.assertFalse(controller.tx_active)
        self.assertEqual(self.count(radio, 'close'), 1)

    def test_input_error_is_fatal_but_repeated_eof_retains_verified_connection(self):
        for status in (dict(eof=True), dict(input_error=True), dict(stopped=True)):
            with self.subTest(status=status):
                controller = self.controller()
                radio, lease = controller.radio, controller.lease
                first_event = len(self.events)
                radio.status_override = status
                if status.get('input_error'):
                    self.wait(lambda: any(event.get('state') == 'error' for event in self.events[first_event:]))
                    self.assertIsNone(controller.radio)
                    self.assertTrue(lease.closed)
                    self.assertEqual(self.count(radio, 'close'), 1)
                else:
                    self.wait(lambda: controller.rx_health == 'suspended')
                    self.assertIs(controller.radio, radio)
                    self.assertFalse(lease.closed)
                    self.assertEqual(self.count(radio, 'start_receive'), 3)
                self.assertFalse(controller.rx_active)
                self.assertFalse(controller.tx_active)

    def test_telecontrol_restores_rx_without_restarting_previous_text(self):
        controller = self.controller()
        radio = controller.radio
        controller.submit('send', text='old')
        self.wait(lambda: controller.tx_active)
        controller.submit('telecontrol', requested=dict(operation='frequency'))
        self.wait(lambda: self.count(radio, 'start_receive') == 2)
        self.assertTrue(controller.rx_active)
        self.assertFalse(controller.tx_active)
        self.assertFalse(controller.tc_active)
        self.assertEqual(self.count(radio, 'start_tx'), 1)
        self.assertEqual(self.count(radio, 'stop_receive'), 1)
        self.assertEqual(len(controller.transaction.requested), 1)

    def test_telecontrol_failure_resumes_rx_without_retrying_transmission(self):
        controller = self.controller()
        radio = controller.radio
        controller.transaction.fail = True
        controller.submit('telecontrol', requested={})
        self.wait(lambda: any(event.get('channel') == 'control' and event.get('state') == 'error'
                              for event in self.events))
        self.assertIs(controller.radio, radio)
        self.assertTrue(controller.rx_active)
        self.assertFalse(controller.tx_active)
        self.assertEqual(self.count(radio, 'start_tx'), 0)
        self.assertEqual(self.count(radio, 'start_receive'), 2)

    def test_telecontrol_failure_retains_unsent_text_as_retry(self):
        controller = self.controller()
        radio = controller.radio
        controller.transaction.block = controller.transaction.fail = True
        controller.submit('telecontrol', requested={})
        self.assertTrue(controller.transaction.entered.wait(2))
        item = controller.submit('send', text='stale after failure')
        controller.transaction.release.set()
        self.wait(lambda: any(event.get('channel') == 'control' and event.get('state') == 'error'
                              for event in self.events))
        error_index = next(index for index, event in enumerate(self.events)
                           if event.get('channel') == 'control' and event.get('state') == 'error')
        self.wait(lambda: any(event['type'] == 'rx' for event in self.events[error_index+1:]))
        self.assertTrue(controller.commands.empty())
        self.assertEqual(controller.jobs[item]['state'], 'retry')
        self.assertEqual(self.count(radio, 'start_tx'), 0)
        self.assertFalse(any(event['type'] == 'tx' for event in self.events))
        self.assertTrue(controller.rx_active)

    def test_cancel_telecontrol_retains_unsent_retry_and_resumes_only_rx(self):
        controller = self.controller()
        radio = controller.radio
        controller.transaction.block = True
        controller.submit('telecontrol', requested={})
        self.assertTrue(controller.transaction.entered.wait(2))
        item = controller.submit('send', text='stale queued text')
        controller.submit('cancel_tc')
        self.wait(lambda: controller.rx_active and not controller.tc_active
                  and not controller.interrupt.is_set())
        self.assertTrue(controller.commands.empty())
        self.assertEqual(self.count(radio, 'start_tx'), 0)
        self.assertEqual(self.count(radio, 'start_receive'), 2)
        self.assertEqual(controller.jobs[item]['state'], 'retry')
        self.assertFalse(any(event['type'] == 'tx' for event in self.events))

    def test_close_preempts_telecontrol_and_clears_old_commands(self):
        controller = self.controller()
        radio, lease = controller.radio, controller.lease
        controller.transaction.block = True
        controller.submit('telecontrol', requested={})
        self.assertTrue(controller.transaction.entered.wait(2))
        item = controller.submit('send', text='must never be sent')
        controller.submit('close')
        controller.worker.join(3)
        self.assertFalse(controller.worker.is_alive())
        self.assertTrue(controller.commands.empty())
        self.assertEqual(self.count(radio, 'start_tx'), 0)
        self.assertEqual(self.count(radio, 'start_receive'), 1)
        self.assertTrue(lease.closed)
        self.assertIsNone(controller.radio)
        self.assertTrue(any(event.get('state') == 'closed' for event in self.events))
        self.assertEqual(controller.jobs[item]['state'], 'retry')

    def test_terminal_two_cannot_execute_telecontrol(self):
        controller = self.controller('receiver')
        radio = controller.radio
        controller.submit('telecontrol', requested={})
        self.wait(lambda: any(event.get('state') == 'error' for event in self.events))
        self.assertIsNone(controller.transaction)
        self.assertEqual(self.count(radio, 'start_tx'), 0)

    @staticmethod
    def frame(text, sequence=1, corrupt=False):
        payload = encode_message(text, '1234abcd', sequence).encode('utf-8')
        return dict(payload_hex=payload.hex(), crc16=_link.crc16(payload) ^ int(corrupt),
                    carrier_offset_hz=-250000)

    def test_real_payload_crc_duplicate_and_conflict_checks(self):
        controller = self.controller()
        radio = controller.radio
        radio.pending.append([self.frame('actual')])
        self.wait(lambda: any(event['type'] == 'rx' and event.get('messages') for event in self.events))
        radio.pending.append([self.frame('actual'), self.frame('conflicting')])
        self.wait(lambda: any(event['type'] == 'log' and event.get('level') == 'error' for event in self.events))
        messages = [message for event in self.events if event['type'] == 'rx' for message in event['messages']]
        self.assertEqual([message['text'] for message in messages], ['actual'])
        self.assertTrue(messages[0]['crc_valid'])
        self.assertEqual(messages[0]['message_id'], '1234abcd:0001')
        radio.pending.append([self.frame('bad crc', sequence=2, corrupt=True)])
        self.wait(lambda: any(event.get('state') == 'error' for event in self.events))
        self.assertIsNone(controller.radio)
        self.assertFalse(any(message['text'] == 'bad crc' for event in self.events
                             if event['type'] == 'rx' for message in event['messages']))

    def test_plan_change_discards_old_sampling_and_restarts_receive(self):
        controller = self.controller()
        radio = controller.radio
        controller.poll_seconds=1000;controller.last_poll=time.monotonic()
        radio.pending.append([self.frame('stale pre-retune')])
        controller.submit('apply_plan', tx_center=1990.5, rx_center=2180.5)
        self.wait(lambda: any(e['type']=='local_plan_applied' for e in self.events))
        self.assertTrue(controller.rx_active)
        self.assertEqual(controller.settings['rx_lo_hz_readback'], 2180750000)
        self.assertFalse(radio.pending)
        self.assertFalse(any(message['text'] == 'stale pre-retune' for event in self.events
                             if event['type'] == 'rx' for message in event['messages']))

    def test_remote_ack_leaves_local_plan_unchanged(self):
        c=self.controller(); original=(c.tx_center,c.rx_center)
        transaction=_Transaction.__new__(_Transaction);transaction.owner=c
        transaction.event('result',passed=True,matched=True,
            requested=dict(operation='frequency',rx_hz=1984500000,tx_hz=2179500000),
            ack=dict(rx_hz=1984500000,tx_hz=2179500000))
        self.assertEqual((c.tx_center,c.rx_center),original)
        self.assertFalse(any(e['type']=='confirmed_plan' for e in self.events))

    def test_local_retune_stops_tx_and_does_not_replay_queued_text(self):
        c=self.controller(tx_dwell_seconds=30);r=c.radio
        c.submit('send',text='old active');self.wait(lambda:c.tx_active)
        item=c.submit('send',text='old queued')
        c.submit('apply_plan',tx_center='1985.001',rx_center='2180.002')
        self.wait(lambda:any(e['type']=='local_plan_applied' for e in self.events))
        self.assertFalse(c.tx_active);self.assertTrue(c.rx_active)
        self.assertEqual(c.jobs[item]['state'],'retry')
        self.assertEqual(self.count(r,'start_tx'),1)
        self.assertEqual(c.settings['requested_tx_center_hz'],1985001000)

    def test_local_retune_validation_and_tc_exclusion(self):
        c=self.controller();r=c.radio
        for tx,rx in [('1985.0001','2180'),('1979','2180'),('1985','2200')]:
            with self.assertRaises(ValueError):c.submit('apply_plan',tx_center=tx,rx_center=rx)
        self.assertIs(c.radio,r)
        c.transaction.block=True;c.submit('telecontrol',requested={})
        self.assertTrue(c.transaction.entered.wait(2))
        with self.assertRaises(RuntimeError):c.submit('apply_plan',tx_center=1985,rx_center=2180)
        c.transaction.release.set()

    def test_same_confirmed_plan_keeps_receiver_running(self):
        controller = self.controller('receiver')
        radio = controller.radio
        starts = self.count(radio, 'start_receive')
        mark = len(self.events)
        controller.submit('apply_plan', tx_center=float(controller.tx_center),
                          rx_center=float(controller.rx_center))
        self.wait(lambda: any(event['type'] == 'rx' for event in self.events[mark:]))
        self.assertEqual(self.count(radio, 'start_receive'), starts)
        self.assertEqual(self.count(radio, 'stop_receive'), 0)

    def test_successful_telecontrol_fifo_sends_new_jobs_without_replaying_old_text(self):
        controller = self.controller()
        radio = controller.radio
        old_id = controller.submit('send', text='old already sent')
        self.wait(lambda: controller.jobs[old_id]['state'] == 'sent')
        controller.transaction.block = True
        controller.submit('telecontrol', requested={})
        self.assertTrue(controller.transaction.entered.wait(2))
        ids = [controller.submit('send', text=text) for text in ('new first', 'new second')]
        self.assertEqual([controller.jobs[item]['state'] for item in ids], ['queued', 'queued'])
        self.assertTrue(any(event['type'] == 'tx_queue' and event['request_id'] == ids[-1]
                            and event['state'] == 'queued' for event in self.events))
        self.assertEqual(self.count(radio, 'start_tx'), 1)
        controller.transaction.release.set()
        self.wait(lambda: all(controller.jobs[item]['state'] == 'sent' for item in ids))
        transmitted = [event for event in self.events if event['type'] == 'tx']
        self.assertEqual([event['text'] for event in transmitted],
                         ['old already sent', 'new first', 'new second'])
        self.assertEqual(len({event['message_id'] for event in transmitted}), 3)
        self.assertEqual([event['request_id'] for event in transmitted], [old_id]+ids)
        names = [name for name, _ in radio.calls]
        resumed = names.index('start_receive', names.index('stop_receive'))
        next_tx = names.index('start_tx', names.index('start_tx')+1)
        self.assertLess(resumed, next_tx)
        for item in ids:
            states = [event['state'] for event in self.events if event['type'] == 'tx_queue'
                      and event['request_id'] == item]
            self.assertEqual(states, ['queued', 'sending', 'sent'])

    def test_fifo_minimum_dwell_keeps_polling_receive_between_messages(self):
        controller = self.controller(tx_dwell_seconds=2)
        radio = controller.radio
        first = controller.submit('send', text='first')
        self.wait(lambda: controller.jobs[first]['state'] == 'sent')
        second = controller.submit('send', text='second')
        radio.pending.append([self.frame('peer during transmit')])
        self.wait(lambda: any(event['type'] == 'rx' and event.get('messages') for event in self.events))
        self.assertEqual(controller.jobs[second]['state'], 'queued')
        self.wait(lambda: controller.jobs[second]['state'] == 'sent')
        starts = [stamp for name, stamp in radio.call_times if name == 'start_tx']
        self.assertGreaterEqual(starts[1]-starts[0], 2)
        self.assertEqual(self.count(radio, 'start_receive'), 1)
        self.assertEqual(self.count(radio, 'stop_receive'), 0)
        self.assertEqual([event['text'] for event in self.events if event['type'] == 'tx'], ['first', 'second'])

    def test_queue_validation_capacity_and_idempotency_are_synchronous_during_tc(self):
        controller = self.controller()
        controller.transaction.block = True
        controller.submit('telecontrol', requested={})
        self.assertTrue(controller.transaction.entered.wait(2))
        with self.assertRaises(ValueError): controller.submit('send', text='x'*33)
        with self.assertRaises(ValueError): controller.submit('send', text='')
        ids = [controller.submit('send', text=f'job {index}', request_id=f'job-{index}') for index in range(8)]
        with self.assertRaises(queue.Full): controller.submit('send', text='overflow')
        self.assertEqual(controller.submit('send', text='job 0', request_id=ids[0]), ids[0])
        with self.assertRaises(ValueError): controller.submit('send', text='conflict', request_id=ids[0])
        queued = [event for event in self.events if event['type'] == 'tx_queue' and event['state'] == 'queued']
        self.assertEqual(len(queued), 8)
        self.assertEqual([event['request_id'] for event in queued], ids)
        self.assertFalse(any(event['type'] == 'tx' for event in self.events))
        self.assertEqual(controller.jobs[ids[-1]]['state'], 'queued')

    def test_failed_tc_keeps_jobs_for_manual_retry_in_selected_order(self):
        controller = self.controller()
        radio = controller.radio
        controller.transaction.block = controller.transaction.fail = True
        controller.submit('telecontrol', requested={})
        self.assertTrue(controller.transaction.entered.wait(2))
        first = controller.submit('send', text='queued first')
        second = controller.submit('send', text='queued second')
        controller.transaction.release.set()
        self.wait(lambda: controller.rx_active and all(controller.jobs[item]['state'] == 'retry'
                                                       for item in (first, second)))
        self.assertEqual(self.count(radio, 'start_tx'), 0)
        self.assertEqual(controller.submit('retry', request_id=second), second)
        self.assertEqual(controller.submit('retry', request_id=first), first)
        self.wait(lambda: all(controller.jobs[item]['state'] == 'sent' for item in (first, second)))
        self.assertEqual([event['text'] for event in self.events if event['type'] == 'tx'],
                         ['queued second', 'queued first'])
        with self.assertRaises(ValueError): controller.submit('retry', request_id=first)

    def test_negative_tc_result_and_cancel_keep_unsent_jobs_as_retry(self):
        for cancel in (False, True):
            with self.subTest(cancel=cancel):
                controller = self.controller()
                radio = controller.radio
                controller.transaction.block = True
                controller.transaction.fail_result = not cancel
                controller.submit('telecontrol', requested={})
                self.assertTrue(controller.transaction.entered.wait(2))
                item = controller.submit('send', text='manual retry only')
                if cancel: controller.submit('cancel_tc')
                else: controller.transaction.release.set()
                self.wait(lambda: controller.rx_active and controller.jobs[item]['state'] == 'retry')
                self.assertEqual(self.count(radio, 'start_tx'), 0)
                controller.submit('retry', request_id=item)
                self.wait(lambda: controller.jobs[item]['state'] == 'sent')
                self.assertEqual(self.count(radio, 'start_tx'), 1)

    def test_tc_success_without_active_relay_keeps_new_jobs_for_manual_retry(self):
        outcomes = [dict(requested=dict(operation='frequency')),
                    dict(requested=dict(operation='stop')),
                    dict(requested=dict(operation='status'), relay=dict(valid=True, mode=2,
                         lease_active=False, remaining_lower_bound_ms=0)),
                    dict(relay=dict(valid=True, mode=1, lease_active=True, remaining_lower_bound_ms=0)),
                    dict(ack=dict(rx_hz=1984500000,tx_hz=2179500000)),
                    dict(ack={}),
                    dict(matched=False)]
        for outcome in outcomes:
            with self.subTest(outcome=outcome):
                controller = self.controller()
                radio = controller.radio
                controller.transaction.block = True
                controller.transaction.result_override = outcome
                controller.submit('telecontrol', requested={})
                self.assertTrue(controller.transaction.entered.wait(2))
                item = controller.submit('send', text='requires active relay')
                controller.transaction.release.set()
                self.wait(lambda: controller.rx_active and controller.jobs[item]['state'] == 'retry')
                self.assertEqual(self.count(radio, 'start_tx'), 0)
                self.assertTrue(any(event['type'] == 'tx_queue' and event['request_id'] == item
                                    and event['state'] == 'retry' and event.get('reason') for event in self.events))

    def test_failed_rf_attempt_has_new_message_id_on_manual_retry_after_reconnect(self):
        controller = self.controller()
        controller.radio.fail_prepare_once = True
        item = controller.submit('send', text='try again')
        self.wait(lambda: controller.radio is None and controller.jobs[item]['state'] == 'retry')
        old_message = controller.jobs[item]['message_id']
        controller.submit('connect', port='FAKE_A')
        self.wait(lambda: controller.rx_active)
        self.assertEqual(controller.jobs[item]['state'], 'retry')
        controller.submit('retry', request_id=item)
        self.wait(lambda: controller.jobs[item]['state'] == 'sent')
        self.assertNotEqual(controller.jobs[item]['message_id'], old_message)
        sent = [event for event in self.events if event['type'] == 'tx']
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]['request_id'], item)

    def test_guard_not_started_does_not_emit_false_sent_confirmation(self):
        controller = self.controller()
        controller.radio.guard = 'stopped'
        item = controller.submit('send', text='not actually enabled')
        self.wait(lambda: controller.radio is None)
        self.assertEqual(controller.jobs[item]['state'], 'retry')
        self.assertFalse(any(event['type'] == 'tx' for event in self.events))
        self.assertFalse(any(event['type'] == 'tx_queue' and event['state'] == 'sent' for event in self.events))

    def test_disconnect_preserves_retry_without_automatic_replay_after_reconnect(self):
        controller = self.controller()
        controller.transaction.block = True
        controller.submit('telecontrol', requested={})
        self.assertTrue(controller.transaction.entered.wait(2))
        item = controller.submit('send', text='manual after reconnect')
        controller.submit('disconnect')
        self.wait(lambda: controller.radio is None and not controller.interrupt.is_set())
        self.assertEqual(controller.jobs[item]['state'], 'retry')
        with self.assertRaises(RuntimeError): controller.submit('retry', request_id=item)
        controller.submit('connect', port='FAKE_A')
        self.wait(lambda: controller.rx_active)
        self.assertEqual(controller.jobs[item]['state'], 'retry')
        self.assertFalse(any(event['type'] == 'tx' for event in self.events))
        controller.submit('retry', request_id=item)
        self.wait(lambda: controller.jobs[item]['state'] == 'sent')

    def test_concurrent_submission_journal_is_complete_json_and_queue_bounded(self):
        controller = self.controller()
        controller.transaction.block = True
        controller.submit('telecontrol', requested={})
        self.assertTrue(controller.transaction.entered.wait(2))
        accepted, rejected = [], []
        def submit(index):
            try: accepted.append(controller.submit('send', text=f'thread {index}'))
            except queue.Full: rejected.append(index)
        threads = [threading.Thread(target=submit, args=(index,)) for index in range(12)]
        for thread in threads: thread.start()
        for thread in threads: thread.join(2)
        self.assertEqual(len(accepted), 8)
        self.assertEqual(len(rejected), 4)
        records = [json.loads(line) for line in (controller.log_dir/'events.jsonl').read_text(encoding='utf-8').splitlines()]
        queued = [record for record in records if record.get('type') == 'tx_queue' and record['state'] == 'queued']
        self.assertEqual({record['request_id'] for record in queued}, set(accepted))

    def test_both_terminals_transmit_and_receive_concurrently(self):
        first, second = self.controller(), self.controller('receiver')
        first_id = first.submit('send', text='to terminal two')
        second_id = second.submit('send', text='to terminal one')
        self.wait(lambda: first.tx_active and second.tx_active)
        first.radio.pending.append([self.frame('to terminal one')])
        second.radio.pending.append([self.frame('to terminal two', sequence=2)])
        self.wait(lambda: len([event for event in self.events if event['type'] == 'rx' and event.get('messages')]) >= 2)
        self.assertTrue(first.rx_active and second.rx_active)
        self.assertEqual(first.jobs[first_id]['state'], 'sent')
        self.assertEqual(second.jobs[second_id]['state'], 'sent')
        self.assertEqual(self.count(first.radio, 'start_receive'), 1)
        self.assertEqual(self.count(second.radio, 'start_receive'), 1)


if __name__ == '__main__':
    unittest.main()
