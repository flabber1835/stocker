"""Operation-owned integrity work has one complete independently pinned edge."""
import hashlib
import json

import pytest

from sentinel import runtime_admission as admission, url_selected_source_basis as basis
from tests.support.source_history import expanded_profile, encoded_profile

REVISION='277160861e2353d8ad93d15da8e2615ebdb11c18'
CLOSURE='c4cdbfa7dca223924b047587710750062eec1dd107c38e2964bc1ec125dd56bc'
CHANGED={'backup_runtime_authority.py','economic_manifest.py','execution/reconcile.py',
    'execution/feed_actions.py','operation_read_source_basis.py','backup_maintenance_integrity.py',
    'url_selected_source_basis.py'}


def test_integrity_work_is_one_exact_complete_successor_without_old_map_loss():
    profile=basis._profile()
    assert basis.INTEGRITY_WORK_PREDECESSOR_REVISION==REVISION
    before=profile['retained_predecessors'][REVISION]['files']
    assert len(before)==466 and admission.source_closure(before)==CLOSURE
    actual=profile['retained_predecessors'][basis.BACKUP_DEADLINE_PREDECESSOR_REVISION]['files']
    assert len(actual)==468 and set(actual)-set(before)=={
        'operation_read_source_basis.py','backup_maintenance_integrity.py'}
    assert not set(before)-set(actual)
    assert {n for n in actual if actual[n]!=before.get(n)}==CHANGED
    assert basis.predecessor_view(admission._source_files(basis.PROFILE.parent),previous=before)==before
    assert len(profile['retained_predecessors'])==41 and profile['authority_effect']=='NONE'
    originals={revision:value for revision,value in profile['retained_predecessors'].items()
               if revision not in {REVISION,basis.BACKUP_DEADLINE_PREDECESSOR_REVISION,basis.MAINTENANCE_CONTINUITY_PREDECESSOR_REVISION,basis.OPENING_REPAIR_PREDECESSOR_REVISION,basis.TRANSPORT_RESOLUTION_PREDECESSOR_REVISION,basis.RETIREMENT_RENEWAL_PREDECESSOR_REVISION,basis.INSTALL_CRITICAL_PATH_PREDECESSOR_REVISION,basis.CLOSE_ROOT_PREDECESSOR_REVISION,basis.BACKUP_REFRESH_PREDECESSOR_REVISION}}
    canonical=json.dumps(originals,sort_keys=True,separators=(',',':')).encode()
    assert hashlib.sha256(canonical).hexdigest()=='452757473116229ab60a0211fc580da7b31ac9030866231d2cb878e59b42d814'


@pytest.mark.parametrize('fault',['changed','missing','extra'])
def test_partial_or_unknown_successor_cannot_inherit_predecessor(fault):
    profile=basis._profile();before=profile['retained_predecessors'][REVISION]['files']
    actual=admission._source_files(basis.PROFILE.parent)
    if fault=='changed':actual['backup_runtime_authority.py']='0'*64
    elif fault=='missing':actual.pop('operation_read_source_basis.py')
    else:actual['unqualified_neighbor.py']='0'*64
    assert basis.predecessor_view(actual,previous=before)==actual


@pytest.mark.parametrize('module',['execution/reconcile.py','execution/feed_actions.py'])
def test_mixed_known_compilers_cannot_qualify_whole_runtime_handover(module):
    profile=basis._profile();before=profile['retained_predecessors'][REVISION]['files']
    mixed=admission._source_files(basis.PROFILE.parent)
    mixed[module]=before[module]
    assert basis.predecessor_view(mixed,previous=before)==mixed


@pytest.mark.parametrize('fault',['changed','missing','extra'])
def test_repinning_does_not_replace_independently_pinned_predecessor(tmp_path,monkeypatch,fault):
    profile=expanded_profile();before=profile['retained_predecessors'][REVISION]
    if fault=='changed':before['files']['execution/reconcile.py']='0'*64
    elif fault=='missing':before['files'].pop('execution/reconcile.py')
    else:before['files']['unqualified_neighbor.py']='0'*64
    before['source_sha256']=basis._closure(before['files'])
    raw=encoded_profile(profile);path=tmp_path/'forged.json';path.write_bytes(raw)
    monkeypatch.setattr(basis,'PROFILE',path)
    monkeypatch.setattr(basis,'PROFILE_SHA256',hashlib.sha256(raw).hexdigest())
    with pytest.raises(ValueError,match='RETAINED_PREDECESSOR_CHANGED'):basis._profile()
