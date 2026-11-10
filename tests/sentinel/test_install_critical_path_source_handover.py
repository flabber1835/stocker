"""Retirement renewal retains the complete installed source and economic map."""
import hashlib
import json
import pytest
from sentinel import runtime_admission as admission, url_selected_source_basis as basis
from tests.support.source_history import expanded_profile, encoded_profile

REVISION='21dfb0e8508d8d924a8b29a121977b1502997a0c'
CLOSURE='1e01510061f93445999f81fb503d70255e46be3fc46a40337a1886a28bc7ce9e'
CHANGED=frozenset(['panel/authority_reader.py', 'panel/verification_service.py', 'shadow_recovery.py', 'shadow_service.py', 'url_selected_source_basis.py'])


def test_install_critical_path_successor_preserves_every_installed_map():
    profile=basis._profile();assert basis.INSTALL_CRITICAL_PATH_PREDECESSOR_REVISION==REVISION
    before=profile['retained_predecessors'][REVISION]['files']
    assert len(before)==469 and admission.source_closure(before)==CLOSURE
    actual=profile['retained_predecessors'][basis.CLOSE_ROOT_PREDECESSOR_REVISION]['files']
    assert set(actual)==set(before)
    assert {n for n in actual if actual[n]!=before.get(n)}==CHANGED
    assert basis.predecessor_view(admission._source_files(basis.PROFILE.parent),previous=before)==before
    assert len(profile['retained_predecessors'])==40 and profile['authority_effect']=='NONE'
    originals={rev:value for rev,value in profile['retained_predecessors'].items() if rev not in {REVISION,basis.CLOSE_ROOT_PREDECESSOR_REVISION}}
    raw=json.dumps(originals,sort_keys=True,separators=(',',':')).encode()
    assert hashlib.sha256(raw).hexdigest()=='0f8e6ea143307164086576678c587c7f9cf6ac73d1f95e85c678482d44d2a00d'


@pytest.mark.parametrize('fault',['changed','missing','extra'])
def test_unknown_or_partial_retry_runtime_cannot_translate(fault):
    profile=basis._profile();previous=profile['retained_predecessors'][REVISION]['files']
    actual=admission._source_files(basis.PROFILE.parent)
    if fault=='changed':actual['backup_integrity_reuse.py']='0'*64
    elif fault=='missing':actual.pop('backup_maintenance_integrity.py')
    else:actual['unqualified.py']='0'*64
    assert basis.predecessor_view(actual,previous=previous)==actual


@pytest.mark.parametrize('fault',['changed','missing','extra'])
def test_independent_predecessor_pin_cannot_be_replaced(tmp_path,monkeypatch,fault):
    profile=expanded_profile();before=profile['retained_predecessors'][REVISION]
    if fault=='changed':before['files']['backup_integrity_reuse.py']='0'*64
    elif fault=='missing':before['files'].pop('backup_runtime_authority.py')
    else:before['files']['unqualified.py']='0'*64
    before['source_sha256']=basis._closure(before['files'])
    raw=encoded_profile(profile);path=tmp_path/'forged.json';path.write_bytes(raw)
    monkeypatch.setattr(basis,'PROFILE',path);monkeypatch.setattr(basis,'PROFILE_SHA256',hashlib.sha256(raw).hexdigest())
    with pytest.raises(ValueError,match='RETAINED_PREDECESSOR_CHANGED'):basis._profile()
