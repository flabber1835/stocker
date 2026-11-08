"""Exact obsolete-checkpoint relocation and finance-role falsifiers; DATA only."""
import gzip
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import core_volatility_recovery as recovery
from core_volatility_admit import extract
from core_volatility_source import sha
from core_volatility_job import command, require_continuation_stage


def fixture(tmp_path, monkeypatch):
    old = {'source_cursor': '2018-02-08', 'completed': 27, 'journals': {'daily': {'bytes': 1937750}}}
    raw = gzip.compress(json.dumps(old).encode())
    name = 'book/pre-event/old-uncommitted.json.gz'
    path = tmp_path/name
    path.parent.mkdir(parents=True)
    path.write_bytes(raw)
    monkeypatch.setattr(recovery, 'SUPERSEDED', name)
    monkeypatch.setattr(recovery, 'SUPERSEDED_FILE', sha(raw))
    for name in ('checkpoint.json.gz', 'daily.jsonl', 'formation.jsonl', 'watch.jsonl', 'monthly.jsonl', 'interrupted-daily-original.jsonl'):
        (tmp_path/'book'/name).write_bytes(b'INERT ORIGINAL BYTES\n')
    return path, raw


def test_only_obsolete_gzip_moves_all_financial_and_tail_bytes_stay(tmp_path, monkeypatch):
    path, raw = fixture(tmp_path, monkeypatch)
    before = recovery.financial_inventory(tmp_path)
    proof = recovery.relocate(tmp_path)
    assert recovery.financial_inventory(tmp_path) == before and not path.exists()
    assert (tmp_path/proof['stored']).read_bytes() == raw and proof['financial_sessions_advanced'] == 0


def test_changed_or_unrelated_checkpoint_cannot_be_archived(tmp_path, monkeypatch):
    path, raw = fixture(tmp_path, monkeypatch)
    path.write_bytes(raw+b'wrong')
    with pytest.raises(ValueError, match='EXACT_SUPERSEDED_CHECKPOINT_ONLY'):
        recovery.relocate(tmp_path)
    assert path.exists()


def test_failed_review_never_enters_normal_financial_admission(tmp_path):
    with pytest.raises(ValueError, match='REVIEWED_STATUS_ONLY'):
        extract(tmp_path/'unused.zip', tmp_path/'not-created', b'K'*32,
                {'status': 'WORKER_STOPPED_PREFIX_PRESERVED'})
    assert not (tmp_path/'not-created').exists()


def test_wrong_failed_epoch_refuses_before_any_transport(tmp_path):
    with pytest.raises(ValueError, match='EXACT_FAILED_REVIEW_EVIDENCE_ONLY'):
        recovery.extract_evidence(tmp_path/'unused.zip', tmp_path/'not-created', b'K'*32,
            {'run_id': 0, 'head': recovery.HEAD, 'arm': 'VOL075'})
    assert not (tmp_path/'not-created').exists()


def test_recovery_success_requires_zero_advances():
    req = {'stage': 'OWN_REVIEW_RECOVERY', 'maximum': 0}
    receipt = {'status': 'PARTIAL_ARM_REVIEWED_PENDING_ARTIFACT_ADMISSION',
               'worker': {'exit_code': 0}, 'reviewer': {'exit_code': 0}}
    outcome = {'completed': 232, 'session': '2018-11-30', 'financial_sessions_advanced': 0, 'recovered_existing_prefix': True}
    require_continuation_stage(req, receipt, outcome, 'VOL075')
    outcome['financial_sessions_advanced'] = 1
    with pytest.raises(ValueError, match='RECOVERY_ONLY_NO_FINANCIAL_ADVANCE'):
        require_continuation_stage(req, receipt, outcome, 'VOL075')


def test_recovery_entrypoint_argument_is_explicit(monkeypatch):
    import full_system_trials_job as original
    monkeypatch.setattr(original, 'os', SimpleNamespace(getuid=lambda: 1001, getgid=lambda: 1001))
    values = command('core-volatility-vol075-worker-123-1', Path('/source'), Path('/frozen'),
                     Path('/out'), 'VOL075', maximum=0, previous=Path('/previous'), recover_prefix=True)
    assert values[-3:] == ['--resume-root', '/previous', '--recover-prefix']
    assert '--aaap-model' not in values


def test_recovery_canonical_imports_closed_locally(monkeypatch):
    monkeypatch.setenv('FULL_SYSTEM_HOSTED', '1')
    with pytest.raises(ValueError, match='HOSTED_CORE_ONLY'):
        recovery.run(Path('/previous'), 'VOL075', 0)
