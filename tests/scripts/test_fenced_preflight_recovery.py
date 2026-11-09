"""Expired stopped installation earns new evidence without rewriting history."""
from copy import deepcopy
from datetime import timedelta
import importlib

import pytest

from tests.scripts.test_sentinel_local_delivery_coordinator import coordinator, model, operation

recovery = importlib.import_module(coordinator.__package__+'.fenced_recovery')


def expired(operation, monkeypatch):
    host, journal, delivery = operation
    host.values['SENTINEL_LOCAL_PAPER_BACKUP_POLICY'] = 'REQUIRED_V1'
    host.supports_verification_recovery = True
    while journal.read()['stage'] != 'COMPOSE_INSTALLED':
        with host.owned():delivery.step()
    now=model.utcnow()+timedelta(seconds=1000)
    for module in (model, coordinator, recovery):
        monkeypatch.setattr(module, 'utcnow', lambda: now)
    monkeypatch.setattr(recovery.environment, 'install', lambda h,v: h.calls.append('reader-proof'))
    return host,journal,delivery


def test_stopped_roll_reearns_proof_preserves_history_and_finishes(operation,monkeypatch):
    host,journal,delivery=expired(operation,monkeypatch)
    before=deepcopy(journal.read());canonical=host.canonical_count
    with pytest.raises(model.DeliveryRefused,match='HANDOFF_INTERVAL_EXPIRED'):delivery.advance()
    result=recovery.recover(delivery,'new-proof')
    assert result['stage']=='VERIFIED'
    assert result['history'][:len(before['history'])]==before['history']
    assert all(result['artifacts'][k]==v for k,v in before['artifacts'].items())
    assert host.canonical_count==canonical+1 and 'reader-proof' in host.calls
    certificate=model.read_json(journal.folder/recovery.CERTIFICATE)
    assert certificate['original']==before and certificate['authority_effect']=='NONE'
    with pytest.raises(model.DeliveryRefused):recovery.recover(delivery,'again')


@pytest.mark.parametrize('fault', ['canonical','state','native','configuration','process','reader','storage','deadline'])
def test_recovery_current_negatives_never_issue_certificate(operation,monkeypatch,fault):
    host,journal,delivery=expired(operation,monkeypatch)
    before=journal.read()
    if fault=='canonical':monkeypatch.setattr(recovery.evidence,'canonical_check',lambda *a:{'changed':True})
    elif fault=='state':host.state['commands']='changed'
    elif fault=='native':host.native['native-id']='18'
    elif fault=='configuration':host.values['SECRET']='changed'
    elif fault=='process':host.items['sentinel-panel']['State']['Running']=True
    elif fault=='reader':monkeypatch.setattr(recovery.environment,'install',lambda *a:model.require(False,'READER_REFUSED'))
    elif fault=='storage':monkeypatch.setattr(host,'postgres',lambda:{'different':True})
    else:monkeypatch.setattr(delivery,'monotonic',iter([0,601]).__next__)
    with pytest.raises(model.DeliveryRefused):recovery.recover(delivery,'negative')
    assert journal.read()==before and not (journal.folder/recovery.CERTIFICATE).exists()


def test_explicit_certificate_has_fixed_age_and_cannot_hide_changed_original(operation,monkeypatch):
    host,journal,delivery=expired(operation,monkeypatch)
    recovery.recover(delivery,'fixed')
    value=model.read_json(journal.folder/recovery.CERTIFICATE)
    timestamp=value['original']['artifacts']['preflight_at']
    later=model.utcnow()+timedelta(seconds=901)
    monkeypatch.setattr(coordinator,'utcnow',lambda:later)
    with pytest.raises(model.DeliveryRefused,match='HANDOFF_INTERVAL_EXPIRED'):delivery._fresh(timestamp)
    value['request_sha256']='f'*64
    (journal.folder/recovery.CERTIFICATE).write_bytes(model.canonical(value))
    with pytest.raises(model.DeliveryRefused,match='IDENTITY_CHANGED'):delivery._fresh(timestamp)


def test_canonical_recovery_guard_has_executed_falsifier(operation,monkeypatch):
    real=recovery.require
    monkeypatch.setattr(recovery,'require',lambda ok,reason:
        None if reason=='CANONICAL_ECONOMIC_PROOF_CHANGED' else real(ok,reason))
    with pytest.raises(pytest.fail.Exception,match='DID NOT RAISE'):
        test_recovery_current_negatives_never_issue_certificate(operation,monkeypatch,'canonical')


def test_preflight_reader_refusal_precedes_drain(operation):
    host,journal,delivery=operation
    host.preflight_environment=lambda values:model.require(False,'READER_REFUSED')
    with pytest.raises(model.DeliveryRefused,match='READER_REFUSED'):delivery.advance()
    assert journal.read()['stage']=='NEW'
    assert all(v['State']['Running'] for v in host.items.values())
