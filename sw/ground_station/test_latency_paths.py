"""Fast-path guards and RAM reuse; fixtures never open a hardware device."""
import hashlib
import unittest
from unittest.mock import Mock, patch
from .rf_session import _USB_KEYS
from .terminal_radio import TerminalRadio


class LatencyPathTests(unittest.TestCase):
    def test_terminal_runtime_binding_rejects_reboot_or_usb_change(self):
        for change in ('none', 'boot', 'usb'):
            with self.subTest(change=change):
                r = object.__new__(TerminalRadio)
                usb = {k:k for k in _USB_KEYS}
                r.info = dict(port='fixture')
                r._fingerprint = dict(usb, linux_boot_id='boot')
                r._closed = False
                r.phy, r.tx, r.rx = '/phy', '/tx', '/rx'
                r.close = Mock()
                r.run = Mock(return_value=('changed' if change == 'boot' else 'boot')+
                             '\nad9361-phy\ncf-ad9361-dds-core-lpc\ncf-ad9361-lpc')
                now = dict(usb)
                if change == 'usb': now['usb_serial'] = 'changed'
                with patch('sw.ground_station.business_live._usb_identity', return_value=now):
                    if change == 'none':
                        self.assertTrue(r.verify_binding())
                        r.close.assert_not_called()
                    else:
                        with self.assertRaises(RuntimeError): r.verify_binding()
                        r.close.assert_called_once()
                self.assertFalse(any('iio_info' in str(c) for c in r.run.call_args_list))

    def test_batched_mute_requires_all_hardware_readbacks(self):
        for response, valid in [('1\n-89.000000 dB\n-89.000000 dB\n'+'\n'.join(['0']*8), True),
                                ('1\n-89\n-89\n'+'\n'.join(['0']*7), False),
                                ('1\n-89\n-89\n'+'\n'.join(['0']*9), False),
                                ('0\n-89\n-89\n'+'\n'.join(['0']*8), False),
                                ('1\n-89\n-50\n'+'\n'.join(['0']*8), False),
                                ('1\n-89\n-89\n0.25\n'+'\n'.join(['0']*7), False),
                                ('1\n-89\n-89', False)]:
            with self.subTest(response=response):
                r = object.__new__(TerminalRadio)
                r.owned, r._closed = True, False
                r.phy, r.tx = '/phy', '/tx'
                r.verify_binding = Mock()
                r.run = Mock(return_value=response)
                if valid: r.mute()
                else:
                    with self.assertRaises(RuntimeError): r.mute()
                command = r.run.call_args[0][0]
                self.assertLess(len(command)+150, 900)
                self.assertIn('echo 1 >', command)
                self.assertIn('for n in 0 1', command)
                self.assertIn('|| bad=1', command)

    def test_receiver_cache_is_reused_only_after_checksum_verification(self):
        r = object.__new__(TerminalRadio)
        r.stream, r.business_mode, r.rx_channel = None, True, 1
        r.phy, r.tx, r.rx = '/phy', '/tx', '/rx'
        r.record = r.verify_binding = r.ensure_receive_cpu = r.verify_stream = r.renew_receive = Mock()
        r.stream_owners = {}
        raw = b'\x7fELFtest fixture'
        digest = hashlib.sha256(raw).hexdigest()
        r.receiver_binary = Mock(return_value=raw)
        r.read = lambda p: 'le:S12/16>>0' if p.endswith('_type') else ('1' if p.endswith('/enable') else '100 200')
        r._launch_owned = Mock()
        r.run = Mock(side_effect=lambda c: digest+'  file' if c.startswith('sha256sum ') else '')
        with patch('sw.ground_station.terminal_radio.AutonomousRadio.require_idle'), \
             patch('sw.ground_station.terminal_radio.snapshot_script', return_value=b'fixture'), \
             patch('sw.ground_station.terminal_radio.Console.upload') as upload:
            r.start_receive()
            r.stream = None
            r.start_receive()
            self.assertEqual(sum(c.args[1].endswith('/decode') for c in upload.call_args_list), 1)
            before = r._launch_owned.call_count
            r.stream = None
            r.run = Mock(return_value='0'*64+'  file')
            with self.assertRaisesRegex(RuntimeError, '摘要变化'): r.start_receive()
            self.assertEqual(r._launch_owned.call_count, before)


if __name__ == '__main__':
    unittest.main()
