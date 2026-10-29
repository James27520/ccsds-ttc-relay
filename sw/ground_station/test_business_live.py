"""V2 local endpoint tests. Fake transports are not hardware evidence."""
import json
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

import numpy as np

from .business_live import BusinessController, BusinessReceiver, BusinessSource
from .device_lease import PortLease
from .protocol import generate_message_iq


class LeaseTests(unittest.TestCase):
    def test_same_process_case_alias_and_cross_process_exclusion(self):
        with tempfile.TemporaryDirectory() as root:
            a=PortLease('com98',root)
            try:
                with self.assertRaises(RuntimeError):PortLease(' COM98 ',root)
                script=('from sw.ground_station.device_lease import PortLease\n'
                        'import sys\ntry:\n p=PortLease("COM98",sys.argv[1])\n'
                        'except RuntimeError:\n sys.exit(7)\nelse:\n p.close()\n')
                child=subprocess.run([sys.executable,'-B','-c',script,root],capture_output=True)
                self.assertEqual(child.returncode,7,child.stderr)
            finally:a.close()
            self.assertEqual(subprocess.run([sys.executable,'-B','-c',script,root],capture_output=True).returncode,0)


class AdapterTests(unittest.TestCase):
    def test_business_whitelist_does_not_allow_host_tx_enable_or_tc_frequency(self):
        s=BusinessSource.__new__(BusinessSource)
        s.owned=True;s._closed=False;s.phy='/phy';s.verify_binding=Mock()
        for path,value in [('out_altvoltage1_TX_LO_powerdown',0),
                           ('out_altvoltage1_TX_LO_frequency',100000000),
                           ('out_voltage0_hardwaregain',-30)]:
            with self.assertRaises(ValueError):s.write('/phy/'+path,value)
        s.verify_binding.assert_not_called()

    def test_each_message_has_fresh_directory_length_hash_and_finite_profile(self):
        s=BusinessSource.__new__(BusinessSource);s._prepare_waveform=Mock()
        dirs=[]
        for seq,text in enumerate(['hello','第二笔']):
            manifest=s.prepare_message(text,'1234abcd',seq,50,lambda:None)
            dirs.append(s.remote)
            args=s._prepare_waveform.call_args
            self.assertEqual(len(args.args[0]),args.kwargs['block_samples']*4)
            self.assertEqual(args.kwargs['lo_hz'],900000000)
            self.assertEqual(args.kwargs['attenuation_db'],50)
            self.assertEqual(manifest['application']['text'],text)
        self.assertNotEqual(dirs[0],dirs[1])
        manifest=s.prepare_message('901 profile','1234abcd',2,50,lambda:None,tx_rf_mhz=901.5)
        self.assertEqual(s._prepare_waveform.call_args.kwargs['lo_hz'],901000000)
        self.assertEqual(manifest['business_center_hz'],901500000)
        with self.assertRaises(ValueError):s.prepare_message('x','1234abcd',2,30,lambda:None)
        with self.assertRaises(ValueError):s.prepare_message('x','1234abcd',2,50,lambda:None,tx_rf_mhz=902.5)

    def test_apply_frequency_is_muted_local_tuning_without_dma_or_guard(self):
        s=BusinessSource.__new__(BusinessSource)
        s.owned=False;s.phy='/phy';s.verify_binding=Mock();s.require_idle=Mock()
        s.read=Mock(return_value='1');s.mute=Mock();s.write=Mock(return_value='901000000')
        s.start=Mock();s.run=Mock()
        self.assertEqual(s.apply_frequency(901000000,lambda:None),901000000)
        self.assertTrue(s.owned)
        s.write.assert_called_once_with('/phy/out_altvoltage1_TX_LO_frequency',901000000,10)
        s.mute.assert_called_once();s.start.assert_not_called();s.run.assert_not_called()
        for reason in ('busy','tx-on'):
            s.owned=False;s.mute.reset_mock();s.write.reset_mock()
            s.require_idle.side_effect=RuntimeError('busy') if reason=='busy' else None
            s.read.return_value='0'
            with self.assertRaises(RuntimeError):s.apply_frequency(900000000,lambda:None)
            self.assertFalse(s.owned);s.mute.assert_not_called();s.write.assert_not_called()
        with self.assertRaises(ValueError):s.apply_frequency(100000000,lambda:None)

    def test_identity_failure_prevents_stop_writes(self):
        s=BusinessSource.__new__(BusinessSource);s.owned=True
        s.verify_binding=Mock(side_effect=RuntimeError('reboot'));s.run=Mock();s.mute=Mock()
        with self.assertRaisesRegex(RuntimeError,'reboot'):s.stop()
        s.run.assert_not_called();s.mute.assert_not_called()

    def test_stream_binding_checks_boot_usb_and_mapping_without_verbose_probe(self):
        from .rf_session import _USB_KEYS
        c=BusinessReceiver.__new__(BusinessReceiver)
        c._closed=False;c.phy='/phy';c.tx='/tx';c.rx='/rx';c.info={'port':'TEST'}
        usb={k:k for k in _USB_KEYS};c._fingerprint=dict(usb,linux_boot_id='boot')
        c.run=Mock(return_value='boot\nad9361-phy\ncf-ad9361-dds-core-lpc\ncf-ad9361-lpc')
        c.close=Mock();c._identify=Mock()
        with patch('sw.ground_station.business_live._usb_identity',return_value=usb):
            c.verify_stream_binding();c._identify.assert_not_called()
            for value in ['other-boot\nad9361-phy\ncf-ad9361-dds-core-lpc\ncf-ad9361-lpc','boot\nwrong']:
                c.run.return_value=value
                with self.assertRaises(RuntimeError):c.verify_stream_binding()
            self.assertEqual(c.close.call_count,2)


class FakeBoard:
    def __init__(self,port,record):
        self.info=dict(port=port,model='fixture',usb_serial='fixture')
        self.phy,self.tx,self.rx='/phy','/tx','/rx'
        self.remote='/tmp/fixture';self.owned=False
        self.calls=[];self.guard='enabled';self.closed=False;self.powerdown='1'
        self.download_hook=None;self.stop_error=False;self.prepare_error=False
        self.guard_alive=True;self.remaining=20
        self.tx_lo=900000000;self.rx_lo=1000750000;self.attenuation=89
        iq,_=generate_message_iq('来自接收采样','2345abcd',3,offset_hz=-250000)
        self.raw=(np.resize(iq,(32768,2))//64).astype('<i2').tobytes()
    def verify_binding(self):self.calls.append('identity')
    def verify_stream_binding(self):self.calls.append('stream identity')
    def require_idle(self):self.calls.append('idle')
    def read(self,path):
        if path.endswith('TX_LO_powerdown'):return self.powerdown
        if path.endswith('/owned'):return '123 456'
        if path.endswith('/guard_owned'):return '124 457'
        if path.endswith('buffer/enable'):return '0'
        if path.endswith('guard_state'):return self.guard
        if path.endswith('TX_LO_frequency'):return str(self.tx_lo)
        if path.endswith('RX_LO_frequency'):return str(self.rx_lo)
        if path.endswith('hardwaregain'):return str(-self.attenuation)
        if path.endswith('_type'):return 'le:S12/16>>0'
        if path.endswith('_index'):return '0' if 'voltage0' in path else '1'
        return '0'
    def write(self,path,value,tolerance=0):
        self.calls.append(('write',path,value))
        if path.endswith('TX_LO_frequency'):self.tx_lo=int(value)
        if path.endswith('RX_LO_frequency'):self.rx_lo=int(value)
        return str(value)
    def run(self,command,**kwargs):
        self.calls.append(command)
        if 'echo $((' in command:return str(self.remaining)
        if 'test "$(awk' in command and not self.guard_alive:raise RuntimeError('guard disappeared')
        return '0' if 'echo $?' in command else ''
    def mute(self):self.calls.append('mute');self.powerdown='1';self.attenuation=89
    def close(self):self.closed=True;self.calls.append('close')
    def apply_frequency(self,lo_hz,check):
        check();self.mute();self.tx_lo=lo_hz;self.owned=True
        self.calls.append(('apply_frequency',lo_hz));return lo_hz
    def prepare_message(self,text,session,sequence,atten,check,*,tx_rf_mhz=900.5):
        check();self.calls.append(('prepare',text,sequence));self.owned=True
        self.calls.append(('prepare_rf',tx_rf_mhz));self.tx_lo=int((tx_rf_mhz-.5)*1e6);self.attenuation=atten
        if self.prepare_error:raise RuntimeError('prepare failed')
        return dict(fixture=True)
    def start(self):self.calls.append('start');self.powerdown='0'
    def stop(self):
        self.calls.append('stop');self.powerdown='1'
        if self.stop_error:raise RuntimeError('stop unconfirmed')
    def download(self,path,size):
        if self.download_hook:self.download_hook()
        return self.raw


class ReverseFakeBoard(FakeBoard):
    def __init__(self, *args):
        super().__init__(*args)
        self.debug = '/debug'
        self.two_channels = '1'
        self.bad_layout = False
    def read(self, path):
        if path.endswith('adi,2rx-2tx-mode-enable'):
            return self.two_channels
        if path.endswith('_index'):
            return '0' if self.bad_layout else path.split('in_voltage')[1][0]
        return super().read(path)


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.events=queue.Queue();self.boards=[];self.c=None
    def tearDown(self):
        if self.c:
            self.c.submit('close');self.c.worker.join(4)
            self.assertFalse(self.c.worker.is_alive())
        self.temp.cleanup()
    def make(self,role='sender',factory=None,direction='forward'):
        def create(port,record):
            b=FakeBoard(port,record);self.boards.append(b);return b
        self.c=BusinessController(role,self.events.put,self.root/'session',console_factory=factory or create,
                                  lease_factory=lambda p:PortLease(p,self.root/'locks'),direction=direction)
        self.wait('status','disconnected')
        return self.c
    def wait(self,kind,state=None):
        end=time.monotonic()+4
        while True:
            event=self.events.get(timeout=max(.01,end-time.monotonic()))
            if event['type']==kind and (state is None or event.get('state')==state):return event
    def connect(self):
        self.c.submit('connect',port='TEST');self.wait('identity');self.wait('status','ready')
        self.c.submit('configure');self.wait('settings');self.wait('status','ready')
    def test_only_local_port_multiple_messages_guard_stop_and_reconnect(self):
        self.make();self.connect();b=self.boards[-1]
        self.assertIsNone(self.c.relay)
        self.assertTrue(self.c.settings['configured'])
        self.assertEqual(self.c.settings['tx_lo_hz_readback'],900000000)
        self.assertNotIn('start',b.calls)
        ids=[]
        for text in ['Hello V2','第二条']:
            self.c.submit('send',text=text);ids.append(self.wait('tx')['message_id']);self.wait('status','transmitting')
        self.assertEqual(len(set(ids)),2)
        b.guard='stopped';self.c.last_guard_check=0
        self.wait('status','stopped');self.assertEqual(b.powerdown,'1')
        self.c.submit('disconnect');self.wait('status','disconnected')
        self.assertTrue(b.closed);self.connect()

    def test_reverse_receiver_selects_second_pair_and_only_decodes_local_iq(self):
        self.make('receiver', factory=ReverseFakeBoard, direction='reverse'); self.connect()
        b = self.c.console
        self.assertEqual(self.c.settings['rx_channel'], 2)
        self.assertIn(('write', '/phy/in_voltage1_hardwaregain', 30), b.calls)
        self.assertNotIn(('write', '/phy/in_voltage0_hardwaregain', 30), b.calls)
        self.c.submit('receive'); self.wait('status', 'receiving')
        event = self.wait('rx')
        self.assertEqual(event['direction'], 'reverse')
        self.assertEqual(event['rx_channel'], 2)
        self.assertTrue(event['messages'])
        self.assertEqual(event['messages'][0]['text'], '来自接收采样')
        commands = [x for x in b.calls if isinstance(x, str) and 'iio_readdev' in x]
        self.assertTrue(commands)
        self.assertIn('voltage2 voltage3', commands[0])
        self.assertNotIn('voltage0 voltage1', commands[0])
        self.assertIsNone(self.c.relay)
        self.assertNotIn('start', b.calls)

    def test_reverse_receiver_rejects_missing_channel_before_rx_configuration(self):
        def factory(port, record):
            b = ReverseFakeBoard(port, record); b.two_channels = '0'; return b
        self.make('receiver', factory=factory, direction='reverse')
        self.c.submit('connect', port='TEST'); self.wait('identity'); self.wait('status', 'ready')
        b = self.c.console
        self.c.submit('configure')
        self.assertIn('第二射频通道', self.wait('status', 'error')['message'])
        self.assertFalse(any(isinstance(x, tuple) and x[0] == 'write' and '/in_' in x[1] for x in b.calls))

    def test_reverse_layout_change_during_capture_never_publishes_wrong_channel(self):
        self.make('receiver', factory=ReverseFakeBoard, direction='reverse'); self.connect()
        b = self.c.console
        b.download_hook = lambda: setattr(b, 'bad_layout', True)
        self.c.submit('receive'); self.wait('status', 'receiving')
        self.assertIn('I/Q格式', self.wait('status', 'error')['message'])
        self.assertFalse(list((self.root/'session').glob('rx_*.json')))

    def test_reverse_sender_default_is_muted_and_rejects_untested_frequency(self):
        self.make(direction='reverse'); self.connect(); b = self.c.console
        self.assertEqual(self.c.settings['expected_rf_hz'], 901500000)
        self.assertEqual(self.c.settings['tx_atten_db_requested'], 60)
        self.assertEqual(b.powerdown, '1')
        self.assertNotIn('start', b.calls)
        self.c.submit('configure', tx_rf_mhz=900.5)
        self.assertIn('回信当前工作点', self.wait('status', 'error')['message'])
        self.assertNotIn('start', b.calls)

    def test_both_sender_centers_apply_while_muted_and_send_uses_applied_lo(self):
        self.make();self.connect();b=self.boards[-1]
        self.assertEqual(b.powerdown,'1')
        self.assertEqual(self.c.settings['expected_rf_hz'],900500000)
        self.c.submit('configure',tx_rf_mhz=901.5,tx_atten_db=55)
        settings=self.wait('settings')['values'];self.wait('status','ready')
        self.assertEqual(settings['tx_lo_hz_readback'],901000000)
        self.assertEqual(settings['tx_atten_db_requested'],55)
        self.assertEqual(settings['tx_atten_db_readback'],89)
        self.assertEqual(b.powerdown,'1');self.assertNotIn('start',b.calls)
        self.c.submit('send',text='new frequency')
        self.wait('tx');self.wait('status','transmitting')
        self.assertIn(('prepare_rf',901.5),b.calls)
        self.assertEqual(self.c.settings['tx_lo_hz_readback'],901000000)
        self.assertEqual(self.c.settings['expected_rf_hz'],901500000)

    def test_receiver_actually_retunes_lo_for_independent_target_and_decodes_its_iq(self):
        self.make('receiver');self.connect();b=self.boards[-1]
        self.c.submit('configure',expected_rf_mhz=1001.5)
        values=self.wait('settings')['values'];self.wait('status','ready')
        self.assertEqual(values['rx_lo_hz_readback'],1001750000)
        self.assertEqual(values['expected_rf_mhz'],1001.5)
        self.assertIn(('write','/phy/out_altvoltage0_RX_LO_frequency',1001750000),b.calls)
        self.assertNotIn('start',b.calls)
        self.c.submit('receive');self.wait('status','receiving')
        received=self.wait('rx')
        self.assertEqual(received['messages'][0]['text'],'来自接收采样')
        self.assertAlmostEqual(received['carrier_hz'],1001500000,delta=10000)

    def test_unapproved_sender_frequency_rejects_before_tuning_and_never_starts(self):
        self.make();self.connect();b=self.boards[-1]
        count=sum(isinstance(call,tuple) and call[0]=='apply_frequency' for call in b.calls)
        self.c.submit('configure',tx_rf_mhz=902.5,tx_atten_db=50)
        self.wait('status','error')
        self.assertEqual(sum(isinstance(call,tuple) and call[0]=='apply_frequency' for call in b.calls),count)
        self.assertNotIn('start',b.calls)
        self.assertTrue(b.closed)
    def test_busy_or_open_failure_never_mutes_unowned_board_and_releases_lease(self):
        b=FakeBoard('TEST',None);b.powerdown='0'
        self.make(factory=lambda *_:b);self.c.submit('connect',port='TEST')
        self.wait('status','error')
        self.assertNotIn('stop',b.calls);self.assertNotIn('mute',b.calls);self.assertTrue(b.closed)
        l=PortLease('TEST',self.root/'locks');l.close()
    def test_stop_failure_closes_device_and_allows_explicit_reconnect(self):
        self.make();self.connect();self.boards[-1].stop_error=True
        self.c.submit('stop');self.wait('status','error')
        self.assertTrue(self.boards[-1].closed);self.connect()
    def test_dead_guard_is_not_trusted_from_enabled_file(self):
        self.make();self.connect();self.c.submit('send',text='guard test');self.wait('tx')
        b=self.boards[-1];b.guard_alive=False;self.c.last_guard_check=0
        self.wait('status','error')
        self.assertEqual(b.powerdown,'1');self.assertTrue(b.closed)
    def test_elapsed_board_deadline_stops_even_if_enabled_file_remains(self):
        self.make();self.connect();self.c.submit('send',text='deadline');self.wait('tx')
        b=self.boards[-1];b.remaining=0;self.c.last_guard_check=0
        self.wait('status','stopped');self.assertEqual(b.powerdown,'1')
    def test_receiver_decodes_only_its_iq_and_stop_during_download_emits_no_rx(self):
        self.make('receiver');self.connect();b=self.boards[-1]
        self.c.submit('receive');self.wait('status','receiving')
        rx=self.wait('rx')
        self.assertTrue(rx['messages'])
        self.assertEqual(rx['messages'][0]['text'],'来自接收采样')
        b.download_hook=lambda:self.c.submit('stop')
        self.assertEqual(self.wait('status','error')['category'],'cancelled')
        self.wait('status','disconnected')
        pending=[]
        while not self.events.empty():pending.append(self.events.get_nowait())
        self.assertFalse(any(e['type']=='rx' for e in pending))
    def test_close_event_survives_disk_failure(self):
        self.make();original=self.c.record
        def record(**values):
            if values.get('type')=='closed':raise OSError('fixture disk failure')
            original(**values)
        self.c.record=record;self.c.submit('close');self.wait('closed')


if __name__=='__main__':unittest.main()
