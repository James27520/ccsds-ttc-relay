"""Chinese voice announcements for key terminal steps.

Speech runs in a separate ``announce.ps1`` helper process (Windows SAPI), so the
Tk event loop never blocks and no Python speech package is required.  Every cue
is announced at most once per cooldown window, which keeps repeated events such
as a burst of received texts from talking over each other.  When speech is not
available the original system sound is used instead, and any failure is silent.
"""
from __future__ import annotations

import atexit
import base64
import os
from pathlib import Path
from queue import Empty, Full, Queue
import subprocess
import threading
import time

try:  # pragma: no cover - platform dependent import
    import winsound
except Exception:  # pragma: no cover - non-Windows or restricted runtime
    winsound = None

# cue -> (Chinese announcement, Windows system sound used as fallback)
CUES = {
    'connected': ('连接成功', 'SystemAsterisk'),
    'disconnected': ('已断开连接', 'SystemExit'),
    'sent': ('发送成功', 'SystemDefault'),
    'received': ('收到新文本', 'SystemNotification'),
    'error': ('连接异常', 'SystemHand'),
}

# A burst of received texts must not restart the sentence every frame.
COOLDOWN = {
    'connected': 4.0,
    'disconnected': 3.0,
    'sent': 3.0,
    'received': 8.0,
    'error': 6.0,
}


class Notifier:
    """Announces one short cue per step; swallowing failures by design."""

    def __init__(self, enabled=None, speaker=None, player=None, cooldown=None, clock=time.monotonic):
        if enabled is None:
            enabled = os.environ.get('CCSDS_STATION_SOUND', '1') != '0'
        self.enabled = bool(enabled)
        self.last_cue = None
        self._speaker = speaker
        self._player = player
        self._cooldown = dict(COOLDOWN, **(cooldown or {}))
        self._clock = clock
        self._last = {}
        self._proc = None
        self._jobs = None
        self._lock = threading.Lock()

    def set_enabled(self, value):
        self.enabled = bool(value)
        if not self.enabled:
            self.close()
        return self.enabled

    def play(self, cue):
        """Return True when a cue is accepted for playback."""
        entry = CUES.get(cue)
        if entry is None or not self.enabled:
            self.last_cue = cue if entry else self.last_cue
            return False
        text, alias = entry
        now = self._clock()
        with self._lock:
            if now - self._last.get(cue, float('-inf')) < self._cooldown.get(cue, 0.0):
                return False
            self._last[cue] = now
        self.last_cue = cue
        if self._speaker is not None:
            try:
                if self._speaker(text) is not False:
                    return True
            except Exception:
                pass
            return self._beep(alias)
        if os.name != 'nt':
            return self._beep(alias)
        with self._lock:
            if self._jobs is None:
                self._jobs = Queue(maxsize=len(CUES))
                threading.Thread(target=self._run, args=(self._jobs,), daemon=True,
                                 name='terminal-voice').start()
                atexit.register(self.close)
            try:
                self._jobs.put_nowait((text, alias))
            except Full:
                return False
        return True

    def close(self):
        with self._lock:
            jobs, self._jobs = self._jobs, None
            if jobs is None:
                return
            atexit.unregister(self.close)
            while True:
                try:
                    jobs.get_nowait()
                except Empty:
                    break
            jobs.put_nowait(None)
            if self._proc is not None:
                try:
                    self._proc.kill()
                except OSError:
                    pass
                self._proc = None

    def _run(self, jobs):
        script = Path(__file__).with_name('announce.ps1')
        try:
            proc = subprocess.Popen(
                ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(script)],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                encoding='ascii', creationflags=subprocess.CREATE_NO_WINDOW)
        except OSError:
            proc = None
        try:
            with self._lock:
                if jobs is not self._jobs:
                    return
                self._proc = proc
            for text, alias in iter(jobs.get, None):
                if proc is not None and proc.poll() is None:
                    try:
                        proc.stdin.write(base64.b64encode(text.encode('utf-8')).decode('ascii')+'\n')
                        proc.stdin.flush()
                        if proc.stdout.readline().strip() == 'OK':
                            continue
                    except OSError:
                        pass
                with self._lock:
                    if jobs is self._jobs:
                        self._beep(alias)
        finally:
            if proc is not None:
                with proc:
                    if proc.poll() is None:
                        proc.kill()

    # -- fallback sound ---------------------------------------------------
    def _beep(self, alias):
        try:
            player = self._player
            if player is not None:
                player(alias)
                return True
            if winsound is None:
                return False
            winsound.PlaySound(alias, winsound.SND_ALIAS | winsound.SND_ASYNC)
            return True
        except Exception:
            return False
