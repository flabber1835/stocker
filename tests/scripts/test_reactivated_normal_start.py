"""First-pass reactivated startup keeps real alerts and the original deadline."""
from copy import deepcopy
from datetime import timedelta
import hashlib
from pathlib import Path

import pytest

from tests.scripts.test_sentinel_local_delivery_coordinator import coordinator, model, operation
from tests.scripts.test_sentinel_reactivated_local_patch import reactivated_host
checks = coordinator.evidence.checks
reactivated_readiness = coordinator.reactivated_readiness
reactivated = coordinator.evidence.reactivated


ALERT_ID = 'c' * 64


def ready_start(operation, monkeypatch):
    host, old, delivery = operation
    selected = dict(old.request, schema=model.REACTIVATED_SCHEMA,
                    handoff_mode='POST_TRADE_REACTIVATED')
    model.atomic_json(old.folder/'request.json', selected)
    host.request = selected
    journal = model.Journal(old.folder)
    delivery.journal = journal
    host.supports_post_trade = host.supports_post_trade_successor = True
    host.supports_post_trade_reactivated = True
    host.state = reactivated_host().state
    host.state['cycle']['execution_close_at'] = (model.utcnow()+timedelta(minutes=20)).isoformat()
    host.state['cycle']['completed_at'] = model.utcnow().isoformat()
    host.history = {group:{} for group in ('alerts','delivered_alerts','events',
                                           'fanouts','recipients','delivered_recipients')}
    host.history['alerts']['original'] = 'immutable-original'

    def snapshot(h, *, startup_alert_id=None):
        state = deepcopy(h.state)
        if startup_alert_id is None and ALERT_ID in state['retained_incidents']:
            model.require(False, 'REACTIVATED_UNRELATED_INCIDENT')
        reactivated.require_lineage(state, startup_alert_id=startup_alert_id)
        return state

    monkeypatch.setattr(coordinator.evidence, 'snapshot', snapshot)
    monkeypatch.setattr(coordinator.evidence, 'notification_history',
                        lambda h: deepcopy(h.history))

    def history(h, previous):
        now = h.history
        model.require(all(now[group].get(key) == value for group, records in previous.items()
                          for key, value in records.items()), 'HISTORY_CHANGED')
        return {group:len(set(now[group])-set(previous[group])) for group in previous}

    monkeypatch.setattr(coordinator.evidence, 'check_notification_history', history)
    monkeypatch.setattr(coordinator.evidence, 'canonical_check',
                        lambda h, *args, **kwargs: dict(book='same',
                            settled_native_positions=deepcopy(h.native)))
    monkeypatch.setattr(coordinator.evidence, 'leader', lambda h:dict(
        current=True, holder='owner', generation=h.state['control']['generation'],
        fence=8, heartbeat=h.heartbeat))
    panel_states = []

    def panel(h, state, *, wait_until):
        panel_states.append(deepcopy(state))
        return dict(installation_panel_valid_until=(model.utcnow()+timedelta(seconds=25)).isoformat(),
                    operational_ready=False)

    monkeypatch.setattr(coordinator.evidence, 'panel', panel)
    original_item = host.item

    def item(image, running, service=None):
        value = original_item(image, running, service)
        if image == host.request['candidate']['image']:
            value['Id'] = hashlib.sha256((service or 'unknown').encode()).hexdigest()
            value['State']['StartedAt'] = model.utcnow().isoformat()
        return value

    host.item = item
    host.sql = lambda query: (
        deepcopy(host.state) if query == checks.snapshot_sql('POST_TRADE_REACTIVATED') else
        deepcopy(host.state['retained_incidents']) if query == coordinator.evidence.REACTIVATED_RETAINED_INCIDENTS_SQL else
        ['10', '11'] if query == reactivated_readiness._EVENTS_FOR_ALERT.format(ALERT_ID) else
        dict(holder='owner', generation=host.state['control']['generation'], fence=8,
             acquired=host.items['sentinel-automation']['State']['StartedAt'])
        if query == reactivated_readiness._CURRENT_ACQUISITION else
        None if query == reactivated_readiness._HEALTH_EPISODE else
        pytest.fail('unexpected SQL'))
    monkeypatch.setattr(reactivated_readiness, 'require_qualified_same_tool', lambda h: None)
    witness_calls = []

    def witness(h, receipt, current):
        assert receipt['stage'] == 'APPLICATIONS_STARTED'
        assert current == h.state
        witness_calls.append(receipt['artifacts']['started_applications'])
        return dict(alert_id=ALERT_ID, alert_sha256=model.digest(current['retained_incidents'][ALERT_ID]),
                    claim_seq=10, delivery_seq=11)

    monkeypatch.setattr(reactivated_readiness.reactivated_startup,
                        'observe_startup_append', witness)
    while journal.read()['stage'] != 'START_REQUESTED':
        delivery.step()
    return host, journal, delivery, panel_states, witness_calls


def add_alert(host, *, reason='WAITING_FOR_LEADER', unsettled=0):
    host.state['retained_incidents'][ALERT_ID] = dict(
        event_type='AUTOMATION_OPERATIONAL_RED', severity='CRITICAL',
        ack_state='UNACKNOWLEDGED', created_at=model.utcnow().isoformat(),
        payload=dict(reason=reason, control_generation=host.state['control']['generation'],
                     broker_outcome_unresolved=0))
    host.state['reactivation']['unsettled_alerts'] = unsettled
    host.history['alerts'][ALERT_ID] = 'immutable-new'
    if not unsettled:
        host.history['delivered_alerts'][ALERT_ID] = 'immutable-delivery'
        host.history['events'].update({'10':'immutable-claim','11':'immutable-delivered'})


def alerting_compose(host, *, unsettled=0):
    compose = host.compose

    def startup(values, *args, **kwargs):
        result = compose(values, *args, **kwargs)
        if args[0] == 'up' and 'sentinel-automation' in args:
            add_alert(host, unsettled=unsettled)
        return result

    host.compose = startup


def test_first_pass_records_exact_processes_then_verifies_witnessed_append(operation, monkeypatch):
    host, journal, delivery, panels, witnesses = ready_start(operation, monkeypatch)
    compose = host.compose

    def startup(values, *args, **kwargs):
        result = compose(values, *args, **kwargs)
        if args[0] == 'up' and 'sentinel-automation' in args:
            add_alert(host)
        return result

    host.compose = startup
    started = delivery.step()
    assert started['stage'] == 'APPLICATIONS_STARTED'
    assert started['artifacts']['startup_tentative_alert']['alert_id'] == ALERT_ID
    assert set(started['artifacts']['started_applications']) == set(coordinator.SERVICES)
    assert all(len(item['Id']) == 64 for item in started['artifacts']['started_applications'].values())
    assert host.state['retained_incidents'][ALERT_ID]['ack_state'] == 'UNACKNOWLEDGED'
    verified = delivery.step()
    assert verified['stage'] == 'VERIFIED'
    assert verified['artifacts']['startup_append_witness']['alert_id'] == ALERT_ID
    assert verified['artifacts']['preserved']['retained_incidents'] != panels[-1]['retained_incidents']
    assert panels[-1] == host.state and witnesses
    assert verified['artifacts']['operational_ready'] is False


def test_resume_after_lost_start_stage_ack_accepts_only_same_running_candidate(operation, monkeypatch):
    host, journal, delivery, _, _ = ready_start(operation, monkeypatch)
    compose = host.compose

    def lost_ack(values, *args, **kwargs):
        result = compose(values, *args, **kwargs)
        if args[0] == 'up' and 'sentinel-automation' in args:
            add_alert(host)
            raise model.DeliveryRefused('LOST_COMPOSE_ACK')
        return result

    host.compose = lost_ack
    with pytest.raises(model.DeliveryRefused, match='LOST_COMPOSE_ACK'):
        delivery.step()
    assert journal.read()['stage'] == 'START_REQUESTED'
    host.compose = compose
    resumed = delivery.step()
    assert resumed['stage'] == 'APPLICATIONS_STARTED'
    assert resumed['artifacts']['startup_tentative_alert']['alert_id'] == ALERT_ID


def test_pending_alert_waits_for_delivery_without_recording_unsettled_state(operation, monkeypatch):
    host, journal, delivery, _, _ = ready_start(operation, monkeypatch)
    alerting_compose(host, unsettled=1)
    old_sleep = delivery.sleep
    waits = []

    def deliver(seconds):
        waits.append(seconds)
        assert journal.read()['stage'] == 'START_REQUESTED'
        assert host.state['reactivation']['unsettled_alerts'] == 1
        host.state['reactivation']['unsettled_alerts'] = 0
        host.history['delivered_alerts'][ALERT_ID] = 'immutable-delivery'
        host.history['events'].update({'10':'immutable-claim','11':'immutable-delivered'})
        old_sleep(seconds)

    delivery.sleep = deliver
    result = delivery.step()
    assert result['stage'] == 'APPLICATIONS_STARTED' and waits
    assert result['artifacts']['preserved']['reactivation']['unsettled_alerts'] == 0
    assert host.state['reactivation']['unsettled_alerts'] == 0


def test_panel_expiry_after_final_history_check_refuses_verification(operation, monkeypatch):
    host, journal, delivery, _, _ = ready_start(operation, monkeypatch)
    alerting_compose(host)
    assert delivery.step()['stage'] == 'APPLICATIONS_STARTED'
    before = deepcopy(journal.read())
    base = model.utcnow()
    late = [False]
    monkeypatch.setattr(coordinator, 'utcnow', lambda: base+timedelta(seconds=3 if late[0] else 0))

    def panel(h, state, *, wait_until):
        return dict(installation_panel_valid_until=(base+timedelta(seconds=2)).isoformat(),
                    operational_ready=False)

    monkeypatch.setattr(coordinator.evidence, 'panel', panel)
    original = reactivated_readiness.final_notification_append

    def delayed(*args):
        original(*args)
        late[0] = True

    monkeypatch.setattr(reactivated_readiness, 'final_notification_append', delayed)
    with pytest.raises(model.DeliveryRefused, match='INSTALLATION_PANEL_EXPIRED'):
        delivery.step()
    assert journal.read() == before


@pytest.mark.parametrize('fault', ['other_alert', 'old_notification', 'financial_change'])
def test_unrelated_change_never_records_startup_stage(operation, monkeypatch, fault):
    host, journal, delivery, _, _ = ready_start(operation, monkeypatch)
    compose = host.compose

    def startup(values, *args, **kwargs):
        result = compose(values, *args, **kwargs)
        if args[0] == 'up' and 'sentinel-automation' in args:
            add_alert(host, reason='OTHER' if fault == 'other_alert' else 'WAITING_FOR_LEADER')
            if fault == 'old_notification': host.history['alerts']['original'] = 'mutated'
            if fault == 'financial_change': host.state['inflight'] = 1
        return result

    host.compose = startup
    with pytest.raises(model.DeliveryRefused):
        delivery.step()
    assert journal.read()['stage'] == 'START_REQUESTED'


def test_old_qualified_release_cannot_borrow_new_host_rule(tmp_path):
    from types import SimpleNamespace
    runtime = Path(reactivated_readiness.__file__).resolve().parents[2]
    old = SimpleNamespace(request=dict(source=str(runtime), qualification=dict(source_files={
        'scripts/sentinel_local_delivery/coordinator.py':'0'*64})))
    with pytest.raises(RuntimeError, match='REACTIVATED_STARTUP_HOST_NOT_QUALIFIED'):
        reactivated_readiness.require_qualified_same_tool(old)
