"""Temporary-directory lease tests; never use the real user's sequence registry."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from .tc_sequence import LEASE_SECONDS, SequencePool, SequenceStateError


class SequencePoolTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name)/'leases.json'
        self.now = 1000.0
        self.pool = SequencePool(self.path, clock=lambda: self.now)

    def tearDown(self):
        self.directory.cleanup()

    def test_hint_does_not_reserve_and_lease_survives_new_pool(self):
        self.assertEqual(self.pool.next_available(), 0)
        self.assertEqual(self.pool.next_available(), 0)
        self.assertFalse(self.path.exists())
        self.pool.reserve(0)
        self.assertEqual(SequencePool(self.path, clock=lambda: self.now).next_available(), 1)
        state = json.loads(self.path.read_text(encoding='utf-8'))
        self.assertEqual(state['leases']['0'], dict(reserved_at=1000.0, expires_at=1600.0))
        with self.assertRaises(ValueError):
            self.pool.reserve(0)

    def test_expiry_is_at_least_600_seconds_and_expired_value_can_be_reused(self):
        self.pool.reserve(0)
        self.now += LEASE_SECONDS-.001
        self.assertEqual(self.pool.next_available(), 1)
        with self.assertRaises(ValueError):
            self.pool.reserve(0)
        self.now += .001
        self.assertEqual(self.pool.next_available(), 0)
        self.pool.reserve(0)
        self.assertGreaterEqual(json.loads(self.path.read_text())['leases']['0']['expires_at'], self.now+600)

    def test_exact_requested_sequence_is_reserved_without_substitution(self):
        self.pool.reserve(seq=9)
        self.assertEqual(self.pool.next_available(), 0)
        self.assertEqual(set(json.loads(self.path.read_text())['leases']), {'9'})
        for value in (-1, 256, True, 1.0, '2', None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.pool.reserve(value)

    def test_all_leased_raises_and_earliest_expired_is_chosen(self):
        leases = {str(seq): dict(reserved_at=1000, expires_at=1600) for seq in range(256)}
        self.path.write_text(json.dumps(dict(version=1, leases=leases)), encoding='utf-8')
        with self.assertRaises(ValueError):
            self.pool.next_available()
        leases['17'] = dict(reserved_at=0, expires_at=600)
        self.path.write_text(json.dumps(dict(version=1, leases=leases)), encoding='utf-8')
        self.assertEqual(self.pool.next_available(), 17)

    def test_corruption_never_silently_resets_or_overwrites_registry(self):
        values = ('', '{bad', '[]', 'null', '{}', '{"version":true,"leases":{}}',
                  '{"version":2,"leases":{}}', '{"version":1,"leases":[]}',
                  '{"version":1,"leases":{"0":{"reserved_at":1000,"expires_at":1100}}}',
                  '{"version":1,"leases":{"256":{"reserved_at":1000,"expires_at":1600}}}',
                  '{"version":1,"leases":{"0":{"reserved_at":true,"expires_at":1600}}}',
                  '{"version":1,"leases":{"0":{"reserved_at":1000,"expires_at":Infinity}}}',
                  '{"version":1,"leases":{},"leases":{}}')
        for raw in values:
            with self.subTest(raw=raw):
                self.path.write_text(raw, encoding='utf-8')
                with self.assertRaises(SequenceStateError):
                    self.pool.next_available()
                with self.assertRaises(SequenceStateError):
                    self.pool.reserve(0)
                self.assertEqual(self.path.read_text(encoding='utf-8'), raw)
        self.path.write_bytes(b'\xff\xfe')
        with self.assertRaises(SequenceStateError):
            self.pool.next_available()

    def test_invalid_clock_and_rollback_never_release_an_active_lease(self):
        self.pool.reserve(0)
        self.now = 500
        self.assertEqual(self.pool.next_available(), 1)
        for value in (float('nan'), float('inf'), -1, None, True, 10**1000):
            self.now = value
            with self.subTest(value=value), self.assertRaises(SequenceStateError):
                self.pool.reserve(1)

    def test_atomic_write_failure_preserves_existing_file_and_removes_temporary(self):
        self.pool.reserve(0)
        before = self.path.read_bytes()
        with patch('sw.ground_station.tc_sequence.os.replace', side_effect=OSError('fake replace failure')):
            with self.assertRaises(OSError):
                self.pool.reserve(1)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(list(self.path.parent.glob('*.tmp')), [])
        self.assertEqual(self.pool.next_available(), 1)

    def test_threads_cannot_lose_updates_or_reserve_same_sequence(self):
        def reserve(seq):
            try:
                SequencePool(self.path, clock=lambda: 1000).reserve(seq)
                return True
            except ValueError:
                return False
        with ThreadPoolExecutor(max_workers=8) as executor:
            self.assertEqual(sum(executor.map(reserve, [0]*8)), 1)
            self.assertTrue(all(executor.map(reserve, range(1, 9))))
        self.assertEqual(set(json.loads(self.path.read_text())['leases']), {str(i) for i in range(9)})

    def test_process_file_lock_serializes_reservations(self):
        code = ('import sys\nfrom sw.ground_station.tc_sequence import SequencePool\n'
                'try:\n SequencePool(sys.argv[1],clock=lambda:1000).reserve(int(sys.argv[2]))\n'
                'except ValueError:\n sys.exit(3)\n')
        processes = []
        try:
            for seq in (7, 7, 8, 9):
                processes.append(subprocess.Popen([sys.executable, '-c', code, str(self.path), str(seq)],
                                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True))
            codes = []
            for process in processes:
                stdout, stderr = process.communicate(timeout=15)
                self.assertFalse(stderr, stderr)
                codes.append(process.returncode)
            self.assertEqual(sorted(codes), [0, 0, 0, 3])
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill()
                    process.communicate()
        self.assertEqual(set(json.loads(self.path.read_text())['leases']), {'7', '8', '9'})

    def test_default_path_is_user_scoped_and_constructor_performs_no_registration(self):
        with patch('sw.ground_station.tc_sequence.Path.home', return_value=Path(self.directory.name)):
            pool = SequencePool(clock=lambda: 1000)
        self.assertEqual(pool.path, Path(self.directory.name)/'CCSDSGroundStation'/'tc_sequences.json')
        self.assertFalse(pool.path.exists())
        self.assertFalse(pool.lock_path.exists())


if __name__ == '__main__':
    unittest.main()
