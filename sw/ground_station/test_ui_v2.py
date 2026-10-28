"""Review UI: no radio actions, no invented receive results, explicit history."""
import json
import gc
from pathlib import Path
import tempfile
import threading
import tkinter as tk
import unittest
import weakref
from unittest.mock import patch

from .test_tc_evidence import evidence
from ._tk_test_support import dispose_tk_test
from .ui_v2 import ReviewSession, main
from .ui_v2_model import (command_request, device_choices, frequency_plan,
                         format_mhz, load_historical_transaction, text_bytes, business_frequency_plan)


PORTS = [dict(port='COM_A', description='USB A', vid=1027, pid=24592, serial='sender-unique'),
         dict(port='COM_B', description='USB B', vid=1027, pid=24592, serial='receiver-unique')]
ALIASES = [dict(PORTS[0], role='sender'), dict(PORTS[1], role='receiver')]


def history_fixture(directory):
    request, before, frozen, spi, report, sequence = evidence()
    directory = Path(directory)
    (directory/'downlink').mkdir()
    (directory/'downlink'/'rf_000001.json').write_text(json.dumps(report), encoding='utf-8')
    result = dict(requested=request, control=dict(before=before, frozen=frozen, spi=spi),
                  dac_sequence=sequence, final_spi=spi, probe_only=False, cleanup_errors=[],
                  rf_report='D:/old_machine/downlink/rf_000001.json', assessment={'passed': False})
    path = directory/'result.json'
    path.write_text(json.dumps(result), encoding='utf-8')
    return path


class ReviewDataTests(unittest.TestCase):
    def test_authorized_business_profiles_keep_exact_centers_and_original_if(self):
        for role,center,lo,offset in (('sender','900.5',900000000,500000),('sender','901.5',901000000,500000),
                                     ('receiver','1000.5',1000750000,-250000),('receiver','1001.5',1001750000,-250000)):
            self.assertEqual(business_frequency_plan(role,center),dict(center_hz=lo+offset,lo_hz=lo,offset_hz=offset))
        for role,center in (('sender','902.5'),('sender','900.500001'),('receiver','1001.75'),
                            ('receiver','NaN'),('control','900.5'),('sender',True)):
            with self.subTest(role=role,center=center),self.assertRaises(ValueError):
                business_frequency_plan(role,center)
    def test_rf_center_is_converted_to_lo_without_label_substitution(self):
        self.assertEqual(command_request('900.5', '1001.5', 240),
                         dict(rx_mhz=900, tx_mhz=1001, air_seq=240))
        for value in ('NaN', 'sNaN', 'Infinity', '900', '900.6', 'text'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                command_request(value, '1001.5', 0)
        for sequence in (True, -1, 256, 1.0):
            with self.assertRaises(ValueError):
                command_request('900.5', '1001.5', sequence)

    def test_free_entry_preserves_hz_and_legacy_encoding_does_not_round(self):
        self.assertEqual(frequency_plan('1234.567891', '2450'),
                         dict(input_hz=1234567891, output_hz=2450000000))
        self.assertEqual(command_request('70.5', '6000.5', 1),
                         dict(rx_mhz=70, tx_mhz=6000, air_seq=1))
        self.assertEqual(command_request('1234.5', '2450.5', 2)['rx_mhz'], 1234)
        for value in ('70.499999', '6000.500001', '1e999', '900.5000001',
                      '900.5000000000000000000000000001', ''):
            with self.subTest(value=value), self.assertRaises(ValueError):
                frequency_plan(value, '1001.5')
        for hz in (70_500_000, 1_234_567_891, 1_000_000_000, 6_000_500_000):
            self.assertEqual(frequency_plan(format_mhz(hz), '1001.5')['input_hz'], hz)
        with self.assertRaises(ValueError):
            command_request('1234.567891', '2450', 2)

    def test_device_labels_filter_management_and_reject_ambiguous_identity(self):
        ports = PORTS + [dict(port='BT', vid=None),
                         dict(port='MGMT', vid=1027, pid=1, serial='management'),
                         dict(port='UNKNOWN', vid=7, pid=8, serial=None)]
        aliases = ALIASES + [dict(ports[3], role='management')]
        choices = device_choices(ports, aliases)
        self.assertEqual(len(choices), 3)
        self.assertIn('发送板（上次识别） · COM_A', choices)
        self.assertIn('未识别 USB 串口 · UNKNOWN', choices)
        duplicate = dict(PORTS[0], port='DUPLICATE')
        choices = device_choices(PORTS+[duplicate], ALIASES)
        self.assertNotIn('发送板（上次识别） · COM_A', choices)
        self.assertEqual(choices['未识别 USB 串口 · COM_A']['role'], None)

    def test_text_limit_is_utf8_bytes(self):
        self.assertEqual(text_bytes('你好'), 6)
        self.assertEqual(text_bytes('a'*32), 32)
        for text in ('', 'a'*33, '国'*11):
            with self.assertRaises(ValueError):
                text_bytes(text)

    def test_relocated_history_revalidates_bytes_and_ignores_summary(self):
        with tempfile.TemporaryDirectory() as directory:
            path = history_fixture(directory)
            self.assertTrue(load_historical_transaction(path)['assessment']['passed'])
            report_path = Path(directory)/'downlink'/'rf_000001.json'
            report = json.loads(report_path.read_text())
            report['frames'][0]['crc16'] ^= 1
            report_path.write_text(json.dumps(report), encoding='utf-8')
            with self.assertRaises(ValueError):
                load_historical_transaction(path)
            for content in ('[]', 'null'):
                path.write_text(content, encoding='utf-8')
                with self.assertRaises(ValueError):
                    load_historical_transaction(path)


class ReviewWindowTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.tk.call('tk', 'scaling', 1.33)
        self.serial_patch = patch('serial.Serial', side_effect=AssertionError('UI review opened hardware'))
        self.serial_patch.start()
        self.session = ReviewSession(self.root, port_provider=lambda: PORTS, aliases=ALIASES)

    def tearDown(self):
        try:
            dispose_tk_test(self)
        finally:
            self.serial_patch.stop()

    def test_three_windows_share_only_pc1_selection_and_never_receive_a_draft(self):
        sender, receiver, control = [self.session.show(role) for role in ('sender', 'receiver', 'control')]
        sender.selection.set('发送板（上次识别） · COM_A')
        self.assertEqual(control.selection.get(), sender.selection.get())
        self.assertEqual(receiver.selection.get(), '接收板（上次识别） · COM_B')
        sender.message_input.insert('1.0', '实际内容')
        self.root.update()
        self.assertEqual(sender.byte_count.get(), '12 / 32 字节')
        control.generate_command()
        self.assertIsNotNone(control.draft)
        self.assertEqual(receiver.received_text.get(), '等待接收文本')
        self.assertEqual(receiver.history.get_children(), ())
        self.assertEqual(sender.history.get_children(), ())
        for widget in (sender.send_button, receiver.receive_button, control.command_send_button,
                       sender.connect_button, receiver.connect_button, control.connect_button):
            self.assertTrue(widget.instate(['disabled']))

    def test_parameter_change_invalidates_prepared_request(self):
        control = self.session.show('control')
        control.generate_command()
        self.assertEqual(control.draft['request']['tx_mhz'], 1001)
        control.output_frequency.set('1000.5')
        self.assertIsNone(control.draft)
        self.assertIn('重新生成', control.request_note.get())

    def test_sequences_are_internal_and_fractional_plans_are_not_encoded(self):
        control = self.session.show('control')
        control.input_frequency.set('1234.5')
        control.generate_command()
        first = control.draft['request']['air_seq']
        control.generate_command()
        self.assertEqual(control.draft['request']['air_seq'], (first+1) % 256)
        self.assertFalse(hasattr(control, 'sequence'))
        control.input_frequency.set('1234.567891')
        control.generate_command()
        self.assertIsNone(control.draft['request'])
        self.assertIsNone(control.draft['body_hex'])
        self.assertEqual(control.draft['plan']['input_hz'], 1234567891)
        self.assertIn('不能编码', control.request_note.get())

    def test_refresh_preserves_identity_but_never_rebinds_a_replaced_port(self):
        original = self.session.source_selection.get()
        self.session.refresh_devices()
        self.assertEqual(self.session.source_selection.get(), original)
        self.session.port_provider = lambda: [dict(PORTS[0], serial='replacement'), PORTS[1]]
        self.session.refresh_devices()
        self.assertEqual(self.session.source_selection.get(), '')

    def test_simulation_is_labelled_isolated_and_cleared_by_edit_or_bad_history(self):
        control = self.session.show('control')
        receiver = self.session.show('receiver')
        for scenario in ('成功', '失败', '超时'):
            control.preview_outcome.set(scenario)
            control.preview_report()
            self.assertEqual(control.simulation['source'], 'simulation')
            self.assertIn('模拟', control.reply_title.get())
            self.assertIn(scenario, control.reply_title.get())
            self.assertTrue(all('模拟' in item.cget('text') for item in control.step_labels))
            self.assertIsNone(control.historical)
            self.assertEqual(receiver.history.get_children(), ())
            self.assertEqual(receiver.received_text.get(), '等待接收文本')
        control.output_frequency.set('1234.567891')
        self.assertIsNone(control.simulation)
        self.assertEqual(control.reply_body.get(), '')
        control.preview_report()
        self.assertIsNone(control.draft['body_hex'])
        with tempfile.TemporaryDirectory() as directory:
            path = history_fixture(directory)
            self.assertTrue(control.load_record(path))
            self.assertIsNone(control.simulation)
            self.assertIn('历史', control.reply_title.get())
            control.preview_report()
            self.assertIsNone(control.historical)
            path.write_text('{}', encoding='utf-8')
            self.assertFalse(control.load_record(path))
            self.assertIsNone(control.simulation)

    def test_history_is_not_current_success_and_bad_import_clears_it(self):
        control = self.session.show('control')
        control.generate_command()
        with tempfile.TemporaryDirectory() as directory:
            path = history_fixture(directory)
            self.assertTrue(control.load_record(path))
            self.assertIn('历史', control.reply_title.get())
            self.assertIn('未发送', control.step_labels[0].cget('text'))
            self.assertEqual(control.step_labels[3].cget('fg'), '#728195')
            path.write_text('{}', encoding='utf-8')
            self.assertFalse(control.load_record(path))
            self.assertIsNone(control.historical)
            self.assertIn('未通过', control.reply_title.get())

    def test_key_workspaces_visible_at_minimum_size(self):
        for role in ('sender', 'receiver', 'control'):
            with self.subTest(role=role):
                page = self.session.show(role)
                page.window.geometry('1040x800')
                self.root.update()
                bottom = page.window.winfo_rooty()+page.window.winfo_height()
                tree_bottom = page.history.winfo_rooty()+page.history.winfo_height()
                self.assertLess(tree_bottom, bottom)
                self.assertGreater(page.history.winfo_height(), 80)
                page.toggle_details()
                self.root.update()
                self.assertFalse(page.history.winfo_ismapped())
                action = getattr(page, 'generate_button', getattr(page, 'send_button',
                         getattr(page, 'receive_button', None)))
                self.assertTrue(action.winfo_ismapped())
                self.assertLess(action.winfo_rooty()+action.winfo_height(), bottom)
                page.toggle_details()
                self.root.update()
                self.assertTrue(page.history.winfo_ismapped())


class FakeTelecontrolController:
    def __init__(self, emit, log_dir=None):
        self.emit, self.calls = emit, []

    def submit(self, action, **kwargs):
        self.calls.append((action, kwargs))
        if action == getattr(self, 'fail_action', None):
            raise RuntimeError('fake uncertain submission')


class OnlineControlTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.tk.call('tk', 'scaling', 1.33)
        self.serial_patch = patch('serial.Serial', side_effect=AssertionError('UI test opened hardware'))
        self.serial_patch.start()
        self.session = ReviewSession(self.root, port_provider=lambda: PORTS, aliases=ALIASES,
                                     online_control=True, controller_factory=FakeTelecontrolController)
        self.control = self.session.show('control')
        self.controller = self.control.controller

    def tearDown(self):
        try:
            dispose_tk_test(self)
        finally:
            self.serial_patch.stop()

    def connected(self, next_sequence=None):
        self.control.connect_online()
        self.control._handle_online_event(dict(type='status', state='connecting', message='核验本地设备'))
        event = dict(type='connected', source=dict(port='COM_A', model='fake SDR', usb_serial='actual-fake'))
        if next_sequence is not None:
            event['next_sequence'] = next_sequence
        self.control._handle_online_event(event)
        self.control._handle_online_event(dict(type='status', state='connected', message='本地连接完成'))

    def sent(self):
        self.connected()
        self.control.generate_command()
        self.control.send_online()
        return dict(self.control.active_request)

    def result(self, request, **changes):
        event = dict(type='result', passed=True, requested=request,
                     ack=dict(rx_hz=request['rx_mhz']*1_000_000, tx_hz=request['tx_mhz']*1_000_000),
                     frame_count=3, report_path='FAKE_REPORT.json', iq_path='FAKE_CAPTURE.iq')
        event.update(changes)
        self.control._handle_online_event(event)

    def test_online_startup_and_draft_never_connect_or_transmit_automatically(self):
        self.assertEqual(self.controller.calls, [])
        self.assertIsNone(self.control.online_identity)
        self.assertIn('上次识别', self.control.selection.get())
        self.assertIn('待在线核验', self.control.device_detail.get())
        self.control.generate_command()
        self.assertEqual(self.controller.calls, [])
        self.assertTrue(self.control.command_send_button.instate(['disabled']))
        self.assertFalse(self.control.connect_button.instate(['disabled']))
        sender, receiver = self.session.show('sender'), self.session.show('receiver')
        self.assertTrue(sender.send_button.instate(['disabled']))
        self.assertTrue(sender.connect_button.instate(['disabled']))
        self.assertTrue(receiver.receive_button.instate(['disabled']))

    def test_true_connected_identity_is_required_and_only_control_is_enabled(self):
        self.control.connect_button.invoke()
        self.assertEqual(self.controller.calls, [('connect', dict(source_port='COM_A'))])
        self.control.generate_command()
        self.control._handle_online_event(dict(type='status', state='connected', message='status alone'))
        self.assertTrue(self.control.command_send_button.instate(['disabled']))
        self.control._handle_online_event(dict(type='connected', source=dict(port='COM_A', model='real identity', usb_serial='verified')))
        self.assertFalse(self.control.command_send_button.instate(['disabled']))
        self.assertIn('verified', self.control.device_detail.get())
        self.assertIn('远端就绪', self.control.device_detail.get())
        sender = self.session.show('sender')
        self.assertTrue(sender.send_button.instate(['disabled']))
        self.assertTrue(sender.port_combo.instate(['disabled']))
        self.assertEqual(len(self.controller.calls), 1)

    def test_queued_startup_disconnected_does_not_cancel_a_quick_connect_click(self):
        self.controller.emit(dict(type='status', state='disconnected', message='startup status'))
        self.control.connect_online()
        self.control._drain_online_events()
        self.assertTrue(self.control.accept_connected)
        self.control._handle_online_event(dict(type='connected', source=dict(port='COM_A', model='fake', usb_serial='fake')))
        self.assertIsNotNone(self.control.online_identity)

    def test_online_cannot_import_history_or_preview_simulation(self):
        for widget in (self.control.preview_button, self.control.preview_combo, self.control.record_button):
            self.assertTrue(widget.instate(['disabled']))
        self.control.preview_report()
        self.assertIsNone(self.control.simulation)
        self.assertIsNone(self.control.draft)
        self.assertFalse(self.control.load_record('not_opened.json'))
        self.assertIsNone(self.control.historical)
        self.assertEqual(self.control.reply_title.get(), '等待执行回报')

    def test_only_measured_integer_lo_plans_can_be_sent(self):
        self.connected()
        for rx in ('900.5', '901.5'):
            for tx in ('1000.5', '1001.5'):
                self.control.input_frequency.set(rx)
                self.control.output_frequency.set(tx)
                self.control.generate_command()
                self.assertIsNotNone(self.control.draft['body_hex'])
                self.assertFalse(self.control.command_send_button.instate(['disabled']))
        for rx in ('1234.5', '900.6', '900.567891'):
            self.control.input_frequency.set(rx)
            self.control.generate_command()
            self.assertIsNone(self.control.draft['body_hex'])
            self.assertTrue(self.control.command_send_button.instate(['disabled']))
            self.control.send_online()
        self.control.input_frequency.set('invalid')
        self.control.generate_command()
        self.assertIsNone(self.control.draft)
        self.assertTrue(self.control.command_send_button.instate(['disabled']))
        self.assertFalse(any(action == 'send' for action, _ in self.controller.calls))

    def test_send_is_explicit_once_with_frozen_request_and_true_result(self):
        request = self.sent()
        self.assertEqual(self.controller.calls[-1], ('send', dict(requested=request, wiring_confirmed=True)))
        self.assertEqual(self.session.next_sequence, 1)
        self.control.send_online()
        self.control.generate_command()
        self.assertEqual(sum(action == 'send' for action, _ in self.controller.calls), 1)
        self.assertNotIn('成功', self.control.reply_title.get())
        self.control._handle_online_event(dict(type='status', state='receiving', message='等待本次射频帧'))
        self.assertIn('等待射频回报', self.control.reply_title.get())
        self.result(dict(request, air_seq=100))
        self.assertNotIn('成功', self.control.reply_title.get())
        self.result(request)
        self.assertEqual(self.control.reply_title.get(), '改频成功')
        self.assertIn('转发模式/电平未由本回报报告',self.control.reply_body.get())
        self.assertIn('FAKE_CAPTURE.iq', self.control.reply_body.get())
        self.assertNotIn('独立', self.control.reply_body.get())
        self.assertIsNone(self.control.active_request)
        self.assertIsNone(self.control.historical)
        self.assertIsNone(self.control.simulation)

    def test_uncorrelated_or_bad_result_never_becomes_success(self):
        request = self.sent()
        self.result(dict(request, air_seq=1))
        self.assertIsNotNone(self.control.active_request)
        self.result(request, ack=dict(rx_hz=900_100_000, tx_hz=1_001_000_000))
        self.assertEqual(self.control.reply_title.get(), '执行失败')
        self.assertIsNone(self.control.active_request)
        self.assertIsNone(self.control.online_identity)
        self.result(request)
        self.assertNotIn('成功', self.control.reply_title.get())

    def test_timeout_failure_and_cancel_have_distinct_results(self):
        self.sent()
        for category, title in (('timeout', '等待超时'), ('validation', '执行失败'), ('cancelled', '操作已取消')):
            self.control._handle_online_event(dict(type='status', state='error', message='backend detail', category=category))
            self.assertIn(title, self.control.reply_title.get())
            self.assertIsNone(self.control.online_identity)
            self.assertTrue(self.control.command_send_button.instate(['disabled']))

    def test_stop_releases_source_and_late_events_cannot_restore_success_or_send(self):
        request = self.sent()
        self.control.stop_button.invoke()
        self.assertEqual(self.controller.calls[-1], ('stop', {}))
        self.assertTrue(self.control.cancel_pending)
        self.result(request)
        self.control._handle_online_event(dict(type='connected', source=dict(port='COM_A')))
        self.control._handle_online_event(dict(type='status', state='connected', message='late status'))
        self.assertIsNone(self.control.online_identity)
        self.assertNotIn('成功', self.control.reply_title.get())
        self.control._handle_online_event(dict(type='status', state='disconnected', message='stopped'))
        self.control._handle_online_event(dict(type='connected', source=dict(port='COM_A')))
        self.result(request)
        self.assertTrue(self.control.command_send_button.instate(['disabled']))
        self.assertFalse(self.control.connect_button.instate(['disabled']))
        self.assertIn('未知', self.control.reply_title.get())

    def test_connect_button_can_cancel_connect_and_disconnect_connected_source(self):
        self.control.connect_button.invoke()
        self.assertEqual(self.control.connect_button.cget('text'), '取消连接')
        self.control.connect_button.invoke()
        self.assertEqual(self.controller.calls[-1], ('disconnect', {}))
        self.control._handle_online_event(dict(type='status', state='disconnected', message='cancelled'))
        self.connected()
        self.assertEqual(self.control.connect_button.cget('text'), '断开连接')
        self.control.connect_button.invoke()
        self.assertEqual(self.controller.calls[-1], ('disconnect', {}))

    def test_selection_change_cancels_binding_and_wrong_identity_cannot_connect(self):
        self.control.connect_online()
        self.control._handle_online_event(dict(type='connected', source=dict(port='COM_B', model='wrong board')))
        self.assertIsNone(self.control.online_identity)
        self.assertEqual(self.controller.calls[-1], ('disconnect', {}))
        self.control._handle_online_event(dict(type='status', state='disconnected', message='released'))
        self.connected()
        self.session.source_selection.set('接收板（上次识别） · COM_B')
        self.assertIsNone(self.control.online_identity)
        self.assertEqual(self.controller.calls[-1], ('disconnect', {}))

    def test_sequences_are_consumed_on_submission_and_never_wrap_or_reset_on_reopen(self):
        self.connected()
        self.control.generate_command()
        self.control.generate_command()
        self.assertEqual(self.session.next_sequence, 0)
        self.session.next_sequence = 255
        self.control.generate_command()
        self.control.send_online()
        request = dict(self.control.active_request)
        self.assertEqual(request['air_seq'], 255)
        self.assertEqual(self.session.next_sequence, 256)
        self.result(request)
        self.control._handle_online_event(dict(type='status', state='connected', message='done'))
        self.control.generate_command()
        self.assertIsNone(self.control.draft)
        self.assertIn('已用完', self.control.request_note.get())
        self.assertTrue(self.control.command_send_button.instate(['disabled']))
        sender = self.session.show('sender')
        self.session.close('control')
        self.control._handle_online_event(dict(type='status', state='closed', message='closed'))
        self.control = self.session.show('control')
        self.control.generate_command()
        self.assertIn('已用完', self.control.request_note.get())
        self.assertEqual(self.session.next_sequence, 256)

    def test_error_does_not_reuse_uncertain_air_sequence(self):
        self.sent()
        self.control._handle_online_event(dict(type='status', state='error', category='hardware', message='lost reply'))
        self.connected()
        self.control.generate_command()
        self.assertEqual(self.control.draft['request']['air_seq'], 1)

    def test_controller_sequence_hint_invalidates_old_draft_and_never_rewinds_session(self):
        self.control.generate_command()
        self.assertEqual(self.control.draft['request']['air_seq'], 0)
        self.connected(next_sequence=17)
        self.assertEqual(self.session.next_sequence, 17)
        self.assertIsNone(self.control.draft)
        self.assertIn('重新生成', self.control.request_note.get())
        self.control.generate_command()
        self.assertEqual(self.control.draft['request']['air_seq'], 17)
        self.control.send_online()
        self.assertEqual(self.controller.calls[-1][1]['requested']['air_seq'], 17)
        self.control._handle_online_event(dict(type='status', state='error', category='validation', message='reserved by another process'))
        self.connected(next_sequence=3)
        self.assertEqual(self.session.next_sequence, 18)
        self.control.generate_command()
        self.assertEqual(self.control.draft['request']['air_seq'], 18)
        self.assertEqual(sum(action == 'send' for action, _ in self.controller.calls), 1)

    def test_exhausted_or_invalid_controller_sequence_hint_never_enables_send(self):
        self.connected(next_sequence=256)
        self.assertEqual(self.session.next_sequence, 256)
        self.assertIn('已用完', self.control.request_note.get())
        self.assertTrue(self.control.command_send_button.instate(['disabled']))
        self.control.cancel_online('disconnect')
        self.control._handle_online_event(dict(type='status', state='disconnected', message='released'))
        for suggested in (-1, 257, True, 1.0):
            self.control.connect_online()
            self.control._handle_online_event(dict(type='connected', next_sequence=suggested,
                                                  source=dict(port='COM_A', model='fake', usb_serial='fake')))
            self.assertIsNone(self.control.online_identity)
            self.assertTrue(self.control.command_send_button.instate(['disabled']))
            self.assertEqual(self.controller.calls[-1], ('disconnect', {}))
            self.control._handle_online_event(dict(type='status', state='disconnected', message='released'))

    def test_cancelled_late_connected_event_cannot_change_sequence_hint(self):
        self.control.connect_online()
        self.control.cancel_online('stop')
        self.control._handle_online_event(dict(type='connected', next_sequence=99, source=dict(port='COM_A')))
        self.assertEqual(self.session.next_sequence, 0)

    def test_uncertain_submission_consumes_sequence_and_waits_for_stop_ack(self):
        self.connected()
        self.control.generate_command()
        self.controller.fail_action = 'send'
        self.control.send_online()
        self.assertEqual(self.session.next_sequence, 1)
        self.assertEqual(self.controller.calls[-1], ('stop', {}))
        self.assertTrue(self.control.cancel_pending)
        self.assertTrue(self.control.connect_button.instate(['disabled']))
        self.assertNotIn('成功', self.control.reply_title.get())

    def test_cancelled_error_before_stop_ack_cannot_enable_new_connect(self):
        self.sent()
        self.control.cancel_online('stop')
        self.control._handle_online_event(dict(type='status', state='error', category='cancelled', message='cancelled in worker'))
        self.assertTrue(self.control.cancel_pending)
        self.assertTrue(self.control.connect_button.instate(['disabled']))
        self.control._handle_online_event(dict(type='status', state='disconnected', message='urgent stop completed'))
        self.assertFalse(self.control.cancel_pending)
        self.assertFalse(self.control.connect_button.instate(['disabled']))

    def test_worker_events_are_queued_and_close_waits_for_closed_ack(self):
        self.connected()
        self.control.generate_command()
        self.control.send_online()
        request = dict(self.control.active_request)
        worker = threading.Thread(target=lambda: self.controller.emit(dict(type='status', state='receiving', message='worker event')))
        worker.start(); worker.join()
        self.assertNotEqual(self.control.online_state, 'receiving')
        self.control._drain_online_events()
        self.assertEqual(self.control.online_state, 'receiving')
        self.session.close('control')
        self.assertIn('control', self.session.windows)
        self.assertEqual(self.controller.calls[-1], ('close', {}))
        self.assertTrue(self.control.window.winfo_exists())
        self.result(request)
        self.assertNotIn('成功', self.control.reply_title.get())
        self.session.close('control')
        self.assertEqual(sum(action == 'close' for action, _ in self.controller.calls), 1)
        self.control._handle_online_event(dict(type='status', state='closed', message='worker closed'))
        self.assertNotIn('control', self.session.windows)
        self.control._handle_online_event(dict(type='connected', source=dict(port='COM_A')))
        self.control._handle_online_event(dict(type='result', passed=True, requested=request))

    def test_closed_page_releases_private_tk_objects_before_other_worker_gc(self):
        sender = self.session.show('sender')
        private_variable = weakref.ref(self.control.input_frequency)
        private_window = weakref.ref(self.control.window)
        removed_trace = self.control.selection_trace
        self.session.close('control')
        self.control._handle_online_event(dict(type='status', state='closed'))
        self.assertIsNone(private_variable())
        self.assertIsNone(private_window())
        self.assertIsNone(self.control.input_frequency)
        self.assertIsNone(self.control.window)
        self.assertTrue(self.control.closed)
        self.assertNotIn(removed_trace, [command for _, command in self.session.source_selection.trace_info()])
        self.session.source_selection.set('接收板（上次识别） · COM_B')
        self.assertIn('COM_B', sender.device_detail.get())
        collected = []
        worker = threading.Thread(target=lambda: collected.append(gc.collect()))
        worker.start(); worker.join()
        self.assertEqual(len(collected), 1)

    def test_last_page_releases_session_variables_on_main_thread(self):
        source_selection = weakref.ref(self.session.source_selection)
        receiver_selection = weakref.ref(self.session.receiver_selection)
        self.session.close('control')
        self.control._handle_online_event(dict(type='status', state='closed'))
        self.assertIsNone(source_selection())
        self.assertIsNone(receiver_selection())
        self.assertIsNone(self.session.root)
        self.assertEqual(self.session.windows, {})

    def test_online_minimum_layout_keeps_action_row_and_history_visible(self):
        self.control.window.geometry('1040x800')
        self.root.update()
        bottom = self.control.window.winfo_rooty()+self.control.window.winfo_height()
        for widget in (self.control.command_send_button, self.control.stop_button, self.control.history):
            self.assertTrue(widget.winfo_ismapped())
            self.assertLess(widget.winfo_rooty()+widget.winfo_height(), bottom)
        self.assertGreaterEqual(self.control.command_send_button.winfo_height(), self.control.command_send_button.winfo_reqheight())

    def test_long_evidence_paths_use_existing_details_and_do_not_squeeze_actions(self):
        request = self.sent()
        iq_path = 'C:/Users/Lu/CCSDSGroundStation/sessions/20261028_220000_tc_123abc45/command_0001/reply.bin'
        report_path = iq_path.replace('.bin', '.json')
        self.result(request, iq_path=iq_path, report_path=report_path)
        self.assertIn(iq_path, self.control.device_detail.get())
        self.assertIn(report_path, self.control.device_detail.get())
        self.assertIn('reply.bin', self.control.reply_body.get())
        self.control.window.geometry('1040x800')
        self.root.update()
        for widget in (self.control.command_send_button, self.control.stop_button):
            self.assertGreaterEqual(widget.winfo_height(), widget.winfo_reqheight())
        self.control.toggle_details()
        self.root.update()
        self.assertGreaterEqual(self.control.command_send_button.winfo_height(), self.control.command_send_button.winfo_reqheight())

    def test_offline_review_never_constructs_online_factory(self):
        other_root = tk.Toplevel(self.root)
        offline = ReviewSession(other_root, port_provider=lambda: PORTS, aliases=ALIASES,
                                controller_factory=lambda *a, **kw: self.fail('offline constructed a controller'))
        page = offline.show('control')
        page.generate_command()
        self.assertIsNone(page.controller)
        offline.close('control')

    def test_cli_online_flag_is_explicit_and_default_remains_review(self):
        for argv, expected in ((['--all'], False), (['--role', 'control', '--online-control'], True)):
            with patch('sw.ground_station.ui_v2.tk.Tk'), patch('sw.ground_station.ui_v2.ReviewSession') as factory:
                main(argv)
                self.assertIs(factory.call_args.kwargs['online_control'], expected)


if __name__ == '__main__':
    unittest.main()
