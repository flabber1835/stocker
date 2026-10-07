"""Run the actual descriptor-ownership helper on minimum supported host Python."""
import fcntl
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
import sentinel_backup_lock as backup
import sentinel_go_lock as go


class LockOwnershipCompatibility(unittest.TestCase):
    def test_backup_wait_admission_on_minimum_host_python(self):
        with patch.object(backup, '_hold', return_value=0) as hold:
            self.assertEqual(backup.main(['hold', '--wait-seconds', '3660', 'fixture']), 0)
            hold.assert_called_once_with(['fixture'], wait_seconds=3660, standby_if_busy=False)
        for wait in ('-1', '3661', '1.5', '\u0661', '9' * 100):
            with self.subTest(wait=wait), patch.object(backup, '_hold') as hold:
                self.assertEqual(backup.main(['hold', '--wait-seconds', wait, 'fixture']), 2)
                hold.assert_not_called()

    def test_backup_standby_admission_on_minimum_host_python(self):
        with patch.object(backup, '_hold', return_value=0) as hold:
            self.assertEqual(backup.main(['hold', '--standby-if-busy', 'fixture']), 0)
            hold.assert_called_once_with(['fixture'], wait_seconds=0, standby_if_busy=True)

    def test_linux310_procfs_with_real_flocks(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'lock'
            with path.open('a+') as owner, path.open('a+') as other:
                with patch.object(backup, '_lock_path', return_value=path), patch.object(go, 'LOCK', path):
                    with patch.object(Path, 'open', return_value=io.BytesIO()) as proc:
                        proc.side_effect = lambda *a, **k: io.BytesIO(b'pos: 0\nflags: 02500002\n')
                        for module, verify in ((backup, backup.lock_is_held), (go, go.lifecycle_lock_is_held)):
                            values = {module.LOCK_HELD_ENV: '1', module.LOCK_FD_ENV: str(owner.fileno())}
                            self.assertFalse(verify(values))
                            fcntl.flock(owner, fcntl.LOCK_SH)
                            self.assertFalse(verify(values))
                            fcntl.flock(owner, fcntl.LOCK_EX)
                            self.assertTrue(verify(values))
                            values[module.LOCK_FD_ENV] = str(other.fileno())
                            self.assertFalse(verify(values))
                            with self.assertRaises(BlockingIOError):
                                fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
                            fcntl.flock(owner, fcntl.LOCK_UN)

    def test_both_verifiers_accept_only_the_actual_exclusive_description(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'lock'
            with path.open('a+') as owner, path.open('a+') as other:
                fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with patch.object(backup, '_lock_path', return_value=path), patch.object(go, 'LOCK', path):
                    for module, verify in ((backup, backup.lock_is_held), (go, go.lifecycle_lock_is_held)):
                        values = {module.LOCK_HELD_ENV: '1', module.LOCK_FD_ENV: str(owner.fileno())}
                        self.assertTrue(verify(values))
                        values[module.LOCK_FD_ENV] = str(other.fileno())
                        self.assertFalse(verify(values))
                with self.assertRaises(BlockingIOError):
                    fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def test_duplicate_survives_original_descriptor_close(self):
        from sentinel_lock_ownership import owns_exclusive_flock
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'lock'
            with path.open('a+') as owner:
                fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
                duplicate = os.dup(owner.fileno())
            try:
                self.assertTrue(owns_exclusive_flock(duplicate))
                fcntl.flock(duplicate, fcntl.LOCK_UN)
                self.assertFalse(owns_exclusive_flock(duplicate))
            finally:
                os.close(duplicate)


if __name__ == '__main__':
    unittest.main()
