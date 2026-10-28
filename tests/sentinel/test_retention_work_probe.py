"""Real SQL proves empty work before ownership; disposal still needs backup proof."""
import uuid

import pytest

from sentinel import backup_runtime_authority
from sentinel.feed import normalized_layout,retention
from tests.sentinel.test_rolling_snapshot_publisher import pg  # noqa: F401


CID='00000000-0000-0000-0000-000000000099'


@pytest.fixture
def metadata(pg,monkeypatch):
    import psycopg
    conn=psycopg.connect(pg.sync_dsn)
    definitions={
        'sentinel_snapshot_jobs':'job_id text,candidate_id uuid,state text,reason text,deadline timestamptz,owner text',
        'sentinel_price_candidates':'candidate_id uuid,reference_sha256 text,source_evidence_sha256 text',
        'sentinel_snapshot_retirements':'candidate_id uuid,retired_at timestamptz DEFAULT clock_timestamp()',
        'sentinel_operational_snapshots':'candidate_id uuid,publication_version integer,job_id text',
        'sentinel_corpus_publications':'version integer',
        'sentinel_snapshot_comparisons':'candidate_id uuid,version integer,job_id text,producer_sha256 text',
        'sentinel_action_coverage':'publication_version integer',
        'sentinel_snapshot_bars':'candidate_id uuid,session date,security_id text',
        'sentinel_snapshot_benchmarks':'candidate_id uuid,session date',
        'sentinel_snapshot_evidence':'evidence_sha256 text,payload jsonb,canonical_payload text',
        'sentinel_snapshot_validations':'validation_sha256 text',
        'sentinel_operational_snapshot_validations':'validation_sha256 text',
        'sentinel_sep_staging':'run_id text',
        'sentinel_snapshot_workers':'owner text,job_id text',
        'sentinel_acquisition_parts':'part_id text',
        'live_parts':'part_id text',
        'sentinel_normalized_blocks':'block_sha256 text,canonical_payload text',
        'sentinel_candidate_blocks':'candidate_id uuid,block_sha256 text',
        'sentinel_snapshot_maintenance':'id boolean,diagnostic jsonb,updated_at timestamptz DEFAULT clock_timestamp()',
    }
    for name,fields in definitions.items():conn.execute(f'CREATE TEMP TABLE {name}({fields})')
    conn.execute('CREATE UNIQUE INDEX ON sentinel_snapshot_maintenance(id)')
    function_schema='retention_probe_'+uuid.uuid4().hex
    conn.execute(f'CREATE SCHEMA {function_schema}')
    conn.execute(f'SET search_path TO pg_temp,{function_schema},public')
    conn.execute(f'CREATE FUNCTION {function_schema}.sentinel_acquisition_part_pinned(target text) RETURNS boolean '
        'LANGUAGE SQL STABLE AS $$ SELECT EXISTS(SELECT 1 FROM live_parts WHERE part_id=target) $$')
    conn.execute("INSERT INTO sentinel_snapshot_maintenance(id,diagnostic) VALUES(TRUE,'{\"original\":true}')")
    conn.commit()
    monkeypatch.setattr(normalized_layout,'available',lambda _:True)
    monkeypatch.setattr(retention,'opening_execution_due',lambda _:False)
    try:yield conn
    finally:
        conn.rollback()
        conn.execute(f'DROP SCHEMA {function_schema} CASCADE')
        conn.commit()
        conn.close()


def seed(conn,kind):
    if kind=='expired_job':
        conn.execute("INSERT INTO sentinel_snapshot_jobs VALUES('job',NULL,'ACQUIRING','WAIT',clock_timestamp()-interval '1 second',NULL)")
    elif kind=='candidate':
        conn.execute('INSERT INTO sentinel_price_candidates(candidate_id) VALUES(%s)',(CID,))
        conn.execute("INSERT INTO sentinel_snapshot_jobs VALUES('job',%s,'PUBLISHED','DONE',NULL,NULL)",(CID,))
    elif kind=='retired_payload':
        conn.execute('INSERT INTO sentinel_snapshot_retirements(candidate_id) VALUES(%s)',(CID,))
        conn.execute("INSERT INTO sentinel_snapshot_bars VALUES(%s,'2026-10-27','security')",(CID,))
    elif kind=='evidence':
        conn.execute("INSERT INTO sentinel_price_candidates VALUES(%s,'evidence','evidence')",(CID,))
        conn.execute('INSERT INTO sentinel_snapshot_retirements(candidate_id) VALUES(%s)',(CID,))
        conn.execute("INSERT INTO sentinel_snapshot_evidence VALUES('evidence','{}',NULL)")
    elif kind=='scratch':
        conn.execute("INSERT INTO sentinel_snapshot_jobs VALUES('job',NULL,'PUBLISHED','DONE',NULL,NULL)")
        conn.execute("INSERT INTO sentinel_snapshot_workers VALUES('old-owner','job')")
        conn.execute("INSERT INTO sentinel_sep_staging VALUES('old-owner')")
    elif kind=='acquisition':conn.execute("INSERT INTO sentinel_acquisition_parts VALUES('part')")
    elif kind=='normalized':conn.execute("INSERT INTO sentinel_normalized_blocks VALUES('block','{}')")
    else:raise AssertionError(kind)
    conn.commit()


@pytest.mark.parametrize('kind',['expired_job','candidate','retired_payload','evidence','scratch','acquisition','normalized'])
def test_each_disposal_class_remains_possible_work(metadata,kind):
    seed(metadata,kind)
    assert retention._possible_work(metadata),kind+' was hidden from disposal admission'
    assert metadata.info.transaction_status.value==0


@pytest.mark.parametrize('pin',['current','comparison','active_job','unowned','action_archive_missing'])
def test_only_small_positive_metadata_pins_can_prove_candidate_nonwork(metadata,pin):
    metadata.execute('INSERT INTO sentinel_price_candidates(candidate_id) VALUES(%s)',(CID,))
    if pin!='unowned':
        metadata.execute("INSERT INTO sentinel_snapshot_jobs VALUES('job',%s,'PUBLISHED','DONE',NULL,NULL)",(CID,))
    if pin=='current':
        metadata.execute('INSERT INTO sentinel_corpus_publications VALUES(1)')
        metadata.execute("INSERT INTO sentinel_operational_snapshots VALUES(%s,1,'job')",(CID,))
        metadata.execute('INSERT INTO sentinel_action_coverage VALUES(1)')
    elif pin=='comparison':metadata.execute("INSERT INTO sentinel_snapshot_comparisons VALUES(%s,1,'job',NULL)",(CID,))
    elif pin=='active_job':metadata.execute("UPDATE sentinel_snapshot_jobs SET state='STAGING',deadline=clock_timestamp()+interval '1 hour'")
    elif pin=='action_archive_missing':
        metadata.execute('INSERT INTO sentinel_corpus_publications VALUES(2)')
        metadata.execute("INSERT INTO sentinel_operational_snapshots VALUES(%s,1,'job')",(CID,))
    metadata.commit()
    assert retention._possible_work(metadata) is False


def test_all_metadata_candidates_are_considered_beyond_the_pass_cursor(metadata):
    metadata.execute('INSERT INTO sentinel_price_candidates(candidate_id) VALUES '+','.join(
        '(%s)' for _ in range(33)),tuple(str(uuid.UUID(int=i)) for i in range(1,34)))
    metadata.commit()
    seed(metadata,'candidate')
    assert retention._possible_work(metadata),'pinned prefix starved later possible work'


def test_metadata_query_actually_runs_in_a_read_only_transaction(metadata):
    class Observed:
        def execute(self,query,*args):
            if query.startswith('SELECT\n EXISTS('):
                assert metadata.execute("SELECT current_setting('transaction_read_only')").fetchone()[0]=='on'
            return metadata.execute(query,*args)
        def rollback(self):metadata.rollback()
    assert retention._possible_work(Observed()) is False
    assert metadata.info.transaction_status.value==0


def test_no_work_never_takes_writer_or_changes_progress_and_is_not_cached(metadata,monkeypatch):
    before=metadata.execute('SELECT diagnostic,updated_at FROM sentinel_snapshot_maintenance').fetchone()
    metadata.commit()
    calls=[]
    def refused(*a,**kw):
        calls.append(True)
        raise backup_runtime_authority.BackupRuntimeUnavailable('writer must not run')
    monkeypatch.setattr(backup_runtime_authority,'require',refused)
    assert retention.maintain(metadata)==dict(status='COMPLETE',reason='NO_WORK',deleted_rows=0,more_work=False)
    assert not calls and metadata.info.transaction_status.value==0
    assert metadata.execute('SELECT diagnostic,updated_at FROM sentinel_snapshot_maintenance').fetchone()==before
    metadata.commit()
    seed(metadata,'acquisition')
    assert retention.maintain(metadata)['status']=='RETRY' and calls==[True]
    assert metadata.execute('SELECT count(*) FROM sentinel_acquisition_parts').fetchone()[0]==1


def test_actual_positive_path_requires_backup_before_any_disposal(metadata,monkeypatch):
    seed(metadata,'retired_payload')
    calls=[]
    def refused(*a,**kw):
        calls.append(kw['operation'])
        raise backup_runtime_authority.BackupRuntimeUnavailable('archive proof unavailable')
    monkeypatch.setattr(backup_runtime_authority,'require',refused)
    monkeypatch.setattr(retention,'_pass',lambda *a,**kw:pytest.fail('unproved deletion pass ran'))
    assert retention.maintain(metadata)['status']=='RETRY'
    assert calls==['plan/execution writer mutation']
    assert metadata.execute('SELECT count(*) FROM sentinel_snapshot_bars').fetchone()[0]==1


def test_probe_timeout_retains_data_and_never_takes_writer(metadata,monkeypatch):
    seed(metadata,'acquisition')
    class Timed:
        info=metadata.info
        def execute(self,query,*args):
            if query.startswith('SELECT\n EXISTS('):return metadata.execute('SELECT pg_sleep(2)')
            return metadata.execute(query,*args)
        def rollback(self):metadata.rollback()
    monkeypatch.setattr(backup_runtime_authority,'require',lambda *a,**kw:pytest.fail('timeout entered writer'))
    assert retention.maintain(Timed())['status']=='RETRY'
    assert metadata.info.transaction_status.value==0
    assert metadata.execute('SELECT count(*) FROM sentinel_acquisition_parts').fetchone()[0]==1


def test_dropping_a_disposal_class_is_detected(metadata,monkeypatch):
    guard='EXISTS(SELECT 1 FROM sentinel_acquisition_parts a WHERE NOT sentinel_acquisition_part_pinned(a.part_id))'
    assert retention._WORK_QUERY.count(guard)==1
    monkeypatch.setattr(retention,'_WORK_QUERY',retention._WORK_QUERY.replace(guard,'FALSE'))
    with pytest.raises(AssertionError,match='hidden from disposal admission'):
        test_each_disposal_class_remains_possible_work(metadata,'acquisition')


def test_removing_the_empty_gate_is_detected(metadata,monkeypatch):
    monkeypatch.setattr(retention,'_possible_work',lambda _:True)
    with pytest.raises(AssertionError):
        test_no_work_never_takes_writer_or_changes_progress_and_is_not_cached(metadata,monkeypatch)


def test_probe_has_no_book_or_checkpoint_pin_reader_and_keeps_ordered_price_lookup():
    assert 'sentinel_processed_sessions' not in retention._WORK_QUERY
    assert 'sentinel_snapshot_pins(' not in retention._WORK_QUERY
    assert retention.RETIRED_PAYLOAD_QUERY in retention._WORK_QUERY
    assert 'canonical_payload::' not in retention._WORK_QUERY
