"""Recovery wiring for one witnessed candidate startup warning, never an ACK."""
from copy import deepcopy
from datetime import timedelta

import pytest

from tests.scripts.test_sentinel_local_delivery_coordinator import model, operation  # noqa: F401
from tests.scripts.test_sentinel_reactivated_local_patch import expired_reactivation
from tests.scripts.test_install_verification_recovery import recovery


ALERT_ID = 'c' * 64
HOST_TOOL = {'qualified_host': 'fixture'}


def startup_operation(operation, monkeypatch):
    host, journal, delivery = expired_reactivation(operation, monkeypatch, close_minutes=18)
    original = deepcopy(journal.read())
    current_generation = host.state['control']['generation']
    host.state['retained_incidents'][ALERT_ID] = dict(
        event_type='AUTOMATION_OPERATIONAL_RED', severity='CRITICAL',
        ack_state='UNACKNOWLEDGED', created_at=model.utcnow().isoformat(),
        payload=dict(reason='WAITING_FOR_LEADER', control_generation=current_generation,
                     broker_outcome_unresolved=0))
    host.notifications[ALERT_ID] = 'immutable-candidate-alert'
    def sql(query):
        if query == recovery.evidence.REACTIVATED_RETAINED_INCIDENTS_SQL:
            return deepcopy(host.state['retained_incidents'])
        return deepcopy(host.state)

    host.sql = sql
    lineage = recovery.evidence.reactivated.require_lineage

    def snapshot(h, *, startup_alert_id=None):
        state = deepcopy(h.state)
        lineage(state, startup_alert_id=startup_alert_id)
        return state

    monkeypatch.setattr(recovery.evidence, 'snapshot', snapshot)
    seen_witnesses = []

    def witness(h, receipt, current):
        assert h is host and receipt == original
        before = receipt['artifacts']['preserved']['retained_incidents']
        model.require(set(current['retained_incidents']) - set(before) == {ALERT_ID},
                      'REACTIVATED_STARTUP_APPEND_UNPROVED')
        proof = dict(alert_id=ALERT_ID,
                     alert_sha256=model.digest(current['retained_incidents'][ALERT_ID]),
                     generation=current['control']['generation'])
        seen_witnesses.append(proof)
        return proof

    monkeypatch.setattr(recovery.reactivated_startup, 'observe_startup_append', witness)
    verified_tools = []

    def revalidate(tool, request):
        assert tool == HOST_TOOL and request == host.request
        verified_tools.append(tool)

    monkeypatch.setattr(recovery.recovery_host_tool, 'revalidate', revalidate)
    return host, journal, delivery, original, seen_witnesses, verified_tools


def test_one_witnessed_append_uses_exact_current_snapshot_without_rewriting_preflight(
        operation, monkeypatch):
    host, journal, delivery, original, witnesses, tools = startup_operation(operation, monkeypatch)
    with pytest.raises(model.DeliveryRefused, match='REACTIVATED_UNRELATED_INCIDENT'):
        recovery.evidence.snapshot(host)
    observed = deepcopy(host.state)
    canonical_states, panel_states = [], []
    original_canonical = recovery.evidence.canonical_check
    original_panel = recovery.evidence.panel

    def canonical(h, values, state, **kwargs):
        canonical_states.append(deepcopy(state))
        return original_canonical(h, values, state, **kwargs)

    def panel(h, state, **kwargs):
        panel_states.append(deepcopy(state))
        return original_panel(h, state, **kwargs)

    monkeypatch.setattr(recovery.evidence, 'canonical_check', canonical)
    monkeypatch.setattr(recovery.evidence, 'panel', panel)
    calls = len(host.calls)
    result = recovery.recover(delivery, 'witnessed-startup', host_tool=HOST_TOOL)
    assert result['stage'] == 'VERIFIED'
    assert result['history'][:-1] == original['history']
    assert all(result['artifacts'][key] == value for key, value in original['artifacts'].items())
    assert result['artifacts']['preserved'] == original['artifacts']['preserved']
    assert result['artifacts']['installation_scope'] == 'POST_TRADE_REACTIVATED_SOFTWARE_ONLY'
    assert result['artifacts']['operational_ready'] is False
    assert canonical_states == panel_states == [observed]
    assert len(witnesses) >= 3 and all(witness == witnesses[0] for witness in witnesses)
    assert len(tools) >= 2
    intent = model.read_json(journal.folder/'verification-recovery-witnessed-startup.json')
    assert intent['original_receipt'] == original and intent['host_tool'] == HOST_TOOL
    assert intent['startup_append_witness'] == witnesses[0]
    assert result['artifacts']['verification_recovery']['host_tool'] == HOST_TOOL
    assert result['artifacts']['verification_recovery']['startup_append_witness'] == witnesses[0]
    sidecar = model.read_json(journal.folder/'verification-recovery-witnessed-startup.result.json')
    assert sidecar['outcome'] == 'VERIFIED' and sidecar['host_tool'] == HOST_TOOL
    assert not any(isinstance(call, (list, tuple)) for call in host.calls[calls:])


@pytest.mark.parametrize('post_panel_delay', [0, 3])
def test_expensive_witness_precedes_finite_panel_and_expired_page_still_refuses(
        operation, monkeypatch, post_panel_delay):
    host, journal, delivery, original, _, _ = startup_operation(operation, monkeypatch)
    base = recovery.utcnow()
    elapsed = [0]
    monkeypatch.setattr(recovery, 'utcnow', lambda: base + timedelta(seconds=elapsed[0]))
    real_witness = recovery.reactivated_startup.observe_startup_append
    witness_calls = []

    def expensive_witness(*args):
        witness_calls.append(1)
        if len(witness_calls) == 3:
            elapsed[0] += 26
        elif len(witness_calls) > 3:
            elapsed[0] += 3
        return real_witness(*args)

    monkeypatch.setattr(recovery.reactivated_startup, 'observe_startup_append', expensive_witness)
    real_panel = recovery.evidence.panel

    def finite_panel(*args, **kwargs):
        result = real_panel(*args, **kwargs)
        result['installation_panel_valid_until'] = (
            recovery.utcnow() + timedelta(seconds=2)).isoformat()
        elapsed[0] += post_panel_delay
        return result

    monkeypatch.setattr(recovery.evidence, 'panel', finite_panel)
    if post_panel_delay:
        with pytest.raises(model.DeliveryRefused, match='INSTALLATION_PANEL_EXPIRED'):
            recovery.recover(delivery, 'finite-panel', host_tool=HOST_TOOL)
        assert journal.read() == original
    else:
        assert recovery.recover(delivery, 'finite-panel', host_tool=HOST_TOOL)['stage'] == 'VERIFIED'
    assert len(witness_calls) == 3


def test_final_receipt_read_cannot_commit_after_panel_expiry(operation, monkeypatch):
    host, journal, delivery, original, _, _ = startup_operation(operation, monkeypatch)
    base = recovery.utcnow()
    elapsed = [0]
    monkeypatch.setattr(recovery, 'utcnow', lambda: base + timedelta(seconds=elapsed[0]))
    panel_returned = [False]
    real_panel = recovery.evidence.panel

    def finite_panel(*args, **kwargs):
        result = real_panel(*args, **kwargs)
        result['installation_panel_valid_until'] = (
            recovery.utcnow() + timedelta(seconds=2)).isoformat()
        panel_returned[0] = True
        return result

    monkeypatch.setattr(recovery.evidence, 'panel', finite_panel)
    real_read = journal.read
    crossed = [False]

    def slow_final_read():
        receipt = real_read()
        if panel_returned[0] and not crossed[0]:
            crossed[0] = True
            elapsed[0] += 3
        return receipt

    monkeypatch.setattr(journal, 'read', slow_final_read)
    with pytest.raises(model.DeliveryRefused, match='INSTALLATION_PANEL_EXPIRED'):
        recovery.recover(delivery, 'late-final-read', host_tool=HOST_TOOL)
    assert crossed == [True] and real_read() == original


@pytest.mark.parametrize('fault', ['missing_tool', 'second_alert', 'changed_preflight',
                                   'changed_after_canonical', 'changed_after_panel'])
def test_startup_recovery_refuses_unbound_or_changing_history(
        operation, monkeypatch, fault):
    host, journal, delivery, original, _, _ = startup_operation(operation, monkeypatch)
    if fault == 'second_alert':
        host.state['retained_incidents']['d' * 64] = deepcopy(host.state['retained_incidents'][ALERT_ID])
    elif fault == 'changed_preflight':
        host.state['retained_incidents']['a' * 64]['payload']['control_generation'] = -1
    elif fault == 'changed_after_canonical':
        real = recovery.evidence.canonical_check

        def canonical(*args, **kwargs):
            result = real(*args, **kwargs)
            host.state['retained_incidents'][ALERT_ID]['payload']['broker_outcome_unresolved'] = 1
            return result

        monkeypatch.setattr(recovery.evidence, 'canonical_check', canonical)
    elif fault == 'changed_after_panel':
        real = recovery.evidence.panel

        def panel(*args, **kwargs):
            result = real(*args, **kwargs)
            host.state['retained_incidents'][ALERT_ID]['payload']['broker_outcome_unresolved'] = 1
            return result

        monkeypatch.setattr(recovery.evidence, 'panel', panel)
    with pytest.raises(model.DeliveryRefused):
        recovery.recover(delivery, 'refused-startup',
                         host_tool=None if fault == 'missing_tool' else HOST_TOOL)
    assert journal.read() == original
    assert host.state['retained_incidents'][ALERT_ID]['ack_state'] == 'UNACKNOWLEDGED'
