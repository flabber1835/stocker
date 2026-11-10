"""Fresh proof recovers bookkeeping without replaying financial installation."""
from copy import deepcopy
from datetime import datetime, timedelta
import importlib

import pytest

from tests.scripts.test_sentinel_local_delivery_coordinator import coordinator, model, operation

recovery = importlib.import_module(coordinator.__package__+'.verification_recovery')


def expired(operation, monkeypatch):
    host, journal, delivery = operation
    host.values['SENTINEL_LOCAL_PAPER_BACKUP_POLICY'] = 'REQUIRED_V1'
    host.supports_verification_recovery = True
    while journal.read()['stage'] != 'APPLICATIONS_STARTED':
        with host.owned():
            delivery.step()
    now = model.utcnow()+timedelta(seconds=1000)
    monkeypatch.setattr(model, 'utcnow', lambda: now)
    monkeypatch.setattr(coordinator, 'utcnow', lambda: now)
    monkeypatch.setattr(recovery, 'utcnow', lambda: now)
    return host, journal, delivery


def test_fresh_recovery_preserves_original_attempt_and_never_restarts(operation, monkeypatch):
    host, journal, delivery = expired(operation, monkeypatch)
    before = journal.read()
    calls, canonical = len(host.calls), host.canonical_count
    with pytest.raises(model.DeliveryRefused, match='APPLICATION_READINESS_DEADLINE'):
        delivery.advance()
    result = recovery.recover(delivery, 'fresh-proof')
    assert result['stage'] == 'VERIFIED'
    assert result['history'][:-1] == before['history']
    assert all(result['artifacts'][k] == v for k, v in before['artifacts'].items())
    assert host.canonical_count == canonical+1
    assert not any(isinstance(c, (tuple, list)) for c in host.calls[calls:])
    intent = model.read_json(journal.folder/'verification-recovery-fresh-proof.json')
    assert intent['original_receipt'] == before
    assert intent['original_receipt_sha256'] == model.digest(before)
    assert result['artifacts']['verification_recovery']['intent_sha256'] == model.digest(intent)
    assert model.read_json(journal.folder/'verification-recovery-fresh-proof.result.json')['outcome'] == 'VERIFIED'
    assert delivery.advance() == result
    with pytest.raises(model.DeliveryRefused, match='FINAL_STAGE'):
        recovery.recover(delivery, 'again')


@pytest.mark.parametrize('fault,reason', [
    ('canonical','CANONICAL_ECONOMIC'), ('preservation','PRESERVED_STATE'),
    ('native','NATIVE_HOLDINGS'), ('notifications','HISTORY_CHANGED'),
    ('postgres','POSTGRES_CHANGED'), ('configuration','NON_RUNTIME_CONFIGURATION'),
    ('process','APPLICATION_STARTUP_PROCESS'), ('image','APPLICATION_STARTUP_FAILED'),
    ('deadline','RECOVERY_DEADLINE'), ('expired_panel','INSTALLATION_PANEL_EXPIRED'),
    ('changed_during_proof','PRESERVED_STATE'), ('changed_after_panel','APPLICATION_STARTUP_PROCESS'),
])
def test_recovery_refuses_current_negative_without_journal_changes(operation, monkeypatch, fault, reason):
    host, journal, delivery = expired(operation, monkeypatch)
    before = journal.read()
    if fault == 'canonical':
        monkeypatch.setattr(recovery.evidence, 'canonical_check', lambda *a: {'book':'changed'})
    elif fault == 'preservation': host.state['commands'] = 'changed'
    elif fault == 'native': host.native['native-id'] = '18'
    elif fault == 'notifications': host.notifications['old'] = 'changed'
    elif fault == 'postgres':
        monkeypatch.setattr(host, 'postgres', lambda: {'system':'different'})
    elif fault == 'configuration': host.values['SECRET'] = 'changed'
    elif fault == 'process': host.items['sentinel-panel']['RestartCount'] += 1
    elif fault == 'image': host.items['sentinel-panel']['Image'] = 'other-image'
    elif fault in {'deadline','changed_during_proof'}:
        def canonical(*a):
            if fault == 'deadline': host.clock += recovery.SECONDS+1
            else: host.state['commands'] = 'changed'
            return before['artifacts']['canonical_proof']
        monkeypatch.setattr(recovery.evidence, 'canonical_check', canonical)
    else:
        panel = recovery.evidence.panel
        def observe(*a, **kw):
            value = panel(*a, **kw)
            if fault == 'expired_panel':
                value['installation_panel_valid_until'] = model.utcnow().isoformat()
            else: host.items['sentinel-panel']['RestartCount'] += 1
            return value
        monkeypatch.setattr(recovery.evidence, 'panel', observe)
    with pytest.raises(model.DeliveryRefused, match=reason):
        recovery.recover(delivery, 'refusal')
    assert journal.read() == before
    assert model.read_json(journal.folder/'verification-recovery-refusal.result.json')['outcome'] == 'REFUSED'
    with pytest.raises(model.DeliveryRefused, match='RECOVERY_ID_ALREADY_USED'):
        recovery.recover(delivery, 'refusal')


@pytest.mark.parametrize('fault', ['stage','mode','adapter','policy','bindings','fresh','id'])
def test_explicit_recovery_scope_is_closed(operation, monkeypatch, fault):
    host, journal, delivery = expired(operation, monkeypatch)
    if fault == 'stage':
        before = journal.read()
        monkeypatch.setattr(journal, 'read', lambda: dict(before, stage='SHADOW_VERIFIED'))
    elif fault == 'mode': host.request['handoff_mode'] = 'POST_TRADE'
    elif fault == 'adapter': host.supports_verification_recovery = False
    elif fault == 'policy': host.values['SENTINEL_LOCAL_PAPER_BACKUP_POLICY'] = 'off'
    elif fault == 'bindings':
        before = deepcopy(journal.read());before['artifacts'].pop('started_applications')
        monkeypatch.setattr(journal, 'read', lambda: before)
    elif fault == 'fresh':
        monkeypatch.setattr(recovery, 'utcnow', lambda: model.utcnow()-timedelta(seconds=1000))
    with pytest.raises(model.DeliveryRefused):
        recovery.recover(delivery, '../escape' if fault == 'id' else 'scope')
    assert not list(journal.folder.glob('verification-recovery-*'))


def test_canonical_equality_guard_has_an_executed_falsifier(operation, monkeypatch):
    real = recovery.require
    monkeypatch.setattr(recovery, 'require', lambda condition, reason:
        None if reason == 'CANONICAL_ECONOMIC_PROOF_CHANGED' else real(condition, reason))
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        test_recovery_refuses_current_negative_without_journal_changes(
            operation, monkeypatch, 'canonical', 'CANONICAL_ECONOMIC')


def clean_retired_state():
    return dict(control=dict(generation=77), plan=dict(plan_id='immutable-plan'),
        reconciliation=dict(seq=247), retired_plan_commands=0,
        cycle=dict(state='SUPERSEDED', cycle_id='original-cycle', plan_id='immutable-plan',
            historical_state_only=False, control_generation=77,
            failure_code=recovery.checks.CASH_RETIRED_REASON,
            failure_detail=recovery.checks.CASH_RETIRED_DETAIL,
            last_clean_reconciliation_id='247', completed_at=(model.utcnow()-timedelta(minutes=1)).isoformat(),
            diagnostic=dict(clean=True, runtime_state='RUNNING', cash_plan_superseded=True,
                restricted_securities={}, observation_id=247, unresolved=[], foreign_orders=[], foreign_positions=[])))


def retired_operation(operation, monkeypatch):
    host, journal, _ = operation
    assert journal.read()['stage'] == 'NEW'
    selected = deepcopy(journal.request);selected['handoff_mode'] = 'POST_TRADE'
    model.atomic_json(journal.folder/'request.json', selected)
    journal = model.Journal(journal.folder);host.request = selected
    host.supports_post_trade = host.supports_post_trade_verification_recovery = True
    host.state.update(clean_retired_state())
    original = recovery.evidence.canonical_check
    def canonical(h, *args):
        return dict(original(h, *args), settled_native_positions=deepcopy(h.native))
    monkeypatch.setattr(recovery.evidence, 'canonical_check', canonical)
    delivery = coordinator.Delivery(host, journal, monotonic=lambda: host.clock, sleep=host.sleep)
    return expired((host, journal, delivery), monkeypatch)


def test_exact_clean_retired_recovery_preserves_original_attempt_and_never_restarts(operation, monkeypatch):
    host, journal, delivery = retired_operation(operation, monkeypatch)
    before = journal.read();calls = len(host.calls)
    result = recovery.recover(delivery, 'clean-retired')
    assert result['stage'] == 'VERIFIED'
    assert result['history'][:-1] == before['history']
    assert all(result['artifacts'][key] == value for key, value in before['artifacts'].items())
    assert result['artifacts']['preserved']['cycle']['state'] == 'SUPERSEDED'
    assert result['artifacts']['preserved']['retired_plan_commands'] == 0
    assert not any(isinstance(call, (tuple, list)) for call in host.calls[calls:])
    intent = model.read_json(journal.folder/'verification-recovery-clean-retired.json')
    assert intent['original_receipt'] == before and intent['authority_effect'] == 'NONE'
    assert intent['original_receipt_sha256'] == model.digest(before)
    assert (datetime.fromisoformat(intent['expires_at'])-
            datetime.fromisoformat(intent['started_at'])).total_seconds() == recovery.SECONDS


@pytest.mark.parametrize('fault', ['reason', 'detail', 'state', 'clean', 'unknown', 'foreign',
    'runtime', 'observation', 'generation', 'plan', 'completed', 'future', 'historical'])
def test_retired_recovery_requires_the_exact_preserved_positive_proof(fault):
    state = clean_retired_state();cycle = state['cycle']
    if fault == 'reason':cycle['failure_code'] = 'OTHER_RETIREMENT'
    elif fault == 'detail':cycle['failure_detail'] = 'other'
    elif fault == 'state':cycle['state'] = 'RECONCILING'
    elif fault == 'clean':cycle['diagnostic']['clean'] = 'true'
    elif fault == 'unknown':cycle['diagnostic']['unresolved'] = ['UNKNOWN']
    elif fault == 'foreign':cycle['diagnostic']['foreign_positions'] = ['foreign']
    elif fault == 'runtime':cycle['diagnostic']['runtime_state'] = 'RECONCILING'
    elif fault == 'observation':state['reconciliation']['seq'] = 248
    elif fault == 'generation':cycle['control_generation'] = 76
    elif fault == 'plan':state['plan']['plan_id'] = 'foreign'
    elif fault == 'completed':cycle['completed_at'] = None
    elif fault == 'future':cycle['completed_at'] = (model.utcnow()+timedelta(minutes=1)).isoformat()
    else:cycle['historical_state_only'] = True
    with pytest.raises(model.DeliveryRefused):
        recovery._completed_post_trade(dict(preserved=state), now=model.utcnow())


@pytest.mark.parametrize('commands', [1, None, False, '0'])
def test_retired_recovery_refuses_even_known_terminal_commands(commands):
    state = clean_retired_state();state['retired_plan_commands'] = commands
    with pytest.raises(model.DeliveryRefused, match='RECOVERY_RETIRED_PLAN_COMMANDS_EXIST'):
        recovery._completed_post_trade(dict(preserved=state), now=model.utcnow())


def test_removed_retired_zero_command_guard_is_detected(monkeypatch):
    original = recovery.require
    monkeypatch.setattr(recovery, 'require', lambda condition, reason:
        None if reason == 'RECOVERY_RETIRED_PLAN_COMMANDS_EXIST' else original(condition, reason))
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        test_retired_recovery_refuses_even_known_terminal_commands(1)


@pytest.mark.parametrize('fault', ['canonical', 'native', 'preservation', 'process', 'expired_panel', 'deadline'])
def test_retired_recovery_still_refuses_fresh_failures_without_advancing(operation, monkeypatch, fault):
    host, journal, delivery = retired_operation(operation, monkeypatch)
    before = journal.read()
    if fault == 'canonical':monkeypatch.setattr(recovery.evidence, 'canonical_check', lambda *a: {'wrong': True})
    elif fault == 'native':host.native['native-id'] = '18'
    elif fault == 'preservation':host.state['commands'] = 'changed'
    elif fault == 'process':host.items['sentinel-panel']['RestartCount'] += 1
    elif fault == 'deadline':
        def late(*a):
            host.clock += recovery.SECONDS+1
            return before['artifacts']['canonical_proof']
        monkeypatch.setattr(recovery.evidence, 'canonical_check', late)
    else:
        original = recovery.evidence.panel
        def stale(*a, **kwargs):
            return dict(original(*a, **kwargs), installation_panel_valid_until=model.utcnow().isoformat())
        monkeypatch.setattr(recovery.evidence, 'panel', stale)
    with pytest.raises(model.DeliveryRefused):
        recovery.recover(delivery, 'failed-retired')
    assert journal.read() == before
    assert model.read_json(journal.folder/'verification-recovery-failed-retired.result.json')['outcome'] == 'REFUSED'


@pytest.mark.parametrize('wrong_scope', [False, True])
def test_retired_review_only_recovery_preserves_its_exact_restricted_scope(operation, monkeypatch, wrong_scope):
    host, journal, delivery = retired_operation(operation, monkeypatch)
    before = journal.read()
    original = recovery.evidence.panel
    scope = 'CLEAN_RETIRED_PLAN_COMPATIBLE_APPLICATION_REPAIR'
    def amber(*a, **kwargs):
        return dict(original(*a, **kwargs), installation_review_pending=True, operational_ready=False,
                    installation_scope='POST_TRADE_COMPATIBLE_APPLICATION_REPAIR_WITH_OPERATOR_REVIEW' if wrong_scope else scope)
    monkeypatch.setattr(recovery.evidence, 'panel', amber)
    if wrong_scope:
        with pytest.raises(model.DeliveryRefused, match='RECOVERY_REVIEW_SCOPE_INVALID'):
            recovery.recover(delivery, 'review-retired')
        assert journal.read() == before
    else:
        result = recovery.recover(delivery, 'review-retired')
        assert result['artifacts']['operational_ready'] is False
        assert result['artifacts']['installation_scope'] == scope
        assert result['artifacts']['preserved']['cycle']['state'] == 'SUPERSEDED'
