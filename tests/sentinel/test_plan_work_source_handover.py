"""The local work/view correction preserves every installed economic witness."""
import hashlib
import json

import pytest

from sentinel import runtime_admission as admission, url_selected_source_basis as basis
from tests.support.source_history import expanded_profile, encoded_profile

REVISION='1e7f4b181fbcb998b3086833ab813c21b1c2ca8e'
CLOSURE='17e4297b1d60a397b73994d8259252d8fd9275beb0f2657816fc357301a3de9b'
CHANGED={'automation/service.py','automation_runtime.py','backup_integrity_reuse.py',
    'backup_runtime_authority.py','panel/overview.py','paper/preparation.py',
    'supervisor_io.py','url_selected_source_basis.py'}


def test_operational_successor_preserves_all_twenty_four_source_maps():
    profile=basis._profile()
    assert basis.PLAN_WORK_PREDECESSOR_REVISION==REVISION
    previous=profile['retained_predecessors'][REVISION]['files']
    actual=profile['retained_predecessors'][basis.BACKUP_RENEWAL_PREDECESSOR_REVISION]['files']
    assert len(previous)==463 and len(actual)==464
    assert admission.source_closure(previous)==CLOSURE
    assert set(actual)-set(previous)=={'backup_integrity_reuse.py'}
    assert {name for name in actual if actual[name]!=previous.get(name)}==CHANGED
    assert basis.predecessor_view(admission._source_files(basis.PROFILE.parent),previous=previous)==previous
    originals={revision:value for revision,value in profile['retained_predecessors'].items()
               if revision not in {REVISION,basis.BACKUP_RENEWAL_PREDECESSOR_REVISION,
                                   basis.OPENING_OBSERVATION_PREDECESSOR_REVISION,
                                   basis.BOUNDARY_DISPLAY_PREDECESSOR_REVISION,
                                   basis.DISPLAY_DEPENDENCY_PREDECESSOR_REVISION,
                                   basis.DISPLAY_SEQUENCE_PREDECESSOR_REVISION,
                                   basis.CLOSE_TRACE_PREDECESSOR_REVISION,
                                   basis.ACCOUNT_CLOCK_PREDECESSOR_REVISION,
                                   basis.INTEGRITY_WORK_PREDECESSOR_REVISION,
                                   basis.BACKUP_DEADLINE_PREDECESSOR_REVISION,basis.MAINTENANCE_CONTINUITY_PREDECESSOR_REVISION,basis.OPENING_REPAIR_PREDECESSOR_REVISION,basis.TRANSPORT_RESOLUTION_PREDECESSOR_REVISION,basis.RETIREMENT_RENEWAL_PREDECESSOR_REVISION,basis.INSTALL_CRITICAL_PATH_PREDECESSOR_REVISION,basis.CLOSE_ROOT_PREDECESSOR_REVISION,basis.BACKUP_REFRESH_PREDECESSOR_REVISION,basis.BACKUP_MARGIN_PREDECESSOR_REVISION,basis.OPENING_STABILITY_PREDECESSOR_REVISION}}
    assert len(originals)==24
    assert hashlib.sha256(json.dumps(originals,sort_keys=True,separators=(',',':')).encode()).hexdigest()==(
        'a5c06518948b779dbc47890fb6c30b27000aaa948c6bd9bbafbc8f8554e82a08')
    assert profile['authority_effect']=='NONE' and profile['schema']=='sentinel.url-selected-trading-transition/44'


@pytest.mark.parametrize('fault',['changed','missing','extra'])
def test_repinning_cannot_substitute_the_independent_installed_source(tmp_path,monkeypatch,fault):
    profile=expanded_profile();previous=profile['retained_predecessors'][REVISION]
    if fault=='changed':previous['files']['backup_runtime_authority.py']='f'*64
    elif fault=='missing':previous['files'].pop('backup_runtime_authority.py')
    else:previous['files']['unreviewed.py']='f'*64
    previous['source_sha256']=basis._closure(previous['files'])
    raw=encoded_profile(profile);path=tmp_path/'forged-profile.json';path.write_bytes(raw)
    monkeypatch.setattr(basis,'PROFILE',path)
    monkeypatch.setattr(basis,'PROFILE_SHA256',hashlib.sha256(raw).hexdigest())
    with pytest.raises(ValueError,match='RETAINED_PREDECESSOR_CHANGED'):basis._profile()
