"""Issuer child records preserve the exact installed operational contract."""
import hashlib
import importlib
import inspect
from pathlib import Path
import textwrap

import pytest

from sentinel import operational_catalog, operational_ddl_epoch, operational_schema
from sentinel import retained_input_namespaces
from sentinel.execution import issuer_admission, journal
from sentinel.feed.issuer_reference import IssuerReferenceSnapshot
from sentinel.panel import operational_schema as panel_schema
from tests.sentinel.test_operational_catalog_integration import cluster, conn  # noqa: F401

PREDECESSOR = '20065ee9db6231bffe52498f1ec692fbd9933018'
# Extracted from exact Git predecessor bytes, independently of current imports.
PREDECESSOR_SOURCE_SHA256 = {
    'retained_input_namespaces.py': 'a6cf3ad730474696bc9cd99b4b46a11960f737d20af801aa8fa964a599e283a6',
    'execution/evidence_schema.py': '1ea9ff8c5105841c2726782c66e3c11b0f3131c6eb716b5e229bf514794217e8',
    'mirror_schema.py': '1fca20eaaf7a4cb029867acf4699c9491817c4cb9a7dd7c301a5f2ef6259aaf6',
    'panel/operational_schema.py': '04e1ad2e9173111c4ad71389d033bd683d16f3cf3288b92a4d071ff0b7d4e66a',
    'feed/normalized_layout.py': 'ee4c969df6fcf66aab60064fe7b081e1d85163e30fcb574585cae42c0bff1e53',
    'feed/generation_admission.py': '89e3a88e19bf74ecb241950efa46d9e6c9fb847fe882e960c1a6a9b55a3c75c7',
    'operational_ddl_epoch.py': 'b13648c84d2a677963343500320e973071668734ac5460c32dc90ddf1696abb9',
    'operational_schema.py': '2a63ef4a57d12308c85dfd828f38474caafce602369753d8de3c74bd131863aa',
    'operational_catalog.py': '9533edea8aaea8af7cef456d416c4308ea4fdeaa021f6f92e65da6aa914b3f36',
    'operational-catalog-v1.json': 'ea3f77ef0d5f532d16dcc0368f383344cc4d2ec80a6ccca7160b37eaf0ce4611',
}
# Independently read from the installed predecessor's original authenticated marker.
PREDECESSOR_CONTRACTS = {
    'sentinel.execution.evidence_schema': '1e9ed6fec6fa737400f79e2040af73bbec43855675fd7823aea34058f7d4adff',
    'sentinel.mirror_schema': '1003ffc74e39caf888d4490400c1eaddb0b3ab3d8f199b30babc406baff6669a',
    'sentinel.panel.operational_schema': '777d37fdd99199e3dd74ef7f8b3802aae6142712be82174b3df7f9f0948f628b',
    'sentinel.feed.normalized_layout': '3e1e78aac11e620aa03a2753211c3d2a8007c25e4cb326d161ea714abab9f838',
    'sentinel.feed.generation_admission': '8f302d90322ac1433f28633b25e30aebc676ee442bc1e23d74c9e2bc7f09c105',
    'sentinel.operational_ddl_epoch': '18564d7e9ffcf22c91e1b463944c3aa722aeecf2b943d6a71e55f1809c649da6',
    'sentinel.operational_schema': '255f03baf4ec3cdb74c927a7538ffea218dfbc66a910f00e948ed835aa91fd76',
}


def assert_predecessor_contracts():
    root = Path(operational_schema.__file__).resolve().parent
    for name, expected in PREDECESSOR_SOURCE_SHA256.items():
        assert hashlib.sha256((root/name).read_bytes()).hexdigest() == expected, (PREDECESSOR, name)
    assert operational_schema.contracts() == PREDECESSOR_CONTRACTS
    assert operational_catalog.CATALOG_SHA256 == PREDECESSOR_SOURCE_SHA256['operational-catalog-v1.json']


def test_issuer_storage_keeps_exact_predecessor_sources_catalog_and_contracts():
    assert_predecessor_contracts()
    assert not any(prefix.startswith('issuer-')
        for prefix in retained_input_namespaces.PAPER_CURSOR_PREFIXES)
    assert all(prefix.startswith('protected-buy-funding:v1:issuer-policy:v1:')
        for prefix in issuer_admission.PREFIXES)


def test_native_sec_cache_updates_advance_only_paper_without_changing_retained_contracts(conn,monkeypatch):
    from sentinel.execution import issuer_refresh
    from tests.sentinel.test_issuer_refresh import EMAIL,NOW,Opener,setup
    assert_predecessor_contracts()
    installed=operational_schema.install_quiescent(conn)
    marker=conn.execute('SELECT session,state,updated_at FROM sentinel_processed_sessions WHERE cursor_name=%s',
                        (operational_schema.CURSOR,)).fetchone()
    epoch=operational_ddl_epoch.current(conn)
    revisions=dict(conn.execute('SELECT scope,revision FROM sentinel_operational_read_revisions').fetchall())
    conn.rollback()
    setup(conn,monkeypatch)
    assert issuer_refresh.collect(conn,email=EMAIL,now=NOW,opener=Opener())['status']=='REFRESHED'
    after=dict(conn.execute('SELECT scope,revision FROM sentinel_operational_read_revisions').fetchall())
    assert after['PAPER']>revisions['PAPER'] and after['SHADOW']==revisions['SHADOW']
    assert operational_ddl_epoch.current(conn)==epoch
    assert conn.execute('SELECT session,state,updated_at FROM sentinel_processed_sessions WHERE cursor_name=%s',
                        (operational_schema.CURSOR,)).fetchone()==marker
    assert operational_schema.installation(conn)==installed
    assert operational_schema.require_schema(conn)
    assert_predecessor_contracts()


def test_private_issuer_appends_advance_only_paper_without_schema_or_epoch_change(conn):
    from tests.sentinel.test_issuer_admission import (
        BINDING, NOW, instruments, prepare, reconciliation, state,
    )

    assert_predecessor_contracts()

    installation = operational_schema.install_quiescent(conn)
    assert installation['contracts'] == PREDECESSOR_CONTRACTS
    before_marker = conn.execute('SELECT session,state,updated_at FROM sentinel_processed_sessions '
        'WHERE cursor_name=%s', (operational_schema.CURSOR,)).fetchone()
    before_revisions = dict(conn.execute(
        'SELECT scope,revision FROM sentinel_operational_read_revisions').fetchall())
    before_epoch = operational_ddl_epoch.current(conn)
    conn.rollback()
    source = IssuerReferenceSnapshot.create(observed_at_utc=NOW,
        associations=[dict(cik='0000000001', ticker=ticker, exchange='NYSE')
            for ticker in ('AAA', 'AAA-A')], coverage='PARTIAL',
        source_method='WEB_EXTRACTED_REPRESENTATION')
    # The fixture owns only this freshly created private database. Exercise the
    # production append paths under their actual database writer lock.
    with conn.transaction():
        conn.execute('SELECT pg_advisory_xact_lock(%s)', (journal.WRITER_LOCK_KEY,))
        issuer_admission.enroll(conn, binding=BINDING, state=state(),
            reconciliation=reconciliation(), snapshot=source, instruments=instruments(), now=NOW)
        _state, _plan, _projection, evidence = prepare(conn, source, pending=('A', 'A2'))
        denied = issuer_admission.check_buy(conn, evidence=evidence, security_id='A2',
            reconciliation=reconciliation(), now=NOW)
        assert not denied.allowed
        admitted = issuer_admission.check_buy(conn, evidence=evidence, security_id='A',
            reconciliation=reconciliation(), now=NOW, reserve=True)
        assert admitted.allowed
    for prefix in issuer_admission.PREFIXES:
        assert conn.execute('SELECT count(*) FROM sentinel_processed_sessions WHERE cursor_name LIKE %s',
            (prefix+'%',)).fetchone()[0] > 0
    after_revisions = dict(conn.execute(
        'SELECT scope,revision FROM sentinel_operational_read_revisions').fetchall())
    assert after_revisions['PAPER'] > before_revisions['PAPER']
    assert after_revisions['SHADOW'] == before_revisions['SHADOW']
    assert operational_ddl_epoch.current(conn) == before_epoch
    assert conn.execute('SELECT session,state,updated_at FROM sentinel_processed_sessions '
        'WHERE cursor_name=%s', (operational_schema.CURSOR,)).fetchone() == before_marker
    assert operational_schema.installation(conn) == installation
    assert operational_schema.require_schema(conn)
    for name in PREDECESSOR_CONTRACTS:
        assert operational_catalog.require_extension(conn, name)
        expected = operational_catalog._catalog()[name]
        assert operational_catalog.capture_extension(conn, importlib.import_module(name)) == expected
    assert_predecessor_contracts()


@pytest.mark.parametrize('deny,reserve',[(False,False),(True,False),(False,True)])
def test_prepared_issuer_metadata_does_not_block_fresh_authority_verdict(conn,monkeypatch,deny,reserve):
    from contextlib import closing
    from sentinel.execution import issuer_runtime
    from sentinel.execution.contract import BrokerInstrument
    from sentinel.feed import store
    from tests.sentinel.test_issuer_admission import BINDING,NOW,instruments,prepare,reconciliation,state

    operational_schema.install_quiescent(conn)
    source=IssuerReferenceSnapshot.create(observed_at_utc=NOW,
        associations=[dict(cik='0000000001',ticker='UNCOVERED' if deny else 'AAA',exchange='NYSE')])
    conn.execute('SELECT pg_advisory_lock(%s)',(journal.WRITER_LOCK_KEY,))
    try:
        issuer_admission.enroll(conn,binding=BINDING,state=state(),
            reconciliation=reconciliation(),snapshot=source,instruments=instruments(),now=NOW)
        conn.commit()
        current,plan,projection,_evidence=prepare(conn,source,pending=('A',))
        context=issuer_runtime.PaperIssuerAdmission(conn=conn,binding=BINDING,clock=lambda:NOW)
        context.prepare_for_transport(publication=None,state=current,plan=plan,
            projection=projection,reconciliation=reconciliation())
        assert context.evidence is not None and context.error is None
        if deny or reserve:
            decision=context.check_buy(security_id='A',reconciliation=reconciliation(),
                instruments={'A':BrokerInstrument('A','AAA','native-A')},reserve=True)
            if deny:
                assert not decision.allowed and decision.reason=='ISSUER_IDENTITY_UNRESOLVED'
            else:
                assert decision.allowed
        # This is the real dependency/trigger written by fresh guarded reads.
        # The second connection must complete while the session writer remains.
        with closing(store.connect(conn.info.dsn)) as fresh:
            if reserve:
                assert conn.execute('SELECT count(*) FROM sentinel_processed_sessions '
                    'WHERE cursor_name LIKE %s',(issuer_admission.CLAIM_PREFIX+'%',)).fetchone()[0]==1
                assert fresh.execute('SELECT count(*) FROM sentinel_processed_sessions '
                    'WHERE cursor_name LIKE %s',(issuer_admission.CLAIM_PREFIX+'%',)).fetchone()[0]==0
                issuer_admission._lock(conn)
                assert not journal.load_commands(conn,BINDING)
                return
            fresh.execute("SET LOCAL lock_timeout='250ms'")
            fresh.execute("UPDATE sentinel_automation_control SET authority_verdict='PASS',"
                          "authority_detail='private fresh broker read' WHERE id=1")
            fresh.commit()
        issuer_admission._lock(conn)
        assert not journal.load_commands(conn,BINDING)
        assert_predecessor_contracts()
    finally:
        conn.rollback()
        conn.execute('SELECT pg_advisory_unlock(%s)',(journal.WRITER_LOCK_KEY,))
        conn.commit()


def test_removing_pre_transport_metadata_commit_is_detected(conn,monkeypatch):
    import psycopg
    from sentinel.execution import issuer_runtime
    source=textwrap.dedent(inspect.getsource(issuer_runtime.PaperIssuerAdmission.prepare_for_transport))
    guard='    self.conn.commit()'
    assert source.count(guard)==1
    namespace={}
    exec(compile(source.replace(guard,'    pass'),'<missing issuer preparation commit>','exec'),
         issuer_runtime.__dict__,namespace)
    monkeypatch.setattr(issuer_runtime.PaperIssuerAdmission,'prepare_for_transport',
                        namespace['prepare_for_transport'])
    with pytest.raises(psycopg.errors.LockNotAvailable):
        test_prepared_issuer_metadata_does_not_block_fresh_authority_verdict(conn,monkeypatch,False,False)


def test_removing_denied_shortfall_commit_is_detected(conn,monkeypatch):
    import psycopg
    from sentinel.execution import issuer_runtime
    source=textwrap.dedent(inspect.getsource(issuer_runtime.PaperIssuerAdmission.check_buy))
    guard='        self.conn.commit()'
    assert source.count(guard)==1
    namespace={}
    exec(compile(source.replace(guard,'        pass'),'<missing issuer shortfall commit>','exec'),
         issuer_runtime.__dict__,namespace)
    monkeypatch.setattr(issuer_runtime.PaperIssuerAdmission,'check_buy',namespace['check_buy'])
    with pytest.raises(psycopg.errors.LockNotAvailable):
        test_prepared_issuer_metadata_does_not_block_fresh_authority_verdict(conn,monkeypatch,True,False)


def test_committing_an_admitted_reservation_before_its_command_is_detected(conn,monkeypatch):
    from sentinel.execution import issuer_runtime
    source=textwrap.dedent(inspect.getsource(issuer_runtime.PaperIssuerAdmission.check_buy))
    guard='if decision.allowed is not True:'
    assert source.count(guard)==1
    namespace={}
    exec(compile(source.replace(guard,'if True:'),'<premature issuer reservation commit>','exec'),
         issuer_runtime.__dict__,namespace)
    monkeypatch.setattr(issuer_runtime.PaperIssuerAdmission,'check_buy',namespace['check_buy'])
    with pytest.raises(AssertionError):
        test_prepared_issuer_metadata_does_not_block_fresh_authority_verdict(conn,monkeypatch,False,True)


def test_top_level_issuer_registration_contract_change_is_detected(monkeypatch):
    original = retained_input_namespaces.PAPER_CURSOR_PREFIXES
    assert_predecessor_contracts()
    try:
        monkeypatch.setattr(retained_input_namespaces, 'PAPER_CURSOR_PREFIXES',
            (*original, 'issuer-admission-enrollment:v1:'))
        importlib.reload(panel_schema)
        with pytest.raises(AssertionError):
            assert_predecessor_contracts()
        changed = operational_schema.contracts()
        assert {name for name in changed if changed[name] != PREDECESSOR_CONTRACTS[name]} == {
            'sentinel.panel.operational_schema'}
    finally:
        monkeypatch.setattr(retained_input_namespaces, 'PAPER_CURSOR_PREFIXES', original)
        importlib.reload(panel_schema)
    assert_predecessor_contracts()
