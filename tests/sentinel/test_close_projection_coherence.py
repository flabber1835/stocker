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
    result = waiting.project_panel(original, now=NOW)
    assert result.row('feed').effective_status(NOW) == model.WARN
    assert result.row('feed').valid_until == original.row('shadow_worker').valid_until
    assert result.row('feed').as_of == original.row('feed').as_of
    assert result.row('shadow_verification') == original.row('shadow_verification')
    assert waiting.project_panel(original, now=NOW) == result
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
    assert waiting.project_panel(original, now=NOW).row('feed').effective_status(NOW) == model.FAIL


@pytest.fixture
def metadata(conn, monkeypatch):
    monkeypatch.setenv('SENTINEL_GIT_COMMIT', '1'*40)
    monkeypatch.setenv('SENTINEL_RUNTIME_IMAGE_DIGEST', 'sha256:'+'2'*64)
    for sql in (
        'CREATE TEMP TABLE sentinel_corpus_publications(version int,previous_version int,window_end date,evidence jsonb,window_start date,run_id uuid,published_at timestamptz)',
        'CREATE TEMP TABLE sentinel_operational_snapshots(publication_version int,job_id uuid,candidate_id uuid,validation_sha256 text)',
        'CREATE TEMP TABLE sentinel_snapshot_jobs(job_id uuid,candidate_id uuid,state text,publication_version int,request jsonb,request_sha256 text,created_at timestamptz,deadline timestamptz,updated_at timestamptz)',
        'CREATE TEMP TABLE sentinel_operational_snapshot_jobs(job_id uuid)',
    ): conn.execute(sql)
    job, candidate = uuid.uuid4(), uuid.uuid4()
    request = rolling_jobs.PreparationRequest(window=PriceWindow.through('2026-11-09'),
        expected_publication_version=16, strategy_sha256='a'*64, dependencies_sha256=digest({
            'schema':operational_snapshot.SCHEMA,'dependencies':digest({'scope':rolling_go_inputs.SCHEMA})}))
    binding = dict(schema=operational_snapshot.SCHEMA,job_id=str(job),candidate_id=str(candidate),validation_sha256='c'*64)
    conn.execute('INSERT INTO sentinel_corpus_publications VALUES(17,16,\'2026-11-09\',%s,%s,NULL,%s)',
        (Jsonb(dict(rolling_snapshot=binding)),request.window.start,NOW-timedelta(minutes=1)))
    conn.execute('INSERT INTO sentinel_operational_snapshots VALUES(17,%s,%s,%s)', (job,candidate,'c'*64))
    conn.execute('INSERT INTO sentinel_operational_snapshot_jobs VALUES(%s)', (job,))
    conn.execute('INSERT INTO sentinel_snapshot_jobs VALUES(%s,%s,\'PUBLISHED\',17,%s,%s,%s,%s,%s)',
        (job,candidate,Jsonb(request.model_dump(mode='json')),request.request_sha256,
         NOW-timedelta(minutes=40),NOW+timedelta(hours=1),NOW-timedelta(minutes=1)))
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
    result = waiting.project_panel(replace(original,trial_details={**original.trial_details,'readiness_handoff':proof}),
        now=NOW,subject=SUBJECT)
    assert result.row('feed').effective_status(NOW) == model.WARN
    assert result.row('feed').feed_readiness == 'AWAITING_VERDICT'
    assert result.row('feed').recovery.phase == 'READINESS_HANDOFF'
    assert result.row('shadow_verification') == original.row('shadow_verification')
    assert result.row('feed').as_of == original.row('feed').as_of
    assert result.row('feed').effective_status(NOW+timedelta(seconds=46)) == model.FAIL
    recorded = replace(original, trial_details={**original.trial_details, 'readiness_handoff':proof})
    assert waiting.project_panel(recorded, now=NOW, subject=SUBJECT) == result


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
    # The current attempt's admission binds it to this publication. Its inherited
    # chain can be older, but its clock must still apply to the entire display.
    started = NOW - timedelta(minutes=10) + timedelta(seconds=1)
    attempt.update(supersession_started_at=started.isoformat(),
                   supersession_deadline=(started+timedelta(minutes=10)).isoformat())
    proof = capture((conn, original))
    assert datetime.fromisoformat(proof['deadline']) == NOW + timedelta(seconds=1)
    assert handoff.capture(conn, original, subject=SUBJECT, owner_expiry=NOW+timedelta(minutes=5),
                           now=NOW+timedelta(seconds=1)) is None


def test_november_19_commit_during_supersession_starts_a_new_matching_attempt(metadata):
    conn, original = metadata
    # Exact offsets from the first stored red page at 21:13:42.766077Z.
    published = NOW - timedelta(seconds=8, microseconds=117589)
    header = published - timedelta(seconds=40, microseconds=228708)
    chain = published - timedelta(seconds=16, microseconds=308139)
    admitted = published + timedelta(microseconds=835641)
    working = published + timedelta(microseconds=989056)
    conn.execute('UPDATE sentinel_corpus_publications SET published_at=%s', (header,))
    conn.execute('UPDATE sentinel_snapshot_jobs SET updated_at=%s', (published,))
    attempt = original.trial_details['verification_attempts']['SHADOW']['latest']
    attempt.update(admitted_at=admitted.isoformat(), deadline=(working+timedelta(minutes=5)).isoformat(),
        work_started_at=working.isoformat(), work_deadline=(working+timedelta(minutes=5)).isoformat(),
        supersession_started_at=chain.isoformat(), supersession_deadline=(chain+timedelta(minutes=10)).isoformat())
    panel = replace(original, rows=[replace(r, as_of=published) if r.key=='feed' else r for r in original.rows])
    proof = capture((conn, panel))
    assert proof and proof['attempt_id']==attempt['attempt_id'] and proof['subject_sha256']==SUBJECT
    signed = replace(panel,trial_details={**panel.trial_details,'readiness_handoff':proof})
    result = waiting.project_panel(signed, now=NOW, subject=SUBJECT)
    assert result.row('feed').as_of == published and result.row('feed').effective_status(NOW) == model.WARN
    assert result.row('feed').operational_fact.state == 'AWAITING_VERDICT'
    assert handoff.deadline(signed, subject=SUBJECT, now=datetime.fromisoformat(proof['deadline'])) is None
    attempt['admitted_at'] = (published-timedelta(microseconds=1)).isoformat()
    assert capture((conn, panel)) is None


@pytest.mark.parametrize('fault', [None, 'no_rollover', 'worker_idle', 'older_attempt',
                                   'chain_before_publication', 'work_expired'])
def test_running_prior_subject_can_explain_published_readiness_rollover(metadata, fault):
    conn, original = metadata
    published = original.row('feed').as_of
    admitted = published + timedelta(seconds=3)
    attempt = original.trial_details['verification_attempts']['SHADOW']['latest']
    attempt.update(subject_sha256='c'*64, admitted_at=admitted.isoformat(),
        work_started_at=(admitted+timedelta(seconds=1)).isoformat(),
        work_deadline=(NOW+timedelta(seconds=15)).isoformat(),
        supersession_started_at=admitted.isoformat(),
        supersession_deadline=(admitted+timedelta(minutes=10)).isoformat())
    worker = original.row('shadow_worker')
    if fault != 'worker_idle':
        worker = replace(worker, operational_fact=model.OperationalFact(
            kind='SHADOW_WORKER', state='ACTIVE_WORKER'))
    if fault == 'no_rollover':
        attempt.update(supersession_started_at=None, supersession_deadline=None)
    elif fault == 'older_attempt':
        conn.execute('UPDATE sentinel_corpus_publications SET published_at=%s', (admitted,))
        attempt['supersession_started_at'] = published.isoformat()
    elif fault == 'chain_before_publication':
        chain = published - timedelta(microseconds=1)
        attempt.update(supersession_started_at=chain.isoformat(),
                       supersession_deadline=(chain+timedelta(minutes=10)).isoformat())
    elif fault == 'work_expired':
        attempt['work_deadline'] = NOW.isoformat()
    # The composite feed may sample the exact published frontier after the
    # rolling observer has already started. The physical publication did not move.
    feed = replace(original.row('feed'), as_of=NOW-timedelta(seconds=2))
    panel = replace(original, rows=[feed, original.row('shadow_verification'), worker])
    proof = capture((conn, panel))
    if fault is not None:
        assert proof is None
        return
    assert datetime.fromisoformat(proof['verification_publication_at']) == published
    assert datetime.fromisoformat(proof['deadline']) == NOW+timedelta(seconds=15)
    signed = replace(panel, trial_details={**panel.trial_details, 'readiness_handoff': proof})
    result = waiting.project_panel(signed, now=NOW, subject=SUBJECT)
    assert result.row('feed').effective_status(NOW) == model.WARN
    assert result.row('feed').as_of == feed.as_of
    assert result.row('feed').operational_fact.state == 'AWAITING_VERDICT'
    deadline = NOW+timedelta(seconds=15)
    assert waiting.project_panel(signed, now=deadline, subject=SUBJECT).row('feed').effective_status(deadline) == model.FAIL


def test_foreign_attempt_publication_guard_has_an_executed_falsifier(metadata, monkeypatch):
    source = inspect.getsource(handoff._superseded_attempt)
    guard = 'and published <= attempt.supersession_started_at'
    assert source.count(guard) == 1
    scope = dict(vars(handoff))
    exec(compile(source.replace(guard, ''),'<unbound foreign attempt>','exec'),scope)
    monkeypatch.setattr(handoff,'_superseded_attempt',scope['_superseded_attempt'])
    with pytest.raises(AssertionError):
        test_running_prior_subject_can_explain_published_readiness_rollover(metadata,'chain_before_publication')


def test_committed_close_can_bridge_only_the_original_verifier_admission_gap(metadata):
    conn, original = metadata
    published_at = NOW - timedelta(seconds=47)
    conn.execute('UPDATE sentinel_corpus_publications SET published_at=%s', (published_at,))
    conn.execute('UPDATE sentinel_snapshot_jobs SET updated_at=%s', (published_at,))
    attempt = original.trial_details['verification_attempts']['SHADOW']['latest']
    attempt.update(outcome='VERIFIED', subject_sha256='e'*64,
        admitted_at=(NOW-timedelta(minutes=2)).isoformat(),
        work_started_at=(NOW-timedelta(minutes=2)).isoformat(),
        completed_at=(NOW-timedelta(seconds=65)).isoformat())
    feed = replace(original.row('feed'), as_of=NOW-timedelta(seconds=5))
    worker = replace(original.row('shadow_worker'), operational_fact=model.OperationalFact(
        kind='SHADOW_WORKER', state='ACTIVE_WORKER'))
    panel = replace(original, rows=[feed, original.row('shadow_verification'), worker])
    proof = capture((conn, panel))
    deadline = published_at + timedelta(seconds=60)
    assert proof is not None and datetime.fromisoformat(proof['deadline']) == deadline
    assert datetime.fromisoformat(proof['admission_publication_at']) == published_at
    signed = replace(panel, trial_details={**panel.trial_details, 'readiness_handoff':proof})
    projected = waiting.project_panel(signed, now=NOW, subject=SUBJECT)
    assert projected.row('feed').effective_status(NOW) == model.WARN
    assert projected.row('feed').as_of == feed.as_of
    assert projected.row('feed').operational_fact.state == 'AWAITING_VERDICT'
    assert waiting.project_panel(signed, now=deadline, subject=SUBJECT).row('feed').effective_status(deadline) == model.FAIL
    assert waiting.project_panel(signed, now=NOW, subject='c'*64).row('feed').effective_status(NOW) == model.FAIL
    attempt.update(outcome='FAILED')
    assert capture((conn, panel)) is None
    assert waiting.project_panel(signed, now=NOW, subject=SUBJECT).row('feed').effective_status(NOW) == model.FAIL


@pytest.mark.parametrize('fault', [None, 'job_precedes_header', 'job_after_observation',
                                   'predecessor_after_job', 'admission_expired'])
def test_prior_verifier_finishing_while_publication_transaction_is_open(metadata, fault):
    conn, panel = metadata
    header = NOW - timedelta(seconds=50)
    terminal = header + timedelta(seconds=46)
    finished = header + timedelta(seconds=3)
    feed_at = terminal
    if fault == 'job_precedes_header':
        terminal = header - timedelta(milliseconds=1)
        finished = terminal - timedelta(seconds=1)
    elif fault == 'job_after_observation':
        terminal = feed_at + timedelta(milliseconds=1)
    elif fault == 'predecessor_after_job':
        finished = terminal
        feed_at = terminal + timedelta(seconds=1)
    elif fault == 'admission_expired':
        header, finished, terminal = (t-timedelta(seconds=60) for t in (header, finished, terminal))
    conn.execute('UPDATE sentinel_corpus_publications SET published_at=%s', (header,))
    conn.execute('UPDATE sentinel_snapshot_jobs SET updated_at=%s', (terminal,))
    attempt = panel.trial_details['verification_attempts']['SHADOW']['latest']
    attempt.update(outcome='VERIFIED', subject_sha256='e'*64,
        admitted_at=(finished-timedelta(minutes=2)).isoformat(),
        work_started_at=(finished-timedelta(seconds=118)).isoformat(), completed_at=finished.isoformat())
    feed = replace(panel.row('feed'), as_of=feed_at)
    worker = replace(panel.row('shadow_worker'), operational_fact=model.OperationalFact(
        kind='SHADOW_WORKER', state='ACTIVE_WORKER'))
    panel = replace(panel, rows=[feed, panel.row('shadow_verification'), worker])
    proof = capture((conn, panel))
    if fault:
        assert proof is None
        return
    assert proof and datetime.fromisoformat(proof['admission_publication_at']) == terminal
    signed = replace(panel, trial_details={**panel.trial_details, 'readiness_handoff':proof})
    row = waiting.project_panel(signed, now=NOW, subject=SUBJECT).row('feed')
    assert row.effective_status(NOW) == model.WARN and row.feed_readiness == 'AWAITING_VERDICT'
    assert row.effective_status(row.valid_until+timedelta(microseconds=1)) == model.FAIL


def candidate_panel(metadata):
    conn, original = metadata
    observed = NOW-timedelta(seconds=45)
    attempt = original.trial_details['verification_attempts']['SHADOW']['latest']
    attempt.update(outcome='VERIFIED', completed_at=(observed+timedelta(seconds=1)).isoformat(),
                   subject_sha256='e'*64)
    shadow = replace(original.row('shadow_verification'), as_of=observed,
        source_publication_version=17, source_session='2026-11-09')
    worker = replace(original.row('shadow_worker'), operational_fact=model.OperationalFact(
        kind='SHADOW_WORKER', state='ACTIVE_WORKER'))
    return replace(original, rows=[original.row('feed'), shadow, worker],
                   display_basis={'native':{'SHADOW':SUBJECT}})


def test_candidate_handoff_has_one_owned_exact_witness_and_negative_precedence(metadata, monkeypatch):
    conn, _ = metadata
    original = candidate_panel(metadata)
    observed = original.row('shadow_verification').as_of
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
    current = waiting.project_panel(signed, subject=SUBJECT, now=NOW)
    assert current.row('feed').effective_status(NOW) == model.WARN
    assert current.row('shadow_verification').value == 'CHECKING'
    failed = replace(original.row('shadow_verification'), status=model.FAIL, recovery=None)
    signed = replace(signed, rows=[signed.row('feed'), failed, original.row('shadow_worker')])
    assert read(signed) is None
    assert waiting.project_panel(signed, subject=SUBJECT, now=NOW).row('feed').effective_status(NOW) == model.FAIL


def test_only_the_composition_authenticates_the_cold_candidate(metadata, monkeypatch):
    from sentinel.panel import attempt_store, review_store
    conn, _ = metadata
    panel = candidate_panel(metadata)
    diagnostic = panel.trial_details['verification_attempts']['SHADOW']
    monkeypatch.setattr(attempt_store, 'read_owned', lambda *args, **kwargs: diagnostic)
    monkeypatch.setattr(review_store, 'database_now', lambda conn: NOW)
    owner = uuid.uuid4()
    conn.execute('CREATE TEMP TABLE sentinel_operational_verification_owner(id int,owner_id uuid,expires_at timestamptz)')
    conn.execute("INSERT INTO sentinel_operational_verification_owner VALUES(1,%s,clock_timestamp()+interval '10 minutes')",
                 (owner,))
    calls = []
    def archive_check(conn, *, pub, binding, closed, now):
        calls.append(pub.version)
        return 'd'*64, panel.row('shadow_verification').as_of
    monkeypatch.setattr(handoff, '_checkpoint_bound', archive_check)
    memo = handoff.CandidateMemo()
    assert handoff._compose_candidate_owned(conn, uuid.uuid4(), panel, memo) is None and not calls
    witness = handoff._compose_candidate_owned(conn, owner, panel, memo)
    assert witness['progress']['checkpoint_sha256'] == 'd'*64 and calls == [17]
    assert handoff._compose_candidate_owned(conn, owner, panel, memo) == witness and calls == [17]
    def fast(value, subject=SUBJECT, now=NOW, owner_expiry=NOW+timedelta(minutes=5)):
        return handoff.capture(conn, panel, subject=subject, now=now, owner_expiry=owner_expiry,
                               prepared_candidate=value)
    assert fast(witness) == witness['progress']
    assert fast(None) is None, 'fast publisher authenticated an absent composition witness'
    assert fast(witness, subject='f'*64) is None
    assert fast(witness, owner_expiry=NOW) is None
    for field, invalid in (('checkpoint_sha256', None), ('subject_sha256','e'*64), ('session','2026-11-06'),
                           ('publication_version',18), ('attempt_id','b'*32), ('deadline',NOW.isoformat())):
        wrong = deepcopy(witness)
        wrong['progress'][field] = invalid
        assert fast(wrong) is None
    assert fast({**witness, 'publication_sha256':'f'*64}) is None
    assert fast(witness, now=datetime.fromisoformat(witness['progress']['deadline'])) is None
    assert calls == [17], 'five-second publication tried to reauthenticate the full archive'
    # Every installation, including those with legacy checkpoint encodings, uses
    # the full authenticated reader on a cold composition. A failed read cannot
    # reach fast publication through a new native subject.
    monkeypatch.setattr(handoff, '_checkpoint_bound', lambda *args, **kwargs: None)
    assert handoff._compose_candidate_owned(conn, owner, panel, handoff.CandidateMemo()) is None

    # The composition should not repeat the fast publisher's metadata query
    # for ordinary current, queued, invalid or already-finished work.
    def unexpected(*args, **kwargs):
        pytest.fail('ineligible candidate attempted publication lineage or archive IO')
    monkeypatch.setattr(handoff, 'capture', unexpected)
    attempt = diagnostic['latest']
    prior = dict(attempt)
    for change in ({'subject_sha256':SUBJECT}, {'outcome':'QUEUED', 'completed_at':None,
                        'work_started_at':None, 'work_deadline':None},
                   {'completed_at':(panel.row('shadow_verification').as_of-timedelta(seconds=1)).isoformat()},
                   {'outcome':'RUNNING', 'completed_at':None}, {'outcome':'malformed'}):
        diagnostic['latest'] = {**prior, **change}
        assert handoff._compose_candidate_owned(conn, owner, panel, memo) is None


def test_ordinary_composition_opens_no_candidate_database_connection(monkeypatch):
    from sentinel.feed import store
    def unexpected(*args, **kwargs):
        pytest.fail('ordinary composition opened a candidate database connection')
    monkeypatch.setattr(store, 'connect', unexpected)
    for snapshot in (page(), page(typed=True), model.Panel(now=NOW, rows=[])):
        assert handoff.compose_candidate('unused', 'unused', snapshot, memo=handoff.CandidateMemo()) is None


def test_restoring_a_cold_fallback_in_fast_publication_breaks_its_budget_contract(metadata, monkeypatch):
    source = inspect.getsource(handoff.capture)
    guard = 'if candidate_memo is not None:'
    assert source.count(guard) == 1
    scope = dict(vars(handoff))
    exec(compile(source.replace(guard, 'if candidate_memo is not None or (candidate_memo := CandidateMemo()):'),
                 '<cold archive on fast path>', 'exec'), scope)
    monkeypatch.setattr(handoff, 'capture', scope['capture'])
    with pytest.raises(AssertionError, match='fast publisher authenticated an absent composition witness'):
        test_only_the_composition_authenticates_the_cold_candidate(metadata, monkeypatch)


def test_row_clock_diagnostic_is_closed_and_preserves_strict_refusal(monkeypatch,caplog):
    monkeypatch.setenv('SENTINEL_PUBLICATION_RECEIPT_KEY','private-test-'+'x'*40)
    bad = model.Row('secret DSN account text','secret','secret',model.OK,
        as_of=NOW.astimezone(timezone(timedelta(hours=-5))))
    with caplog.at_level(logging.WARNING), pytest.raises(wire.SnapshotUnavailable,match='SNAPSHOT_ROW_CLOCK_INVALID'):
        wire.encode(model.Panel(now=NOW,rows=[bad]),context_sha256='a'*64,
            subjects={'SHADOW':'b'*64,'PAPER':'c'*64})
    assert 'key=OTHER field=as_of kind=NON_UTC' in caplog.text
    assert 'secret' not in caplog.text and '-05:00' not in caplog.text
