"""Stdlib-only tests executed by the dedicated host Python 3.8 lane."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from scripts import sentinel_forward_run
from scripts import sentinel_test_run
from scripts import sentinel_host_command


ROOT = Path(os.environ.get(
    "SENTINEL_REPO_ROOT", str(Path(__file__).resolve().parents[2])
))
_STATE_SPEC = importlib.util.spec_from_file_location(
    "sentinel_certification_state_under_test",
    ROOT / "scripts" / "sentinel_certification_state.py",
)
if _STATE_SPEC is None or _STATE_SPEC.loader is None:  # pragma: no cover
    raise RuntimeError("cannot load Sentinel certification state helper")
state = importlib.util.module_from_spec(_STATE_SPEC)
_STATE_SPEC.loader.exec_module(state)


GIT = "1" * 40
RUNTIME_SHA = "2" * 64
TEST_SHA = "3" * 64


def _write(path: Path, value) -> Path:
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    return path


def _image(repository: str, digest: str, *, commit: str = GIT):
    return {
        "source_revision": commit,
        "repo_digests": [repository + "@sha256:" + digest],
    }


def _manifest(*, lifecycle="FINALIZED", verdict="PASS", closure="4",
              lock_sha=None):
    lock_sha = lock_sha or "5" * 64
    return {
        "schema": "sentinel.certification_manifest/2",
        "lifecycle": lifecycle,
        "verdict": verdict,
        "failures": [] if verdict == "PASS" else ["abandoned"],
        "git_tree_clean": True,
        "git_commit": GIT,
        "identity_hash": "6" * 64,
        "final_identity_hash": "6" * 64,
        "corpus_hash": "7" * 64,
        "final_corpus_hash": "7" * 64,
        "sentinel_source_hash": "8" * 64,
        "wealth_core_source_hash": "9" * 64,
        "distributions_hash": closure * 64,
        "requirements_lock_sha256": lock_sha,
        "image_source_hashes": {"certification_inputs": "a" * 64},
        "parity_generations": {"sentinel_data_version": 1},
        "sentinel_runtime_image": _image(
            "registry.example/runtime", RUNTIME_SHA),
        "sentinel_test_image": _image(
            "registry.example/test", TEST_SHA),
    }


class HostPythonCompatibilityTests(unittest.TestCase):

    def test_retained_parity_validator_does_not_import_runtime_dependencies(self):
        from scripts import sentinel_go_validate as go
        from unittest.mock import patch
        import builtins
        checks = {key: True for key in ('prior_unchanged', 'input_unchanged', 'restart_equivalent',
            'result_roundtrip_equivalent', 'frontier_advanced', 'publication_version_bound',
            'strategy_bound', 'decision_present')}
        strategy = dict(strategy='retained-fixture', market_input_policy='CURRENT_WINDOW_V1',
            startup_policy='CURRENT_WINDOW_FORMATION_V1', controller_rule_sha256='a'*64)
        retained = {key: 'a'*64 for key in ('origin_sha256', 'checkpoint_sha256', 'record_sha256',
            'state_sha256', 'input_sha256', 'prior_state_sha256', 'book_runtime_sha256',
            'process_sha256', 'runtime_receipt_sha256')}
        retained.update(schema='sentinel.retained-transition-proof/1', authority_effect='NONE',
            scope='ROLLING_RETAINED_STATE_AND_RESTART', observation_id='primary', session='2026-07-31',
            admission_sha256=None, strategy_sha256=go._evidence_digest(strategy), checks=checks)
        proof = dict(scope=retained['scope'], runtime_contract='sentinel.rolling-shadow-runtime/1',
            strategy_identity=strategy, starting_cash='50000', decision_session='2026-07-31',
            data_version=1, warmup_input=dict(session_count=299, warmup_input_sha256='a'*64),
            checks=checks, retained=retained)
        proof.update({key: 'a'*64 for key in ('input_sha256', 'prior_state_sha256', 'result_state_sha256',
            'decision_sha256', 'controller_configuration_sha256', 'sentinel_source_sha256',
            'wealth_core_source_sha256', 'proof_helper_sha256')})
        report = dict(schema='sentinel.production-operational-parity/1', verdict='PASS', authority_effect='NONE',
            runtime_authority_changed=False, transaction=dict(isolation='repeatable read', read_only='on'),
            publication_coherence=dict(coherent=True, scope='ROLLING_CURRENT_INPUTS_ONLY', version=1,
                blocking_runs=[], snapshot=dict(data_version=1, scope='DATA_ONLY', operational_go=False,
                    candidate_id='11111111-1111-1111-1111-111111111111',
                    job_id='22222222-2222-2222-2222-222222222222', snapshot_id='a'*64)),
            held_publication=dict(publication_fingerprint='a'*64, visible_frontier='2026-07-31'),
            source_identity=dict(identity_hash='a'*64, image_source_revision=GIT,
                environment=dict(compatible=True, pins_match=True, sources_known=True, lock_present=True,
                    pin_drift={}, sentinel_source=dict(hash='a'*64), wealth_core_source=dict(hash='a'*64))),
            proof=proof)
        original = builtins.__import__
        def host_import(name, *args, **kwargs):
            if name == 'sentinel' or name.startswith('sentinel.') or name == 'pydantic':
                raise AssertionError('host imported an engine dependency')
            return original(name, *args, **kwargs)
        with patch.object(builtins, '__import__', host_import):
            self.assertTrue(go._operational_parity_report_valid(report, commit=GIT, starting_cash='50000'))
            retained['checks'] = dict(checks, restart_equivalent=1)
            self.assertFalse(go._operational_parity_report_valid(report, commit=GIT, starting_cash='50000'))

    def test_separate_software_installer_imports_on_minimum_host_python(self):
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/sentinel_installation_phase.py'),
                                 '--explain'], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('immutable INSTALLED/FENCED', result.stdout)

    def test_activation_coordinator_cli_imports_on_minimum_host_python(self):
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/sentinel_activation_coordinator.py'),
                                 '--help'], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--queue-from-installation', result.stdout)

    def test_final_host_command_timeout_on_minimum_python(self):
        with tempfile.TemporaryDirectory() as directory:
            result = sentinel_host_command.run(
                [sys.executable, "-c", "import time; time.sleep(10)"],
                cwd=directory, env=dict(os.environ, SENTINEL_GO_COMMAND_TIMEOUT_SECONDS="1"))
            self.assertEqual(result.returncode, 124)
            self.assertIn("deadline exceeded", result.stderr)

    def test_preflight_exercises_host_call_graph_and_repo_digest_paths(self):
        completed = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "sentinel_host_python.py")],
            cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(
            completed.returncode, 0,
            completed.stderr.decode("utf-8", errors="replace"),
        )
        self.assertIn(b"host_python_compatible:", completed.stdout)

    def test_test_run_parses_real_immutable_manifest_path(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = _manifest(lifecycle="FROZEN", verdict=None)
            manifest["failures"] = []
            path = _write(Path(directory) / "frozen.json", manifest)
            binding, raw = sentinel_test_run.manifest_binding(path)
            self.assertEqual(binding["runtime_image_digest"],
                             "sha256:" + RUNTIME_SHA)
            self.assertEqual(binding["test_image_digest"],
                             "sha256:" + TEST_SHA)
            self.assertEqual(sentinel_test_run.test_image_ref(path),
                             "registry.example/test@sha256:" + TEST_SHA)
            self.assertEqual(binding["sha256"],
                             hashlib.sha256(raw).hexdigest())

    def test_forward_run_parses_real_finalized_manifest_path(self):
        with tempfile.TemporaryDirectory() as directory:
            path = _write(Path(directory) / "final.json", _manifest())
            binding, test_ref = sentinel_forward_run.manifest_binding(path)
            self.assertEqual(binding["runtime_image_digest"],
                             "sha256:" + RUNTIME_SHA)
            self.assertEqual(binding["test_image_digest"],
                             "sha256:" + TEST_SHA)
            self.assertEqual(test_ref,
                             "registry.example/test@sha256:" + TEST_SHA)

    def test_build_push_and_resume_are_bound_to_immutable_images(self):
        runtime_id = "sha256:" + "b" * 64
        test_id = "sha256:" + "c" * 64
        runtime_tag = "registry.example/runtime:" + GIT
        test_tag = "registry.example/test:" + GIT
        runtime_digest = "registry.example/runtime@sha256:" + RUNTIME_SHA
        test_digest = "registry.example/test@sha256:" + TEST_SHA
        identities = {
            "sentinel-authorized:latest": (runtime_id, []),
            "sentinel-test:latest": (test_id, []),
            runtime_tag: (runtime_id, [runtime_digest]),
            test_tag: (test_id, [test_digest]),
            runtime_digest: (runtime_id, [runtime_digest]),
            test_digest: (test_id, [test_digest]),
        }

        def invoke(argv, **_kwargs):
            image_id, repo_digests = identities[argv[-1]]
            payload = [{
                "Id": image_id,
                "RepoDigests": repo_digests,
                "Config": {"Labels": {
                    "org.opencontainers.image.revision": GIT,
                }},
            }]
            return subprocess.CompletedProcess(
                argv, 0, json.dumps(payload).encode("utf-8"), b"")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            build_path = root / "build.json"
            build = state.build_record(
                git_commit=GIT, runtime_ref="sentinel-authorized:latest",
                test_ref="sentinel-test:latest", invoke=invoke)
            state.write_no_clobber(build, build_path)
            promotion = state.promotion_record(
                build_path=build_path, runtime_tag=runtime_tag,
                test_tag=test_tag, invoke=invoke)
            promotion_path = root / "promotion.json"
            state.write_no_clobber(promotion, promotion_path)

            # A mutable local tag can move after promotion. Resume inspects the
            # retained RepoDigests and therefore still resolves the exact build.
            identities["sentinel-authorized:latest"] = (
                "sha256:" + "d" * 64, [])
            verified = state.verify_promotion(
                promotion_path, git_commit=GIT, invoke=invoke)
            self.assertEqual(verified["runtime_image"]["repo_digest"],
                             runtime_digest)
            self.assertEqual(verified["test_image"]["repo_digest"], test_digest)

    def test_abandoned_attempt_is_not_a_certified_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lock = root / "requirements.lock"
            lock.write_bytes(b"locked\n")
            lock_sha = hashlib.sha256(lock.read_bytes()).hexdigest()
            baseline = _write(
                root / "manifest-certified.json",
                _manifest(closure="4", lock_sha=lock_sha),
            )
            _write(
                root / "manifest-abandoned.json",
                _manifest(lifecycle="BLOCKED", verdict="BLOCKED",
                          closure="e", lock_sha="f" * 64),
            )
            identity = _write(root / "identity.json", {"environment": {
                "distributions_hash": "4" * 64,
                "image_lock_sha256": lock_sha,
            }})
            context = state.validate_closure_context(
                art=root, identity_path=identity, lock_path=lock,
                git_commit=GIT, baseline_path=baseline)
            self.assertEqual(context["baseline"]["path"], baseline.as_posix())
            self.assertIsNone(context["transition"])

    def test_reviewed_transition_retains_prior_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old_lock_sha = "5" * 64
            baseline = _write(
                root / "manifest-certified.json",
                _manifest(closure="4", lock_sha=old_lock_sha),
            )
            old_bytes = baseline.read_bytes()
            new_lock = root / "requirements.lock"
            new_lock.write_bytes(b"reviewed-new-lock\n")
            new_lock_sha = hashlib.sha256(new_lock.read_bytes()).hexdigest()
            identity = _write(root / "identity.json", {"environment": {
                "distributions_hash": "e" * 64,
                "image_lock_sha256": new_lock_sha,
            }})
            transition = state.review_transition(
                baseline_path=baseline, identity_path=identity,
                lock_path=new_lock, git_commit=GIT, reviewer="reviewer",
                reason="reviewed lock update",
                reviewed_at=datetime(2026, 8, 15, tzinfo=timezone.utc),
            )
            transition_path = root / "transition.json"
            state.write_no_clobber(transition, transition_path)
            context = state.validate_closure_context(
                art=root, identity_path=identity, lock_path=new_lock,
                git_commit=GIT, baseline_path=baseline,
                transition_path=transition_path)
            self.assertIsNotNone(context["transition"])
            self.assertEqual(baseline.read_bytes(), old_bytes)
            self.assertEqual(context["target"]["requirements_lock_sha256"],
                             new_lock_sha)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
