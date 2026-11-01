"""Unified terminal ownership and control subscription tests; no hardware."""
import queue
import tkinter as tk
import unittest
from unittest.mock import patch

from .ui_v2 import ReviewSession
from .test_ui_v2 import PORTS, ALIASES
from ._tk_test_support import dispose_tk_test


class FakeTerminal:
    def __init__(self, role, emit, log_dir=None):
        self.role, self.emit, self.calls = role, emit, []

    def submit(self, action, **kwargs):
        self.calls.append((action, kwargs))


class UnifiedSessionTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.created = []

        def factory(*args, **kwargs):
            controller = FakeTerminal(*args, **kwargs)
            self.created.append(controller)
            return controller

        self.session = ReviewSession(self.root, port_provider=lambda: PORTS,
            aliases=ALIASES, online_control=True, online_business=True,
            terminal_controller_factory=factory)

    def tearDown(self):
        dispose_tk_test(self)

    def flush(self):
        # The periodic callback is intentionally bypassed, keeping tests deterministic.
        if self.session._terminal_poll_id:
            self.root.after_cancel(self.session._terminal_poll_id)
            self.session._terminal_poll_id = None
        self.session._drain_terminal_events()

    def test_sender_and_control_share_worker_and_filter_channels(self):
        business, control = [], []
        sender = self.session.terminal_controller('sender', business.append)
        tc = self.session.terminal_controller('control', control.append)
        self.assertEqual(len(self.created), 1)
        backend = self.created[0]
        tc.submit('send', requested={'air_seq': 3}, wiring_confirmed=True)
        self.assertEqual(backend.calls[-1], ('telecontrol', dict(requested={'air_seq': 3}, wiring_confirmed=True)))
        backend.emit(dict(type='rx', messages=[]))
        backend.emit(dict(type='result', channel='control', passed=True))
        backend.emit(dict(type='terminal_state', connected=True, rx_active=True, tx_active=False, tc_active=False))
        self.assertEqual(business, [])
        self.flush()
        self.assertEqual([event['type'] for event in business], ['rx', 'terminal_state'])
        self.assertEqual([event['type'] for event in control], ['result', 'terminal_state'])
        self.assertIsNone(self.session.other_owner('sender'))
        tc.submit('disconnect')
        self.assertEqual(backend.calls[-1], ('cancel_tc', {}))
        sender.submit('stop_tx')
        self.assertEqual(backend.calls[-1], ('stop_tx', {}))

    def test_detach_keeps_worker_until_final_owner_and_waits_for_closed(self):
        business, control = [], []
        sender = self.session.terminal_controller('sender', business.append)
        tc = self.session.terminal_controller('control', control.append)
        backend = self.created[0]
        tc.close()
        self.assertEqual(control[-1]['type'], 'closed')
        self.assertNotIn(('close', {}), backend.calls)
        sender.close()
        self.assertEqual(backend.calls[-1], ('close', {}))
        self.assertEqual(business, [])
        backend.emit(dict(type='closed'))
        self.flush()
        self.assertEqual(business[-1]['type'], 'closed')
        self.assertFalse(self.session._terminals)

    def test_close_cancels_submitted_tc_despite_delayed_old_or_idle_states(self):
        self.session.terminal_controller('sender', lambda event: None)
        tc = self.session.terminal_controller('control', lambda event: None)
        backend = self.created[0]
        # These belong to a previous TC but have not reached the Tk session poll.
        backend.emit(dict(type='terminal_state', connected=True, tc_active=True))
        backend.emit(dict(type='status', channel='control', state='error', category='cancelled'))
        backend.emit(dict(type='terminal_state', connected=True, tc_active=False))
        tc.submit('send', requested=dict(air_seq=7))
        # An unrelated business state while this TC is still queued is not completion.
        backend.emit(dict(type='terminal_state', connected=True, tc_active=False, tx_active=True))
        backend.emit(dict(type='result', channel='control', requested=dict(air_seq=6), passed=True))
        tc.close()
        self.assertEqual([action for action, values in backend.calls], ['telecontrol', 'cancel_tc'])
        self.assertIsNotNone(tc.tc_pending)

    def test_close_consumes_completed_tc_before_deciding_to_cancel_business(self):
        self.session.terminal_controller('sender', lambda event: None)
        tc = self.session.terminal_controller('control', lambda event: None)
        backend = self.created[0]
        tc.submit('send', requested=dict(air_seq=8))
        backend.emit(dict(type='terminal_state', connected=True, tc_active=True))
        self.flush()
        backend.emit(dict(type='result', channel='control', requested=dict(air_seq=8), passed=True))
        backend.emit(dict(type='terminal_state', connected=True, tc_active=False,
            rx_active=True, tx_active=True))
        # Completion is produced, but the periodic poll has not yet consumed it.
        tc.close()
        self.assertIsNone(tc.tc_pending)
        self.assertEqual([action for action, values in backend.calls], ['telecontrol'])
        self.assertTrue(self.session._terminals['sender']['state']['tx_active'])

    def test_cancelled_queued_tc_releases_pending_without_an_active_transition(self):
        self.session.terminal_controller('sender', lambda event: None)
        tc = self.session.terminal_controller('control', lambda event: None)
        backend = self.created[0]
        tc.submit('send', requested=dict(air_seq=9))
        tc.submit('stop')
        backend.emit(dict(type='status', channel='control', state='error', category='cancelled'))
        backend.emit(dict(type='terminal_state', connected=True, tc_active=False, rx_active=True))
        self.flush()
        self.assertIsNone(tc.tc_pending)
        before = list(backend.calls)
        tc.close()
        self.assertEqual(backend.calls, before)

    def test_rejected_tc_queue_leaves_no_pending_or_unrelated_stop(self):
        control = self.session.show('control')
        backend = self.created[0]
        backend.emit(dict(type='terminal_state', connected=True, source=dict(port='COM_A'),
            tc_active=False, rx_active=True, tx_active=True))
        self.flush()
        control._drain_online_events()
        control.generate_command()
        with patch.object(backend, 'submit', side_effect=queue.Full('测控队列已满')) as submit:
            control.send_online()
            self.assertEqual(submit.call_count, 1)
            self.assertEqual(submit.call_args.args, ('telecontrol',))
        self.assertIsNone(control.controller.tc_pending)
        self.assertFalse(control.cancel_pending)
        self.assertTrue(control.local_claimed)
        self.assertIn('未提交', control.request_note.get())
        self.session.close('control')
        control._drain_online_events()
        self.assertNotIn('control', self.session.windows)
        self.assertEqual(backend.calls, [])

    def test_remote_plan_never_retunes_either_terminal(self):
        self.session.terminal_controller('sender', lambda event: None)
        self.session.terminal_controller('receiver', lambda event: None)
        sender, receiver = self.created
        sender.emit(dict(type='confirmed_plan', tx_center='2200.5', rx_center='2180.5'))
        self.assertEqual(receiver.calls, [])
        self.flush()
        self.assertEqual(receiver.calls, [])
        self.assertEqual(sender.calls, [])

    def test_retry_queue_state_is_retained_when_business_page_detaches(self):
        first, replayed = [], []
        sender = self.session.terminal_controller('sender', first.append)
        self.session.terminal_controller('control', lambda event: None)
        backend = self.created[0]
        backend.emit(dict(type='tx_queue', request_id='pending:1', text='keep me', state='retry'))
        self.flush()
        sender.close()
        self.session.terminal_controller('sender', replayed.append)
        self.assertEqual(len(self.created), 1)
        self.assertEqual(replayed, [dict(type='tx_queue', request_id='pending:1', text='keep me', state='retry')])
        self.assertNotIn(('close', {}), backend.calls)

    def test_control_only_mode_opens_passive_terminal_connection_entry(self):
        self.session.online_business = False
        control = self.session.show('control')
        sender = self.session.windows['sender']
        self.assertTrue(sender.business_online)
        self.assertEqual(len(self.created), 1)
        self.assertEqual(self.created[0].calls, [])
        self.assertEqual(control.online_state, 'disconnected')
        self.assertEqual(str(sender.connect_button['state']), 'normal')

    def test_control_error_keeps_inherited_connection_and_recovers_query(self):
        control = self.session.show('control')
        backend = self.created[0]
        backend.emit(dict(type='terminal_state', connected=True, source=dict(port='COM_A'),
            rx_active=True, tx_active=False, tc_active=False))
        self.flush()
        control._drain_online_events()
        identity = control.online_identity
        for category in ('timeout', 'hardware'):
            control.generate_command()
            control.send_online()
            backend.emit(dict(type='status', channel='control', state='error',
                category=category, message='transaction failed'))
            self.flush()
            control._drain_online_events()
            self.assertIs(control.online_identity, identity)
            self.assertTrue(control.local_claimed)
            self.assertIn('结果未知', control.reply_title.get())
            self.assertNotIn('断开', control.connection_status.get())
            self.assertNotIn('重新连接', control.request_note.get())
            backend.emit(dict(type='status', channel='control', state='disconnected'))
            self.flush()
            control._drain_online_events()
            self.assertIs(control.online_identity, identity)
            self.assertNotIn('断开', control.connection_status.get())
            backend.emit(dict(type='terminal_state', connected=True, source=dict(port='COM_A'),
                rx_active=True, tx_active=False, tc_active=False))
            self.flush()
            control._drain_online_events()
            identity = control.online_identity
            control.operation.set('查询状态')
            control.generate_command()
            self.assertEqual(str(control.command_send_button['state']), 'normal')

    def test_cancellation_ack_finishes_title_without_claiming_disconnect(self):
        control = self.session.show('control')
        backend = self.created[0]
        backend.emit(dict(type='terminal_state', connected=True, source=dict(port='COM_A'),
            rx_active=True, tx_active=False, tc_active=False))
        self.flush()
        control._drain_online_events()
        control.generate_command()
        control.send_online()
        control.cancel_online()
        self.assertEqual(control.reply_title.get(), '正在取消测控')
        backend.emit(dict(type='status', channel='control', state='error',
            category='cancelled', message='cancelled'))
        backend.emit(dict(type='terminal_state', connected=True, source=dict(port='COM_A'),
            rx_active=True, tx_active=False, tc_active=False))
        self.flush()
        control._drain_online_events()
        self.assertEqual(control.reply_title.get(), '测控已取消 · 结果未知')
        self.assertIn('业务接收已恢复', control.reply_body.get())
        self.assertNotIn('断开', control.connection_status.get())
        self.assertIsNotNone(control.online_identity)
        self.assertFalse(control.cancel_pending)
        self.assertEqual(control.online_state, 'connected')

    def test_remote_plan_does_not_submit_to_receiver_even_if_queue_is_full(self):
        control = self.session.show('control')
        receiver = self.session.show('receiver')
        source_backend, receiver_backend = self.created
        with patch.object(receiver_backend, 'submit', side_effect=queue.Full):
            source_backend.emit(dict(type='confirmed_plan', tx_center=1990.5, rx_center=2180.5))
            self.flush()
        control._drain_online_events()
        receiver._drain_online_events()
        self.assertNotIn('终端2频率同步失败', control.request_note.get())
        self.assertEqual(receiver_backend.calls, [])
        self.assertIsNotNone(self.session._terminal_poll_id)
        source_backend.emit(dict(type='terminal_state', connected=True,
            rx_active=True, tx_active=False, tc_active=False))
        source_backend.emit(dict(type='confirmed_plan', tx_center=1990.5, rx_center=2180.5))
        self.flush()
        control._drain_online_events()
        self.assertEqual(control.online_state, 'connected')
        self.assertEqual(receiver_backend.calls, [])

    def test_later_receiver_does_not_inherit_remote_plan(self):
        self.session.terminal_controller('sender', lambda e: None)
        self.created[0].emit(dict(type='confirmed_plan',tx_center=1985,rx_center=2180))
        self.flush()
        self.session.terminal_controller('receiver', lambda e: None)
        self.assertEqual(self.created[1].calls, [])

    def test_control_inherits_connection_and_cannot_disconnect_business(self):
        sender = self.session.show('sender')
        control = self.session.show('control')
        self.assertIs(sender.controller.session, control.controller.session)
        backend = self.created[0]
        self.assertFalse(control.port_combo.winfo_manager())
        self.assertFalse(control.connect_button.winfo_manager())
        backend.emit(dict(type='terminal_state', connected=True,
            rx_active=True, tx_active=False, tc_active=False))
        self.flush()
        control._drain_online_events()
        self.assertEqual(control.online_state, 'connected')
        self.assertIsNotNone(control.online_identity)
        control.generate_command()
        self.assertEqual(str(control.command_send_button['state']), 'normal')
        control.cancel_online()
        self.assertEqual(backend.calls[-1], ('cancel_tc', {}))
        backend.emit(dict(type='terminal_state', connected=True,
            rx_active=True, tx_active=False, tc_active=False))
        self.flush()
        control._drain_online_events()
        self.assertFalse(control.cancel_pending)
        self.assertEqual(control.online_state, 'connected')


if __name__ == '__main__':
    unittest.main()
