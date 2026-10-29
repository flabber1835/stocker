"""Exact pre-DDL witness, actual migration and atomic coverage transfer on PG16."""
import copy
import inspect

import pytest

from sentinel import binding, chain_progress_recovery as recovery, operational_schema, schema
from sentinel import mirror_projection
from sentinel.execution import evidence_projection as coverage, journal
from sentinel.feed import store
from tests.support.postgres import _EphemeralPostgres

BASE='base-20261029T072734Z'
MARKER='sentinel-backup-20261029T072734Z-123'


@pytest.fixture
def database():
    server=_EphemeralPostgres();server.start()
    c=store.connect(server.sync_dsn)
    try:yield c
    finally:c.close();server.stop()


@pytest.fixture
def prepared(database, monkeypatch, request):
    c=database
    monkeypatch.setenv('SENTINEL_PUBLICATION_RECEIPT_KEY','private-migration-recovery-'*4)
    schema.ensure_schema(c);store.migrate_schema(c)
    binding.bind(c,deployment_id='fixture-paper',broker='alpaca',broker_account_id='PA-fixture')
    c.execute(schema._BACKUP_PROGRESS_V1_DDL[2])
    c.execute(schema._BACKUP_PROGRESS_V1_DDL[3])
    c.execute(schema._BACKUP_PROGRESS_V1_DDL[4])
    c.execute('DROP FUNCTION sentinel_backup_progress_guard_v2()')
    c.execute('CREATE TABLE sentinel_backup_recovery_markers ('
        'marker TEXT PRIMARY KEY,created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())')
    c.commit()
    operational_schema.install_quiescent(c)
    c.execute('INSERT INTO sentinel_backup_recovery_markers(marker) VALUES(%s)',(MARKER,));c.commit()
    for producer in (journal.bootstrap_observation_integrity,mirror_projection.bootstrap_step):
        for _ in range(20):
            value=producer(c,limit=128);c.commit()
            if value['body']['stage']=='COMPLETE':break
        else:raise AssertionError('bounded empty fixture bootstrap did not complete')
    class PausedRestore:
        # External physical-recovery observation only; every schema, receipt,
        # prefix and read-only SQL operation still runs on the actual database.
        def __getattr__(self,name):return getattr(c,name)
        def execute(self,statement,*args):
            if isinstance(statement,str) and statement in {'SELECT pg_is_in_recovery()','SELECT pg_get_wal_replay_pause_state()'}:
                class Result:
                    def fetchone(self):return (True,) if 'pg_is_in_recovery' in statement else ('paused',)
                return Result()
            return c.execute(statement,*args)
    document=recovery.snapshot(PausedRestore(),backup=BASE,marker=MARKER,metadata_sha256='a'*64)
    assert c.execute('SHOW transaction_read_only').fetchone()[0]=='on'
    before=recovery.operational_ddl_epoch.current(c)
    c.rollback()
    schema.ensure_schema(c)
    complete=getattr(request,'param',True)
    if complete:store.migrate_schema(c)
    after=recovery.operational_ddl_epoch.current(c);c.rollback()
    assert after[0]==before[0] and after[1]-before[1]==(recovery.DDL_ADVANCE if complete else 1)
    try:yield c,document
    finally:
        c.rollback()


def apply(c,document):
    return recovery.apply(c,document,expected_backup=BASE,expected_account='PA-fixture',
                          expected_deployment='fixture-paper')


def raw(c):
    rows=c.execute('SELECT domain,payload,hmac_sha256 FROM sentinel_execution_evidence_coverage ORDER BY domain').fetchall()
    c.rollback();return rows


def test_real_migration_preserves_bodies_and_transfers_both_exact_prefixes_once(prepared):
    c,document=prepared
    before=raw(c)
    for domain in recovery.DOMAINS:
        with pytest.raises(coverage.EvidenceCoverageRefused,match='BINDING_CHANGED'):
            coverage.load(c,domain)
        c.rollback()
    result=apply(c,document)
    assert result['operational_ready'] is False and result['broker_contacted'] is False
    after=raw(c)
    for (d,old,_sig),(new_d,new,_new_sig) in zip(before,after,strict=True):
        assert d==new_d and old['inventory']!=new['inventory']
        assert {k:v for k,v in old.items() if k!='inventory'}=={k:v for k,v in new.items() if k!='inventory'}
        assert coverage.require_current(c,d)==new
    c.rollback()
    with pytest.raises(recovery.RecoveryRefused,match='prefix changed'):
        apply(c,document)
    assert raw(c)==after


@pytest.mark.parametrize('fault',['signature','system','binding','epoch','head','prefix','domain','backup'])
def test_forged_or_wrong_subject_witness_never_transfers_either_prefix(prepared,fault):
    c,document=prepared
    document=copy.deepcopy(document);value=document['witness']
    if fault=='signature':document['hmac_sha256']='0'*64
    if fault=='system':value['system']='1'
    if fault=='binding':value['binding'][2]='PA-other'
    if fault=='epoch':value['ddl'][1]+=1
    if fault=='head':value['heads']['MIRROR'][1]+=1
    if fault=='prefix':value['prefixes']['MIRROR']='b'*64
    if fault=='domain':del value['heads']['MIRROR']
    if fault=='backup':value['backup']='base-20261028T000000Z'
    if fault!='signature':document['hmac_sha256']=recovery._sign(value)
    before=raw(c)
    with pytest.raises((recovery.RecoveryRefused,ValueError)):
        apply(c,document)
    c.rollback();assert raw(c)==before


@pytest.mark.parametrize('fault',['extra-ddl','source-insert','bad-prefix-hmac'])
def test_changed_live_evidence_refuses_without_reset_or_reanchoring(prepared,fault):
    c,document=prepared
    if fault=='extra-ddl':c.execute('CREATE TABLE unrelated_migration_test(id integer)')
    if fault=='source-insert':
        c.execute("INSERT INTO sentinel_observations(observed_at,completeness) VALUES(clock_timestamp(),'PARTIAL')")
    if fault=='bad-prefix-hmac':
        c.execute("UPDATE sentinel_execution_evidence_coverage SET hmac_sha256=%s WHERE domain='MIRROR'",('0'*64,))
    c.commit();before=raw(c)
    with pytest.raises((recovery.RecoveryRefused,coverage.EvidenceCoverageRefused)):
        apply(c,document)
    c.rollback();assert raw(c)==before
    if fault=='extra-ddl':c.execute('DROP TABLE unrelated_migration_test');c.commit()


def test_second_domain_failure_rolls_back_the_first_transfer(prepared,monkeypatch):
    c,document=prepared;before=raw(c);write=coverage.write
    def fault(conn,domain,**kwargs):
        if domain=='MIRROR':raise recovery.RecoveryRefused('second domain fault')
        return write(conn,domain,**kwargs)
    monkeypatch.setattr(coverage,'write',fault)
    with pytest.raises(recovery.RecoveryRefused,match='second domain'):
        apply(c,document)
    assert raw(c)==before


def test_snapshot_on_primary_cannot_issue_restore_witness(prepared):
    c,_document=prepared
    with pytest.raises(recovery.RecoveryRefused,match='paused isolated physical restore'):
        recovery.snapshot(c,backup=BASE,marker=MARKER,metadata_sha256='a'*64)
    c.rollback()


def test_already_migrated_schema_cannot_issue_a_new_predecessor_witness(prepared):
    c,_document=prepared
    with pytest.raises(schema.SchemaMigrationRefused):
        recovery._snapshot(c,backup=BASE,marker=MARKER,metadata_sha256='a'*64)
    c.rollback()


@pytest.mark.parametrize('remove_fence',[False,True])
def test_live_lease_refuses_and_native_fence_removal_is_killed(prepared,monkeypatch,remove_fence):
    c,document=prepared
    c.execute("UPDATE sentinel_automation_lease SET holder_id='fixture-live',fence_token=1,"
        "control_generation=1,acquired_at=clock_timestamp(),heartbeat_at=clock_timestamp(),"
        "expires_at=clock_timestamp()+interval '1 minute' "
        "WHERE id=1")
    c.commit()
    if remove_fence:
        monkeypatch.setattr(recovery.deployment_fence,'require',lambda _conn:None)
        with pytest.raises(pytest.fail.Exception,match='DID NOT RAISE'):
            with pytest.raises(recovery.deployment_fence.DeploymentFenceRefused):
                apply(c,document)
    else:
        with pytest.raises(recovery.deployment_fence.DeploymentFenceRefused):
            apply(c,document)


def test_removing_exact_ddl_advance_guard_is_killed_by_extra_ddl_regression(prepared):
    c,document=prepared
    source=inspect.getsource(recovery.apply)
    needle="_require(ddl[0]==value['ddl'][0] and ddl[1]==value['ddl'][1]+DDL_ADVANCE,"
    assert source.count(needle)==1
    namespace={}
    exec(compile(source.replace(needle,'_require(True,'),'removed-exact-ddl-guard','exec'),vars(recovery),namespace)
    c.execute('CREATE TABLE extra_ddl_recovery_falsifier(id integer)');c.commit()
    with pytest.raises(pytest.fail.Exception,match='DID NOT RAISE'):
        with pytest.raises(recovery.RecoveryRefused):
            namespace['apply'](c,document,expected_backup=BASE,expected_account='PA-fixture',
                               expected_deployment='fixture-paper')


@pytest.mark.parametrize('remove_source_proof',[False,True])
def test_untracked_source_change_is_independently_refused_and_guard_removal_is_killed(
        prepared,remove_source_proof):
    c,document=prepared
    # Simulate a privileged bypass without producing a DDL event or a tracked
    # suffix. The independent source-byte proof must still reject it.
    c.execute("SET LOCAL session_replication_role='replica'")
    c.execute("INSERT INTO sentinel_observations(observed_at,completeness) VALUES(clock_timestamp(),'PARTIAL')")
    c.commit()
    method=recovery.apply
    if remove_source_proof:
        source=inspect.getsource(method)
        needle="_require(_source_digests(conn)==value['sources'], 'watched source rows changed')"
        assert source.count(needle)==1
        namespace={}
        exec(compile(source.replace(needle,"_require(True, 'watched source rows changed')"),
            'removed-source-byte-proof','exec'),vars(recovery),namespace)
        method=namespace['apply']
    def check():
        with pytest.raises(recovery.RecoveryRefused,match='watched source rows changed'):
            method(c,document,expected_backup=BASE,expected_account='PA-fixture',
                   expected_deployment='fixture-paper')
    if remove_source_proof:
        with pytest.raises(pytest.fail.Exception,match='DID NOT RAISE'):check()
    else:check()


@pytest.mark.parametrize('remove_empty_guard',[False,True])
def test_unlogged_scratch_stays_in_proof_and_nonempty_primary_refuses(prepared,monkeypatch,remove_empty_guard):
    c,document=prepared
    assert 'sentinel_sep_staging' in document['witness']['sources']
    c.execute("INSERT INTO sentinel_sep_staging(run_id,chunk,session,ticker) "
              "VALUES(gen_random_uuid(),'fixture','2026-10-28','FIXTURE')")
    c.commit()
    if remove_empty_guard:
        source=inspect.getsource(recovery._source_digests)
        needle="_require(not conn.execute('SELECT EXISTS(SELECT 1 FROM sentinel_sep_staging LIMIT 1)')\n                         .fetchone()[0],'vendor scratch is not empty')"
        assert source.count(needle)==1
        namespace={}
        exec(compile(source.replace(needle,"_require(True,'vendor scratch is not empty')"),
            'removed-empty-scratch-guard','exec'),vars(recovery),namespace)
        monkeypatch.setattr(recovery,'_source_digests',namespace['_source_digests'])
    def check():
        with pytest.raises(recovery.RecoveryRefused,match='scratch is not empty'):
            apply(c,document)
    if remove_empty_guard:
        with pytest.raises(pytest.fail.Exception,match='DID NOT RAISE'):check()
    else:check()
    c.rollback()


def test_paused_physical_recovery_proves_unlogged_scratch_without_reading_it(monkeypatch):
    import os,shutil,tempfile,time
    from pathlib import Path
    import psycopg
    from tests.support.postgres import _find_pg_bin,_as_pg_user,_run
    primary,restored=_EphemeralPostgres(),_EphemeralPostgres()
    base=Path(tempfile.mkdtemp(prefix='sentinel_scratch_witness_',dir=Path(primary.datadir).parent))
    try:
        primary.start()
        with psycopg.connect(primary.sync_dsn) as c:
            schema.ensure_schema(c);store.migrate_schema(c);c.commit()
        monkeypatch.setattr(recovery,'_sources',lambda _conn:{'sentinel_sep_staging'})
        with psycopg.connect(primary.sync_dsn) as c:
            expected=recovery._source_digests(c)
        if os.geteuid()==0:shutil.chown(base,user='postgres',group='postgres')
        result=_run(_as_pg_user([_find_pg_bin('pg_basebackup'),'-h','127.0.0.1',
            '-p',str(primary.port),'-U',primary.user,'-D',str(base),'-Fp','-Xs','-c','fast']))
        assert result.returncode==0,result.stderr
        target=Path(restored.datadir)
        shutil.copytree(base,target,dirs_exist_ok=True)
        with (target/'postgresql.auto.conf').open('a') as f:
            f.write("\nrecovery_target='immediate'\nrecovery_target_action='pause'\nrestore_command='false'\n")
        (target/'recovery.signal').touch()
        if os.geteuid()==0:
            for item in [target,*target.rglob('*')]:shutil.chown(item,user='postgres',group='postgres')
        result=_run(_as_pg_user([_find_pg_bin('pg_ctl'),'-D',str(target),
            '-o',f'-p {restored.port} -h 127.0.0.1 -k {target}',
            '-l',str(target/'restored.log'),'-w','-t','30','start']))
        assert result.returncode==0,result.stderr
        restored._started=True
        with psycopg.connect(restored.sync_dsn,autocommit=True) as c:
            deadline=time.monotonic()+15
            while c.execute('SELECT pg_get_wal_replay_pause_state()').fetchone()[0]!='paused':
                assert time.monotonic()<deadline;time.sleep(.1)
            with pytest.raises(psycopg.errors.FeatureNotSupported):
                c.execute('SELECT 1 FROM sentinel_sep_staging LIMIT 1')
            assert recovery._source_digests(c)==expected
            assert 'sentinel_sep_staging' in expected
        with psycopg.connect(primary.sync_dsn) as c:
            c.execute('ALTER TABLE sentinel_sep_staging ADD COLUMN unexpected integer');c.commit()
            with pytest.raises(recovery.RecoveryRefused,match='column contract changed'):
                recovery._source_digests(c)
    finally:
        restored.stop();primary.stop()
        assert base.name.startswith('sentinel_scratch_witness_')
        shutil.rmtree(base)


def test_complete_canonical_installer_migration_preserves_sources_and_measures_epoch(prepared):
    c,document=prepared
    # The installer follows ensure_schema with this reviewed public feed entry.
    # Qualify the complete entrypoint, not just the three trigger statements.
    current=recovery.operational_ddl_epoch.current(c)
    assert current[0]==document['witness']['ddl'][0]
    advance=current[1]-document['witness']['ddl'][1]
    print('COMPLETE_CANONICAL_MIGRATION_DDL_ADVANCE='+str(advance),flush=True)
    assert advance==66
    schema.require_runtime_schema(c);operational_schema.require_schema(c)
    assert recovery._source_digests(c)==document['witness']['sources']


@pytest.mark.parametrize('prepared',[False],indirect=True)
def test_lower_level_helper_alone_is_not_the_installer_migration(prepared):
    c,document=prepared
    before=raw(c)
    with pytest.raises(recovery.RecoveryRefused,match='exact progress migration'):
        apply(c,document)
    c.rollback()
    assert raw(c)==before
