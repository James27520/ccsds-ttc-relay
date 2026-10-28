"""RF binding/fault tests with fake USB and UARTs; never enumerate real ports."""
import copy
import json
import time
import types
import unittest
from unittest.mock import Mock, patch

from . import rf_session as rf
from .telemetry import TelemetrySerial
from .transport import Console, _board_identity
from .test_telemetry import wire

BOOT = '9068ea50-9aba-4b71-95d6-d491ace21f35'
NAMES = ('/sys/bus/iio/devices/iio:device0 ad9361-phy\n'
         '/sys/bus/iio/devices/iio:device1 cf-ad9361-dds-core-lpc\n'
         '/sys/bus/iio/devices/iio:device2 cf-ad9361-lpc')
TX_STATUS = ['TM_TX enabled=1 seq=18 pending=0 stopping=0 status=00000028 diag=00000000',
             'TM_DAC verified=1 finished=1 diagnostic=102a0110 rc=0']
STATUS = ['CONTROLLER auto=0 capture_state=0 capture_valid=0 consumed=0',
          'STATUS network=1 armed=0 pending=0']


class PairTests(unittest.TestCase):
    def setUp(self):
        rf._BINDINGS.clear()
        self.usb = {name: dict(port=name, usb_vid=0x0403, usb_pid=0x6010,
                              usb_serial='', usb_location=name+'-location', hwid='USB')
                    for name in ('RX_PORT', 'ADDA_PORT')}
        self.handles, self.commands = [], []
        self.boot, self.model, self.iio_serial = BOOT, 'Test Pluto model', ''
        self.uptime_offset = 10000
        self.started = time.monotonic()
        self.adda_fail = False
        self.patches = [
            patch.object(rf, '_usb_identity', side_effect=lambda p: copy.deepcopy(self.usb[p])),
            patch.object(rf, '_open_usb', side_effect=self.open_usb),
            patch.object(Console, 'run', autospec=True, side_effect=self.console_run),
            patch.object(TelemetrySerial, '_exchange', autospec=True, side_effect=self.cli)]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def open_usb(self, name, timeout):
        if self.adda_fail and name == 'ADDA_PORT':
            raise RuntimeError('open failed')
        handle = Mock()
        self.handles.append(handle)
        return handle

    def console_run(self, console, command, timeout=8):
        self.commands.append(command)
        if command == 'cat /proc/sys/kernel/random/boot_id':
            return self.boot
        if command == 'iio_info -u local:':
            return ('hw_model: '+self.model+'\nhw_serial: '+self.iio_serial+
                    '\nfw_version: ignored\nad9361-phy\ncf-ad9361-lpc')
        if command == rf._NAMES:
            return NAMES
        raise AssertionError('Unexpected probe command: '+command)

    def cli(self, adda, command):
        self.commands.append(command)
        if command == 'status':
            return STATUS+['CLI_RESULT rc=0']
        if command == 'tmstatus':
            return TX_STATUS+['CLI_RESULT rc=0']
        if command == 'telemetry':
            uptime = self.uptime_offset+int((time.monotonic()-self.started)*1000)
            return [wire(uptime_ms=uptime), 'CLI_RESULT rc=0']
        if command in ('tmsend', 'tmstop', 'tmclear'):
            return ['CLI_RESULT rc=0']
        raise AssertionError(command)

    def probe(self):
        return rf.probe_pair('RX_PORT', 'ADDA_PORT')

    def test_probe_is_serializable_read_only_and_closes_every_handle(self):
        binding = self.probe()
        self.assertEqual(json.loads(json.dumps(binding)), binding)
        self.assertEqual(binding['receiver']['iio_serial'], '')
        self.assertIn('RX only', binding['receiver']['identity_scope'])
        self.assertIn('no boot nonce', binding['adda']['identity_scope'])
        self.assertTrue(all(h.close.call_count == 1 for h in self.handles))
        self.assertEqual(set(self.commands), {
            'cat /proc/sys/kernel/random/boot_id', 'iio_info -u local:', rf._NAMES,
            'status', 'telemetry', 'tmstatus'})
        for handle in self.handles:
            handle.write.assert_not_called()
        with self.assertRaises(RuntimeError):
            _board_identity('hw_serial: \nfw_version: 123', '')

    def test_open_revalidates_enables_only_this_pair_and_token_is_one_use(self):
        binding = self.probe()
        rx, adda = rf.open_pair(binding)
        self.assertIsInstance(rx, Console)
        self.assertTrue(rx.verify_binding())
        self.assertTrue(adda.verify_binding())
        self.assertEqual(adda.query()['spi_valid'], 0)
        self.assertTrue(adda.status().startswith('STATUS network='))
        status = adda.tmstatus()
        self.assertEqual(status['status'], 0x28)
        self.assertEqual(status['dac_diagnostic'], 0x102a0110)
        self.assertTrue(all(type(value) is int for value in status.values()))
        with self.assertRaises(RuntimeError):
            rf.open_pair(binding)
        rx.close()
        adda.close()

    def test_probe_failure_closes_first_port_and_duplicate_ports_never_open(self):
        self.adda_fail = True
        with self.assertRaises(RuntimeError):
            self.probe()
        self.handles[0].close.assert_called_once()
        self.handles.clear()
        with self.assertRaises(ValueError):
            rf.probe_pair('RX_PORT', 'rx_port')
        self.assertFalse(self.handles)

    def test_modified_foreign_or_reused_probe_cannot_open(self):
        for field, value in [('process_token', 'foreign'), ('receiver', {'port': 'other'})]:
            with self.subTest(field=field):
                binding = self.probe()
                binding[field] = value
                count = len(self.handles)
                with self.assertRaises(RuntimeError):
                    rf.open_pair(binding)
                self.assertEqual(count, len(self.handles))
                with self.assertRaises(RuntimeError):
                    rf.open_pair(binding)

    def test_receiver_boot_model_iio_or_usb_changes_fail_closed(self):
        changes = [('boot', BOOT.replace('9068', 'abcd')),
                   ('model', 'Different SDR'), ('iio_serial', 'different')]
        for attr, changed in changes:
            with self.subTest(attr=attr):
                old = getattr(self, attr)
                binding = self.probe()
                setattr(self, attr, changed)
                with self.assertRaises(RuntimeError):
                    rf.open_pair(binding)
                self.handles[-1].close.assert_called_once()
                setattr(self, attr, old)
        binding = self.probe()
        rx, adda = rf.open_pair(binding)
        self.usb['RX_PORT']['usb_pid'] += 1
        with self.assertRaises(RuntimeError):
            rx.verify_binding()
        self.assertTrue(rx._closed)
        with self.assertRaises(RuntimeError):
            rx.write(rx.phy+'/in_voltage_sampling_frequency', 2500000)
        adda.close()

    def test_adda_usb_swap_or_reboot_closes_both_on_open_failure(self):
        binding = self.probe()
        self.uptime_offset -= 5000
        with self.assertRaisesRegex(RuntimeError, 'uptime'):
            rf.open_pair(binding)
        for handle in self.handles[-2:]:
            handle.close.assert_called_once()

        binding = self.probe()
        self.usb['ADDA_PORT']['usb_serial'] = 'changed'
        with self.assertRaisesRegex(RuntimeError, 'ADDA changed'):
            rf.open_pair(binding)
        for handle in self.handles[-2:]:
            handle.close.assert_called_once()

    def test_control_to_downlink_probe_preserves_old_boot_constraint(self):
        a = rf.SessionAdda('ADDA_PORT')
        continuity = (a._boot_interval, a._uptime)
        a.close()
        binding = rf.probe_pair('RX_PORT', 'ADDA_PORT', adda_continuity=continuity)
        self.assertIn(binding['token'], rf._BINDINGS)
        count = len(rf._BINDINGS)
        self.uptime_offset -= 5000
        with self.assertRaisesRegex(RuntimeError, 'uptime'):
            rf.probe_pair('RX_PORT', 'ADDA_PORT', adda_continuity=continuity)
        self.assertEqual(len(rf._BINDINGS), count)
        for handle in self.handles[-2:]:
            handle.close.assert_called_once()

    def test_adda_failed_freshcheck_is_terminal_and_controls_have_no_preflight(self):
        rx, adda = rf.open_pair(self.probe())
        self.commands.clear()
        adda.clear()
        adda.send()
        adda.stop()
        self.assertEqual(self.commands, ['tmclear', 'tmsend', 'tmstop'])
        self.uptime_offset -= 5000
        with self.assertRaises(RuntimeError):
            adda.verify_binding()
        with self.assertRaises(RuntimeError):
            adda.send()
        self.assertTrue(adda._closed)
        rx.close()

    def test_write_values_are_fixed_and_upload_tx_start_forbidden(self):
        rx, adda = rf.open_pair(self.probe())
        with patch.object(Console, 'write', return_value='ok') as write:
            for suffix, value in [('in_voltage_sampling_frequency', 2500000),
                                  ('in_voltage_rf_bandwidth', 3000000),
                                  ('in_voltage0_hardwaregain', 20),
                                  ('out_altvoltage0_RX_LO_frequency', 90000000),
                                  ('out_altvoltage1_TX_LO_powerdown', 1)]:
                self.assertEqual(rx.write(rx.phy+'/'+suffix, value), 'ok')
            count = write.call_count
            for suffix, value in [('in_voltage0_hardwaregain', 30),
                                  ('out_altvoltage1_TX_LO_powerdown', 0),
                                  ('out_altvoltage1_TX_LO_frequency', 90500000),
                                  ('in_voltage_sampling_frequency', '2500000; reboot')]:
                with self.assertRaises(ValueError):
                    rx.write(rx.phy+'/'+suffix, value)
            self.assertEqual(count, write.call_count)
        with self.assertRaises(ValueError):
            rx.upload('/tmp/file', b'123')
        for forbidden in ('network on', 'auto on', 'arm on', 'tmsend; reboot'):
            with self.assertRaises(ValueError):
                adda._command(forbidden)
        rx.close()
        adda.close()

    def test_unbound_probe_objects_cannot_control(self):
        rx = rf.SessionRxConsole('RX_PORT')
        adda = rf.SessionAdda('ADDA_PORT')
        with self.assertRaises(RuntimeError):
            rx.write(rx.phy+'/in_voltage0_hardwaregain', 20)
        with self.assertRaises(RuntimeError):
            adda.send()
        with self.assertRaises(ValueError):
            adda._command('tmsend')
        rx.close()
        adda.close()


class ProtocolTests(unittest.TestCase):
    def test_tmstatus_missing_duplicate_failure_and_range_are_rejected(self):
        for lines in (TX_STATUS[:1], TX_STATUS+TX_STATUS,
                      [TX_STATUS[0], TX_STATUS[1].replace('rc=0', 'rc=-1')],
                      [TX_STATUS[0].replace('seq=18', 'seq=4294967296'), TX_STATUS[1]]):
            with self.subTest(lines=lines), self.assertRaises(RuntimeError):
                rf._tmstatus(lines)

    def exchange(self, response):
        adda = rf.SessionAdda.__new__(rf.SessionAdda)
        adda._closed = False
        adda._writable = True
        adda.record = Mock()
        adda.port = Mock()
        data = bytearray(response)
        adda.port.in_waiting = 3
        def read(size):
            result = bytes(data[:3])
            del data[:3]
            return result
        adda.port.read.side_effect = read
        adda.port.write.side_effect = len
        return adda

    def test_controls_wait_for_fragmented_success_ack_and_fail_without_one(self):
        adda = self.exchange(b'tmsend\r\nCLI_RESULT rc=0\r\n')
        self.assertEqual(adda.send()[-1], 'CLI_RESULT rc=0')
        self.assertGreater(adda.port.read.call_count, 1)
        self.assertEqual(adda.port.write.call_args.args, (b'tmsend\r\n',))
        adda = self.exchange(b'CLI_RESULT rc=-2\r\n')
        with self.assertRaises(RuntimeError):
            adda.send()
        adda = self.exchange(b'partial response')
        with patch.object(rf.time, 'monotonic', side_effect=range(10)):
            with self.assertRaises(RuntimeError):
                adda.stop()

    def test_common_telemetry_still_rejects_control_before_uart_access(self):
        ordinary = TelemetrySerial.__new__(TelemetrySerial)
        for command in ('tmstatus', 'tmsend', 'tmclear', 'tmstop', 'network on'):
            with self.assertRaises(ValueError):
                ordinary._command(command)


if __name__ == '__main__':
    unittest.main()
