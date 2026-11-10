"""Opening repair retains the complete installed source and economic map."""
import hashlib
import json
import pytest
from sentinel import runtime_admission as admission, url_selected_source_basis as basis
from tests.support.source_history import expanded_profile, encoded_profile

REVISION='e4d8671cb84af325fb5000cf8eaa2a4e0cf454c7'
CLOSURE='396f96370ede595c548245f042315e7b016a2ff96a339d1b40ad0c90472f3895'
CHANGED={'panel/model.py', 'execution/broker_cash.py', 'checkpoint_read_source_basis.py', 'rolling_daily_checkpoint.py', 'execution/protected_funding.py', 'panel/sources.py', 'semantic_source_basis.py', 'panel/authority_reader.py', 'rolling_checkpoint.py', 'url_selected_source_basis.py', 'committed_read.py', 'panel/presentation.py', 'panel/projection_service.py', 'paper/cash.py'}


def test_opening_repair_successor_preserves_every_installed_map():
    profile=basis._profile();assert basis.OPENING_REPAIR_PREDECESSOR_REVISION==REVISION
    before=profile['retained_predecessors'][REVISION]['files']
    assert len(before)==468 and admission.source_closure(before)==CLOSURE
    actual=admission._source_files(basis.PROFILE.parent)
    assert set(actual)==set(before)|{'checkpoint_read_source_basis.py'}
    assert {n for n in actual if actual[n]!=before.get(n)}==CHANGED
    assert basis.predecessor_view(admission._source_files(basis.PROFILE.parent),previous=before)==before
    assert len(profile['retained_predecessors'])==36 and profile['authority_effect']=='NONE'
    originals={rev:value for rev,value in profile['retained_predecessors'].items() if rev!=REVISION}
    raw=json.dumps(originals,sort_keys=True,separators=(',',':')).encode()
    assert hashlib.sha256(raw).hexdigest()=='055028672260eb415fe9d134c6c4dedf0bcc638552bb88166b564e901ed19862'


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
