"""Current-profile composition, substituting external data/clock/artifact inputs only.

No legacy autouse guard substitutions, production credentials or existing data.
The host independently qualifies the exact deliverable image after this workflow.
"""
from datetime import timedelta
from decimal import Decimal
import hashlib
import json
import time
import uuid

import pytest

from sentinel import binding, identity, local_paper, operational_schema, shadow_runtime
from sentinel import rolling_initialization as init
from sentinel.feed import operational_snapshot as snapshots, publisher_pipeline
from sentinel.feed.alpaca_source import AlpacaSource
from sentinel.feed.alpaca_transport import ASSETS
from sentinel.feed.rolling_contract import CurrentFormationWindow, digest
from sentinel.strategy import production_strategy
from tests.sentinel.test_alpaca_daily_formation import Prices
from tests.sentinel.test_alpaca_operational_snapshot import FakeClassifier
from tests.sentinel.test_operational_catalog_integration import cluster, conn  # noqa: F401
from tests.support.current_workflow_authority import issue_current_paper_authority, private_exposure_ceiling
from tests.support.current_workflow_clock import prospective_clock
from tests.support.current_workflow_run import paper_and_delivery

OBSERVATION = 'current-operational-workflow'
ACCOUNT = 'PAISOLATEDWORKFLOW'


def test_private_issuer_covers_full_healthy_domain_and_refuses_partial_or_levered_permission(monkeypatch):
    from sentinel import authority
    from tests.support import current_workflow_authority as issuer
    assert private_exposure_ceiling() == '1'
    # The former fixture cap must fail before the expensive source/formation
    # campaign. Leverage still fails the production claim parser itself.
    monkeypatch.setattr(issuer, 'PRIVATE_MAXIMUM_EXPOSURE', '0.55')
    with pytest.raises(AssertionError, match='healthy unlevered domain'):
        private_exposure_ceiling()
    monkeypatch.setattr(issuer, 'PRIVATE_MAXIMUM_EXPOSURE', '1.01')
    with pytest.raises(authority.AuthorityRefused, match='canonical Decimal'):
        private_exposure_ceiling()


class BroadPrices(Prices):
    def __init__(self,window,clock):
        super().__init__()
        self.window,self.clock = window,clock
        self.origin = str(window.start)

    def get(self, endpoint, params):
        assert endpoint == ASSETS
        return [{'id': str(uuid.uuid5(uuid.NAMESPACE_URL,f'isolated-current-asset:{i}')),
                 'symbol': f'T{i:03}', 'name': f'Company {i}',
                 'class': 'us_equity', 'status': 'active', 'tradable': True,
                 'exchange': 'NASDAQ'} for i in range(500)], {
                     'observed_at': self.clock.now().isoformat()}

    def pages(self,endpoint,params,*,key):
        for material,_proof in super().pages(endpoint,params,key=key):
            yield material,{'observed_at':self.clock.now().isoformat()}


@pytest.fixture
def current(conn, monkeypatch):
    # Fail immediately if this disposable issuer cannot authorize the current
    # controller's full healthy domain, before acquiring 426 source sessions.
    assert private_exposure_ceiling() == '1'
    commit = 'a' * 40
    image = 'sha256:' + 'b' * 64
    # These are issuer/host artifact inputs for the private runtime. No validator
    # is replaced; image sealing and host OCI identity are separate release gates.
    values = {
        'SENTINEL_GIT_COMMIT': commit, 'SENTINEL_IMAGE_SOURCE_REVISION': commit,
        'SENTINEL_RUNTIME_IMAGE_DIGEST': image, 'SENTINEL_TEST_IMAGE_DIGEST': image,
        'SENTINEL_FEED_GIT_COMMIT': commit, 'SENTINEL_FEED_RUNTIME_IMAGE_DIGEST': image,
        'SENTINEL_FEED_AUTHORIZED': identity.FEED_AUTHORIZATION_VALUE,
        local_paper.MODE_ENV: local_paper.MODE, local_paper.ACCOUNT_ENV: ACCOUNT,
        'ALPACA_BASE_URL': 'https://paper-api.alpaca.markets',
        'SENTINEL_PAPER_BUY_POLICY': 'PROTECTED_LIMIT_DAY_V1',
        'SENTINEL_PAPER_BUY_CAP_BPS': '100',
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    # Exercise real public-file parsers before the expensive source/formation
    # stages, so an incomplete private input set fails immediately.
    from sentinel import authority, observation_authority
    from sentinel.execution.authority_gate import publication_policy_implementation_sha256
    assert observation_authority.accepted_boundary_bytes()
    assert authority.validation.load_trust_roots()
    assert authority.execution_config_identity(paper_base_url=authority.PAPER_BASE_URL)
    assert publication_policy_implementation_sha256()
    monkeypatch.setenv('SENTINEL_REVIEWED_DEPLOYMENT_MODE','dual')
    monkeypatch.setenv('SENTINEL_SHADOW_OBSERVATION_ENABLED','0')
    monkeypatch.setenv('SENTINEL_SHADOW_OBSERVATION_ID',OBSERVATION)
    monkeypatch.setenv('SENTINEL_SHADOW_STARTING_CASH','50000')
    monkeypatch.setenv('SENTINEL_DATABASE_URL',conn.info.dsn)
    monkeypatch.delenv('SENTINEL_FEED_SERVICE_MODE', raising=False)
    clock,closed = prospective_clock(monkeypatch)
    binding.bind(conn, deployment_id='isolated-current-workflow', broker='alpaca',
                 broker_account_id=ACCOUNT)
    # This is generated account inception, before any observations/projections.
    # Its native business observations may represent this morning even when
    # CI starts in the afternoon. Keep real DB lease/mutation clocks untouched.
    assert conn.info.dbname.startswith('operational_')
    assert conn.execute('SELECT count(*) FROM sentinel_observations').fetchone()[0] == 0
    assert conn.execute('SELECT count(*) FROM sentinel_commands').fetchone()[0] == 0
    conn.execute('UPDATE sentinel_account_binding SET established_at=%s WHERE id=1',
                 (clock.now()-timedelta(days=1),))
    conn.execute('UPDATE sentinel_notification_policy SET web_push_activated_at=%s WHERE id=1',
                 (clock.now()-timedelta(days=1),))
    conn.commit()
    operational_schema.install_quiescent(conn)
    from sentinel.execution import journal
    for _ in range(100):
        progress = journal.bootstrap_observation_integrity(conn, limit=64)
        conn.commit()
        if progress['body']['stage'] == 'COMPLETE':
            break
    else:
        raise AssertionError('bounded bootstrap did not complete')
    conn.commit()
    from sentinel import mirror_projection
    for _ in range(100):
        progress = mirror_projection.bootstrap_step(conn,limit=64)
        conn.commit()
        if progress['body']['stage']=='COMPLETE':
            break
    else:
        raise AssertionError('bounded mirror bootstrap did not complete')
    prices = BroadPrices(CurrentFormationWindow.through(closed),clock)
    monkeypatch.setattr(publisher_pipeline, '_operational_source',
        lambda window, conn, lease, **kw: AlpacaSource(window, conn, lease,
            client=prices, classifier=FakeClassifier(),
            verify_during_coverage=kw['verify_during_coverage']))
    actual = identity.rehearsal_identity()
    assert actual['certification']['certified'], actual['certification']
    monkeypatch.setenv('SENTINEL_VALIDATED_SOURCE_IDENTITY_SHA256', actual['identity_hash'])
    reviewed = {
        'schema': 'sentinel.shadow-reviewed-config/1', 'observation_id': OBSERVATION,
        'starting_cash': '50000', 'execution_model': shadow_runtime.SHADOW_EXECUTION_MODEL,
        'cutoff_policy': shadow_runtime.SHADOW_CUTOFF_POLICY,
        'publication_timing_policy': shadow_runtime.SHADOW_PUBLICATION_TIMING_POLICY,
        'validated_source_identity_sha256': actual['identity_hash'],
    }
    encoded = json.dumps(reviewed, sort_keys=True, separators=(',', ':'),
                         ensure_ascii=True, allow_nan=False).encode('ascii')
    monkeypatch.setenv('SENTINEL_VALIDATED_SHADOW_CONFIG_SHA256', hashlib.sha256(encoded).hexdigest())
    _, strategy = production_strategy()
    job = snapshots.enqueue(conn, strategy_sha256=digest(strategy),
                            dependencies_sha256=digest('isolated-current-workflow'))
    conn.commit()
    published = snapshots.prepare(conn, job)
    with snapshots.pinned(conn) as (publication, _):
        subject = shadow_runtime._data_publication_subject_sha256(publication, publication.window_end)
    monkeypatch.setenv('SENTINEL_VALIDATED_DATA_PUBLICATION_SHA256', subject)
    conn.rollback()
    return prices, published, clock


def test_real_current_source_readiness_uses_panel_budget_without_forming_a_book(conn,current):
    """Isolate source SQL at real breadth before the expensive formed-book run.

    This proves authenticated input closure/readiness only. No canonical book,
    signed execution authority, broker transport or financial readiness exists.
    """
    from psycopg.pq import TransactionStatus
    from sentinel import committed_read, rolling_checkpoint
    from sentinel.feed import rolling_go_inputs, rolling_store, store
    from sentinel.panel import sources
    prices,published,clock=current
    assert len(prices.window.sessions)==426
    assert sources.STATEMENT_TIMEOUT_MS==8000
    conn.rollback()
    proof_owner=store.connect(conn.info.dsn,connect_timeout=sources.CONNECT_TIMEOUT_SECONDS,
        statement_timeout_ms=sources.STATEMENT_TIMEOUT_MS)
    started=time.monotonic()
    try:
        with committed_read.proof_connection(proof_owner) as proof:
            assert proof.execute('SHOW transaction_isolation').fetchone()[0]=='repeatable read'
            assert proof.execute('SHOW transaction_read_only').fetchone()[0]=='on'
            assert proof.execute('SHOW statement_timeout').fetchone()[0] in {'8s','8000ms'}
            rolling_go_inputs.require_schemas(proof)
            with rolling_go_inputs.pinned(proof) as publication:
                bound,report=rolling_go_inputs.validate_status(proof,publication,now=clock.now())
                assert report.ready,report
                assert bound['candidate_id']==published['candidate_id']
                assert bound['snapshot_id']==published['snapshot_id']
                manifest=rolling_store.manifest(proof,bound['candidate_id'])
                assert len(manifest.window.sessions)==426 and manifest.bar_count==500*426
                assert rolling_store.readiness_facts(proof,bound['candidate_id']) is not None
                assert proof.execute('SHOW statement_timeout').fetchone()[0] in {'8s','8000ms'}
        assert proof_owner.info.transaction_status==TransactionStatus.IDLE
    finally:
        proof_owner.close()
    print(f'CURRENT_SOURCE_READINESS_SECONDS={time.monotonic()-started:.6f}',flush=True)
    assert rolling_checkpoint.read(conn) is None
    assert conn.execute('SELECT count(*) FROM sentinel_execution_plans').fetchone()[0]==0
    assert conn.execute('SELECT count(*) FROM sentinel_commands').fetchone()[0]==0
    conn.rollback()


def test_real_current_source_formation_restart_paper_execution_notifications_and_http(
        conn,current,monkeypatch,tmp_path):
    from sentinel.core.formation_inputs import FormationInputs
    from sentinel.feed import normalized_layout
    prices, published, clock = current
    assert len(prices.window.sessions) == 426
    first = init.initialize(conn, observation_id=OBSERVATION, starting_cash=Decimal('50000'))
    assert first.state.last_processed_session == str(prices.window.end)
    assert first.state.wealth_core['episodes']
    before = first.state.state_hash
    restored = init.resume(conn, observation_id=OBSERVATION, starting_cash=Decimal('50000'))
    assert restored.state.state_hash == before
    from sentinel import rolling_runtime
    attested = rolling_runtime.advance(conn,through=str(prices.window.end),
        observation_id=OBSERVATION,starting_cash=Decimal('50000'))
    assert attested.verification == 'VERIFIED'
    assert attested.state.state_hash == before
    with snapshots.pinned(conn) as (publication, bound):
        material = FormationInputs(conn, bound, publication)
        assert material is not None
        from sentinel.feed import rolling_store
        manifest = rolling_store.manifest(conn, published['candidate_id'])
        normalized_layout.require_layout(conn, published['candidate_id'], manifest)
    conn.rollback()
    controller,strategy = production_strategy()
    from sentinel.automation.model import AutomationConfig
    config = AutomationConfig()
    certificate = issue_current_paper_authority(conn,monkeypatch,tmp_path,
        now=clock.now(),observation_id=OBSERVATION,controller=controller,
        strategy=strategy,automation_config_sha256=config.fingerprint)
    paper_and_delivery(conn,published,clock,config,certificate,monkeypatch,tmp_path)
