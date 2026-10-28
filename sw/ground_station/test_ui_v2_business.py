"""Business v2 UI checks use fake controllers only, never serial or real workers."""
import threading
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

from .test_ui_v2 import ALIASES, PORTS, FakeTelecontrolController, history_fixture
from ._tk_test_support import dispose_tk_test
from .ui_v2 import ReviewSession, main


class FakeBusinessController:
    def __init__(self, role, emit, log_dir=None):
        self.role, self.emit, self.calls = role, emit, []

    def submit(self, action, **kwargs):
        self.calls.append((action, kwargs))


class BusinessWindowTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.tk.call('tk', 'scaling', 1.33)
        self.serial_patch = patch('serial.Serial', side_effect=AssertionError('UI opened hardware'))
        self.serial_patch.start()
        self.session = ReviewSession(self.root, port_provider=lambda: PORTS, aliases=ALIASES,
            online_business=True, online_control=True, controller_factory=FakeTelecontrolController,
            business_controller_factory=FakeBusinessController)
        self.sender, self.receiver, self.control = [self.session.show(role) for role in ('sender', 'receiver', 'control')]

    def tearDown(self):
        try:
            dispose_tk_test(self)
        finally:
            self.serial_patch.stop()

    def event(self, page, kind, **values):
        page._handle_online_event(dict(type=kind, **values))

    def connect(self, page):
        page.connect_business()
        port = 'COM_A' if page.role == 'sender' else 'COM_B'
        self.event(page, 'identity', identity=dict(port=port, model='fake local SDR', usb_serial='verified-fake'))

    def ready(self, page):
        self.connect(page)
        self.event(page, 'status', state='ready', message='connected, await configure')
        self.assertFalse(page.business_configured)
        values = dict(configured=True)
        if page.role == 'receiver':
            center=float(page.expected_rf.get())
            values.update(rx_lo_hz_readback=int((center+.25)*1e6), expected_rf_mhz=center)
        else:
            values.update(tx_lo_hz_readback=int((float(page.tx_rf.get())-.5)*1e6),tx_atten_db_readback=89)
        self.event(page, 'settings', values=values)
        self.event(page, 'status', state='ready', message='configured local profile')
        self.assertTrue(page.business_configured)

    def text(self, value):
        self.sender.message_input.delete('1.0', 'end')
        self.sender.message_input.insert('1.0', value)
        self.sender.message_input.edit_modified(True)
        self.sender._text_changed()

    def tx(self, text='actual business text', message_id='fixture:0001'):
        self.event(self.sender, 'status', state='transmitting', message='bounded local transmitter')
        self.event(self.sender, 'tx', text=text, message_id=message_id, payload_bytes=len(text.encode('utf-8')))

    def rx(self, page=None, **changes):
        event = dict(messages=[dict(text='RF received only', message_id='remote:0001', crc_valid=True, duplicate=False)],
            valid_frames=1, crc_rejected=2, rms_codes=13.5, carrier_hz=1000500123,
            spectrum=dict(freq_mhz=[1000.25,1000.5,1000.75], dbfs=[-60,-20,-61]),
            capture_seconds=12.5, received_at=1793000000, capture_file='FAKE_ACTUAL_IQ.bin')
        event.update(changes)
        self.event(page or self.receiver, 'rx', **event)

    def test_startup_is_passive_and_only_local_board_choices_are_present(self):
        for page in (self.sender, self.receiver, self.control):
            self.assertEqual(page.controller.calls, [])
            self.assertFalse(page.local_claimed)
        self.assertFalse(self.sender.connect_button.instate(['disabled']))
        self.assertFalse(self.receiver.connect_button.instate(['disabled']))
        self.assertFalse(self.control.connect_button.instate(['disabled']))
        self.assertFalse(hasattr(self.sender, 'relay_port_combo'))
        self.assertTrue(self.sender.send_button.instate(['disabled']))
        self.assertTrue(self.receiver.receive_button.instate(['disabled']))

    def test_default_review_does_not_construct_business_controller(self):
        container=tk.Toplevel(self.root)
        offline=ReviewSession(container,port_provider=lambda:PORTS,aliases=ALIASES,
            business_controller_factory=lambda *_a,**_k:self.fail('review constructed a live business worker'))
        for role in ('sender','receiver'):
            page=offline.show(role)
            self.assertFalse(page.business_online)
            self.assertIsNone(page.controller)
        for role in tuple(offline.windows):
            offline.close(role)

    def test_identity_auto_configures_once_and_first_ready_cannot_enable_send(self):
        self.text('hello')
        self.connect(self.sender)
        self.assertEqual(self.sender.controller.calls, [('connect', dict(port='COM_A')),
                                                      ('configure', dict(tx_atten_db=50,tx_rf_mhz=900.5))])
        self.event(self.sender, 'status', state='ready', message='connection ready')
        self.assertTrue(self.sender.send_button.instate(['disabled']))
        self.event(self.sender, 'settings', values=dict(configured=True, tx_atten_db_requested=50))
        self.assertTrue(self.sender.send_button.instate(['disabled']))
        self.event(self.sender, 'settings', values=dict(configured=True,tx_lo_hz_readback=900000000,tx_atten_db_readback=89))
        self.event(self.sender, 'status', state='ready', message='software profile configured')
        self.assertFalse(self.sender.send_button.instate(['disabled']))
        self.assertEqual(self.sender.sender_frequency.get(), '900.500')
        self.assertIn('本地回读', self.sender.sender_frequency_note.get())
        self.assertIn('900.000000',self.sender.sender_readback.get())
        self.assertEqual(sum(action=='configure' for action,_ in self.sender.controller.calls), 1)

    def test_startup_status_and_wrong_or_late_identity_never_rebind(self):
        self.sender.connect_business()
        self.event(self.sender, 'status', state='disconnected', message='startup event')
        self.assertTrue(self.sender.accept_connected)
        self.event(self.sender, 'identity', identity=dict(port='COM_B', model='wrong'))
        self.assertIsNone(self.sender.online_identity)
        self.assertEqual(self.sender.controller.calls[-1], ('disconnect', {}))
        self.event(self.sender, 'status', state='disconnected', message='released')
        self.event(self.sender, 'identity', identity=dict(port='COM_A', model='late'))
        self.assertIsNone(self.sender.online_identity)
        self.assertFalse(any(action=='configure' for action,_ in self.sender.controller.calls))

    def test_real_sender_readback_changes_frequency_without_claiming_remote_delivery(self):
        self.ready(self.sender)
        self.sender.tx_rf.set('901.5')
        self.sender.configure_business()
        self.event(self.sender, 'settings', values=dict(configured=True,tx_lo_hz_readback=901000000,tx_atten_db_readback=50))
        self.event(self.sender,'status',state='ready',message='frequency applied while muted')
        self.assertEqual(self.sender.sender_frequency.get(), '901.500')
        self.assertIn('本地回读', self.sender.sender_frequency_note.get())
        self.assertIn('901.000000', self.sender.sender_readback.get())
        self.assertEqual(self.receiver.received_text.get(), '等待接收文本')
        self.assertEqual(self.receiver.history.get_children(), ())

    def test_sender_has_explicit_bounded_send_restart_and_utf8_gate(self):
        self.ready(self.sender)
        for invalid in ('', '国'*11):
            self.text(invalid)
            self.sender.send_business()
        self.assertFalse(any(action=='send' for action,_ in self.sender.controller.calls))
        self.text('actual business text')
        self.sender.send_business()
        self.sender.send_business()
        self.assertEqual(sum(action=='send' for action,_ in self.sender.controller.calls), 1)
        self.assertEqual(self.sender.history.get_children(), ())
        self.tx()
        row = self.sender.history.item(self.sender.history.get_children()[0], 'values')
        self.assertEqual(row[1:3], ('fixture:0001','actual business text'))
        self.assertIn('限时', row[3])
        self.assertEqual(self.receiver.received_text.get(), '等待接收文本')
        self.text('new message')
        self.sender.send_business()
        self.assertEqual(self.sender.controller.calls[-1], ('send',dict(text='new message')))
        self.tx('new message','fixture:0002')
        self.event(self.sender,'status',state='stopped',message='30 seconds reached, TX muted')
        self.assertFalse(self.sender.send_button.instate(['disabled']))
        self.assertIn('静音',self.sender.history.item(self.sender.business_tx_row,'values')[-1])

    def test_receiver_requires_its_own_valid_iq_messages_and_displays_measurements(self):
        self.ready(self.receiver)
        self.receiver.receive_business()
        self.event(self.receiver,'status',state='receiving',message='real IQ polling')
        self.rx(messages=[dict(text='invalid expected text',message_id='bad',crc_valid=False)])
        self.assertEqual(self.receiver.received_text.get(),'等待本次接收文本')
        self.assertEqual(self.receiver.carrier_frequency.get(),'—')
        self.rx()
        self.assertEqual(self.receiver.received_text.get(),'RF received only')
        self.assertEqual(self.receiver.carrier_frequency.get(),'1000.500123')
        self.assertIn('remote:0001',self.receiver.received_meta.get())
        self.assertIn('CRC 有效',self.receiver.received_meta.get())
        self.assertIn('CRC 失败 2',self.receiver.frame_stats.get())
        self.assertIn('RMS 13.5',self.receiver.frame_stats.get())
        self.assertEqual(len(self.receiver.spectrum.points),3)
        self.assertIn('FAKE_ACTUAL_IQ.bin',self.receiver.device_detail.get())
        self.rx(messages=[dict(text='RF received only',message_id='remote:0001',crc_valid=True,duplicate=True)])
        self.assertIn('重复',self.receiver.history.item(self.receiver.history.get_children()[0],'values')[-1])

    def test_receiver_prior_and_attenuation_are_local_configure_only(self):
        self.ready(self.receiver)
        self.assertIn('已就绪',self.receiver.received_meta.get())
        self.assertIn('待开始',self.receiver.capture_note.get())
        self.assertFalse(any(action=='receive' for action,_ in self.receiver.controller.calls))
        self.receiver.expected_rf.set('1001.5')
        self.assertTrue(self.receiver.business_plan_dirty)
        self.assertTrue(self.receiver.receive_button.instate(['disabled']))
        self.assertEqual(self.receiver.controller.calls[-1],('configure',dict(expected_rf_mhz=1000.5)))
        self.receiver.business_apply_button.invoke()
        self.assertEqual(self.receiver.controller.calls[-1],('configure',dict(expected_rf_mhz=1001.5)))
        self.event(self.receiver,'settings',values=dict(configured=True,rx_lo_hz_readback=1001750000,expected_rf_mhz=1001.5))
        self.event(self.receiver,'status',state='ready',message='local prior updated')
        self.assertIn('1001.750',self.receiver.receiver_plan_note.get())
        self.assertIn('远端状态未知',self.receiver.receiver_plan_note.get())
        self.ready(self.sender)
        self.sender.attenuation.set('55')
        self.assertEqual(self.sender.controller.calls[-1],('configure',dict(tx_atten_db=50,tx_rf_mhz=900.5)))
        self.sender.business_apply_button.invoke()
        self.assertEqual(self.sender.controller.calls[-1],('configure',dict(tx_atten_db=55,tx_rf_mhz=900.5)))
        self.assertEqual(self.control.controller.calls,[])

    def test_busy_edit_only_changes_pending_plan_until_stop_and_explicit_apply(self):
        self.ready(self.sender)
        self.text('actual business text');self.sender.send_business();self.tx()
        before=list(self.sender.controller.calls)
        self.sender.tx_rf.set('901.5')
        self.assertEqual(self.sender.controller.calls,before)
        self.assertTrue(self.sender.business_plan_dirty)
        self.assertEqual(self.sender.sender_frequency.get(),'900.500')
        self.assertTrue(self.sender.business_apply_button.instate(['disabled']))
        self.assertTrue(self.sender.send_button.instate(['disabled']))
        self.sender.configure_business()
        self.assertEqual(self.sender.controller.calls,before)
        self.sender.stop_business();self.event(self.sender,'status',state='stopped',message='quiet')
        self.assertFalse(self.sender.business_apply_button.instate(['disabled']))
        self.sender.business_apply_button.invoke()
        self.assertEqual(self.sender.controller.calls[-1],('configure',dict(tx_rf_mhz=901.5,tx_atten_db=50)))
        self.event(self.sender,'settings',values=dict(configured=True,tx_lo_hz_readback=901000000,tx_atten_db_readback=89))
        self.event(self.sender,'status',state='ready',message='applied, muted')
        self.assertFalse(self.sender.business_plan_dirty)
        self.assertEqual(sum(action=='send' for action,_ in self.sender.controller.calls),1)

    def test_edit_during_configure_does_not_claim_new_plan_was_applied(self):
        self.ready(self.sender);self.text('next text')
        self.sender.tx_rf.set('901.5');self.sender.configure_business()
        self.sender.tx_rf.set('900.5')
        self.event(self.sender,'settings',values=dict(configured=True,tx_lo_hz_readback=901000000,tx_atten_db_readback=89))
        self.event(self.sender,'status',state='ready',message='earlier requested profile applied')
        self.assertEqual(self.sender.business_applied_plan['tx_rf_mhz'],901.5)
        self.assertEqual(self.sender.tx_rf.get(),'900.5')
        self.assertEqual(self.sender.sender_frequency.get(),'901.500')
        self.assertTrue(self.sender.business_plan_dirty)
        self.assertTrue(self.sender.send_button.instate(['disabled']))
        self.assertFalse(self.sender.business_apply_button.instate(['disabled']))
        self.assertEqual(sum(action=='configure' for action,_ in self.sender.controller.calls),2)

    def test_receiver_edit_while_receiving_keeps_old_local_iq_profile(self):
        self.ready(self.receiver);self.receiver.receive_business()
        self.event(self.receiver,'status',state='receiving',message='current IQ snapshots')
        before=list(self.receiver.controller.calls)
        self.receiver.expected_rf.set('1001.5')
        self.receiver.configure_business()
        self.assertEqual(self.receiver.controller.calls,before)
        self.assertTrue(self.receiver.business_accept_rx)
        self.assertTrue(self.receiver.business_apply_button.instate(['disabled']))
        self.rx()
        self.assertEqual(self.receiver.carrier_frequency.get(),'1000.500123')
        self.assertIn('1000.750',self.receiver.receiver_plan_note.get())
        self.receiver.stop_business();self.event(self.receiver,'status',state='stopped',message='capture stopped')
        self.receiver.business_apply_button.invoke()
        self.assertEqual(self.receiver.controller.calls[-1],('configure',dict(expected_rf_mhz=1001.5)))
        self.assertEqual(sum(action=='receive' for action,_ in self.receiver.controller.calls),1)

    def control_request(self):
        self.control.connect_online()
        self.event(self.control,'connected',source=dict(port='COM_A',model='fake',usb_serial='fake'))
        self.control.input_frequency.set('901.5')
        self.control.generate_command();self.control.send_online()
        return dict(self.control.active_request)

    def control_result(self,request,**changes):
        event=dict(passed=True,requested=request,ack=dict(rx_hz=901000000,tx_hz=1001000000),
                   frame_count=2,iq_path='FAKE_RF_IQ.bin',report_path='FAKE_RF_REPORT.json')
        event.update(changes)
        self.event(self.control,'result',**event)

    def test_only_current_real_control_success_proposes_sender_plan_without_commands(self):
        request=self.control_request()
        self.assertEqual(self.sender.tx_rf.get(),'900.5')
        self.control_result(dict(request,air_seq=255))
        self.assertEqual(self.sender.tx_rf.get(),'900.5')
        self.control_result(request)
        self.assertEqual(self.control.reply_title.get(),'改频成功')
        self.assertIn('转发模式/电平未由本回报报告',self.control.reply_body.get())
        self.assertEqual(self.sender.tx_rf.get(),'901.5')
        self.assertTrue(self.sender.business_plan_dirty)
        self.assertIn('真实 RF 回报',self.sender.plan_status.get())
        self.assertEqual(self.sender.controller.calls,[])
        self.assertEqual(self.receiver.expected_rf.get(),'1000.5')
        self.assertEqual(self.receiver.controller.calls,[])

    def test_control_plan_is_retained_for_sender_opened_after_rf_success(self):
        self.session.close('sender');self.event(self.sender,'closed')
        request=self.control_request();self.control_result(request)
        sender=self.session.show('sender')
        self.assertEqual(sender.tx_rf.get(),'901.5')
        self.assertTrue(sender.business_plan_dirty)
        self.assertEqual(sender.controller.calls,[])

    def test_drafts_simulation_and_history_cannot_change_sender_plan(self):
        container=tk.Toplevel(self.root)
        offline=ReviewSession(container,port_provider=lambda:PORTS,aliases=ALIASES)
        control=offline.show('control');sender=offline.show('sender')
        control.input_frequency.set('901.5');control.generate_command()
        control.preview_report()
        self.assertEqual(sender.tx_rf.get(),'900.5')
        with tempfile.TemporaryDirectory() as directory:
            self.assertTrue(control.load_record(history_fixture(directory)))
        self.assertEqual(sender.tx_rf.get(),'900.5')
        self.assertEqual(offline.sender_center_plan,'900.5')
        for role in tuple(offline.windows):offline.close(role)

    def test_receiver_reconnect_ready_replaces_released_summary_and_rms_is_compact(self):
        self.event(self.receiver,'status',state='disconnected',message='本地已释放')
        self.assertEqual(self.receiver.capture_note.get(),'已断开')
        self.ready(self.receiver)
        self.assertIn('等待开始接收',self.receiver.received_meta.get())
        self.assertNotIn('已释放',self.receiver.received_meta.get())
        self.assertNotIn('已断开',self.receiver.capture_note.get())
        self.receiver.receive_business()
        self.rx(rms_codes=3.465519681234567)
        self.assertIn('RMS 3.47',self.receiver.frame_stats.get())
        self.assertNotIn('3.465519',self.receiver.frame_stats.get())

    def test_stop_and_disconnect_ignore_late_receive_and_release_only_on_ack(self):
        self.ready(self.receiver)
        self.receiver.receive_business()
        self.receiver.stop_business()
        before = self.receiver.received_text.get()
        self.rx()
        self.assertEqual(self.receiver.received_text.get(),before)
        self.assertEqual(self.receiver.history.get_children(),())
        self.assertTrue(self.receiver.local_claimed)
        self.event(self.receiver,'status',state='stopped',message='stopped, configuration kept')
        self.assertTrue(self.receiver.business_configured)
        self.assertTrue(self.receiver.local_claimed)
        self.assertFalse(self.receiver.receive_button.instate(['disabled']))
        self.receiver.connect_business()
        self.assertEqual(self.receiver.controller.calls[-1],('disconnect',{}))
        self.event(self.receiver,'status',state='stopped',message='intermediate stop')
        self.assertTrue(self.receiver.cancel_pending)
        self.assertTrue(self.receiver.local_claimed)
        self.event(self.receiver,'status',state='disconnected',message='released')
        self.rx()
        self.assertFalse(self.receiver.local_claimed)
        self.assertEqual(self.receiver.history.get_children(),())

    def test_cancelled_error_keeps_ownership_until_final_stop_ack(self):
        self.ready(self.sender)
        self.text('actual business text')
        self.sender.send_business()
        self.sender.stop_business()
        self.event(self.sender,'status',state='error',category='cancelled',message='本地操作已取消')
        self.assertTrue(self.sender.local_claimed)
        self.assertTrue(self.sender.connect_button.instate(['disabled']))
        self.assertTrue(self.control.connect_button.instate(['disabled']))
        self.tx('actual business text','cancelled:0001')
        self.assertEqual(self.sender.history.get_children(),())
        self.event(self.sender,'status',state='disconnected',message='urgent stop completed after cancellation cleanup')
        self.assertFalse(self.sender.local_claimed)
        self.assertFalse(self.sender.connect_button.instate(['disabled']))

    def test_explicit_stop_accepts_actual_mute_readback_but_never_late_tx(self):
        self.ready(self.sender)
        self.text('actual business text')
        self.sender.send_business()
        self.tx()
        self.sender.stop_business()
        self.event(self.sender,'settings',values=dict(configured=True,tx_lo_hz_readback=900000000,tx_atten_db_readback=89))
        self.assertIn('89',self.sender.sender_readback.get())
        self.tx('actual business text','late:0002')
        self.assertEqual(len(self.sender.history.get_children()),1)

    def test_pc1_connection_is_exclusive_until_explicit_disconnect(self):
        self.ready(self.sender)
        self.assertTrue(self.control.connect_button.instate(['disabled']))
        self.assertIn('先在该窗口断开',self.control.request_note.get())
        self.control.connect_online()
        self.assertEqual(self.control.controller.calls,[])
        self.sender.stop_business()
        self.assertTrue(self.control.connect_button.instate(['disabled']))
        self.event(self.sender,'status',state='stopped',message='TX stopped')
        self.assertTrue(self.control.connect_button.instate(['disabled']))
        self.sender.stop_business('disconnect')
        self.assertTrue(self.control.connect_button.instate(['disabled']))
        self.event(self.sender,'status',state='disconnected',message='released source')
        self.assertFalse(self.control.connect_button.instate(['disabled']))
        self.control.connect_online()
        self.assertTrue(self.sender.connect_button.instate(['disabled']))
        self.assertTrue(self.sender.port_combo.instate(['disabled']))
        self.sender.connect_business()
        self.assertEqual(self.sender.controller.calls[-1],('disconnect',{}))
        self.control.cancel_online('disconnect')
        self.assertTrue(self.sender.connect_button.instate(['disabled']))
        self.event(self.control,'status',state='disconnected',message='control released')
        self.assertFalse(self.sender.connect_button.instate(['disabled']))

    def test_error_cleanup_can_reconnect_without_accepting_old_tx_or_rx(self):
        self.ready(self.sender)
        self.text('actual business text')
        self.sender.send_business()
        self.event(self.sender,'status',state='error',message='source released after failure')
        self.tx()
        self.assertEqual(self.sender.history.get_children(),())
        self.assertFalse(self.sender.local_claimed)
        self.assertFalse(self.sender.connect_button.instate(['disabled']))
        self.ready(self.sender)
        self.assertTrue(self.sender.business_configured)
        self.assertFalse(self.sender.business_accept_tx)

    def test_worker_callbacks_are_queued_and_close_keeps_pc1_ownership(self):
        self.ready(self.sender)
        self.text('actual business text')
        self.sender.send_business()
        worker=threading.Thread(target=lambda:self.sender.controller.emit(dict(type='tx',text='actual business text',message_id='worker:0001',payload_bytes=20)))
        worker.start();worker.join()
        self.assertEqual(self.sender.history.get_children(),())
        self.sender._drain_online_events()
        self.assertEqual(len(self.sender.history.get_children()),1)
        self.session.close('sender')
        self.assertIn('sender',self.session.windows)
        self.assertTrue(self.control.connect_button.instate(['disabled']))
        self.tx('actual business text','late:0001')
        self.assertEqual(len(self.sender.history.get_children()),1)
        self.event(self.sender,'closed')
        self.assertNotIn('sender',self.session.windows)
        self.assertFalse(self.control.connect_button.instate(['disabled']))

    def test_business_minimum_layout_and_details_preserve_actions_and_history(self):
        for page in (self.sender,self.receiver):
            page.window.geometry('1040x800')
            self.root.update()
            bottom=page.window.winfo_rooty()+page.window.winfo_height()
            action=page.send_button if page.role=='sender' else page.receive_button
            for widget in (action,page.business_stop_button,page.history):
                self.assertTrue(widget.winfo_ismapped())
                self.assertLess(widget.winfo_rooty()+widget.winfo_height(),bottom)
            self.assertGreaterEqual(action.winfo_height(),action.winfo_reqheight())
            page.toggle_details();self.root.update()
            self.assertTrue(action.winfo_ismapped())
            self.assertGreaterEqual(action.winfo_height(),action.winfo_reqheight())
            page.toggle_details()

    def test_real_receiver_snapshot_still_has_visible_spectrum_at_minimum_size(self):
        self.ready(self.receiver)
        self.receiver.receive_business()
        self.event(self.receiver,'status',state='receiving',message='采集本地真实 IQ')
        self.rx()
        self.receiver.window.geometry('1040x800')
        self.root.update()
        self.assertGreaterEqual(self.receiver.spectrum.winfo_height(),80)

    def test_cli_business_is_explicit_and_can_be_combined_with_control(self):
        for argv,business,control in ((['--all'],False,False),(['--all','--online-business'],True,False),
                                     (['--all','--online-business','--online-control'],True,True)):
            with patch('sw.ground_station.ui_v2.tk.Tk'),patch('sw.ground_station.ui_v2.ReviewSession') as factory:
                main(argv)
                self.assertIs(factory.call_args.kwargs['online_business'],business)
                self.assertIs(factory.call_args.kwargs['online_control'],control)


if __name__=='__main__':
    unittest.main()
