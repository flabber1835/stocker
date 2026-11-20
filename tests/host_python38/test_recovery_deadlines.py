"""Actual host minimum-runtime compatibility for recovery deadline wiring."""
from pathlib import Path
import subprocess
import sys
import unittest

SCRIPTS = Path(__file__).resolve().parents[2] / 'scripts'
sys.path.insert(0, str(SCRIPTS))


class RecoveryDeadlines(unittest.TestCase):
    def test_callback_result_survives_child_and_executor_cleanup(self):
        from sentinel_maintenance_process import run_bounded

        class Callback:
            minimum_seconds = 0.1
            calls = 0

            def next_at(self):
                return float('inf') if self.calls else 0

            def __call__(self, remaining):
                self.calls += 1
                if fail:
                    raise OSError('freshness failed')

        for fail in (False, True):
            callback = Callback()
            command = [sys.executable, '-c', "import time; time.sleep(.25); print('finished')"]
            with self.subTest(failure=fail):
                if fail:
                    with self.assertRaisesRegex(OSError, 'freshness failed'):
                        run_bounded(command, on_wait=callback, timeout=5)
                else:
                    result = run_bounded(command, on_wait=callback, timeout=5)
                    self.assertEqual((result.returncode, result.stdout), (0, 'finished\n'))
                self.assertEqual(callback.calls, 1)

    def test_all_recovery_owners_import_with_finite_shared_budgets(self):
        import sentinel_backup_deadlines as budgets
        import sentinel_backup_maintenance as maintenance
        import sentinel_install_backup as installation
        import sentinel_maintenance_process as process
        self.assertEqual(installation.BASE_COMMAND_SECONDS, 900)
        self.assertEqual(maintenance.BASE_COMMAND_SECONDS, 900)
        self.assertEqual(installation.INVOCATION_SECONDS, 3600)
        self.assertEqual(process.INVOCATION_SECONDS, 3600)
        self.assertGreater(budgets.RESTORE_WORKER_SECONDS, installation.RESTORE_COMMAND_SECONDS)
        self.assertLess(budgets.RESTORE_WORKER_SECONDS, installation.INVOCATION_SECONDS)

    def test_shell_budget_is_one_integer_and_unknown_budget_refuses(self):
        argv = [sys.executable, str(SCRIPTS / 'sentinel_backup_deadlines.py')]
        result = subprocess.run(argv + ['restore-worker'], text=True, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, '2160\n')
        refused = subprocess.run(argv + ['unknown'], text=True, capture_output=True, timeout=5)
        self.assertNotEqual(refused.returncode, 0)
        self.assertEqual(refused.stdout, '')


if __name__ == '__main__':
    unittest.main()
