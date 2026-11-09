"""Fresh proof recovers bookkeeping without replaying financial installation."""
from copy import deepcopy
from datetime import timedelta
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
