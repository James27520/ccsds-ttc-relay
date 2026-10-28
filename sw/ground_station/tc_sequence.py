"""Cross-process leases for the 8-bit TC air sequence, independent of radios.

next_available() is a hint, never a reservation. reserve() must succeed before
RF starts. A process crash keeps its lease for 600 seconds. Invalid state is an
error rather than an empty registry. Times are persisted as Unix wall-clock time.
The persistent cursor rotates hints beyond the last reserved value even after
leases expire. Version 1 registries migrate on the next successful reservation.
"""
from contextlib import contextmanager
import errno
import json
import math
import os
from pathlib import Path
import tempfile
import threading
import time

if os.name == 'nt':
    import msvcrt
else:
    import fcntl


LEASE_SECONDS = 600
_THREAD_LOCKS = {}
_THREAD_LOCKS_GUARD = threading.Lock()
_SEQUENCE_KEYS = frozenset(str(seq) for seq in range(256))


class SequenceStateError(ValueError):
    """The registry cannot safely establish which sequence numbers are free."""


class SequencePool:
    def __init__(self, path=None, *, clock=None):
        self.path = (Path(path) if path is not None else
                     Path.home()/'CCSDSGroundStation'/'tc_sequences.json').resolve()
        self.lock_path = self.path.with_name(self.path.name+'.lock')
        self.clock = clock or time.time
        key = os.path.normcase(str(self.path))
        with _THREAD_LOCKS_GUARD:
            self._thread_lock = _THREAD_LOCKS.setdefault(key, threading.RLock())

    @contextmanager
    def _locked(self):
        # The thread lock also handles platforms whose byte locks are per process.
        if not self._thread_lock.acquire(timeout=5):
            raise TimeoutError('测控序号注册表正在使用，请稍后重试')
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.lock_path.open('a+b') as handle:
                handle.seek(0, os.SEEK_END)
                if handle.tell() == 0:
                    handle.write(b'\0')
                    handle.flush()
                deadline = time.monotonic()+5
                while True:
                    try:
                        if os.name == 'nt':
                            handle.seek(0)
                            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                        else:
                            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except OSError as error:
                        if error.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                            raise
                        if time.monotonic() >= deadline:
                            raise TimeoutError('测控序号注册表文件锁等待超时') from error
                        time.sleep(.02)
                try:
                    yield
                finally:
                    if os.name == 'nt':
                        handle.seek(0)
                        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            self._thread_lock.release()

    @staticmethod
    def _number(value):
        try:
            return type(value) in (int, float) and math.isfinite(value) and value >= 0
        except (OverflowError, TypeError):
            return False

    @staticmethod
    def _unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise SequenceStateError('测控序号注册表包含重复字段，不能自动重置或发送')
            result[key] = value
        return result

    def _now(self):
        value = self.clock()
        if not self._number(value) or not math.isfinite(value+LEASE_SECONDS) or value+LEASE_SECONDS <= value:
            raise SequenceStateError('测控序号租约时钟无效')
        return value

    def _read(self):
        try:
            raw = self.path.read_text(encoding='utf-8')
        except FileNotFoundError:
            return {}, 0
        except UnicodeError as error:
            raise SequenceStateError('测控序号注册表编码损坏，不能自动重置或发送') from error
        try:
            data = json.loads(raw, object_pairs_hook=self._unique_object)
        except (ValueError, UnicodeError) as error:
            raise SequenceStateError('测控序号注册表损坏，不能自动重置或发送') from error
        if (type(data) is not dict or type(data.get('version')) is not int or
                data['version'] not in (1, 2) or type(data.get('leases')) is not dict or
                set(data) != ({'version', 'leases'} if data['version'] == 1 else {'version', 'cursor', 'leases'})):
            raise SequenceStateError('测控序号注册表格式无效，不能自动重置或发送')
        leases = data['leases']
        for key, lease in leases.items():
            if (key not in _SEQUENCE_KEYS or type(lease) is not dict or
                    set(lease) != {'reserved_at', 'expires_at'} or
                    not self._number(lease['reserved_at']) or not self._number(lease['expires_at']) or
                    lease['expires_at']-lease['reserved_at'] < LEASE_SECONDS):
                raise SequenceStateError('测控序号注册表租约无效，不能自动重置或发送')
        if data['version'] == 1:
            # Include expired leases: their timestamps are the only v1 history.
            # Equal timestamps have no persisted order; break ties numerically.
            latest = max(leases, key=lambda key: (leases[key]['reserved_at'], int(key))) if leases else None
            cursor = (int(latest)+1) % 256 if latest is not None else 0
        else:
            cursor = data['cursor']
            if type(cursor) is not int or not 0 <= cursor <= 255:
                raise SequenceStateError('测控序号注册表游标无效，不能自动重置或发送')
        return leases, cursor

    def _write(self, leases, cursor):
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=self.path.parent,
                                             prefix='.'+self.path.name+'.', suffix='.tmp', delete=False) as handle:
                temporary = Path(handle.name)
                json.dump(dict(version=2, cursor=cursor, leases=leases), handle,
                          ensure_ascii=False, sort_keys=True, allow_nan=False)
                handle.write('\n')
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()

    def next_available(self):
        """Hint from the persisted rotation cursor; raise ValueError if all leased."""
        with self._locked():
            now = self._now()
            leases, cursor = self._read()
            for offset in range(256):
                sequence = (cursor+offset) % 256
                lease = leases.get(str(sequence))
                if lease is None or lease['expires_at'] <= now:
                    return sequence
        raise ValueError('0–255 测控序号仍在租约内，请等待租约到期后重新建会话')

    def reserve(self, seq):
        """Atomically reserve exactly this sequence for 600 seconds; never swap it."""
        sequence = seq
        if type(sequence) is not int or not 0 <= sequence <= 255:
            raise ValueError('测控序号必须为 0–255 整数')
        with self._locked():
            now = self._now()
            previous, _cursor = self._read()
            leases = {key: lease for key, lease in previous.items() if lease['expires_at'] > now}
            if str(sequence) in leases:
                raise ValueError(f'测控序号 {sequence} 已被预留，请重新连接后生成新指令')
            leases[str(sequence)] = dict(reserved_at=now, expires_at=now+LEASE_SECONDS)
            self._write(leases, (sequence+1) % 256)
