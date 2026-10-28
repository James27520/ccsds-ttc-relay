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
        with self.assertRaises(ValueError):s.prepare_message('x','1234abcd',2,30,lambda:None)

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
        if path.endswith('TX_LO_frequency'):return '900000000'
        if path.endswith('hardwaregain'):return '-50'
        if path.endswith('_type'):return 'le:S12/16>>0'
        if path.endswith('_index'):return '0' if 'voltage0' in path else '1'
        return '0'
    def write(self,path,value,tolerance=0):self.calls.append(('write',path,value));return str(value)
    def run(self,command,**kwargs):
        self.calls.append(command)
        if 'echo $((' in command:return str(self.remaining)
        if 'test "$(awk' in command and not self.guard_alive:raise RuntimeError('guard disappeared')
        return '0' if 'echo $?' in command else ''
    def mute(self):self.calls.append('mute')
    def close(self):self.closed=True;self.calls.append('close')
    def prepare_message(self,text,session,sequence,atten,check):
        check();self.calls.append(('prepare',text,sequence));self.owned=True
        if self.prepare_error:raise RuntimeError('prepare failed')
        return dict(fixture=True)
    def start(self):self.calls.append('start');self.powerdown='0'
    def stop(self):
        self.calls.append('stop');self.powerdown='1'
        if self.stop_error:raise RuntimeError('stop unconfirmed')
    def download(self,path,size):
        if self.download_hook:self.download_hook()
        return self.raw


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.events=queue.Queue();self.boards=[];self.c=None
    def tearDown(self):
        if self.c:
            self.c.submit('close');self.c.worker.join(4)
            self.assertFalse(self.c.worker.is_alive())
        self.temp.cleanup()
    def make(self,role='sender',factory=None):
        def create(port,record):
            b=FakeBoard(port,record);self.boards.append(b);return b
        self.c=BusinessController(role,self.events.put,self.root/'session',console_factory=factory or create,
                                  lease_factory=lambda p:PortLease(p,self.root/'locks'))
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
        self.assertNotIn('tx_lo_hz_readback',self.c.settings)
        ids=[]
        for text in ['Hello V2','第二条']:
            self.c.submit('send',text=text);ids.append(self.wait('tx')['message_id']);self.wait('status','transmitting')
        self.assertEqual(len(set(ids)),2)
        b.guard='stopped';self.c.last_guard_check=0
        self.wait('status','stopped');self.assertEqual(b.powerdown,'1')
        self.c.submit('disconnect');self.wait('status','disconnected')
        self.assertTrue(b.closed);self.connect()
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
