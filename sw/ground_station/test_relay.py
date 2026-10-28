"""LDSDR diagnostic and fault tests using synthetic UART responses only."""
import unittest
from unittest.mock import Mock, patch

from .relay import RelayConsole


GOOD_DIAGNOSTICS = '\n'.join([
    'RFREAD rx_rc=0 tx_rc=0 rx_hz=900000000 tx_hz=1000000000',
    'RFPORT1 addr=0x010 rc=0 raw=0x88',
    'RFATT tx1_mdB_rc=0 value=89000 tx2_mdB_rc=0 value=89000',
    'RFGAIN rx1_db_rc=0 value=30 rx2_db_rc=0 value=30',
    'RFPLL_RX addr=0x247 rc=0 raw=0x02 locked=1',
    'RFPLL_TX addr=0x287 rc=0 raw=0x02 locked=1',
    'RFBIST addr=0x3F4 rc=0 raw=0x00',
    'RFLOOP addr=0x3F5 rc=0 raw=0x00',
    'RFPORT_TEST addr=0x3F6 rc=0 raw=0x00',
    'RFDAC_TEST addr=0x3F7 rc=0 raw=0x00',
    'RFDIAG_END rc=0 ready=1 init_rc=0 spi_errors_total=0',
])
GOOD_STATUS = ('STAT mode=2 fs=30720000 ddc=00000000 duc=00000000 '
               'gain=800 dc=0 rc=0 txatt=89 rxgain=0 clip=0')


def relay_without_serial(response=''):
    relay = RelayConsole.__new__(RelayConsole)
    relay.record = Mock()
    relay.run = Mock(return_value=response)
    return relay


class RelayDiagnosticsTests(unittest.TestCase):
    def test_exact_good_diagnostics_return_actual_readbacks(self):
        relay = relay_without_serial(GOOD_DIAGNOSTICS)
        result = relay.diagnostics()
        self.assertEqual(result, dict(relay_rx_hz_readback=900000000,
                                      relay_tx_hz_readback=1000000000,
                                      relay_tx_atten_db_readback=89,
                                      relay_rx_gain_db_readback=30))

    def test_numeric_prefixes_do_not_establish_matching_readback(self):
        for old, new in [('value=30', 'value=300'), ('value=89000', 'value=890000'),
                         ('spi_errors_total=0', 'spi_errors_total=01'),
                         ('locked=1', 'locked=10')]:
            with self.subTest(new=new), self.assertRaises(RuntimeError):
                relay_without_serial(GOOD_DIAGNOSTICS.replace(old, new)).diagnostics()

    def test_unlock_frequency_test_sources_and_old_firmware_rejected(self):
        damaged = [GOOD_DIAGNOSTICS.replace('locked=1', 'locked=0'),
                   GOOD_DIAGNOSTICS.replace('rx_hz=900000000', 'rx_hz=900000011'),
                   GOOD_DIAGNOSTICS.replace('tx_hz=1000000000', 'tx_hz=1000000011'),
                   GOOD_DIAGNOSTICS.replace('RFPORT1 addr=0x010 rc=0 raw=0x88',
                                            'RFPORT1 addr=0x010 rc=0 raw=0x40'),
                   GOOD_DIAGNOSTICS.replace('RFPORT_TEST addr=0x3F6 rc=0 raw=0x00', ''),
                   GOOD_DIAGNOSTICS.replace('init_rc=0', 'init_rc=-1'),
                   GOOD_DIAGNOSTICS + '\nRFREAD rx_rc=0 tx_rc=0 rx_hz=900000000 tx_hz=1000000000']
        for source in ['RFBIST', 'RFLOOP', 'RFPORT_TEST', 'RFDAC_TEST']:
            damaged.append(GOOD_DIAGNOSTICS.replace(source + ' addr=', source + ' bad_addr='))
            rows = GOOD_DIAGNOSTICS.splitlines()
            damaged.append('\n'.join(row.replace('raw=0x00', 'raw=0x01')
                                     if row.startswith(source + ' ') else row for row in rows))
        for index, response in enumerate(damaged):
            with self.subTest(index=index), self.assertRaises(RuntimeError):
                relay_without_serial(response).diagnostics()

    def test_muting_diagnostics_can_skip_frequency_but_still_check_attenuation(self):
        response = GOOD_DIAGNOSTICS.replace('rx_hz=900000000', 'rx_hz=123000000')
        response = response.replace('value=30', 'value=0')
        result = relay_without_serial(response).diagnostics(atten=89, gain=0, exact_frequency=False)
        self.assertEqual(result['relay_rx_hz_readback'], 123000000)
        with self.assertRaises(RuntimeError):
            relay_without_serial(response.replace('value=89000', 'value=50000')).diagnostics(
                atten=89, gain=0, exact_frequency=False)

    def test_status_requires_one_complete_compatible_baseline(self):
        self.assertEqual(relay_without_serial(GOOD_STATUS).status()['mode'], '2')
        for response in [GOOD_STATUS.replace('fs=30720000', 'fs=10000000'),
                         GOOD_STATUS.replace('gain=800', 'gain=8000'),
                         GOOD_STATUS.replace(' clip=0', ''),
                         GOOD_STATUS + '\n' + GOOD_STATUS, 'unrelated firmware prompt']:
            with self.subTest(response=response), self.assertRaises(RuntimeError):
                relay_without_serial(response).status()

    def test_mute_attempts_all_commands_and_readbacks_after_first_failure(self):
        relay = relay_without_serial()
        relay.run.side_effect = [RuntimeError('mode command failed'), 'OK', 'OK']
        relay.status = Mock(return_value={'mode': '2'})
        relay.diagnostics = Mock(return_value={'relay_tx_atten_db_readback': 89})
        with self.assertRaisesRegex(RuntimeError, 'mode command failed'):
            relay.mute()
        self.assertEqual([call.args[0] for call in relay.run.call_args_list],
                         ['mode 2', 'txatt 89', 'rxgain 0'])
        relay.status.assert_called_once()
        relay.diagnostics.assert_called_once_with(atten=89, gain=0, exact_frequency=False)


class RelayRunTests(unittest.TestCase):
    def fake_port(self, response, short_write=False):
        clock = [0.]
        remaining = bytearray(response)
        port = Mock()
        port.in_waiting = 8192
        port.write.side_effect = lambda value: 1 if short_write else len(value)
        def read(size):
            clock[0] += .001
            result = bytes(remaining[:size])
            del remaining[:size]
            return result
        port.read.side_effect = read
        return port, clock

    def run_response(self, response, short_write=False):
        relay = RelayConsole.__new__(RelayConsole)
        relay.record = Mock()
        relay.port, clock = self.fake_port(response, short_write)
        with patch('sw.ground_station.relay.time.monotonic', side_effect=lambda: clock[0]):
            return relay.run('status')

    def test_empty_error_short_write_and_response_limit_rejected(self):
        for response, short_write in [(b'', False), (b'ERR invalid command', False),
                                      (b'OK', True), (b'x' * 65537, False)]:
            with self.subTest(size=len(response), short_write=short_write), self.assertRaises(RuntimeError):
                self.run_response(response, short_write)


if __name__ == '__main__':
    unittest.main()
