"""The actual opening diagnostic must not confuse history with current transport."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime,timedelta
from decimal import Decimal
import inspect,textwrap
import pytest
from sentinel.panel import sources,model,observer_codec,observer_failure
from sentinel import dual_plan_authority, local_paper
from sentinel import informational_paper_mirror as mirror
from sentinel.paper_plan_preview import PlannedLeg
from sentinel.execution import account_status
from sentinel.execution.contract import OrderTerms
from sentinel.execution.market_buy_policy import MARKET_MODE, MarketBuyPolicy
from tests.sentinel.test_postopen_paper_mirror_readiness import completed,NOW
from tests.sentinel.test_panel_command_progress import cycle,NOW as PROGRESS_NOW


_ALPACA_ACCOUNT_ROW = model.alpaca_account_row


@pytest.fixture
def ongoing(completed):
    v=completed;c=cycle()
    for k,value in c.items():
        if isinstance(value,datetime):c[k]=value+(NOW-PROGRESS_NOW)
    c.update(cycle_id='current-cycle',plan_id='current-plan',plan_fingerprint='a'*64)
    c['diagnostic']['plan']['plan_id']='current-plan'
    v['cycle']=c;v['health'].latest_cycle_state='RECONCILING';v['health'].broker_outcome_unresolved=1
    old=v['row'].trading_run
    intent=old.intent.model_copy(update={'execute_at':c['execute_at'],'legs':[PlannedLeg(security_id='PBR.A',ticker='PBR.A',
        current_quantity=Decimal(71),target_quantity=Decimal(0),change_quantity=Decimal(-71),action='SELL')]})
    order=model.RunOrder(security_id='PBR.A',ticker='PBR.A',client_key='synthetic-key',
        broker_order_id='native-id',side='SELL',quantity=Decimal(71),filled_quantity=Decimal(0),
        state='ACKNOWLEDGED',observed_at=NOW-timedelta(seconds=5),order_terms=OrderTerms().to_dict())
    run=model.TradingRun(intent=intent,state='RECONCILING',updated_at=c['updated_at'],orders=[order])
    v['row']=replace(v['row'],status=model.WARN,trading_run=run,as_of=order.observed_at)
    return v


def observe(v):
    return sources._in_progress_paper_mirror(object(),v['cycle'],v['publication'],'2026-10-30',now=NOW)


def test_known_submitted_transport_is_pending_with_original_wake(ongoing):
    row=observe(ongoing)
    assert row.status==model.WARN and 'PENDING' in row.value and 'NOT VERIFIED' in row.value
    assert row.recovery.phase=='PAPER_TRANSPORT' and row.valid_until==ongoing['cycle']['next_wake_at']
    assert row.effective_status(row.valid_until+timedelta(microseconds=1))==model.FAIL
    assert observer_codec.row_from_observation(observer_codec.pack([row],[],observed_at=NOW)['rows'][0])==row


def test_executing_before_submission_is_not_a_mirror_mismatch(ongoing):
    v=ongoing;v['cycle'].update(state='EXECUTING',failure_code=None,failure_detail=None)
    v['health'].latest_cycle_state='EXECUTING';v['health'].broker_outcome_unresolved=0
    v['cycle']['observation_callback']={'started_at':v['cycle']['updated_at'],'deadline':NOW+timedelta(minutes=2)}
    v['row']=replace(v['row'],trading_run=v['row'].trading_run.model_copy(update={'state':'EXECUTING','orders':[]}))
    assert observe(v).status==model.WARN


def test_due_recovery_wake_uses_actual_fenced_callback_deadline(ongoing):
    c=ongoing['cycle'];c['next_wake_at']=NOW-timedelta(seconds=20)
    c['observation_callback']={'started_at':NOW-timedelta(seconds=15),'deadline':NOW+timedelta(minutes=2)}
    assert observe(ongoing).valid_until==c['observation_callback']['deadline']
    for callback in ({'started_at':NOW-timedelta(minutes=5),'deadline':NOW+timedelta(minutes=2)},
                     {'started_at':NOW-timedelta(seconds=15),'deadline':NOW},
                     {'started_at':NOW+timedelta(seconds=1),'deadline':NOW+timedelta(minutes=2)}):
        c['observation_callback']=callback
        assert observe(ongoing) is None


@pytest.mark.parametrize('fault',['unknown','rejected','missing_order','foreign_order','uncovered',
 'no_local','disabled','authority','unhealthy','foreign_cycle','failed_cycle','different_run',
 'different_plan','publication','frontier','no_plan','stale_run','expired_wake','naive_clock',
 'missing_clean','adverse_preflight','missing_asof'])
def test_uncertain_or_unproved_transport_keeps_refusal(ongoing,fault):
    v=ongoing;c=v['cycle'];run=v['row'].trading_run
    if fault in {'unknown','rejected'}:
        order=run.orders[0].model_copy(update={'state':'UNKNOWN' if fault=='unknown' else 'REJECTED'})
        v['row']=replace(v['row'],trading_run=run.model_copy(update={'orders':[order]}))
    elif fault=='missing_order':v['row']=replace(v['row'],trading_run=run.model_copy(update={'orders':[]}))
    elif fault=='foreign_order':v['row']=replace(v['row'],trading_run=run.model_copy(update={'orders':[run.orders[0].model_copy(update={'client_key':'foreign'})]}))
    elif fault=='uncovered':v['health'].broker_outcome_unresolved=2
    elif fault=='no_local':v['local']=False
    elif fault=='disabled':v['health'].enabled=False
    elif fault=='authority':v['health'].authority_lifecycle_current=False
    elif fault=='unhealthy':v['health'].operational_ready=False
    elif fault=='foreign_cycle':v['health'].latest_cycle_id='foreign'
    elif fault=='failed_cycle':c['state']='BLOCKED'
    elif fault=='different_run':v['row']=replace(v['row'],trading_run=run.model_copy(update={'state':'EXECUTING'}))
    elif fault=='different_plan':v['plan'].fingerprint=lambda:'b'*64
    elif fault=='publication':v['publication'].version=9
    elif fault=='frontier':v['row']=replace(v['row'],trading_run=run.model_copy(update={'intent':run.intent.model_copy(update={'decision_session':run.intent.decision_session-timedelta(days=1)})}))
    elif fault=='no_plan':v['plan']=None
    elif fault=='stale_run':v['row']=replace(v['row'],valid_until=NOW-timedelta(seconds=1))
    elif fault=='expired_wake':c['next_wake_at']=NOW
    elif fault=='naive_clock':c['execute_at']=c['execute_at'].replace(tzinfo=None)
    elif fault=='missing_clean':c['clean_reconciliation_id']=None
    elif fault=='adverse_preflight':c['diagnostic']['preflight']['unresolved']=['unknown']
    elif fault=='missing_asof':v['row']=replace(v['row'],as_of=None)
    assert observe(v) is None


def test_opening_negative_fingerprint_reconstructs_exact_history_dispatch_bug():
    material=dict(errors=[],rows=[dict(key='paper_reconciliation',status='fail',
      value='PAPER NOT VERIFIED · MISMATCH · BLOCKED',
      detail='historical mirror warning remains recorded; current scheduled readiness is unproved · cycle RECONCILING')])
    import json
    failure=observer_failure.failure('NEGATIVE_RESULT','VALIDATION',
        material=json.dumps(material,sort_keys=True,separators=(',',':')).encode())
    assert failure.fingerprint=='f9cc1c37a8a1519c90f31454a0f35562867375e397131e5567b19313e324b656'


def test_history_count_and_warning_remain_during_proven_progress(ongoing,monkeypatch):
    monkeypatch.setattr(sources,'_scheduled_preopen_mirror',lambda *_:None)
    actual=observe(ongoing)
    monkeypatch.setattr(sources,'_in_progress_paper_mirror',lambda *_:actual)
    row=sources._scheduled_paper_mirror(object(),ongoing['cycle'],ongoing['publication'],
      '2026-10-30',{'status':mirror.MISMATCH,'historical_mismatch_count':3})
    assert row.status==model.WARN and '3 historical' in row.detail and 'earlier transported plans' in row.detail
    assert row.valid_until==actual.valid_until and row.recovery==actual.recovery


def test_removed_order_state_guard_fails_oracle(ongoing,monkeypatch):
    code=textwrap.dedent(inspect.getsource(sources._in_progress_paper_mirror))
    guard="any(order.state not in allowed for order in run.orders)"
    assert guard in code;scope=dict(vars(sources));exec(code.replace(guard,'False'),scope)
    monkeypatch.setattr(sources,'_in_progress_paper_mirror',scope['_in_progress_paper_mirror'])
    ongoing['health'].broker_outcome_unresolved = 0
    with pytest.raises(AssertionError):
        test_uncertain_or_unproved_transport_keeps_refusal(ongoing, 'rejected')


def test_first_send_keeps_historical_warning_pending_until_original_callback(ongoing):
    v = ongoing
    c = v['cycle']
    c.update(state='EXECUTING', failure_code=None, failure_detail=None,
             observation_callback={'started_at': c['updated_at'], 'deadline': NOW + timedelta(seconds=30)})
    v['health'].latest_cycle_state = 'EXECUTING'
    run = v['row'].trading_run
    pending = run.orders[0].model_copy(update={'state': 'SEND_PENDING', 'broker_order_id': None})
    v['row'] = replace(v['row'], trading_run=run.model_copy(update={'state': 'EXECUTING', 'orders': [pending]}))
    row = observe(v)
    assert row.status == model.WARN and row.valid_until == c['observation_callback']['deadline']
    assert row.operational_fact.state == 'PENDING'
    c['observation_callback']['deadline'] = NOW
    assert observe(v) is None


@pytest.mark.parametrize('fault', [None, 'expired', 'unresolved', 'no_match'])
def test_protected_day_recovery_uses_exact_original_proof(ongoing, monkeypatch, fault):
    from sentinel.feed import calendar
    from tests.sentinel.test_operator_monitoring import day_wait_wait_payload

    v = ongoing
    c = v['cycle']
    c['effective_session'] = str(v['row'].trading_run.intent.effective_session)
    held_at = NOW - timedelta(seconds=5) if fault != 'expired' else NOW - timedelta(minutes=11)
    _, close = calendar.session_window(c['effective_session'])
    wait = day_wait_wait_payload(held_at, plan_id=c['plan_id'])
    wait.update(effective_session=c['effective_session'], deadline=(close + timedelta(minutes=10)).isoformat())
    c.update(state='RETRY_WAIT', retry_phase='RECOVER', failure_code=None, failure_detail=None,
             protected_day_wait=wait,
             diagnostic={'clean': True, 'runtime_state': 'RUNNING',
                         'unresolved': ['UNKNOWN'] if fault == 'unresolved' else [],
                         'foreign_orders': [], 'foreign_positions': []})
    v['health'].latest_cycle_state = 'RETRY_WAIT'
    run = v['row'].trading_run
    v['row'] = replace(v['row'], trading_run=run.model_copy(update={'state': 'RETRY_WAIT'}))
    monkeypatch.setattr(sources, '_latest_account_evidence', lambda *_: {})
    monkeypatch.setattr(sources, '_bound_account_id', lambda *_: 'synthetic-account')
    monkeypatch.setattr(sources, '_matched_resting_reservation',
        lambda *_args, **_kwargs: None if fault == 'no_match' else wait)
    monkeypatch.setattr(model, 'alpaca_account_row',
        lambda **_: model.Row('alpaca_account', 'Account', 'ACTIVE', model.OK))
    row = observe(v)
    if fault is None:
        assert row.status == model.WARN and row.valid_until == held_at + timedelta(minutes=10)
    else:
        assert row is None


def test_missing_protected_proof_guard_falsifier(ongoing, monkeypatch):
    code = textwrap.dedent(inspect.getsource(sources._in_progress_paper_mirror))
    assert 'if match is None:' in code
    scope = dict(vars(sources))
    exec(code.replace('if match is None:', 'if False:'), scope)
    monkeypatch.setattr(sources, '_in_progress_paper_mirror', scope['_in_progress_paper_mirror'])
    with pytest.raises(AssertionError):
        test_protected_day_recovery_uses_exact_original_proof(ongoing, monkeypatch, 'no_match')


@pytest.mark.parametrize("fault", [None, "expired_wake", "missing_proof", "different_key",
                                    "different_fill", "unknown_outcome", "negative_cash", "old_policy"])
def test_market_buy_retry_stays_pending_only_with_exact_current_native_evidence(ongoing, monkeypatch, fault):
    v = ongoing
    c = v["cycle"]
    c.update(state="RETRY_WAIT", retry_phase="RECOVER", failure_code="COMMANDS_IN_FLIGHT",
             failure_detail="positively observed orders can still fill",
             next_wake_at=NOW + timedelta(seconds=25),
             diagnostic=dict(clean=True, runtime_state="RUNNING", unresolved=[],
                             foreign_orders=[], foreign_positions=[],
                             in_flight_commands=["synthetic-key"]))
    v["health"].latest_cycle_state = "RETRY_WAIT"
    run = v["row"].trading_run
    order = run.orders[0].model_copy(update={"side": "BUY", "state": "PARTIALLY_FILLED",
        "filled_quantity": Decimal(1), "filled_average_price": Decimal("55.21")})
    leg = PlannedLeg(security_id=order.security_id, ticker=order.ticker, current_quantity=Decimal(0),
        target_quantity=order.quantity, change_quantity=order.quantity, action="BUY")
    v["row"] = replace(v["row"], trading_run=run.model_copy(update={"state": "RETRY_WAIT",
        "orders": [order], "intent": run.intent.model_copy(update={"legs": [leg]})}))
    account = dict(broker="alpaca", account_id="paper-account", status="ACTIVE",
        equity=Decimal("10000"), cash=Decimal("2000"), buying_power=Decimal("1850"),
        multiplier=Decimal(1), flags={}, observed_at=NOW-timedelta(seconds=5))
    proof = dict(order=dict(client_key="synthetic-key", broker_order_id="native-id",
        state=order.state, terms=order.order_terms, side="BUY", quantity="71",
        filled_quantity="1", filled_average_price="55.21"), valid_until=c["execution_close_at"])
    if fault == "expired_wake":
        c["next_wake_at"] = NOW
    elif fault == "missing_proof":
        proof = None
    elif fault == "different_key":
        proof["order"]["client_key"] = "another"
    elif fault == "different_fill":
        proof["order"]["filled_average_price"] = "55.20"
    elif fault == "unknown_outcome":
        c["diagnostic"]["unresolved"] = ["UNKNOWN"]
    elif fault == "negative_cash":
        account["cash"] = Decimal(-1)
    monkeypatch.setenv(local_paper.MODE_ENV, local_paper.MODE)
    monkeypatch.setenv(local_paper.ACCOUNT_ENV, "PAfixture")
    monkeypatch.setenv(local_paper.BACKUP_POLICY_ENV, local_paper.BACKUP_POLICY)
    monkeypatch.setenv("SENTINEL_PAPER_BUY_POLICY", MARKET_MODE)
    monkeypatch.delenv("SENTINEL_PAPER_BUY_CAP_BPS", raising=False)
    monkeypatch.delenv("SENTINEL_PAPER_DEBUG_WINDOW", raising=False)
    monkeypatch.setenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
    v["plan"].plan_id = c["plan_id"]
    authority = {"plan_fingerprint": v["plan"].fingerprint()}
    if fault != "old_policy":
        authority["market_buy_policy_sha256"] = MarketBuyPolicy().fingerprint()
    monkeypatch.setattr(dual_plan_authority, "load_authority", lambda *args, **kw: authority)
    monkeypatch.setattr(account_status, "recorded_market_working", lambda *args, **kw: proof)
    monkeypatch.setattr(sources, "_latest_account_evidence", lambda _: account)
    monkeypatch.setattr(model, "alpaca_account_row", _ALPACA_ACCOUNT_ROW)

    row = observe(v)
    if fault is None:
        assert row.status == model.WARN
        assert row.value == "PAPER NOT VERIFIED · PENDING"
        assert row.valid_until == c["next_wake_at"]
        assert row.effective_status(row.valid_until + timedelta(microseconds=1)) == model.FAIL
    else:
        assert row is None


def test_market_buy_pending_policy_guard_falsifier(ongoing, monkeypatch):
    code = textwrap.dedent(inspect.getsource(sources._matched_market_order_wait))
    guard = "dual_plan_authority.require_current_buy_policy(conn, plan=plan)"
    assert code.count(guard) == 1
    scope = dict(vars(sources))
    exec(code.replace(guard, "pass"), scope)
    monkeypatch.setattr(sources, "_matched_market_order_wait", scope["_matched_market_order_wait"])
    with pytest.raises(AssertionError):
        test_market_buy_retry_stays_pending_only_with_exact_current_native_evidence(
            ongoing, monkeypatch, "old_policy")
