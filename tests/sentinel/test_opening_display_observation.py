from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from sentinel.execution import journal, opening_display
from sentinel.execution.identity import CommandIdentity, DeploymentIdentity
from sentinel.panel import delivery, model, presentation
from tests.sentinel.test_operator_monitoring import db, issue369_pg  # noqa: F401
from tests.sentinel.test_paper_account_status import collect, fixture
from tests.sentinel.test_panel_historical_mirror_schedule import healthy_history_panel


BOUND = ('account-display', 'alpaca', 'PAfixture', 1)
CYCLE = 'c' * 64
PLAN = 'opening-display-plan'
ASSET = '22222222-2222-4222-8222-222222222222'


def waiting_cycle(db, *, until=timedelta(minutes=2)):
    now = db.execute('SELECT clock_timestamp()').fetchone()[0]
    execute = now + until
    opened = execute - timedelta(minutes=1)
    decision = opened.date() - timedelta(days=1)
    effective = opened.date()
    old = now - timedelta(minutes=40)
    seq = db.execute("INSERT INTO sentinel_observations(observed_at,completeness,"
        "positions,orders,runtime_state) VALUES (%s,'COMPLETE','{}','[]','RUNNING') "
        "RETURNING seq", (old,)).fetchone()[0]
    db.execute("UPDATE sentinel_automation_control SET enabled=true,kill_switch_engaged=false,"
        "deployment_id=%s,broker=%s,broker_account_id=%s,takeover_epoch=%s,certificate_sha256=%s,"
        "config_sha256=%s,rollout_mode='CONTROLLER',rollout_version=1,authority_verdict='PASS',"
        "enabled_at=%s", (*BOUND, 'a'*64, 'b'*64, opened-timedelta(hours=1)))
    db.execute("UPDATE sentinel_automation_lease SET holder_id='fixture',fence_token=2,"
        "control_generation=1,acquired_at=%s,heartbeat_at=%s,expires_at=%s", (old, now, execute+timedelta(minutes=2)))
    db.execute("INSERT INTO sentinel_execution_plans(plan_id,decision_session,effective_session,"
        "target_exposure,data_version,deployment_id,broker,broker_account_id,takeover_epoch,"
        "publication_fingerprint,rollout_mode,rollout_version,rollout_certificate_sha256) "
        "VALUES (%s,%s,%s,0.55,20,%s,%s,%s,%s,%s,'CONTROLLER',1,%s)",
        (PLAN, decision, effective, *BOUND, 'e'*64, 'a'*64))
    db.execute("INSERT INTO sentinel_automation_cycles(cycle_id,state,decision_session,effective_session,"
        "deployment_id,broker,broker_account_id,takeover_epoch,control_generation,certificate_sha256,"
        "rollout_mode,rollout_version,config_sha256,decision_close_at,prepare_at,execution_open_at,"
        "execute_at,execution_close_at,plan_id,data_version,publication_fingerprint,plan_fingerprint,"
        "last_clean_reconciliation_id,last_fence_token) "
        "VALUES (%s,'WAITING_OPEN',%s,%s,%s,%s,%s,%s,1,%s,'CONTROLLER',1,%s,%s,%s,%s,%s,%s,"
        "%s,20,%s,%s,%s,2)", (CYCLE, decision, effective, *BOUND, 'a'*64, 'b'*64,
        opened-timedelta(hours=1), opened-timedelta(minutes=30), opened, execute,
        execute+timedelta(hours=6), PLAN, 'e'*64, 'f'*64, str(seq)))
    db.commit()
    return seq


@pytest.mark.parametrize('fault', [None, 'different_asset', 'quantity', 'working', 'unknown'])
def test_preopen_collector_uses_native_gets_without_writing_financial_journal(db, monkeypatch, fault):
    f = fixture(db, monkeypatch)
    seq = waiting_cycle(db)
    payload = dict(broker='alpaca', account_id='PAfixture', completeness='COMPLETE',
                   positions=[{'broker_id': ASSET, 'quantity': '2'}])
    monkeypatch.setattr(journal, 'load_observation_payload', lambda *_: payload)
    f.positions.append(dict(symbol='MTD', asset_id='33333333-3333-4333-8333-333333333333'
        if fault == 'different_asset' else ASSET, qty='3' if fault == 'quantity' else '2'))
    if fault == 'working':
        f.orders.append(dict(id='44444444-4444-4444-8444-444444444444', client_order_id='foreign',
            asset_id=ASSET, symbol='MTD', side='buy', status='new', qty='1', filled_qty='0',
            type='limit', limit_price='100', time_in_force='day', extended_hours=False))
    if fault == 'unknown':
        key = CommandIdentity(DeploymentIdentity(*BOUND), PLAN, 'mtd').client_key
        db.execute("INSERT INTO sentinel_commands(client_key,plan_id,security_id,deployment_id,broker,"
            "broker_account_id,takeover_epoch,symbol,side,quantity,state) "
            "VALUES (%s,%s,'mtd',%s,%s,%s,%s,'MTD','BUY',1,'UNKNOWN')", (key, PLAN, *BOUND))
        db.commit()

    assert collect(db, f)
    at = opening_display.observed_at(db, cycle_id=CYCLE, plan_id=PLAN, reconciliation=seq)
    assert (at is not None) is (fault is None)
    assert db.execute('SELECT count(*) FROM sentinel_observations').fetchone()[0] == 1
    assert db.execute('SELECT count(*) FROM sentinel_fills').fetchone()[0] == 0
    if fault is None:
        assert opening_display.observed_at(db, cycle_id=CYCLE, plan_id=PLAN,
                                            reconciliation=seq+1) is None
        f.calls.clear()
        assert collect(db, f)
        assert all(path == '/v2/account' for _, path in f.calls)
        assert opening_display.observed_at(db, cycle_id=CYCLE, plan_id=PLAN, reconciliation=seq) == at
        db.execute("UPDATE sentinel_automation_cycles SET state='EXECUTING'")
        db.commit()
        assert opening_display.observed_at(db, cycle_id=CYCLE, plan_id=PLAN, reconciliation=seq) == at
        assert opening_display.observed_at(db, cycle_id=CYCLE, plan_id=PLAN, waiting=True) is None
        db.execute("UPDATE sentinel_automation_lease SET fence_token=fence_token+1")
        db.commit()
        assert opening_display.observed_at(db, cycle_id=CYCLE, plan_id=PLAN, reconciliation=seq) is None


def test_account_only_poll_outside_preopen_window_never_mints_visibility(db, monkeypatch):
    f = fixture(db, monkeypatch)
    seq = waiting_cycle(db, until=timedelta(minutes=4))
    assert collect(db, f)
    assert all(path == '/v2/account' for _, path in f.calls)
    assert opening_display.observed_at(db, cycle_id=CYCLE, plan_id=PLAN, reconciliation=seq) is None


@pytest.mark.parametrize('fault', [None, 'missing', 'stale', 'at_execution', 'negative'])
def test_bell_handoff_preserves_only_independently_current_waiting_facts(monkeypatch, fault):
    bell = datetime(2026, 11, 2, 14, 30, tzinfo=timezone.utc)
    generated = bell - timedelta(seconds=1)
    execute = bell + timedelta(minutes=1)
    page = healthy_history_panel(now=generated, execute_at=execute)
    broker = page.row('broker')
    broker_at = generated - timedelta(minutes=1)
    broker = replace(broker, as_of=broker_at, valid_until=broker_at+timedelta(minutes=10))
    if fault == 'stale':
        broker = replace(broker, as_of=bell-timedelta(minutes=30), valid_until=bell)
    elif fault == 'negative':
        broker = replace(broker, status=model.FAIL)
    saved = page.row('paper_plan')
    saved = replace(saved, paper_plan=saved.paper_plan.model_copy(update={'execution_open_at':bell}))
    replacements = {'broker':broker, 'paper_plan':saved}
    page = replace(page, rows=[replacements.get(row.key,row) for row in page.rows])
    monkeypatch.setattr(opening_display, 'observed_at', lambda *_, **__: None if fault == 'missing' else broker_at)
    now = execute if fault == 'at_execution' else bell
    keys = delivery.bell_handoff(object(), page, expired_at=bell, now=now)
    assert (keys is not None) is (fault is None)
    if keys is not None:
        view = replace(page, now=now, observation_current=False, observation_retained=True,
                       observation_display_current=True, observation_display_keys=keys)
        assert presentation.dashboard_health(view)['color'] == 'green'
        assert not view.observation_current
