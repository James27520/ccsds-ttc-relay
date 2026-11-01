"""Cold console startup, login and bootloader cases; no real serial devices."""
import unittest
from unittest.mock import Mock, patch

from .transport import Console


class LoginPort:
    def __init__(self, initial=b'', replies=None):
        self.buffer = bytearray(initial)
        self.replies = replies or {}
        self.writes = []
        self.clock = 0.

    @property
    def in_waiting(self):
        return min(3, len(self.buffer))

    def read(self, size):
        self.clock += .01
        result = bytes(self.buffer[:size])
        del self.buffer[:size]
        return result

    def write(self, data):
        self.writes.append(data)
        self.buffer += self.replies.get(data, b'')
        return len(data)


class ConsoleLoginTests(unittest.TestCase):
    def prepare(self, port, timeout=5):
        console = Console.__new__(Console)
        console.port, console.record = port, Mock()
        with patch('sw.ground_station.transport.time.monotonic', side_effect=lambda: port.clock):
            console.prepare_shell(timeout)
        # No credential, output, or arbitrary shell command is logged.
        self.assertEqual(set(console.record.call_args.kwargs), {'kind', 'login_performed'})
        return console

    def test_existing_root_shell_and_idle_shell(self):
        for prompt in (b'# ', b'root@pluto:~# ', b'/ # '):
            p = LoginPort(prompt)
            self.prepare(p)
            self.assertEqual(p.writes, [])
        p = LoginPort(replies={b'\n': b'\r\n# '})
        self.prepare(p)
        self.assertEqual(p.writes, [b'\n'])

    def test_factory_password_and_passwordless_login(self):
        for password in (True, False):
            p = LoginPort(b'Welcome to Pluto\r\npluto login: ', {
                b'root\n': b'root\r\nPassword: ' if password else b'root\r\n# ',
                b'analog\n': b'\r\nWelcome to:\r\n# '})
            self.prepare(p)
            self.assertEqual(p.writes, [b'root\n', b'analog\n'] if password else [b'root\n'])

    def test_previous_bad_username_is_cancelled_before_login(self):
        p = LoginPort(b'Password: ', {b'\x03\n': b'\r\npluto login: ',
            b'root\n': b'\r\nPassword: ', b'analog\n': b'\r\n# '})
        self.prepare(p)
        self.assertEqual(p.writes, [b'\x03\n', b'root\n', b'analog\n'])

    def test_bootloader_never_receives_linux_commands(self):
        p = LoginPort(b'Bad Data CRC\r\nPluto> ')
        with self.assertRaisesRegex(RuntimeError, 'U-Boot'):
            self.prepare(p)
        self.assertEqual(p.writes, [])

    def test_boot_output_is_waited_for_without_aborting_boot(self):
        p = LoginPort(b'Linux version 5.15 #7 SMP\r\nStarting kernel ...\r\npluto login: ',
                      {b'root\n': b'\r\n# '})
        self.prepare(p)
        self.assertEqual(p.writes, [b'root\n'])

    def test_nondefault_password_is_not_retried(self):
        p = LoginPort(b'pluto login: ', {b'root\n': b'\r\nPassword: ',
            b'analog\n': b'\r\nLogin incorrect\r\npluto login: '})
        with self.assertRaisesRegex(RuntimeError, '登录'):
            self.prepare(p)
        self.assertEqual(p.writes, [b'root\n', b'analog\n'])
        p = LoginPort(b'other login: ', {b'root\n': b'\r\nPassword: '})
        with self.assertRaisesRegex(RuntimeError, '非默认登录'):
            self.prepare(p)
        self.assertEqual(p.writes, [b'root\n'])

    def test_no_response_has_bounded_timeout_and_one_newline(self):
        p = LoginPort()
        with self.assertRaisesRegex(TimeoutError, 'Linux'):
            self.prepare(p, timeout=1)
        self.assertEqual(p.writes, [b'\n'])


if __name__ == '__main__':
    unittest.main()
