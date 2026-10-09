"""Guard-removal acceptance against activation's host and real-process tests."""
import argparse
import importlib
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(os.environ.get('SENTINEL_REPO_ROOT') or Path(__file__).resolve().parents[1])
sys.path.insert(0, str(ROOT / 'scripts'))
UNIT = 'tests/sentinel/test_activation_writer_handoff.py'
PROCESS = 'tests/sentinel/test_activation_writer_processes.py'
MUTANTS = {
    'retry_fence': ('            self.confirm_disabled_activation_fence()\n', '',
        UNIT, 'test_readiness_retry_confirms_disabled_fence_before_configuration'),
    'shadow_grace': ("                grace_seconds = max(30, getattr(self.cfg, 'health_timeout', 30))",
        '                grace_seconds = 10', UNIT,
        'test_graceful_shadow_stop_uses_reviewed_budget_and_only_owned_ids'),
    'missing_handoff': ('        self.quiesce_activation_writers()\n', '',
        UNIT, 'test_complete_activation_hands_off_all_writers_before_dispatch'),
    'live_publisher': ('        self._direct_stop_shadow(grace_seconds=max(30, getattr(self.cfg, \'health_timeout\', 30)))',
        '        pass', PROCESS,
        'test_actual_host_handoff_owns_processes_and_all_three_lock_boundaries'),
    'stopped_proof': ('            raise DeployRefused("activation writer handoff requires stopped financial services")',
        '            pass', UNIT, 'test_failed_handoff_never_starts_dispatcher'),
    'resumed_session': ('            if attested.get("session") != decision_session:',
        '            if False:', UNIT, 'test_failed_handoff_never_starts_dispatcher'),
    'released_control': ('            raise DeployRefused("released automation control differs from activation authority")',
        '            pass', UNIT, 'test_failed_handoff_never_starts_dispatcher'),
    'strict_json': ('                last = _json_output(completed, label="shadow attestation")',
        '                last = json.loads(completed.stdout)', UNIT,
        'test_shadow_attestation_json_corruption_is_permanent_refusal'),
    'dispatcher_before_shadow': (
        '        self._require_activation_writers_stopped()\n        self._require_released_activation_control(certificate_sha256)',
        '        self.runner.run(self._authorized_compose() + ["--profile", "automation", "up", "-d", "sentinel-automation"])\n'
        '        self._require_activation_writers_stopped()\n        self._require_released_activation_control(certificate_sha256)',
        UNIT, 'test_complete_activation_hands_off_all_writers_before_dispatch'),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--child', choices=MUTANTS)
    parser.add_argument('--process', action='store_true')
    args = parser.parse_args()
    if args.child:
        import pytest
        module = importlib.import_module('sentinel_autonomous_deploy')
        original, replacement, test_file, name = MUTANTS[args.child]
        source = Path(module.__file__).read_text()
        assert source.count(original) == 1, 'mutation no longer binds one reviewed guard'
        exec(compile(source.replace(original, replacement), module.__file__, 'exec'), module.__dict__)
        # Local fixture adapter may be supplied by the Docker qualification
        # harness. CI's ordinary PostgreSQL binaries need no adapter.
        return pytest.main([test_file + '::' + name, '-q', '--tb=short', '-p', 'no:cacheprovider'])
    failed = []
    for name, (_, _, test_file, _) in MUTANTS.items():
        if (test_file == PROCESS) != args.process:
            continue
        result = subprocess.run([sys.executable, '-m', __spec__.name, '--child', name],
                                capture_output=True, text=True, timeout=180)
        killed = (result.returncode == 1 and 'failed' in result.stdout
                  and 'ERROR ' not in result.stdout and 'ERROR ' not in result.stderr)
        print(name + (': KILLED' if killed else ': NOT PROVED'), flush=True)
        if not killed:
            failed.append(name)
            print(result.stdout, flush=True)
            print(result.stderr, flush=True)
    return bool(failed)


if __name__ == '__main__':
    raise SystemExit(main())
