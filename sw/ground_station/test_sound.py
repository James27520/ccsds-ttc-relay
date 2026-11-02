import os
import threading
import unittest
from unittest.mock import MagicMock, patch

from .sound import CUES, Notifier


class NotifierTests(unittest.TestCase):
    def test_cue_speaks_chinese_announcement(self):
        spoken = []
        notifier = Notifier(enabled=True, speaker=spoken.append, player=lambda _a: None)
        self.assertTrue(notifier.play('connected'))
        self.assertEqual(spoken, [CUES['connected'][0]])

    def test_same_cue_is_announced_only_once_per_cooldown(self):
        now = [0.0]
        spoken = []
        notifier = Notifier(enabled=True, speaker=spoken.append, player=lambda _a: None,
                            clock=lambda: now[0])
        self.assertTrue(notifier.play('received'))
        self.assertFalse(notifier.play('received'))
        now[0] = 9.0
        self.assertTrue(notifier.play('received'))
        self.assertEqual(spoken, ['收到新文本', '收到新文本'])

    def test_different_cues_are_independent(self):
        spoken = []
        notifier = Notifier(enabled=True, speaker=spoken.append, player=lambda _a: None,
                            clock=lambda: 0.0)
        self.assertTrue(notifier.play('connected'))
        self.assertTrue(notifier.play('sent'))
        self.assertEqual(spoken, ['连接成功', '发送成功'])

    def test_disabled_stays_silent(self):
        spoken = []
        notifier = Notifier(enabled=False, speaker=spoken.append, player=lambda _a: None)
        self.assertFalse(notifier.play('sent'))
        self.assertEqual(spoken, [])
        self.assertTrue(notifier.set_enabled(True))
        self.assertTrue(notifier.play('sent'))

    def test_unknown_cue_is_ignored(self):
        spoken = []
        notifier = Notifier(enabled=True, speaker=spoken.append, player=lambda _a: None)
        self.assertFalse(notifier.play('not-a-step'))
        self.assertEqual(spoken, [])

    def test_speech_failure_falls_back_to_system_sound(self):
        played = []

        def boom(_text):
            raise RuntimeError('no speech engine')

        notifier = Notifier(enabled=True, speaker=boom, player=played.append)
        self.assertTrue(notifier.play('error'))
        self.assertEqual(played, [CUES['error'][1]])

    @unittest.skipUnless(os.name == 'nt', 'Windows voice helper')
    def test_muting_interrupts_speech_and_drops_waiting_cues(self):
        started, release, closed = threading.Event(), threading.Event(), threading.Event()
        proc = MagicMock()
        proc.poll.return_value = None
        def acknowledge():
            started.set()
            release.wait(5)
            return 'FALLBACK\n'
        proc.stdout.readline.side_effect = acknowledge
        proc.kill.side_effect = release.set
        proc.__exit__.side_effect = lambda *_: closed.set()
        beeps = []
        with patch('subprocess.Popen', return_value=proc):
            notifier = Notifier(enabled=True, player=beeps.append)
            try:
                self.assertTrue(notifier.play('connected'))
                self.assertTrue(started.wait(3))
                self.assertTrue(notifier.play('received'))
                notifier.set_enabled(False)
                self.assertTrue(closed.wait(3))
                self.assertEqual(proc.stdin.write.call_count, 1)
                self.assertEqual(beeps, [])
            finally:
                release.set()
                notifier.close()

    @unittest.skipUnless(os.name == 'nt', 'Windows voice helper')
    def test_unavailable_voice_response_uses_the_cue_alias(self):
        proc = MagicMock()
        proc.poll.return_value = None
        proc.stdout.readline.return_value = 'FALLBACK\n'
        played, done = [], threading.Event()
        def beep(alias):
            played.append(alias)
            done.set()
        with patch('subprocess.Popen', return_value=proc):
            notifier = Notifier(enabled=True, player=beep)
            try:
                self.assertTrue(notifier.play('received'))
                self.assertTrue(done.wait(3))
                self.assertEqual(played, [CUES['received'][1]])
            finally:
                notifier.close()


if __name__ == '__main__':
    unittest.main()
