"""Current receipts and their derived availability agree in the same response."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import inspect
import json
import logging
import textwrap
import uuid

import pytest
from psycopg.types.json import Jsonb

from sentinel.feed import calendar, operational_snapshot, rolling_jobs, rolling_go_inputs
from sentinel.feed.rolling_contract import PriceWindow, digest
from sentinel.panel import model, operational_snapshot as wire, postclose_feed_wait as waiting
from sentinel.panel import readiness_handoff as handoff
from tests.sentinel.test_supervisor_dependency_bounds import conn, pg  # noqa: F401

NOW = datetime(2026, 11, 9, 21, 47, 10, tzinfo=timezone.utc)
SUBJECT = 'b' * 64


def page(*, typed=False):
    deadline = NOW + timedelta(minutes=4)
    phase = 'SHADOW_ATTESTATION' if typed else 'FINANCIAL_VERIFICATION'
    verification = model.Row('shadow_verification', 'Shadow', 'CHECKING', model.WARN,
        as_of=NOW if typed else None, required_current=True, valid_until=deadline,
        recovery=model.RecoveryEvidence(phase=phase, automatic=True, deadline=deadline),
        source_publication_version=17 if typed else None,
        source_session='2026-11-09' if typed else None)
    feed = model.feed_row(frontier='2026-11-09', sessions_behind=0, ready=None,
        checks_passed=0, checks_total=0, as_of=NOW-timedelta(minutes=1), publication_version=17)
    worker = model.Row('shadow_worker', 'Worker', 'RUNNING', model.OK,
        as_of=NOW, required_current=True, valid_until=NOW+timedelta(seconds=45))
    return model.Panel(now=NOW, rows=[feed, verification, worker])


def test_new_attestation_reprojects_old_red_derivative_without_new_fact_clocks():
    original = page(typed=True)
    assert original.row('feed').effective_status(NOW) == model.FAIL
    result = waiting.reproject(original, now=NOW)
    assert result.row('feed').effective_status(NOW) == model.WARN
    assert result.row('feed').valid_until == original.row('shadow_worker').valid_until
    assert result.row('feed').as_of == original.row('feed').as_of
    assert result.row('shadow_verification') == original.row('shadow_verification')
    assert waiting.reproject(result, now=NOW) == result
    assert result.row('feed').effective_status(NOW+timedelta(seconds=46)) == model.FAIL


@pytest.mark.parametrize('fault', ['generic', 'negative', 'dead', 'foreign_publication', 'foreign_session'])
def test_reprojection_requires_the_exact_current_typed_progress(fault):
    original = page(typed=fault != 'generic')
    updates = {}
    if fault == 'negative': updates['shadow_verification'] = replace(original.row('shadow_verification'), status=model.FAIL)
    elif fault == 'dead': updates['shadow_worker'] = replace(original.row('shadow_worker'), status=model.FAIL)
    elif fault == 'foreign_publication': updates['feed'] = replace(original.row('feed'), source_publication_version=18)
    elif fault == 'foreign_session': updates['feed'] = replace(original.row('feed'), source_session='2026-11-06')
    original = replace(original, rows=[updates.get(row.key, row) for row in original.rows])
    assert waiting.reproject(original, now=NOW).row('feed').effective_status(NOW) == model.FAIL


@pytest.fixture
def metadata(conn, monkeypatch):
    monkeypatch.setenv('SENTINEL_GIT_COMMIT', '1'*40)
    monkeypatch.setenv('SENTINEL_RUNTIME_IMAGE_DIGEST', 'sha256:'+'2'*64)
    for sql in (
        'CREATE TEMP TABLE sentinel_corpus_publications(version int,previous_version int,window_end date,evidence jsonb,window_start date,run_id uuid)',
        'CREATE TEMP TABLE sentinel_operational_snapshots(publication_version int,job_id uuid,candidate_id uuid,validation_sha256 text)',
        'CREATE TEMP TABLE sentinel_snapshot_jobs(job_id uuid,candidate_id uuid,state text,publication_version int,request jsonb,request_sha256 text,created_at timestamptz,deadline timestamptz)',
        'CREATE TEMP TABLE sentinel_operational_snapshot_jobs(job_id uuid)',
    ): conn.execute(sql)
    job, candidate = uuid.uuid4(), uuid.uuid4()
    request = rolling_jobs.PreparationRequest(window=PriceWindow.through('2026-11-09'),
        expected_publication_version=16, strategy_sha256='a'*64, dependencies_sha256=digest({
            'schema':operational_snapshot.SCHEMA,'dependencies':digest({'scope':rolling_go_inputs.SCHEMA})}))
    binding = dict(schema=operational_snapshot.SCHEMA,job_id=str(job),candidate_id=str(candidate),validation_sha256='c'*64)
    conn.execute('INSERT INTO sentinel_corpus_publications VALUES(17,16,\'2026-11-09\',%s,%s,NULL)',
        (Jsonb(dict(rolling_snapshot=binding)),request.window.start))
    conn.execute('INSERT INTO sentinel_operational_snapshots VALUES(17,%s,%s,%s)', (job,candidate,'c'*64))
    conn.execute('INSERT INTO sentinel_operational_snapshot_jobs VALUES(%s)', (job,))
    conn.execute('INSERT INTO sentinel_snapshot_jobs VALUES(%s,%s,\'PUBLISHED\',17,%s,%s,%s,%s)',
        (job,candidate,Jsonb(request.model_dump(mode='json')),request.request_sha256,
         NOW-timedelta(minutes=40),NOW+timedelta(hours=1)))
    attempt = dict(schema='sentinel.financial-observer-attempt/1',attempt_id='a'*32,
        subject_sha256=SUBJECT,outcome='RUNNING',admitted_at=(NOW-timedelta(minutes=1)).isoformat(),
        deadline=(NOW+timedelta(minutes=4)).isoformat(),
        work_started_at=(NOW-timedelta(seconds=59)).isoformat(),
        work_deadline=(NOW+timedelta(minutes=4)).isoformat())
    diagnostic = dict(observation_fresh=True,financial_authority=False,latest=attempt,
        runtime=dict(git_commit='1'*40,image_digest='sha256:'+'2'*64))
    panel = replace(page(),trial_details=dict(verification_attempts={'SHADOW':diagnostic}))
    return conn, panel


def capture(metadata):
    conn, panel = metadata
    return handoff.capture(conn,panel,subject=SUBJECT,owner_expiry=NOW+timedelta(minutes=5),now=NOW)


def test_real_metadata_and_exact_attempt_explain_wait_without_earning_verdict(metadata):
    original = metadata[1]
    proof = capture(metadata)
    assert proof is not None
    assert datetime.fromisoformat(proof['deadline']) == original.row('shadow_worker').valid_until
    result = waiting.reproject(replace(original,trial_details={**original.trial_details,'readiness_handoff':proof}),
        now=NOW,subject=SUBJECT)
    assert result.row('feed').effective_status(NOW) == model.WARN
    assert result.row('feed').feed_readiness == 'AWAITING_VERDICT'
    assert result.row('feed').recovery.phase == 'READINESS_HANDOFF'
    assert result.row('shadow_verification') == original.row('shadow_verification')
    assert result.row('feed').as_of == original.row('feed').as_of
    assert result.row('feed').effective_status(NOW+timedelta(seconds=46)) == model.FAIL
    assert waiting.reproject(result, now=NOW, subject=SUBJECT) == result


@pytest.mark.parametrize('fault', ['subject','failed','superseded','diagnostic','runtime','stale',
    'prior_attempt','future_work','missing_runtime','missing_attempt','bad_hash','wrong_candidate','wrong_job','foreign_publication',
    'foreign_session','expired_job','unpublished','negative_feed','dead_worker','ambiguous'])
def test_missing_unrelated_failed_or_ambiguous_progress_never_quiets_feed(metadata,fault):
    conn, original = metadata
    panel = deepcopy(original)
    diagnostic = panel.trial_details['verification_attempts']['SHADOW']
    attempt = diagnostic['latest']
    if fault == 'subject': attempt['subject_sha256']='c'*64
    elif fault == 'failed': attempt['outcome']='FAILED'
    elif fault == 'superseded': attempt['outcome']='SUPERSEDED'
    elif fault == 'diagnostic': attempt['diagnostic']={}
    elif fault == 'runtime': diagnostic['runtime']['git_commit']='3'*40
    elif fault == 'stale': diagnostic['observation_fresh']=False
    elif fault == 'prior_attempt': attempt['admitted_at']=(NOW-timedelta(hours=2)).isoformat()
    elif fault == 'future_work': attempt['work_started_at']=(NOW+timedelta(seconds=1)).isoformat()
    elif fault == 'missing_runtime':
        import os
        os.environ.pop('SENTINEL_GIT_COMMIT',None)
    elif fault == 'missing_attempt': diagnostic.clear()
    elif fault == 'bad_hash': conn.execute("UPDATE sentinel_snapshot_jobs SET request_sha256=%s",('d'*64,))
    elif fault == 'wrong_candidate': conn.execute('UPDATE sentinel_snapshot_jobs SET candidate_id=%s',(uuid.uuid4(),))
    elif fault == 'wrong_job': conn.execute('DELETE FROM sentinel_operational_snapshot_jobs')
    elif fault == 'foreign_publication': conn.execute('UPDATE sentinel_corpus_publications SET version=18')
    elif fault == 'foreign_session': conn.execute("UPDATE sentinel_corpus_publications SET window_end='2026-11-06'")
    elif fault == 'expired_job': conn.execute('UPDATE sentinel_snapshot_jobs SET deadline=%s',(NOW,))
    elif fault == 'unpublished': conn.execute("UPDATE sentinel_snapshot_jobs SET state='REFUSED'")
    elif fault == 'negative_feed': panel=replace(panel,rows=[replace(row,status=model.FAIL) if row.key=='feed' else row for row in panel.rows])
    elif fault == 'dead_worker': panel=replace(panel,rows=[replace(row,status=model.FAIL) if row.key=='shadow_worker' else row for row in panel.rows])
    else: conn.execute('INSERT INTO sentinel_operational_snapshots SELECT * FROM sentinel_operational_snapshots')
    assert handoff.capture(conn,panel,subject=SUBJECT,owner_expiry=NOW+timedelta(minutes=5),now=NOW) is None, 'unproved progress quieted feed'


def test_removing_exact_attempt_subject_guard_is_detected(metadata,monkeypatch):
    code=textwrap.dedent(inspect.getsource(handoff.capture))
    guard='attempt.subject_sha256 == subject and '
    assert code.count(guard)==1
    namespace={}
    exec(compile(code.replace(guard,''),'<removed-progress-subject>','exec'),vars(handoff),namespace)
    monkeypatch.setattr(handoff,'capture',namespace['capture'])
    with pytest.raises(AssertionError,match='unproved progress'):
        test_missing_unrelated_failed_or_ambiguous_progress_never_quiets_feed(metadata,'subject')


def test_current_attempt_can_explain_original_publication_rollover(metadata):
    conn, original = metadata
    attempt = original.trial_details['verification_attempts']['SHADOW']['latest']
    started = original.row('feed').as_of
    attempt.update(supersession_started_at=started.isoformat(),
                   supersession_deadline=(started+timedelta(minutes=10)).isoformat())
    assert capture((conn, original)) is not None
    started -= timedelta(microseconds=1)
    attempt.update(supersession_started_at=started.isoformat(),
                   supersession_deadline=(started+timedelta(minutes=10)).isoformat())
    assert capture((conn, original)) is None


def test_candidate_handoff_has_one_owned_exact_witness_and_negative_precedence(metadata, monkeypatch):
    conn, original = metadata
    observed = NOW-timedelta(seconds=45)
    attempt = original.trial_details['verification_attempts']['SHADOW']['latest']
    attempt.update(outcome='VERIFIED', completed_at=(observed+timedelta(seconds=1)).isoformat(),
                   subject_sha256='e'*64)
    shadow = replace(original.row('shadow_verification'), as_of=observed,
        source_publication_version=17, source_session='2026-11-09')
    worker = replace(original.row('shadow_worker'), operational_fact=model.OperationalFact(
        kind='SHADOW_WORKER', state='ACTIVE_WORKER'))
    original = replace(original, rows=[original.row('feed'), shadow, worker])
    calls = []
    def checkpoint(conn, *, pub, binding, closed, now):
        calls.append((pub.version, binding['candidate_id']))
        return 'd'*64, observed
    monkeypatch.setattr(handoff, '_checkpoint_bound', checkpoint)
    memo = handoff.CandidateMemo()
    def read(page, subject=SUBJECT):
        return handoff.capture(conn, page, subject=subject, owner_expiry=NOW+timedelta(minutes=5),
                               now=NOW, candidate_memo=memo)
    proof = read(original)
    assert proof['checkpoint_sha256'] == 'd'*64
    assert read(original) == proof and len(calls) == 1
    assert read(original, subject='c'*64) != proof and len(calls) == 2
    signed = replace(original, trial_details={**original.trial_details, 'readiness_handoff':proof})
    current = waiting.reproject(signed, subject=SUBJECT, now=NOW)
    assert current.row('feed').effective_status(NOW) == model.WARN
    assert current.row('shadow_verification').value == 'CHECKING'
    failed = replace(shadow, status=model.FAIL, recovery=None)
    signed = replace(signed, rows=[signed.row('feed'), failed, worker])
    assert read(signed) is None
    assert waiting.reproject(signed, subject=SUBJECT, now=NOW).row('feed').effective_status(NOW) == model.FAIL


def test_row_clock_diagnostic_is_closed_and_preserves_strict_refusal(monkeypatch,caplog):
    monkeypatch.setenv('SENTINEL_PUBLICATION_RECEIPT_KEY','private-test-'+'x'*40)
    bad = model.Row('secret DSN account text','secret','secret',model.OK,
        as_of=NOW.astimezone(timezone(timedelta(hours=-5))))
    with caplog.at_level(logging.WARNING), pytest.raises(wire.SnapshotUnavailable,match='SNAPSHOT_ROW_CLOCK_INVALID'):
        wire.encode(model.Panel(now=NOW,rows=[bad]),context_sha256='a'*64,
            subjects={'SHADOW':'b'*64,'PAPER':'c'*64})
    assert 'key=OTHER field=as_of kind=NON_UTC' in caplog.text
    assert 'secret' not in caplog.text and '-05:00' not in caplog.text
