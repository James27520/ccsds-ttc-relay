"""Process-lifetime locks for one local serial port; no hardware access."""
import hashlib
import os
from pathlib import Path
import threading

_guard = threading.Lock()
_held = set()


class PortLease:
    def __init__(self, port, directory=None):
        if not isinstance(port, str) or not port.strip():
            raise ValueError('设备端口为空')
        self.key = port.strip().upper()
        self.handle = None
        root = Path(directory) if directory else Path.home()/'CCSDSGroundStation'/'locks'
        root.mkdir(parents=True, exist_ok=True)
        path = root/(hashlib.sha256(self.key.encode()).hexdigest()+'.lock')
        self.registry_key = str(path.resolve())
        with _guard:
            if self.registry_key in _held:
                raise RuntimeError('设备正被另一个窗口使用，请先断开该窗口')
            _held.add(self.registry_key)
        try:
            self.handle = path.open('a+b')
            self.handle.seek(0, 2)
            if not self.handle.tell():
                self.handle.write(b'0'); self.handle.flush()
            self.handle.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BaseException as exc:
            self.close()
            raise RuntimeError('设备正被其他进程使用或无法取得端口锁') from exc

    def close(self):
        if self.handle is not None:
            self.handle.close()  # Closing the descriptor releases the OS lock.
            self.handle = None
        with _guard:
            _held.discard(self.registry_key)
