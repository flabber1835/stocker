"""Current ordinary source-job metadata is progress, never financial admission."""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import inspect
import json
from types import SimpleNamespace
import uuid

import psycopg
import pytest

from sentinel.feed import calendar, operational_snapshot, rolling_go_inputs
from sentinel.feed.rolling_contract import PriceWindow, digest
from sentinel.feed.rolling_jobs import PreparationRequest
from sentinel.panel import model, sources
from tests.support.postgres import _EphemeralPostgres


NOW = datetime(2026, 10, 30, 20, 30, tzinfo=timezone.utc)
TARGET = '2026-10-30'


def request(target=TARGET, **changes):
    values = dict(window=PriceWindow.through(target), expected_publication_version=7,
        strategy_sha256='a'*64, dependencies_sha256=digest({
            'schema': operational_snapshot.SCHEMA,
            'dependencies': digest({'scope': rolling_go_inputs.SCHEMA})}))
    values.update(changes)
    return PreparationRequest(**values).model_dump(mode='json')


def record(**changes):
    raw = request()
    job = dict(job_id=str(uuid.uuid4()), request=raw, request_sha256=digest(raw),
        state='ACQUIRING', rows_done=1720712, created_at=NOW-timedelta(minutes=20),
        updated_at=NOW, last_progress_at=NOW-timedelta(minutes=2),
        deadline=NOW+timedelta(hours=1), lease_until=NOW+timedelta(minutes=5),
        fence=4, next_retry=None, publication_version=None)
    job.update(changes)
    return [job, NOW, 7, 6, False, True, 31]


class Connection:
    def __init__(self, candidates, latest=None):
        self.candidates = candidates
        job_id = candidates[0][0]['job_id'] if candidates else str(uuid.uuid4())
        self.latest = latest or ('ACQUIRING', None, NOW, 1720712, None, job_id)
        self.queries = []

    def execute(self, sql, params=None):
        self.queries.append((sql, params))
        return self

    def fetchone(self):
        return self.latest

    def fetchall(self):
        return self.candidates


def test_current_registered_request_exports_dated_progress_without_changing_run_status():
    connection = Connection([record()])
    result = sources._operational_acquisition(connection, now=NOW)[0]
    work = model.PreparationWork.model_validate(result.pop('preparation'))
    assert result == dict(kind='OPERATIONAL SNAPSHOT', status='running', updated_at=NOW,
        rows_written=1720712, chunks_done=0, chunks_total=0,
        current_chunk='ACQUIRING', error_message=None)
    assert work.decision_session == date(2026, 10, 30)
    assert work.effective_session == date(2026, 11, 2)
    assert work.active_at(NOW) and work.rows_done == 1720712 and work.components_done == 31
    assert work.last_progress_at == NOW-timedelta(minutes=2)
    assert len(connection.queries) == 2
    assert connection.queries[1] == (sources._PREPARATION_SQL, (TARGET,))


@pytest.mark.parametrize('fault', ['hash', 'scope', 'cursor', 'target', 'before_close',
    'cas', 'naive_clock', 'future_progress', 'bool_count', 'unknown_field'])
def test_invalid_optional_progress_preserves_the_original_run(fault):
    value = record()
    job = value[0]
    if fault == 'hash': job['request_sha256'] = 'f'*64
    elif fault == 'scope': job['request']['dependencies_sha256'] = 'f'*64
    elif fault == 'cursor': job['request']['cursor'] = TARGET
    elif fault == 'target': job['request'] = request('2026-10-29')
    elif fault == 'before_close': job['created_at'] = calendar.session_window(TARGET)[1]-timedelta(seconds=1)
    elif fault == 'cas': value[2] = 8
    elif fault == 'naive_clock': job['updated_at'] = NOW.replace(tzinfo=None)
    elif fault == 'future_progress': job['last_progress_at'] = NOW+timedelta(seconds=1)
    elif fault == 'bool_count': job['rows_done'] = True
    elif fault == 'unknown_field': job['request']['unreviewed'] = True
    if fault not in {'hash'}: job['request_sha256'] = digest(job['request'])
    result = sources._operational_acquisition(Connection([value]), now=NOW)[0]
    assert 'preparation' not in result, 'invalid request earned current producer progress'
    assert result['status'] == 'running' and result['rows_written'] == 1720712


def test_missing_and_ambiguous_jobs_do_not_promote_activity():
    for rows in ([], [record(), record()]):
        assert 'preparation' not in sources._operational_acquisition(Connection(rows), now=NOW)[0]


def test_another_latest_jobs_status_cannot_receive_the_current_candidates_progress():
    latest = ('ACQUIRING', None, NOW, 777, None, str(uuid.uuid4()))
    result = sources._operational_acquisition(Connection([record()], latest=latest), now=NOW)[0]
    assert 'preparation' not in result, 'another job received current producer ownership'
    assert result['status'] == 'running' and result['rows_written'] == 777


def test_latest_job_identity_guard_has_an_executed_removal_falsifier(monkeypatch):
    source = inspect.getsource(sources._operational_acquisition)
    guard = "if str(candidates[0][0]['job_id']) == str(latest_job_id):"
    assert source.count(guard) == 1
    namespace = dict(vars(sources))
    exec(compile(source.replace(guard, 'if True:'), '<missing-latest-job-binding>', 'exec'), namespace)
    monkeypatch.setattr(sources, '_operational_acquisition', namespace['_operational_acquisition'])
    with pytest.raises(AssertionError, match='another job received'):
        test_another_latest_jobs_status_cannot_receive_the_current_candidates_progress()


@pytest.mark.parametrize('fault', ['owner', 'lease', 'deadline', 'fence'])
def test_dead_expired_and_unfenced_metadata_is_never_working(fault):
    value = record()
    if fault == 'owner': value[5] = False
    elif fault == 'lease': value[0]['lease_until'] = NOW
    elif fault == 'deadline':
        value[0]['deadline'] = NOW
        value[0]['lease_until'] = NOW
    elif fault == 'fence': value[0]['fence'] = 0
    result = sources._operational_acquisition(Connection([value]), now=NOW)[0]
    assert not model.PreparationWork.model_validate(result['preparation']).active_at(NOW)


def test_published_progress_requires_exact_current_publication_job_and_candidate():
    value = record(state='PUBLISHED', publication_version=8)
    value[2:5] = [8, 7, True]
    assert sources._preparation_work(value, target=TARGET)['state'] == 'PUBLISHED'
    for index, changed in ((2, 9), (3, 6), (4, False)):
        bad = deepcopy(value)
        bad[index] = changed
        with pytest.raises(ValueError):
            sources._preparation_work(bad, target=TARGET)


def test_progress_never_calls_strategy_identity_corpus_or_provider_work(monkeypatch):
    from sentinel import strategy
    from sentinel.core import decision

    def forbidden(*args, **kwargs):
        raise AssertionError('progress invoked source identity or financial admission')
    monkeypatch.setattr(strategy, 'production_strategy', forbidden)
    monkeypatch.setattr(decision.identity, 'source_hash', forbidden)
    monkeypatch.setattr(rolling_go_inputs, 'validate_status', forbidden)
    result = sources._operational_acquisition(Connection([record()]), now=NOW)[0]
    assert result['preparation']['rows_done'] == 1720712
    sql = sources._PREPARATION_SQL.lower()
    assert 'limit 2' in sql
    assert all(name not in sql for name in ('sentinel_bars', 'acquisition_prices',
        'sentinel_automation', 'sentinel_execution', 'copy ', 'update ', 'insert '))


def test_feed_ingest_exports_typed_progress_without_changing_the_readiness_verdict(monkeypatch):
    from sentinel.feed import store

    connection = Connection([])
    monkeypatch.setenv('SENTINEL_REVIEWED_DEPLOYMENT_MODE', 'shadow')
    monkeypatch.setattr(store, 'connect', lambda *_: connection)
    monkeypatch.setattr(sources, '_set_statement_timeout', lambda *_: None)
    run = sources._operational_acquisition(Connection([record()]), now=NOW)[0]
    monkeypatch.setattr(sources, '_operational_acquisition', lambda *_: [run])
    monkeypatch.setattr(sources, '_feed_status_snapshot', lambda *_: ('2026-10-29',
        SimpleNamespace(ready=False, checks_passed=13, checks_total=14, computed_at=NOW)))
    monkeypatch.setattr(calendar, 'freshness', lambda *_:
        SimpleNamespace(sessions_behind=1, ahead=False))
    rows, errors = sources._feed_rows('postgresql://fixture@isolated.invalid/fixture', now=NOW)
    ingest = next(row for row in rows if row.key == 'ingest')
    feed = next(row for row in rows if row.key == 'feed')
    assert not errors and ingest.preparation is not None
    assert ingest.preparation.active_at(NOW)
    assert ingest.status == model.WARN and feed.status != model.OK
    assert ingest.preparation.effective_session == date(2026, 11, 2)


def test_current_publication_cas_validation_has_an_executed_removal_falsifier(monkeypatch):
    source = inspect.getsource(sources._preparation_work)
    guard = "elif request.expected_publication_version != current_version:"
    assert source.count(guard) == 1
    namespace = dict(vars(sources))
    exec(compile(source.replace(guard, 'elif False:'), '<missing-progress-cas>', 'exec'), namespace)
    monkeypatch.setattr(sources, '_preparation_work', namespace['_preparation_work'])
    with pytest.raises(AssertionError, match='invalid request earned'):
        test_invalid_optional_progress_preserves_the_original_run('cas')


@pytest.fixture(scope='module')
def private_pg():
    server = _EphemeralPostgres()
    server.start()
    try:
        yield server
    finally:
        server.stop()


def metadata_database(private_pg, *, registered=True, cursor=None, cas=7,
                      published=False, correct_candidate=True):
    conn = psycopg.connect(private_pg.sync_dsn)
    conn.execute('CREATE TEMP TABLE sentinel_snapshot_jobs(job_id uuid PRIMARY KEY, '
        'request jsonb,request_sha256 text,state text,created_at timestamptz,updated_at timestamptz,'
        'last_progress_at timestamptz,deadline timestamptz,lease_until timestamptz,'
        'owner uuid,fence bigint,next_retry timestamptz,rows_done bigint,'
        'publication_version bigint,candidate_id uuid,reason text)')
    conn.execute('CREATE TEMP TABLE sentinel_operational_snapshot_jobs(job_id uuid PRIMARY KEY)')
    conn.execute('CREATE TEMP TABLE sentinel_snapshot_workers(owner uuid PRIMARY KEY,job_id uuid)')
    conn.execute('CREATE TEMP TABLE sentinel_snapshot_job_components(job_id uuid,component text,PRIMARY KEY(job_id,component))')
    conn.execute('CREATE TEMP TABLE sentinel_corpus_publications(version bigint PRIMARY KEY,previous_version bigint)')
    conn.execute('CREATE TEMP TABLE sentinel_operational_snapshots(publication_version bigint PRIMARY KEY,job_id uuid,candidate_id uuid)')
    observed = conn.execute('SELECT clock_timestamp()').fetchone()[0]
    target = calendar.latest_closed_session(observed)
    raw = request(target, expected_publication_version=cas, cursor=cursor)
    job, owner, candidate = (str(uuid.uuid4()) for _ in range(3))
    created = calendar.session_window(target)[1]+timedelta(seconds=1)
    conn.execute('INSERT INTO sentinel_snapshot_jobs(job_id,request,request_sha256,state,created_at,'
        'updated_at,last_progress_at,deadline,lease_until,owner,fence,next_retry,rows_done,'
        'publication_version,candidate_id) VALUES(%s,%s::jsonb,%s,%s,%s,%s,%s,%s,%s,%s,4,NULL,123,%s,%s)',
        (job,json.dumps(raw),digest(raw),'PUBLISHED' if published else 'ACQUIRING',
         created,observed,observed,observed+timedelta(hours=1),observed+timedelta(minutes=5),
         owner,8 if published else None,candidate))
    if registered:
        conn.execute('INSERT INTO sentinel_operational_snapshot_jobs VALUES(%s)', (job,))
    conn.execute('INSERT INTO sentinel_snapshot_workers VALUES(%s,%s)', (owner,job))
    conn.execute("INSERT INTO sentinel_snapshot_job_components VALUES(%s,'SEP')", (job,))
    conn.execute('INSERT INTO sentinel_corpus_publications VALUES(%s,%s)', (8,7) if published else (7,6))
    if published:
        conn.execute('INSERT INTO sentinel_operational_snapshots VALUES(8,%s,%s)',
            (job,candidate if correct_candidate else str(uuid.uuid4())))
    return conn, target


@pytest.mark.parametrize('case,expected', [('current', True), ('unregistered', False),
    ('reconstruction', False), ('foreign_cas', False), ('published', True),
    ('wrong_candidate', False)])
def test_real_sql_selects_only_current_registered_ordinary_cas_or_exact_publication(private_pg, case, expected):
    conn, target = metadata_database(private_pg, registered=case!='unregistered',
        cursor=date(2026, 10, 1) if case=='reconstruction' else None,
        cas=6 if case=='foreign_cas' else 7,
        published=case in {'published','wrong_candidate'}, correct_candidate=case!='wrong_candidate')
    try:
        rows = conn.execute(sources._PREPARATION_SQL, (target,)).fetchall()
        assert bool(rows) is expected, 'foreign metadata earned current source progress'
        if expected:
            progress = model.PreparationWork.model_validate(sources._preparation_work(rows[0], target=target))
            assert progress.components_done == 1 and progress.rows_done == 123
            assert progress.owner_registered
            run = sources._operational_acquisition(conn)[0]
            assert run['preparation']['job_id'] == progress.job_id
            assert run['status'] == ('success' if case == 'published' else 'running')
    finally:
        conn.close()


def test_removing_operational_registration_from_real_sql_is_detected(private_pg, monkeypatch):
    guard = 'JOIN sentinel_operational_snapshot_jobs o USING(job_id)'
    assert sources._PREPARATION_SQL.count(guard) == 1
    monkeypatch.setattr(sources, '_PREPARATION_SQL', sources._PREPARATION_SQL.replace(guard, ''))
    with pytest.raises(AssertionError, match='foreign metadata earned'):
        test_real_sql_selects_only_current_registered_ordinary_cas_or_exact_publication(private_pg, 'unregistered', False)


def test_real_reader_never_attaches_one_jobs_current_progress_to_a_newer_foreign_cas_job(private_pg):
    conn, target = metadata_database(private_pg)
    try:
        foreign = request(target, expected_publication_version=6)
        newer_job = str(uuid.uuid4())
        conn.execute('INSERT INTO sentinel_snapshot_jobs '
            'SELECT %s,%s::jsonb,%s,state,clock_timestamp(),updated_at,last_progress_at,'
            'deadline,lease_until,owner,fence,next_retry,777,publication_version,candidate_id,reason '
            'FROM sentinel_snapshot_jobs LIMIT 1', (newer_job,json.dumps(foreign),digest(foreign)))
        conn.execute('INSERT INTO sentinel_operational_snapshot_jobs VALUES(%s)', (newer_job,))
        candidates = conn.execute(sources._PREPARATION_SQL, (target,)).fetchall()
        assert len(candidates) == 1 and str(candidates[0][0]['job_id']) != newer_job
        run = sources._operational_acquisition(conn)[0]
        assert run['rows_written'] == 777 and run['status'] == 'running'
        assert 'preparation' not in run, 'another job received current producer ownership'
    finally:
        conn.close()
