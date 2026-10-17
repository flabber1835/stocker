"""Real SQL recovery of changing Alpaca captures before atomic publication."""
from copy import deepcopy
from datetime import datetime

import pytest

from sentinel.feed import operational_snapshot as op, preparation_wait
from sentinel.feed import rolling_jobs as jobs, rolling_store
from sentinel.feed.acquisition_parts import MAX_SUCCESSORS
from sentinel.feed.alpaca_source import AlpacaSource
from sentinel.feed.alpaca_transport import ACTION_URL, ASSETS, BAR_URL
from sentinel.feed.rolling_contract import digest
from tests.sentinel.test_alpaca_operational_snapshot import alpaca_path  # noqa: F401
from tests.sentinel.test_rolling_snapshot_publisher import conn, pg  # noqa: F401


def enqueue(conn, *, absolute_deadline=None):
    job = op.enqueue(conn, strategy_sha256=digest('revision-test-strategy'),
                     dependencies_sha256=digest('revision-test-dependencies'), budget_seconds=240,
                     absolute_deadline=absolute_deadline)
    conn.commit()
    return job


def test_foreground_transient_alpaca_failure_retries_original_job(conn, alpaca_path, monkeypatch):
    from sentinel.feed.alpaca_transport import AlpacaTransportUnavailable
    original = alpaca_path.get
    attempts = []
    def get(*args, **kwargs):
        attempts.append(True)
        if len(attempts) == 1:
            raise AlpacaTransportUnavailable('temporary source outage')
        return original(*args, **kwargs)
    monkeypatch.setattr(alpaca_path, 'get', get)
    job = enqueue(conn)
    deadline = jobs.status(conn, job)['deadline']
    def sleep(_seconds):
        state = jobs.status(conn, job)
        assert state['state'] == 'RETRY_WAIT' and state['reason'] == 'SOURCE_RETRY'
        assert state['deadline'] == deadline
        conn.execute('UPDATE sentinel_snapshot_jobs SET next_retry=clock_timestamp() WHERE job_id=%s', (job,))
        conn.commit()
    result = preparation_wait.run(conn, job, prepare=op.prepare,
        check_target=lambda: None, sleep=sleep)
    assert result['job_id'] == job and jobs.status(conn, job)['deadline'] == deadline
    assert len(attempts) >= 2


def test_fresh_equal_partitions_share_verified_payload_without_reusing_observation(conn, alpaca_path, monkeypatch, record_property):
    from sentinel.feed import retention
    monkeypatch.setattr(retention, 'maintain', lambda *_a, **_k: None)
    original = alpaca_path.pages
    revision = [0]
    def pages(endpoint, params, *, key):
        for values, proof in original(endpoint, params, key=key):
            if endpoint == BAR_URL and revision[0] == 2:
                values = deepcopy(values)
                for row in values.get('AAA', []):
                    if row['t'][:10] == str(alpaca_path.window.end):
                        row['c'] += 1
            yield values, {**proof, 'observed_at':f'2026-09-15T00:00:0{revision[0]}+00:00'}
    monkeypatch.setattr(alpaca_path, 'pages', pages)
    first = op.prepare(conn, enqueue(conn))
    rows = conn.execute('SELECT count(*) FROM sentinel_acquisition_prices').fetchone()[0]
    initial_bytes = conn.execute("SELECT pg_total_relation_size('sentinel_acquisition_prices')").fetchone()[0]
    requests = sum(endpoint == BAR_URL for endpoint, _ in alpaca_path.calls)
    revision[0] = 1
    second = op.prepare(conn, enqueue(conn))
    assert sum(endpoint == BAR_URL for endpoint, _ in alpaca_path.calls) == 2 * requests
    assert conn.execute('SELECT count(*) FROM sentinel_acquisition_prices').fetchone()[0] == rows
    shared_bytes = conn.execute("SELECT pg_total_relation_size('sentinel_acquisition_prices')").fetchone()[0]
    shared = conn.execute('SELECT l.part_id,l.payload_part_id,a.manifest,b.manifest '
        'FROM sentinel_acquisition_price_links l JOIN sentinel_acquisition_parts a ON a.part_id=l.part_id '
        'JOIN sentinel_acquisition_parts b ON b.part_id=l.payload_part_id').fetchall()
    assert shared
    assert all(a['job_id'] == second['job_id'] and b['job_id'] == first['job_id']
               and a['evidence'] != b['evidence'] for _, _, a, b in shared)
    assert all(conn.execute('SELECT sentinel_acquisition_part_pinned(%s)', (root,)).fetchone()[0]
               for _, root, _, _ in shared)
    revision[0] = 2
    third = op.prepare(conn, enqueue(conn))
    assert third['snapshot_id'] != second['snapshot_id']
    added = conn.execute('SELECT count(*) FROM sentinel_acquisition_prices').fetchone()[0] - rows
    assert 0 < added < rows
    record_property('fresh_baseline_rows', rows)
    record_property('equal_refresh_additional_rows', 0)
    record_property('changed_refresh_additional_rows', added)
    record_property('baseline_price_relation_bytes', initial_bytes)
    record_property('equal_refresh_price_relation_bytes', shared_bytes)
    record_property('bar_requests_per_complete_observation', requests)
    assert sum(endpoint == BAR_URL for endpoint, _ in alpaca_path.calls) == 3 * requests
    conn.commit()
    import psycopg
    with psycopg.connect(conn.info.dsn) as restarted:
        assert op.published(restarted, second['job_id']) == second
        assert rolling_store.verify_content(restarted, third['candidate_id']).snapshot_id == third['snapshot_id']


def test_retained_partition_auxiliary_missing_key_evidence_is_authenticated(conn, alpaca_path):
    from sentinel.feed.acquisition_parts import Parts, PartCorrupt
    published = op.prepare(conn, enqueue(conn))
    part = conn.execute("SELECT part_id FROM sentinel_acquisition_bindings WHERE job_id=%s "
        "AND component LIKE 'SEP.%%' ORDER BY component LIMIT 1", (published['job_id'],)).fetchone()[0]
    conn.execute('SET LOCAL session_replication_role=replica')
    conn.execute("UPDATE sentinel_acquisition_parts SET reference_payload=%s::jsonb WHERE part_id=%s",
        ('{"pair_absent":[["AAA","2026-09-14"]]}', part))
    with pytest.raises(PartCorrupt, match='auxiliary payload'):
        Parts(conn, None)._manifest(part, defer_prices=True)
    conn.rollback()


def test_backup_renewal_keeps_ready_candidate_and_does_not_repeat_downloads(conn, alpaca_path, monkeypatch, capsys):
    from sentinel import backup_runtime_authority as backup
    job = enqueue(conn)
    deadline = jobs.status(conn, job)['deadline']
    require, corroborate = backup.require, AlpacaSource.corroborate
    ready_checks, observations = [], []
    def durability(conn, *, operation, **kwargs):
        if operation == 'operational publication preflight':
            ready_checks.append(operation)
            if len(ready_checks) == 1:
                raise backup.BackupHorizonExceeded('fixture restore horizon exceeded')
        return require(conn, operation=operation, **kwargs)
    def observed(source):
        observations.append(True)
        return corroborate(source)
    monkeypatch.setattr(backup, 'require', durability)
    monkeypatch.setattr(AlpacaSource, 'corroborate', observed)
    with pytest.raises(backup.BackupHorizonExceeded) as paused:
        op.prepare(conn, job)
    assert paused.value.resume_job_id == job
    assert observations == [] and jobs.status(conn, job)['candidate_id'] is not None
    candidate = jobs.status(conn, job)['candidate_id']
    downloads = sum(endpoint == BAR_URL for endpoint, _ in alpaca_path.calls)
    conn.execute('UPDATE sentinel_snapshot_jobs SET next_retry=clock_timestamp() WHERE job_id=%s', (job,))
    conn.commit()
    result = op.prepare(conn, job)
    assert result['candidate_id'] == candidate and jobs.status(conn, job)['deadline'] == deadline
    assert sum(endpoint == BAR_URL for endpoint, _ in alpaca_path.calls) == downloads
    assert observations == [True] and len(ready_checks) == 2
    assert conn.execute('SELECT COUNT(*) FROM sentinel_corpus_publications').fetchone()[0] == 1
    from scripts import sentinel_go_feed_progress
    progress_output = capsys.readouterr().err
    assert progress_output.count('"stage": "rolling_source_corroboration"') == 2
    parsed = sentinel_go_feed_progress.collect(progress_output)
    assert [event['status'] for event in parsed if event['stage'] == 'rolling_source_corroboration'] == [
        'started', 'completed']


def test_removed_publication_preflight_is_detected(conn, alpaca_path, monkeypatch, capsys):
    """A guard-removal falsifier; mutation exists only in this test process."""
    import inspect
    from sentinel.feed import rolling_publisher
    original = inspect.getsource(rolling_publisher._prepare)
    guard = 'backup_runtime_authority.require(conn, operation="operational publication preflight")'
    assert guard in original
    namespace = dict(vars(rolling_publisher))
    exec(compile(original.replace(guard, 'pass'), '<removed publication preflight>', 'exec'), namespace)
    monkeypatch.setattr(rolling_publisher, '_prepare', namespace['_prepare'])
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        test_backup_renewal_keeps_ready_candidate_and_does_not_repeat_downloads(
            conn, alpaca_path, monkeypatch, capsys)


def changing_source(fake, monkeypatch, *, change, persistent=False):
    version = [0]
    observed = []
    get, pages = fake.get, fake.pages

    def inventory(endpoint, params=None, **kwargs):
        data, proof = get(endpoint, params, **kwargs)
        if endpoint == ASSETS and change == 'inventory' and version[0]:
            data = deepcopy(data)
            data.append({'id':'uuid-CCC', 'symbol':'CCC', 'class':'us_equity',
                         'status':'active', 'tradable':True, 'exchange':'NASDAQ'})
        return data, proof

    def actions(endpoint, params, *, key):
        if endpoint != ACTION_URL:
            yield from pages(endpoint, params, key=key)
            return
        fake.calls.append((endpoint, params))
        record = {'id':'dividend-id', 'process_date':'2026-09-01',
                  'ex_date':'2026-09-01', 'symbol':'BBB', 'rate':0.25, 'foreign':False}
        records = [record] if change in {'removal','amount'} else []
        kind = 'cash_dividends'
        if version[0]:
            if change == 'removal': records = []
            if change == 'amount': record['rate'] = 0.25 + version[0]/4
            if change == 'structural':
                kind = 'forward_splits'
                records = [{'id':'structural-id','process_date':'2026-09-01',
                            'ex_date':'2026-09-01','symbol':'BBB'}]
        yield {kind:records}, {'observed_at':'2026-09-15T00:00:00+00:00',
                              'sha256':digest(records)}

    corroborate = AlpacaSource.corroborate

    def revise(source):
        if persistent or not observed:
            version[0] += 1
        observed.append(sum(endpoint == BAR_URL for endpoint, _ in fake.calls))
        return corroborate(source)

    monkeypatch.setattr(fake, 'get', inventory)
    monkeypatch.setattr(fake, 'pages', actions)
    monkeypatch.setattr(AlpacaSource, 'corroborate', revise)
    return observed


def assert_successor(conn, parent, result, deadline):
    state = jobs.status(conn, parent)
    assert state['state'] == 'REFUSED' and state['reason'] == 'SOURCE_GENERATION_CHANGED'
    child = str(conn.execute('SELECT child_job_id FROM sentinel_acquisition_successors '
                             'WHERE parent_job_id=%s', (parent,)).fetchone()[0])
    assert result['job_id'] == child and jobs.status(conn, child)['state'] == 'PUBLISHED'
    assert jobs.status(conn, child)['deadline'] == deadline
    assert conn.execute('SELECT count(*) FROM sentinel_corpus_publications').fetchone()[0] == 1
    return child


@pytest.mark.parametrize('change', ['removal', 'amount'])
def test_foreground_dividend_revision_reuses_prices_and_original_deadline(
        conn, alpaca_path, monkeypatch, change):
    observed = changing_source(alpaca_path, monkeypatch, change=change)
    parent = enqueue(conn)
    deadline = jobs.status(conn, parent)['deadline']
    result = preparation_wait.run(conn, parent, prepare=op.prepare, check_target=lambda:None)
    assert_successor(conn, parent, result, deadline)
    assert len(observed) == 2 and observed[0] == observed[1]
    assert sum(endpoint == BAR_URL for endpoint, _ in alpaca_path.calls) == observed[0]
    assert len(alpaca_path.classifier.calls) == 1
    reference = rolling_store.load_evidence(conn,
        rolling_store.manifest(conn, result['candidate_id']).reference_sha256)
    assert reference['actions'] == ([] if change == 'removal' else [
        {'date':'2026-09-01','action':'dividend','ticker':'BBB','name':None,
         'value':'0.5','contraticker':None,'contraname':None}])
    bars = list(rolling_store.read_bars(conn, result['candidate_id']))
    event = next(row for row in bars if row.ticker == 'BBB' and str(row.session) == '2026-09-01')
    assert event.dividend_per_share == (0 if change == 'removal' else 0.5)


def test_daily_slice_queues_revision_then_reclaims_child_without_price_downloads(
        conn, alpaca_path, monkeypatch):
    observed = changing_source(alpaca_path, monkeypatch, change='removal')
    parent = enqueue(conn)
    deadline = jobs.status(conn, parent)['deadline']
    with pytest.raises(jobs.JobWaiting, match='successor queued'):
        preparation_wait.once(conn, parent, prepare=op.prepare, check_target=lambda:None)
    assert conn.execute('SELECT count(*) FROM sentinel_corpus_publications').fetchone()[0] == 0
    child = enqueue(conn)
    assert child != parent
    result = preparation_wait.once(conn, child, prepare=op.prepare, check_target=lambda:None)
    assert_successor(conn, parent, result, deadline)
    assert observed[0] == observed[1]
    assert len(alpaca_path.classifier.calls) == 1


def test_structural_revision_reacquires_incompatible_prices(conn, alpaca_path, monkeypatch):
    observed = changing_source(alpaca_path, monkeypatch, change='structural')
    parent = enqueue(conn)
    deadline = jobs.status(conn, parent)['deadline']
    result = preparation_wait.run(conn, parent, prepare=op.prepare, check_target=lambda:None)
    assert_successor(conn, parent, result, deadline)
    assert observed[1] > observed[0]
    assert len(alpaca_path.classifier.calls) == 1
    bars = [row for row in rolling_store.read_bars(conn, result['candidate_id']) if row.ticker == 'BBB']
    assert bars and all(str(row.session) > '2026-09-01' for row in bars)


def test_inventory_revision_rebuilds_classification_and_aggregate_references(
        conn, alpaca_path, monkeypatch):
    observed = changing_source(alpaca_path, monkeypatch, change='inventory')
    parent = enqueue(conn)
    deadline = jobs.status(conn, parent)['deadline']
    result = preparation_wait.run(conn, parent, prepare=op.prepare, check_target=lambda:None)
    assert_successor(conn, parent, result, deadline)
    assert observed[1] > observed[0]
    assert [len(group) for group in alpaca_path.classifier.calls] == [2,3]
    manifest = rolling_store.manifest(conn, result['candidate_id'])
    assert manifest.bar_count == 900
    reference = rolling_store.load_evidence(conn, manifest.reference_sha256)
    assert {row['ticker'] for row in reference['tickers']} == {'AAA','BBB','CCC'}


def test_cosmetic_inventory_revision_does_not_repeat_acquisition(
        conn, alpaca_path, monkeypatch):
    original = alpaca_path.get
    reads = []

    def inventory(endpoint, params=None, **kwargs):
        data, proof = original(endpoint, params, **kwargs)
        if endpoint == ASSETS:
            reads.append(endpoint)
            data = deepcopy(data)
            for asset in data:
                asset['name'] = 'Updated label' if len(reads) > 1 else 'Original label'
        return data, proof

    monkeypatch.setattr(alpaca_path, 'get', inventory)
    job = enqueue(conn)
    result = preparation_wait.run(conn, job, prepare=op.prepare, check_target=lambda:None)
    assert result['job_id'] == job
    assert len(reads) == 2
    assert len(alpaca_path.classifier.calls) == 1
    assert conn.execute('SELECT count(*) FROM sentinel_snapshot_jobs').fetchone()[0] == 1
    assert conn.execute('SELECT count(*) FROM sentinel_acquisition_successors').fetchone()[0] == 0


def test_persistent_alpaca_revision_exhausts_fixed_successor_budget(
        conn, alpaca_path, monkeypatch):
    observed = changing_source(alpaca_path, monkeypatch, change='amount', persistent=True)
    # PostgreSQL JSON omits trailing fractional zeros; typed timestamps do not.
    # Exercise that representation difference deterministically.
    fixed = conn.execute(
        "SELECT date_trunc('milliseconds',clock_timestamp()+interval '240 seconds')"
    ).fetchone()[0]
    parent = enqueue(conn, absolute_deadline=fixed)
    deadline = jobs.status(conn, parent)['deadline']
    with pytest.raises(jobs.JobRefused, match='restart limit'):
        preparation_wait.run(conn, parent, prepare=op.prepare, check_target=lambda:None)
    assert len(observed) == MAX_SUCCESSORS + 1
    assert len(set(observed)) == 1
    assert conn.execute('SELECT count(*) FROM sentinel_corpus_publications').fetchone()[0] == 0
    states = conn.execute('SELECT state,deadline,reason FROM sentinel_snapshot_jobs').fetchall()
    assert len(states) == MAX_SUCCESSORS + 1
    expected_deadline = datetime.fromisoformat(deadline)
    for state, stamp, reason in states:
        assert state == 'REFUSED' and reason == 'SOURCE_GENERATION_CHANGED'
        assert stamp == expected_deadline
