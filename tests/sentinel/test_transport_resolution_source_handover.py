"""Transport resolution retains the complete installed source and economic map."""
import hashlib
import json
import pytest
from sentinel import runtime_admission as admission, url_selected_source_basis as basis
from tests.support.source_history import expanded_profile, encoded_profile

REVISION='1842da067bd5f23bf8fc9ca88859e8208d8b302e'
CLOSURE='d91cc2fa70a92fc893a29571343b767776d82d1a863c8efe4ca38103a7344e55'
CHANGED=frozenset(['panel/model.py', 'panel/presentation.py', 'url_selected_source_basis.py'])


def test_transport_resolution_successor_preserves_every_installed_map():
    profile=basis._profile();assert basis.TRANSPORT_RESOLUTION_PREDECESSOR_REVISION==REVISION
    before=profile['retained_predecessors'][REVISION]['files']
    assert len(before)==469 and admission.source_closure(before)==CLOSURE
    actual=profile['retained_predecessors'][basis.RETIREMENT_RENEWAL_PREDECESSOR_REVISION]['files']
    assert set(actual)==set(before)
    assert {n for n in actual if actual[n]!=before.get(n)}==CHANGED
    assert basis.predecessor_view(admission._source_files(basis.PROFILE.parent),previous=before)==before
    assert len(profile['retained_predecessors'])==42 and profile['authority_effect']=='NONE'
    originals={rev:value for rev,value in profile['retained_predecessors'].items() if rev not in {REVISION,basis.RETIREMENT_RENEWAL_PREDECESSOR_REVISION,basis.INSTALL_CRITICAL_PATH_PREDECESSOR_REVISION,basis.CLOSE_ROOT_PREDECESSOR_REVISION,basis.BACKUP_REFRESH_PREDECESSOR_REVISION,basis.BACKUP_MARGIN_PREDECESSOR_REVISION}}
    raw=json.dumps(originals,sort_keys=True,separators=(',',':')).encode()
    assert hashlib.sha256(raw).hexdigest()=='459299c28279470f6526654e1384315fcf787bbc84f57fed4bc1fb36d3d78c0a'


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
