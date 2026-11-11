"""Market close corrections retain the complete installed source and economic map."""
import hashlib
import json
import pytest
from sentinel import runtime_admission as admission, url_selected_source_basis as basis
from tests.support.source_history import expanded_profile, encoded_profile

REVISION='42d775b6952138191f89deb5054f97c079624bc2'
CLOSURE='890c1546a6ed20243517e263d5b6755e8e89039997fa7447aa4eef30dc20a702'
CHANGED=frozenset(['automation/model.py', 'automation/service.py', 'automation_runtime.py', 'backup_continuity.py', 'backup_runtime_authority.py', 'feed/rolling_go_inputs.py', 'panel/postclose_feed_wait.py', 'panel/presentation.py', 'panel/projection_service.py', 'panel/projection_worker.py', 'panel/shadow_source_wait.py', 'panel/sources.py', 'rolling_runtime.py', 'shadow_runtime.py', 'shadow_supervisor.py', 'url_selected_source_basis.py'])


def test_close_root_corrections_successor_preserves_every_installed_map():
    profile=basis._profile();assert basis.CLOSE_ROOT_PREDECESSOR_REVISION==REVISION
    before=profile['retained_predecessors'][REVISION]['files']
    assert len(before)==469 and admission.source_closure(before)==CLOSURE
    actual=profile['retained_predecessors'][basis.BACKUP_REFRESH_PREDECESSOR_REVISION]['files']
    assert set(actual)==set(before)
    assert {n for n in actual if actual[n]!=before.get(n)}==CHANGED
    assert basis.predecessor_view(admission._source_files(basis.PROFILE.parent),previous=before)==before
    assert len(profile['retained_predecessors'])==41 and profile['authority_effect']=='NONE'
    originals={rev:value for rev,value in profile['retained_predecessors'].items() if rev not in {REVISION,basis.BACKUP_REFRESH_PREDECESSOR_REVISION}}
    raw=json.dumps(originals,sort_keys=True,separators=(',',':')).encode()
    assert hashlib.sha256(raw).hexdigest()=='112941159785c415c2889d50ffb48e1f2d0a0656fb580f29ce22b79ec52d78e3'


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
