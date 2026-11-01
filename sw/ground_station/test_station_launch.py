"""Two-computer deployment: role isolation, portable ports and fail-closed preflight."""
import importlib
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from .ui_v2 import main
from .ui_v2_model import device_choices
from .station_environment import inspect_environment


class ComputerLaunchTests(unittest.TestCase):
    def test_profiles_open_only_local_terminal_and_never_connect(self):
        for computer, role, control in (('1', 'sender', True), ('2', 'receiver', False)):
            with self.subTest(computer=computer), patch('sw.ground_station.ui_v2.tk.Tk'), \
                 patch('sw.ground_station.ui_v2.ReviewSession') as session:
                main(['--computer', computer])
                self.assertTrue(session.call_args.kwargs['online_business'])
                self.assertIs(session.call_args.kwargs['online_control'], control)
                session.return_value.show.assert_called_once_with(role)
                session.return_value.terminal_controller.assert_not_called()

    def test_computer_preview_has_no_online_controllers(self):
        with patch('sw.ground_station.ui_v2.tk.Tk'), patch('sw.ground_station.ui_v2.ReviewSession') as session:
            main(['--computer', '2', '--preview'])
            self.assertFalse(session.call_args.kwargs['online_business'])
            self.assertFalse(session.call_args.kwargs['online_control'])

    def test_computer2_cannot_be_combined_with_remote_control(self):
        with patch('sw.ground_station.ui_v2.tk.Tk') as tk, self.assertRaises(SystemExit):
            main(['--computer', '2', '--online-control'])
        tk.assert_not_called()

    def test_fresh_pc_lists_new_com_and_serial_without_old_alias(self):
        port = dict(port='COM73', description='USB Serial Port', vid=1027, pid=24592, serial='000000000069B')
        devices = device_choices([port], [])
        name, found = next(iter(devices.items()))
        self.assertIn('COM73', name)
        self.assertIn('000000000069B', name)
        self.assertIsNone(found['role'])
        # An old PC's port-pinned label cannot invent a matching role on COM73.
        old = dict(port, port='COM17', role='receiver')
        self.assertIsNone(next(iter(device_choices([port], [old]).values()))['role'])


class EnvironmentTests(unittest.TestCase):
    def test_preflight_checks_shipped_binary_without_opening_usb(self):
        port = SimpleNamespace(device='COM73', description='fixture', vid=1027, pid=24592,
                               serial_number='000000000069B')
        with patch('serial.Serial', side_effect=AssertionError('must not open hardware')), \
             patch('serial.tools.list_ports.comports', return_value=[port]), \
             patch('tkinter.Tk'), patch.dict('os.environ', {}, clear=False):
            report = inspect_environment()
        self.assertTrue(report['passed'], report['errors'])
        self.assertGreater(report['receiver_binary_bytes'], 0)
        self.assertFalse(report['serial_ports_opened'])
        self.assertEqual(report['usb_ports'][0]['port'], 'COM73')

    def test_no_board_does_not_fail_software_installation(self):
        with patch('serial.tools.list_ports.comports', return_value=[]), patch('tkinter.Tk'):
            report = inspect_environment()
        self.assertTrue(report['passed'], report['errors'])
        self.assertEqual(report['usb_ports'], [])

    def test_corrupt_or_missing_binary_prevents_launch(self):
        with patch('sw.ground_station.terminal_radio.TerminalRadio.receiver_binary', side_effect=ValueError('checksum')), \
             patch('serial.tools.list_ports.comports', return_value=[]), patch('tkinter.Tk'):
            report = inspect_environment()
        self.assertFalse(report['passed'])
        self.assertTrue(any('checksum' in e for e in report['errors']))

    def test_missing_dependency_is_reported_without_probing_board(self):
        original = importlib.import_module
        def missing(name):
            if name == 'numpy':
                raise ImportError('numpy fixture')
            return original(name)
        with patch('sw.ground_station.station_environment.importlib.import_module', side_effect=missing), \
             patch('serial.tools.list_ports.comports') as ports:
            report = inspect_environment()
        self.assertFalse(report['passed'])
        self.assertIn('numpy fixture', report['errors'][0])
        ports.assert_not_called()


if __name__ == '__main__':
    unittest.main()
