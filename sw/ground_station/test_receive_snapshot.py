import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from .terminal_radio import TerminalRadio, ReceiveUnavailable
from .receive_snapshot import snapshot_script
from .rf_session import _USB_KEYS


class ReceiveSnapshotTests(unittest.TestCase):
    def test_guard_expiry_between_snapshot_and_pid_read_does_not_disconnect(self):
        r=self.radio('');r.phy='/phy';r.tx='/tx';r.remote='/tmp/tx';r.record=Mock()
        # Exact captured timing: enabled at uptime deadline-0.01, gone 48ms later.
        r.run=Mock(side_effect=['enabled\n0\n23132 7026349\n23119 7026299\n70293\n70292.99 0\n1',
                               'missing\nmissing', 'enabled\n1\n0', 'stopped\n1\n0'])
        with patch('sw.ground_station.terminal_radio._verify_runtime_binding'), \
             patch('sw.ground_station.terminal_radio.time.sleep'):
            self.assertFalse(r.verify_transmit())
        self.assertEqual(r.run.call_count,4)
        self.assertTrue(r.record.called)

    def test_pid_reuse_is_still_fatal_even_near_guard_expiry(self):
        r=self.radio('');r.phy='/phy';r.tx='/tx';r.remote='/tmp/tx';r.record=Mock()
        r.run=Mock(side_effect=['enabled\n0\n23132 7026349\n23119 7026299\n70293\n70292.99 0\n1',
                               'changed\nlive'])
        with patch('sw.ground_station.terminal_radio._verify_runtime_binding'):
            with self.assertRaisesRegex(RuntimeError,'身份变化'):r.verify_transmit()

    def test_partial_guard_state_write_requires_confirmed_off(self):
        r=self.radio('');r.phy='/phy';r.tx='/tx';r.remote='/tmp/tx';r.record=Mock()
        r.run=Mock(side_effect=['0\n201 2001\n202 2002\n101\n100.99 0\n0',
                               'stopped\n1\n0'])
        with patch('sw.ground_station.terminal_radio._verify_runtime_binding'):
            self.assertFalse(r.verify_transmit())

    def test_only_available_boot_limited_second_cpu_is_onlined(self):
        for present, online, cmdline, enable in [('0-1', '0', 'maxcpus=1 root=ram', True),
                                                ('0-1', '0-1', 'maxcpus=1', False),
                                                ('0', '0', 'maxcpus=1', False),
                                                ('0-1', '0', 'root=ram', False)]:
            with self.subTest(present=present, online=online, cmdline=cmdline):
                r=self.radio('')
                r.phy='/phy';r.record=Mock();r.read=Mock(return_value='1')
                r.run=Mock(side_effect=['\n'.join([present,present,online,cmdline])]+(['0-1'] if enable else []))
                with patch('sw.ground_station.terminal_radio._verify_runtime_binding'):
                    r.ensure_receive_cpu()
                self.assertEqual(r.run.call_count, 2 if enable else 1)
                commands='\n'.join(c.args[0] for c in r.run.call_args_list)
                self.assertNotIn('fw_setenv',commands)
                self.assertNotIn('reboot',commands)
                self.assertNotIn('/dev/mtd',commands)
                self.assertEqual('echo 1 >' in commands,enable)

    def radio(self, result):
        r = object.__new__(TerminalRadio)
        r._closed = False
        r.stream = '/tmp/test'
        r.info = dict(port='FAKE')
        r._fingerprint = {k: 'fake-'+k for k in _USB_KEYS}
        r._fingerprint['linux_boot_id'] = 'fake-boot'
        r.run = Mock(return_value=result)
        r.verify_binding = Mock(side_effect=AssertionError('full IIO poll'))
        return r

    def result(self, boot='fake-boot'):
        return 'RXSNAP1\n'+json.dumps(dict(samples=1234))+'\n[]\nRXMETRICS\n0\n0.1 0 0\ncpu 1 2 3\nproc-decoder\nproc-reader\n'+boot

    def test_one_transaction_preserves_two_sided_usb_and_boot_check(self):
        r = self.radio(self.result())
        with patch('sw.ground_station.terminal_radio._usb_identity', return_value=r._fingerprint) as usb:
            status, messages = r.poll_receive()
        self.assertEqual(r.run.call_count, 1)
        self.assertEqual(usb.call_count, 2)
        self.assertEqual(status['samples'], 1234)
        self.assertEqual(status['cpu_online'], '0')
        self.assertEqual(messages, [])

    def test_reused_identity_reboot_and_missing_process_are_distinct(self):
        for result, error in [('RXERROR unavailable reader', ReceiveUnavailable),
                              ('RXERROR identity decoder', RuntimeError),
                              (self.result('new-boot'), RuntimeError),
                              ('bad json', ValueError)]:
            with self.subTest(result=result):
                r = self.radio(result)
                if error is ReceiveUnavailable:
                    r.run = Mock(side_effect=[result, 'RXFINAL\n{"input_error":false}'])
                with patch('sw.ground_station.terminal_radio._usb_identity', return_value=r._fingerprint), \
                     patch('sw.ground_station.terminal_radio._verify_runtime_binding'):
                    with self.assertRaises(error): r.poll_receive()
        r = self.radio(self.result())
        with patch('sw.ground_station.terminal_radio._usb_identity', side_effect=[r._fingerprint, {}]):
            with self.assertRaisesRegex(RuntimeError, 'USB'): r.poll_receive()

    def test_decoder_exit_preserves_fatal_input_error(self):
        r = self.radio('')
        r.run = Mock(side_effect=['RXERROR unavailable decoder', 'RXFINAL\n{"input_error":true}'])
        with patch('sw.ground_station.terminal_radio._usb_identity', return_value=r._fingerprint), \
             patch('sw.ground_station.terminal_radio._verify_runtime_binding'):
            with self.assertRaisesRegex(RuntimeError, '采样输入异常') as caught:
                r.poll_receive()
        self.assertNotIsInstance(caught.exception, ReceiveUnavailable)

    def test_missing_or_normal_final_status_allows_recovery_but_bad_status_does_not(self):
        for raw, recoverable in [('RXFINAL_MISSING', True), ('RXFINAL\n{"input_error":false,"stopped":true}', True),
                                 ('RXFINAL\n{"input_error":true}', False), ('RXFINAL\n{}', False),
                                 ('RXFINAL', False), ('RXFINAL\n', False), ('', False), ('broken', False)]:
            with self.subTest(raw=raw):
                r = self.radio(raw)
                with patch('sw.ground_station.terminal_radio._verify_runtime_binding'):
                    try: r._receive_unavailable('owned process exited')
                    except Exception as exc:
                        self.assertEqual(isinstance(exc, ReceiveUnavailable), recoverable)
                    else: self.fail('missing process was accepted as live')

    def test_script_embeds_current_process_identity_and_checks_all_channels(self):
        r = SimpleNamespace(stream='/tmp/test', phy='/phy',tx='/tx',rx='/rx',rx_channel=2,
            _fingerprint=dict(linux_boot_id='boot'), stream_owners=dict(reader=['101','201'],
            decoder=['102','202'],guard=['103','203']))
        script = snapshot_script(r).decode()
        for pid, ticks, name in [('101','201','reader'), ('102','202','decoder'), ('103','203','guard')]:
            self.assertIn(f'readp {pid} {ticks} {name}', script)
        self.assertIn('/proc/sys/kernel/random/boot_id', script)
        for n in range(4): self.assertIn(f'in_voltage{n}_en',script)
        self.assertNotIn('iio_info',script)
        self.assertNotIn('awk',script)
        self.assertNotIn('kill ',script)
        self.assertNotIn('out_altvoltage1_TX_LO_powerdown',script)


@unittest.skipUnless(os.environ.get('POSIX_TEST_SHELL') or shutil.which('sh'), 'POSIX shell required')
class SnapshotShellTests(unittest.TestCase):
    """Execute the real generated shell against private synthetic proc/sys files."""
    def run_snapshot(self, between_reads=''):
        radio = SimpleNamespace(stream='session', phy='phy', tx='tx', rx='rx', rx_channel=1,
            _fingerprint=dict(linux_boot_id='boot'), stream_owners=dict(reader=['101','201'],
            decoder=['102','202'],guard=['103','203']))
        files = {'proc/sys/kernel/random/boot_id':'boot', 'phy/name':'ad9361-phy',
                 'tx/name':'cf-ad9361-dds-core-lpc', 'rx/name':'cf-ad9361-lpc',
                 'rx/buffer/enable':'1', 'sys/devices/system/cpu/online':'0-1',
                 'proc/loadavg':'0.1 0.2 0.3 1/30 101', 'proc/stat':'cpu 1 2 3',
                 'proc/uptime':'100.00 20.00', 'session/rx.status.json':'{"samples":1234}',
                 'session/rx.messages.json':'[]'}
        for n, value in enumerate(('1','1','0','0')):
            files[f'rx/scan_elements/in_voltage{n}_en'] = value
        for name, (pid, ticks) in radio.stream_owners.items():
            files[f'session/{name}.owned'] = f'{pid} {ticks}'
            files[f'proc/{pid}/stat'] = f'{pid} (process with spaces) S '+('0 '*18)+ticks+' 0'
        script = snapshot_script(radio).decode().replace('/proc/', 'proc/').replace('/sys/devices/', 'sys/devices/')
        script = script.replace('readv proc/loadavg;', between_reads+'\nreadv proc/loadavg;')
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name, content in files.items():
                path = root/name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content+'\n', encoding='ascii', newline='\n')
            (root/'snapshot.sh').write_text(script, encoding='ascii', newline='\n')
            shell = os.environ.get('POSIX_TEST_SHELL') or shutil.which('sh')
            result = subprocess.run([shell, 'snapshot.sh'], cwd=root, text=True,
                                    capture_output=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            return result.stdout.strip()

    def test_valid_snapshot_checks_process_names_with_spaces(self):
        result = self.run_snapshot()
        self.assertTrue(result.startswith('RXSNAP1\n'))
        self.assertIn('RXMETRICS\n0-1\n', result)
        self.assertNotIn('RXERROR', result)

    def test_exit_after_ownership_check_returns_only_unavailable(self):
        self.assertEqual(self.run_snapshot('rm proc/101/stat'), 'RXERROR unavailable reader')

    def test_reused_pid_after_ownership_check_still_fails_identity(self):
        changed = '101 (replacement) S '+('0 '*18)+'999 0'
        self.assertEqual(self.run_snapshot(f"printf '%s\\n' '{changed}' > proc/101/stat"),
                         'RXERROR identity reader')

    def test_existing_but_unreadable_stat_is_not_a_normal_exit(self):
        self.assertEqual(self.run_snapshot(': > proc/101/stat'), 'RXERROR identity reader')
