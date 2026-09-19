"""Run the actual descriptor-ownership helper on minimum supported host Python."""
import fcntl
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
