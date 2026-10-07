"""Behavioral falsifiers for software/financial phase separation; disposable copies only."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
TEST = 'tests/sentinel/test_installation_activation_separation.py'
MUTANTS = (
    ('financial-restore-restored-to-software-finalizer', 'scripts/sentinel_autonomous_deploy.py',
     "        self.runner.run(['bash', 'scripts/sentinel-backup-status.sh'])\n        post_backup = None\n",
     '        post_backup = self._post_deploy_backup()\n',
     TEST + '::test_public_install_success_is_committed_before_separate_handoff'),
    ('software-backup-status-ignored', 'scripts/sentinel_autonomous_deploy.py',
     "        self.runner.run(['bash', 'scripts/sentinel-backup-status.sh'])\n        post_backup = None\n",
     '        post_backup = None\n',
     TEST + '::test_software_finalizer_cannot_ignore_backup_chain_refusal'),
    ('financial-read-inside-install', 'scripts/sentinel_autonomous_deploy.py',
     '        self.reviewed_validation = None\n        self._installation_only = True\n        self.build_promote()',
     '        self.reviewed_validation = None\n        self._installation_only = True\n        self.read_paper_account()\n        self.build_promote()',
     TEST + '::test_every_install_mode_finishes_without_any_financial_input'),
    ('provider-credentials-required-to-install', 'scripts/sentinel_env.py',
     'if profile in {"go", "bootstrap"}:', 'if profile in {"go", "bootstrap", "install"}:',
     TEST + '::test_install_profile_does_not_require_financial_credentials'),
    ('availability-stops-installed-shadow', 'scripts/sentinel_autonomous_deploy.py',
     '        except ActivationPending:\n', '        except ActivationPending:\n            self.fail_close()\n',
     TEST + '::test_activation_availability_preserves_shadow_but_never_weakens_fence'),
    ('process-health-hides-integrity', 'sentinel/shadow_supervisor.py',
     'def _health_snapshot(max_age_seconds, config, *, financial=True):\n',
     'def _health_snapshot(max_age_seconds, config, *, financial=True):\n    if not financial: return 0\n',
     TEST + '::test_process_health_cannot_require_financial_readiness_or_hide_integrity'),
    ('installed-receipt-overwritten', 'scripts/sentinel_phase_records.py',
     'write_document(path, value, immutable=True)', 'write_document(path, value, immutable=False)',
     TEST + '::test_installation_receipt_is_non_overwriting_and_private'),
    ('nonfinite-json-accepted', 'scripts/sentinel_phase_records.py',
     'parse_constant=invalid', 'parse_constant=lambda raw: float(raw)',
     TEST + '::test_phase_and_cli_json_reject_ambiguous_records'),
    ('dead-service-accepted-as-owner', 'scripts/sentinel_activation_coordinator.py',
     "                    and fields.get('ActiveState') == 'active'\n", '',
     TEST + '::test_handoff_requires_exact_independent_systemd_owner'),
    ('wrong-image-revision-accepted', 'scripts/sentinel_installation_phase.py',
     "                or labels.get('org.opencontainers.image.revision') != self.commit\n", '',
     TEST + '::test_independent_software_admission_rejects_mismatch_before_any_financial_work'),
    ('financial-no-go-accepted', 'scripts/sentinel_activation_coordinator.py',
     '    if completed.returncode:\n', '    if False and completed.returncode:\n',
     TEST + '::test_financial_go_failure_never_becomes_authority'),
    ('bundle-byte-mismatch-accepted', 'scripts/sentinel_activation_coordinator.py',
     '    if digest(path) != hashes[0]:\n', '    if False and digest(path) != hashes[0]:\n',
     TEST + '::test_financial_go_failure_never_becomes_authority'),
    ('runtime-selector-fence-removed', 'scripts/sentinel_installation_phase.py',
     "        if state.get('enabled') is not False or state.get('kill_switch_engaged') is not True:\n",
     "        if False:\n",
     TEST + '::test_signed_install_selects_exact_runtime_only_after_durable_fence'),
    ('runtime-selector-left-stale', 'scripts/sentinel_installation_phase.py',
     '        _write_pointer(self.runtime_repo_digest)\n', '        pass\n',
     TEST + '::test_signed_install_selects_exact_runtime_only_after_durable_fence'),
    ('legacy-install-financial-build-restored', 'scripts/sentinel_autonomous_deploy.py',
     "        if getattr(self, '_installation_only', False):\n", '        if False:\n',
     TEST + '::test_legacy_install_objects_cannot_reenter_financial_build_path'),
    ('activation-financial-verification-skipped', 'scripts/sentinel_autonomous_deploy.py',
     '        self._installation_only = False\n', '',
     TEST + '::test_reused_install_object_must_return_to_financial_verification_for_activation'),
)


def execute(path, env, *, root=ROOT):
    return subprocess.run([sys.executable, '-m', 'pytest', '-q', '-p', 'no:cacheprovider',
                           str(root / path.split('::', 1)[0]) +
                           ('::' + path.split('::', 1)[1] if '::' in path else '')],
                          cwd=str(root), env=env, capture_output=True, text=True, timeout=60)


def main():
    env = dict(os.environ)
    baseline = execute(TEST, env)
    if baseline.returncode:
        print(baseline.stdout + baseline.stderr)
        return 2
    evidence = []
    for name, relative, old, new, test in MUTANTS:
        with tempfile.TemporaryDirectory(prefix='sentinel-install-mutant-') as directory:
            mutant = Path(directory)
            for package in ('scripts', 'sentinel', 'shared'):
                shutil.copytree(ROOT / package, mutant / package, ignore=shutil.ignore_patterns('__pycache__'))
            # Child conftest derives its import root from its own path. Copy the
            # narrow test lens too, so production imports cannot escape a mutant.
            for relative_test in ('tests/conftest.py', 'tests/sentinel/conftest.py', TEST):
                destination = mutant / relative_test
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / relative_test, destination)
            path = mutant / relative
            source = path.read_text()
            if source.count(old) != 1:
                print('REFUSED: mutation anchor drift: ' + name)
                return 2
            path.write_text(source.replace(old, new, 1))
            env = dict(os.environ, SENTINEL_REPO_ROOT=str(mutant),
                       PYTHONPATH=str(mutant) + ':' + str(mutant / 'scripts') + ':' +
                                  str(ROOT) + ':' + str(ROOT / 'shared'))
            result = execute(test, env, root=mutant)
            if (result.returncode != 1 or 'FAILED ' not in result.stdout
                    or 'ERROR collecting' in result.stdout or 'SyntaxError' in result.stdout
                    or 'ImportError' in result.stdout):
                print('REFUSED: survived or invalid harness: ' + name)
                print(result.stdout + result.stderr)
                return 1
            evidence.append({'mutation': name, 'detected': True})
            print('KILLED: ' + name, flush=True)
    print(json.dumps({'verdict': 'PASS', 'behavioral_mutations': evidence}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
