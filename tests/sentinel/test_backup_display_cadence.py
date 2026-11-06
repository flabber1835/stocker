"""Actual backup-source composition never borrows the trading scheduler clock."""
import ast
from datetime import datetime, timedelta, timezone
import hashlib
import inspect
import json
import textwrap

import pytest

from sentinel.panel import model, sources
from tests.sentinel.test_operator_monitoring import (  # noqa: F401
    _backup_proofs, db, issue369_pg)

NOW = datetime(2026,11,6,14,48,46,tzinfo=timezone.utc)


def observe(db, monkeypatch, *, wake, age=timedelta(seconds=25), broken=False):
    from sentinel import local_paper
    monkeypatch.delenv(local_paper.MODE_ENV, raising=False)
    monkeypatch.delenv(local_paper.BACKUP_POLICY_ENV, raising=False)
    cycle = {'state':'RETRY_WAIT','retry_phase':'RECOVER','next_wake_at':wake,
        'decision_session':'2026-11-05','failure_code':'CORPORATE_ACTION_PENDING'}
    monkeypatch.setattr(sources, '_latest_automation_cycle', lambda *args, **kwargs: cycle)
    base, restore, runtime = _backup_proofs()
    if broken:runtime['wal_segments']=0
    for kind, proof, at in [('BASE_BACKUP',base,NOW-timedelta(hours=1)),
        ('RESTORE_DRILL',restore,NOW-timedelta(days=1)),('RUNTIME_CHAIN',runtime,NOW-age)]:
        raw=json.dumps(proof,sort_keys=True,separators=(',',':'))
        sha=hashlib.sha256(('sentinel.backup-evidence/1\0'+kind+'\0'+raw).encode()).hexdigest()
        db.execute('INSERT INTO sentinel_backup_evidence(kind,evidence_sha256,proof,observed_at) '
            'VALUES (%s,%s,%s::jsonb,%s)',(kind,sha,raw,at))
    db.commit()
    rows,_=sources._operator_evidence_rows(db.info.dsn,now=NOW)
    return next(row for row in rows if row.key=='backup_restore')


@pytest.mark.parametrize('wake_delta', [timedelta(seconds=-17),timedelta(hours=4)])
def test_fresh_backup_is_independent_of_unrelated_elapsed_or_future_retry(db,monkeypatch,wake_delta):
    row=observe(db,monkeypatch,wake=NOW+wake_delta)
    assert row.status==model.OK and row.effective_status(NOW)==model.OK, row.detail
    assert row.valid_until==NOW-timedelta(seconds=25)+timedelta(minutes=10)
    assert row.as_of==NOW-timedelta(seconds=25)


def test_future_trading_wake_cannot_keep_stopped_backup_producer_current(db,monkeypatch):
    row=observe(db,monkeypatch,wake=NOW+timedelta(hours=4),age=timedelta(minutes=11))
    assert row.status==model.FAIL and row.effective_status(NOW)==model.FAIL
    assert 'past its cadence' in row.detail


def test_composed_backup_expires_at_original_deadline_without_reobservation(db,monkeypatch):
    row=observe(db,monkeypatch,wake=NOW+timedelta(hours=4))
    assert row.effective_status(NOW)==model.OK
    assert row.effective_status(NOW+timedelta(minutes=10))==model.FAIL


def test_fresh_backup_clock_cannot_admit_invalid_wal_proof(db,monkeypatch):
    row=observe(db,monkeypatch,wake=NOW+timedelta(hours=4),broken=True)
    assert row.status==model.FAIL and 'authority is invalid' in row.detail


@pytest.mark.parametrize('earliest', ['base','restore','runtime'])
def test_backup_row_bounds_every_original_producer_objective(earliest):
    base,restore,runtime=_backup_proofs()
    base_at=NOW-timedelta(hours=1)
    restore_at=NOW-timedelta(days=1)
    runtime_until=NOW+timedelta(minutes=10)
    expected=NOW+timedelta(seconds=20)
    if earliest=='base':base_at=expected-timedelta(hours=26)
    elif earliest=='restore':restore_at=expected-timedelta(days=31)
    else:runtime_until=expected
    row=model.backup_restore_row(base_at=base_at,restore_at=restore_at,runtime_at=NOW,
        base_proof=base,restore_proof=restore,runtime_proof=runtime,
        runtime_valid_until=runtime_until,now=NOW)
    assert row.effective_status(NOW)==model.OK
    assert row.valid_until==expected
    assert row.effective_status(expected+timedelta(microseconds=1))==model.FAIL


def test_removed_backup_clock_selection_is_detected(db,monkeypatch):
    tree=ast.parse(textwrap.dedent(inspect.getsource(sources._operator_evidence_rows)))
    matches=[n for n in ast.walk(tree) if isinstance(n,ast.Call)
        and isinstance(n.func,ast.Name) and n.func.id=='_backup_valid_until']
    assert len(matches)==1
    matches[0].func.id='_runtime_valid_until'
    matches[0].args.insert(0,ast.Name(id='cycle',ctx=ast.Load()))
    ast.fix_missing_locations(tree);namespace={}
    exec(compile(tree,'<restored-trading-clock-coupling>','exec'),vars(sources),namespace)
    monkeypatch.setattr(sources,'_operator_evidence_rows',namespace['_operator_evidence_rows'])
    with pytest.raises(AssertionError):
        test_fresh_backup_is_independent_of_unrelated_elapsed_or_future_retry(
            db,monkeypatch,timedelta(seconds=-17))


def test_removed_backup_row_deadline_is_detected(db,monkeypatch):
    tree=ast.parse(textwrap.dedent(inspect.getsource(model.backup_restore_row)))
    matches=[k for n in ast.walk(tree) if isinstance(n,ast.Call) for k in n.keywords
        if k.arg=='valid_until' and isinstance(k.value,ast.Call)
        and isinstance(k.value.func,ast.Name) and k.value.func.id=='min']
    assert len(matches)==1
    matches[0].value=ast.Constant(None)
    ast.fix_missing_locations(tree);namespace={}
    exec(compile(tree,'<removed-backup-delivery-deadline>','exec'),vars(model),namespace)
    monkeypatch.setattr(model,'backup_restore_row',namespace['backup_restore_row'])
    with pytest.raises(AssertionError):
        test_composed_backup_expires_at_original_deadline_without_reobservation(db,monkeypatch)
