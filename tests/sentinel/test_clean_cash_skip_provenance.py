"""Exact terminal metadata needs real account-bound canonical observation proof."""
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
import inspect
import textwrap

import pytest

from sentinel import local_paper
from sentinel.automation import health
from sentinel.execution import journal
from sentinel.execution.contract import BrokerObservation, BrokerAccountIdentity
from sentinel.panel import model, sources
from tests.sentinel.test_journal_and_reconcile import conn, pg  # noqa: F401
from tests.sentinel.test_opening_health_continuity import NOW, OPEN, clean_skip_panel


@pytest.fixture
def case(conn,monkeypatch):
    conn.execute("UPDATE sentinel_account_binding SET broker='alpaca',broker_account_id='PAfixture' WHERE id=1")
    observed=NOW-timedelta(minutes=1)
    native=BrokerObservation(observed,started_at=observed-timedelta(seconds=1),
        terminal_recovery_through=observed-timedelta(seconds=1),
        account_identity=BrokerAccountIdentity('alpaca','PAfixture'))
    seq=journal.record_observation(conn,native,'RUNNING')
    conn.execute("INSERT INTO sentinel_broker_account_evidence(broker,broker_account_id,status,flags,"
        "equity,cash,buying_power,multiplier,observed_at) VALUES('alpaca','PAfixture','ACTIVE','{}',"
        "50000,10000,10000,1,%s)",(NOW,))
    current=replace(clean_skip_panel().row('trading_run'),status=model.FAIL,
        value='SUPERSEDED',valid_until=NOW+timedelta(hours=10),recovery=None)
    cycle=dict(cycle_id='opening-cycle',plan_id='opening-plan',state='SUPERSEDED',
        failure_code='POST_PLAN_CASH_ACTIVITY_RECONCILED',terminal_reason=None,
        clean_reconciliation_id=str(seq),updated_at=current.trading_run.updated_at,
        diagnostic=dict(clean=True,runtime_state='RUNNING',cash_plan_superseded=True,
            observation_id=seq,unresolved=[],foreign_orders=[],foreign_positions=[],restricted_securities={}))
    live=SimpleNamespace(healthy=True,operational_ready=True,enabled=True,kill_switch_engaged=False,
        authority_verdict='PASS',authority_lifecycle_current=True,leader_active=True,
        service_heartbeat_fresh=True,broker_outcome_unresolved=0,
        latest_cycle_id='opening-cycle',latest_cycle_state='SUPERSEDED')
    monkeypatch.setattr(local_paper,'require_bound_account',lambda _:True)
    monkeypatch.setattr(health,'read_health',lambda _:live)
    monkeypatch.setattr(sources,'_current_trading_run',lambda _:current)
    conn.commit()
    return SimpleNamespace(conn=conn,seq=seq,cycle=cycle,health=live,current=current)


def observe(case):
    return sources._clean_cash_supersession(case.conn,case.cycle,now=NOW)


def test_exact_current_cash_skip_requires_real_canonical_provenance_and_account_clock(case):
    fact,account_at,deadline,broker_deadline=observe(case)
    assert fact.state=='AWAITING_NEXT_DECISION'
    assert fact.opening.observation_id==case.seq
    assert fact.opening.cycle_id=='opening-cycle' and fact.opening.plan_id=='opening-plan'
    assert account_at==NOW and deadline==NOW+timedelta(minutes=10)
    assert broker_deadline>deadline
    assert case.current.trading_run.state=='SUPERSEDED'
    assert journal.load_observation_payload(case.conn,case.seq)['completeness']=='COMPLETE'


@pytest.mark.parametrize('field,value',[('clean',False),('runtime_state','FOREIGN_ACTIVITY'),
    ('cash_plan_superseded',False),('unresolved',['unknown']),('foreign_orders',['foreign']),
    ('foreign_positions',['foreign']),('restricted_securities',{'sid':'blocked'}),('observation_id',99999)])
def test_reconciliation_diagnostic_is_positive_and_exact(case,field,value):
    case.cycle['diagnostic'][field]=value
    assert observe(case) is None


@pytest.mark.parametrize('field,value',[('state','BLOCKED'),('failure_code','MISSED_OPEN'),
    ('terminal_reason','FAILED'),('clean_reconciliation_id',None),('plan_id','foreign'),
    ('cycle_id','foreign'),('updated_at',NOW-timedelta(minutes=1))])
def test_arbitrary_terminal_or_foreign_plan_never_becomes_safe_skip(case,field,value):
    case.cycle[field]=value
    assert observe(case) is None


@pytest.mark.parametrize('field,value',[('healthy',False),('operational_ready',False),('enabled',False),
    ('kill_switch_engaged',True),('authority_verdict','FAIL'),('authority_lifecycle_current',False),
    ('leader_active',False),('service_heartbeat_fresh',False),('broker_outcome_unresolved',1),
    ('latest_cycle_id','foreign'),('latest_cycle_state','EXECUTING')])
def test_fresh_current_authority_and_lease_are_independent_requirements(case,field,value):
    setattr(case.health,field,value)
    assert observe(case) is None


@pytest.mark.parametrize('state',['UNKNOWN','SEND_PENDING','ACKNOWLEDGED'])
def test_any_active_command_blocks_safe_terminal_admission(case,monkeypatch,state):
    monkeypatch.setattr(sources,'_active_commands',lambda _:dict(counts={state:1},updated_at=NOW))
    assert observe(case) is None


@pytest.mark.parametrize('fault',['stale','future','blocked','foreign_account','negative_cash','cash_over_equity'])
def test_actual_account_rows_cannot_lend_invalid_health(case,fault):
    if fault=='blocked':
        case.conn.execute("INSERT INTO sentinel_broker_account_evidence(broker,broker_account_id,status,flags,"
            "equity,cash,buying_power,multiplier,observed_at) VALUES('alpaca','PAfixture','ACTIVE',"
            "'{\"trading_blocked\":true}',50000,10000,10000,1,%s)",(NOW+timedelta(microseconds=1),))
    else:
        # Private immutable evidence is replaced only by another explicit test row.
        old=sources._latest_account_evidence(case.conn)
        changes={'stale':{'observed_at':NOW-timedelta(minutes=11)},'future':{'observed_at':NOW+timedelta(minutes=1)},
            'foreign_account':{'account_id':'foreign'},'negative_cash':{'cash':-1},
            'cash_over_equity':{'cash':60000,'buying_power':60000}}[fault]
        old.update(changes)
        # Clock regressions cannot win latest-by-time; a single-row seam isolates
        # the guard while native valid accounts/provenance remain real SQL above.
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(sources,'_latest_account_evidence',lambda _:old)
            if fault=='cash_over_equity':
                with pytest.raises(ValueError):observe(case)
            else:assert observe(case) is None
        return
    assert observe(case) is None


def test_foreign_or_changed_canonical_observation_provenance_refuses(case):
    case.conn.execute('ALTER TABLE sentinel_observation_provenance DISABLE TRIGGER USER')
    case.conn.execute("UPDATE sentinel_observation_provenance SET broker_account_id='foreign' WHERE observation_seq=%s",(case.seq,))
    case.conn.execute('ALTER TABLE sentinel_observation_provenance ENABLE TRIGGER USER')
    with pytest.raises(journal.ObservationEvidenceUncertifiable):observe(case)


def test_removed_canonical_provenance_guard_has_executed_native_falsifier(case,monkeypatch):
    source=textwrap.dedent(inspect.getsource(sources._clean_cash_supersession))
    guard="        payload = journal.load_observation_payload(conn, observation_id)"
    assert source.count(guard)==1
    namespace=dict(vars(sources));exec(compile(source.replace(guard,"        payload = {'completeness':'COMPLETE'}"),
        '<missing-canonical-proof>','exec'),namespace)
    monkeypatch.setattr(sources,'_clean_cash_supersession',namespace['_clean_cash_supersession'])
    with pytest.raises(pytest.fail.Exception):
        test_foreign_or_changed_canonical_observation_provenance_refuses(case)
