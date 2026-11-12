"""Retirement renewal retains the complete installed source and economic map."""
import hashlib
import json
import pytest
from sentinel import runtime_admission as admission, url_selected_source_basis as basis
from tests.support.source_history import expanded_profile, encoded_profile, pre_market_history

REVISION='9d0743834b63a6705b3638a291a8b32f390a9eca'
CLOSURE='361372ad62cdb8b567089cde38da4ef09da1aaa293d33b1a7606e7eb175fb9b5'
CHANGED=frozenset(['panel/model.py', 'panel/presentation.py', 'url_selected_source_basis.py'])


def test_retirement_renewal_successor_preserves_every_installed_map():
    profile=basis._profile();assert basis.RETIREMENT_RENEWAL_PREDECESSOR_REVISION==REVISION
    before=profile['retained_predecessors'][REVISION]['files']
    assert len(before)==469 and admission.source_closure(before)==CLOSURE
    actual=profile['retained_predecessors'][basis.INSTALL_CRITICAL_PATH_PREDECESSOR_REVISION]['files']
    assert set(actual)==set(before)
    assert {n for n in actual if actual[n]!=before.get(n)}==CHANGED
    assert basis.predecessor_view(admission._source_files(basis.PROFILE.parent),previous=before)==before
    assert len(pre_market_history(profile)) == 43 and profile['authority_effect']=='NONE'
    originals={rev:value for rev,value in pre_market_history(profile).items() if rev not in {REVISION,basis.INSTALL_CRITICAL_PATH_PREDECESSOR_REVISION,basis.CLOSE_ROOT_PREDECESSOR_REVISION,basis.BACKUP_REFRESH_PREDECESSOR_REVISION,basis.BACKUP_MARGIN_PREDECESSOR_REVISION,basis.OPENING_STABILITY_PREDECESSOR_REVISION}}
    raw=json.dumps(originals,sort_keys=True,separators=(',',':')).encode()
    assert hashlib.sha256(raw).hexdigest()=='61777ba02bd04ba5169775b6acde744bd65981499ad939552dcd49333a4a0085'


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
