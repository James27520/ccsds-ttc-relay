"""Shared-terminal UI tests; fake controllers, no serial or RF access."""
import tkinter as tk
import unittest
from unittest.mock import patch

from ._tk_test_support import dispose_tk_test
from .test_ui_v2 import ALIASES, PORTS
from .ui_v2 import ReviewSession, main


class FakeTerminalController:
    def __init__(self, emit):
        self.emit = emit
        self.calls = []

    def submit(self, action, **values):
        self.calls.append((action, values))
        return values.get('request_id')


class TerminalWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.session = ReviewSession(self.root, port_provider=lambda: PORTS, aliases=ALIASES,
                                     online_business=True)
        self.session.terminal_controller = lambda role, emit: FakeTerminalController(emit)
        self.sender = self.session.show('sender')
        self.receiver = self.session.show('receiver')

    def tearDown(self):
        dispose_tk_test(self)

    def ready(self, page):
        page.connect_business()
        port = self.session.devices[page.selection.get()]['port']
        page._handle_business_event(dict(type='identity', identity=dict(port=port)))
        page._handle_business_event(dict(type='settings', values=dict(configured=True,
            tx_lo_hz_readback=1989000000, rx_lo_hz_readback=2179750000,
            expected_rf_hz=2179500000)))
        page._handle_business_event(dict(type='status', state='receiving', message='auto receive'))

    def test_both_terminals_send_while_automatically_receiving(self):
        for page in (self.sender, self.receiver):
            self.ready(page)
            page.message_input.insert('1.0', 'hello')
            page._text_changed()
            self.assertEqual(str(page.send_button['state']), 'normal')
            page.send_business()
            action, values = page.controller.calls[-1]
            self.assertEqual(action, 'send')
            self.assertEqual(values['text'], 'hello')
            self.assertEqual(len(values['request_id']), 32)
            self.assertIn('排队中', page.history.item(page.history.get_children()[0], 'values')[3])
            self.assertFalse(any(action in ('receive', 'configure') for action, _ in page.controller.calls))
            self.assertEqual(page.sender_frequency.get(), '1989.500000')
            self.assertEqual(page.receiver_frequency.get(), '2179.500000')
            self.assertIn('2179.750000', page.receiver_plan_note.get())
            self.assertFalse(hasattr(page, 'receive_button'))
            self.assertFalse(hasattr(page, 'tx_frequency_combo'))
            self.assertFalse(hasattr(page, 'rx_apply_button'))

    def test_receive_status_and_send_controls_remain_visible_at_minimum_size(self):
        for page in (self.sender, self.receiver):
            page.window.geometry('1040x800')
            self.ready(page)
            page.received_text.set('bidirectional text 12345678901234')
            self.root.update()
            for widget in (page.local_apply_button, page.send_button,
                           page.received_hero, page.received_meta_label, page.frame_stats_label, page.history):
                self.assertTrue(widget.winfo_ismapped())
                self.assertGreaterEqual(widget.winfo_height(), widget.winfo_reqheight())
                self.assertLessEqual(widget.winfo_rooty()+widget.winfo_height(),
                                     page.window.winfo_rooty()+page.window.winfo_height())

    def test_each_terminal_applies_only_its_own_free_frequency_request(self):
        for page, peer in ((self.sender,self.receiver),(self.receiver,self.sender)):
            self.ready(page)
            page.local_tx_center.set('1985.123')
            page.local_rx_center.set('2180.456')
            page.message_input.insert('1.0', 'pending plan')
            page._text_changed()
            self.assertEqual(str(page.send_button['state']), 'disabled')
            self.assertEqual(str(page.local_apply_button['state']), 'normal')
            other_calls=list(peer.controller.calls)
            page.local_apply_button.invoke()
            self.assertEqual(page.controller.calls[-1], ('apply_plan',dict(tx_center=1985.123,rx_center=2180.456)))
            self.assertEqual(peer.controller.calls,other_calls)
            self.assertTrue(page.local_apply_pending)
            # Draft edits while applying must survive late old settings.
            page.local_tx_center.set('1985.124')
            page._handle_business_event(dict(type='settings',values=dict(configured=True,
                tx_lo_hz_readback=1984622998,rx_lo_hz_readback=2180706000,
                requested_tx_center_hz=1985123000,requested_rx_center_hz=2180456000)))
            page._handle_business_event(dict(type='local_plan_applied'))
            self.assertEqual(page.local_tx_center.get(),'1985.124')
            self.assertFalse(page.local_apply_pending)
            self.assertEqual(str(page.send_button['state']),'disabled')
            page.local_tx_center.set('1985.123')
            self.assertEqual(str(page.send_button['state']),'normal')

    def test_invalid_local_frequency_and_tc_never_apply(self):
        page=self.sender; self.ready(page)
        for value in ('1979','1985.0001','nan','2200'):
            page.local_tx_center.set(value)
            before=list(page.controller.calls)
            page.apply_local_frequency()
            self.assertEqual(page.controller.calls,before)
        page.local_tx_center.set('1985')
        page._handle_business_event(dict(type='terminal_state',connected=True,rx_active=False,tc_active=True))
        self.assertEqual(str(page.local_apply_button['state']),'disabled')
        before=list(page.controller.calls);page.apply_local_frequency()
        self.assertEqual(page.controller.calls,before)

    def test_local_plan_submission_rejection_preserves_connection(self):
        page=self.sender;self.ready(page);page.local_tx_center.set('1985')
        with patch.object(page.controller,'submit',side_effect=RuntimeError('测控尚未结束')):
            page.apply_local_frequency()
        self.assertTrue(page.local_claimed)
        self.assertFalse(page.local_apply_pending)
        self.assertFalse(page.cancel_pending)
        self.assertIn('本机频率未提交',page.connection_issue.get())

    def test_connect_uses_local_draft_and_preview_does_not_apply(self):
        page=self.sender
        page.local_tx_center.set('1985.001');page.local_rx_center.set('2180.002')
        page.connect_business()
        self.assertEqual(page.controller.calls[-1][1]['tx_center'],1985.001)
        self.assertEqual(page.controller.calls[-1][1]['rx_center'],2180.002)
        page.business_online=False
        before=list(page.controller.calls);page.apply_local_frequency()
        self.assertEqual(page.controller.calls,before)

    def test_event_type_classifies_history_independent_of_role(self):
        for page in (self.sender, self.receiver):
            self.ready(page)
            page._handle_business_event(dict(type='tx', text='out', message_id='tx:1'))
            page._handle_business_event(dict(type='rx', messages=[
                dict(text='in', message_id='rx:1', crc_valid=True),
                dict(text='bad', message_id='rx:bad', crc_valid=False)],
                received_at=1793000000, valid_frames=1, crc_rejected=1))
            rows = [page.history.item(item) for item in page.history.get_children()]
            self.assertEqual(len(rows), 2)
            by_text = {row['values'][2]: row for row in rows}
            self.assertIn('sent', by_text['out']['tags'])
            self.assertIn('received', by_text['in']['tags'])
            self.assertIn('CRC 有效', by_text['in']['values'][3])
            self.assertEqual(page.received_text.get(), 'in')
            self.assertEqual(page.received_count.get(), '实收 1 条')

    def test_stop_only_transmits_and_telecontrol_shows_pause(self):
        self.ready(self.sender)
        self.sender._handle_business_event(dict(type='terminal_state', connected=True,
            rx_active=False, tx_active=True, tc_active=False))
        self.assertEqual(str(self.sender.business_stop_button['state']), 'normal')
        self.sender.business_stop_button.invoke()
        self.assertEqual(self.sender.controller.calls[-1], ('stop_tx', {}))
        self.sender._handle_business_event(dict(type='terminal_state', connected=True,
            rx_active=False, tx_active=False, tc_active=True))
        self.assertIn('测控', self.sender.mode_label.get())
        self.sender._handle_business_event(dict(type='terminal_state', connected=True,
            rx_active=True, tx_active=False, tc_active=False))
        self.assertIn('自动接收', self.sender.mode_label.get())
        self.assertEqual(str(self.sender.business_stop_button['state']), 'disabled')

    def test_tc_queue_states_retry_and_tx_share_one_history_row(self):
        page = self.sender
        self.ready(page)
        page._handle_business_event(dict(type='terminal_state', connected=True,
            rx_active=False, tx_active=False, tc_active=True))
        page.message_input.insert('1.0', 'queued text')
        page._text_changed()
        self.assertEqual(str(page.send_button['state']), 'normal')
        page.send_business()
        request_id = page.controller.calls[-1][1]['request_id']
        row = page.tx_requests[request_id]['row']
        self.assertIn('排队中', page.history.set(row, 'status'))
        self.assertEqual(page.sent_count.get(), '已发 0 条')
        page._handle_business_event(dict(type='tx_queue', request_id=request_id,
            text='queued text', state='retry', reason='测控取消'))
        page.history.selection_set(row)
        page.update_business_controls()
        self.assertEqual(str(page.retry_button['state']), 'normal')
        page.retry_button.invoke()
        self.assertEqual(page.controller.calls[-1], ('retry', dict(request_id=request_id)))
        self.assertIn('排队中', page.history.set(row, 'status'))
        page._handle_business_event(dict(type='tx_queue', request_id=request_id,
            text='queued text', state='sending'))
        self.assertIn('发送中', page.history.set(row, 'status'))
        page._handle_business_event(dict(type='tx', request_id=request_id,
            text='queued text', message_id='actual:1'))
        page._handle_business_event(dict(type='tx_queue', request_id=request_id,
            text='queued text', state='sent', message_id='actual:1'))
        self.assertEqual(len(page.history.get_children()), 1)
        self.assertEqual(page.history.set(row, 'status'), '↑ 发出 · 已发送')
        self.assertEqual(page.sent_count.get(), '已发 1 条')
        page._handle_business_event(dict(type='tx_queue', request_id=request_id,
            text='queued text', state='retry'))
        self.assertEqual(str(page.retry_button['state']), 'disabled')
        before = list(page.controller.calls)
        page.retry_selected()
        self.assertEqual(page.controller.calls, before)
        self.assertEqual(page.received_text.get(), '等待接收文本')

    def test_connecting_then_false_state_stays_busy_and_error_is_visibly_bound(self):
        page = self.sender
        self.assertFalse(page.connection_issue_label.winfo_ismapped())
        page.connect_business()
        page.controller.emit(dict(type='status', state='connecting', message='正在核验本地终端'))
        page.controller.emit(dict(type='terminal_state', connected=False,
            rx_active=False, tx_active=False, tc_active=False, message='正在核验本地终端'))
        page._drain_online_events()
        self.root.update_idletasks()
        self.assertEqual(page.online_state, 'connecting')
        self.assertEqual(page.business_pending, 'connect')
        self.assertTrue(page.accept_connected)
        self.assertEqual(str(page.connect_button['state']), 'disabled')
        self.assertIn('正在连接', page.connection_status.get())
        self.assertFalse(page.connection_issue_label.winfo_ismapped())

        # Exact status/state sequence and cause recorded by the real COM17 attempt.
        cause = '板卡停留在启动引导界面（U-Boot），Linux 未运行；请恢复板卡启动后再连接'
        page.controller.emit(dict(type='status', state='error', message=cause))
        page.controller.emit(dict(type='terminal_state', connected=False,
            rx_active=False, tx_active=False, tc_active=False, message=cause))
        page.controller.emit(dict(type='status', state='disconnected', message='已断开'))
        page._drain_online_events()
        self.root.update_idletasks()
        issue = page.connection_issue_label
        self.assertTrue(issue.winfo_ismapped())
        self.assertEqual(self.root.getvar(issue.cget('textvariable')), cause)
        self.assertIs(issue.master, page.connect_button.master.master)
        self.assertGreater(issue.winfo_rooty(), page.connect_button.winfo_rooty())
        self.assertEqual(page.online_state, 'error')
        self.assertEqual(page.business_note.get(), cause)
        self.assertIn('连接异常', page.connection_status.get())
        self.assertEqual(str(page.connect_button['state']), 'normal')

        page.connect_business()
        self.root.update_idletasks()
        self.assertFalse(issue.winfo_ismapped())
        self.assertEqual(self.root.getvar(issue.cget('textvariable')), '')
        self.assertEqual(page.online_state, 'connecting')
        page._handle_business_event(dict(type='terminal_state', connected=True,
            rx_active=True, tx_active=False, tc_active=False))
        self.root.update_idletasks()
        self.assertIsNone(page.last_business_error)
        self.assertFalse(issue.winfo_ismapped())
        self.assertEqual(page.online_state, 'receiving')

    def test_rejected_queue_submission_keeps_connection_and_no_ghost_row(self):
        page = self.sender
        self.ready(page)
        page.message_input.insert('1.0', 'queue full')
        with patch.object(page.controller, 'submit', side_effect=ValueError('发送队列已满')):
            page.send_business()
        self.assertTrue(page.local_claimed)
        self.assertFalse(page.cancel_pending)
        self.assertEqual(page.history.get_children(), ())
        self.assertIn('未加入发送队列', page.business_note.get())
        self.root.update_idletasks()
        issue = page.connection_issue_label
        self.assertTrue(issue.winfo_ismapped())
        self.assertIn('发送队列已满', self.root.getvar(issue.cget('textvariable')))
        # An unrelated healthy-state update must not swallow a rejected-send cause.
        page._handle_business_event(dict(type='terminal_state', connected=True,
            rx_active=True, tx_active=False, tc_active=False))
        self.assertIn('发送队列已满', self.root.getvar(issue.cget('textvariable')))
        page.send_business()
        self.root.update_idletasks()
        self.assertFalse(issue.winfo_ismapped())
        self.assertEqual(self.root.getvar(issue.cget('textvariable')), '')
        self.assertEqual(len(page.history.get_children()), 1)

    def test_close_detaches_without_disconnecting_shared_service(self):
        self.ready(self.sender)
        controller = self.sender.controller
        self.sender.close_business()
        self.assertEqual(controller.calls[-1], ('close', {}))
        self.assertFalse(any(action == 'disconnect' for action, _ in controller.calls))

    def test_explicit_preview_cannot_enable_online_flags(self):
        with patch('sw.ground_station.ui_v2.tk.Tk'), patch('sw.ground_station.ui_v2.ReviewSession') as factory:
            main(['--all', '--preview'])
            self.assertFalse(factory.call_args.kwargs['online_business'])
            self.assertFalse(factory.call_args.kwargs['online_control'])
        with patch('sw.ground_station.ui_v2.tk.Tk') as root_factory, patch('sys.stderr'):
            with self.assertRaises(SystemExit):
                main(['--all', '--preview', '--online-business'])
            root_factory.assert_not_called()

    def test_offline_preview_has_no_controller_or_enabled_actions(self):
        with patch.object(self.session, 'terminal_controller', side_effect=AssertionError('offline hardware')):
            self.session.online_business = False
            self.session._destroy_page('receiver', keep_root=True)
            self.receiver = self.session.show('receiver')
        self.assertIsNone(self.receiver.controller)
        self.assertEqual(str(self.receiver.send_button['state']), 'disabled')
        self.assertEqual(str(self.receiver.connect_button['state']), 'disabled')
        self.assertIn('离线', self.receiver.mode_label.get())
        self.assertIn('[离线预览]', self.receiver.window.title())
        self.assertNotIn('[离线预览]', self.sender.window.title())
        widgets = [self.receiver.window]
        labels = []
        while widgets:
            widget = widgets.pop()
            widgets.extend(widget.winfo_children())
            if isinstance(widget, tk.Label):
                labels.append(widget.cget('text'))
        self.assertTrue(any('start_station_v2.bat' in value for value in labels))


if __name__ == '__main__':
    unittest.main()
