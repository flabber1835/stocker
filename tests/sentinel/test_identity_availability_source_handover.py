"""The operational availability patch retains the exact installed source."""
from copy import deepcopy
import hashlib

import pytest

from tests.support.source_history import expanded_profile, encoded_profile

from sentinel import url_selected_source_basis as basis,runtime_admission as admission

REVISION='34a28504a87610fd5c159115fc0b75017ae944ea'
CLOSURE='e7d7971f85feb8e4432589d06cf796e4395dc2b1c2d7eddf4f5f38877d5ee73c'


def test_exact_installed_map_and_only_identity_availability_and_checker_change():
    profile=basis._profile()
    assert basis.IDENTITY_AVAILABILITY_PREDECESSOR_REVISION==REVISION
    prior=profile['retained_predecessors'][REVISION]['files']
    actual=profile['retained_predecessors'][basis.WORK_COORDINATION_PREDECESSOR_REVISION]['files']
    assert len(prior)==len(actual)==460 and admission.source_closure(prior)==CLOSURE
    assert {name for name in prior if prior[name]!=actual[name]}=={
        'panel/authority_reader.py','url_selected_source_basis.py'}
    assert basis.predecessor_view(admission._source_files(basis.PROFILE.parent),previous=prior)==prior
    assert profile['authority_effect']=='NONE' and len(profile['retained_predecessors'])==24
    assert basis.PROFILE.stat().st_size<1_000_000


@pytest.mark.parametrize('fault',['hash','missing','extra','neighbor'])
def test_installed_source_cannot_be_repinned_with_a_self_consistent_fake_map(tmp_path,monkeypatch,fault):
    profile=expanded_profile();prior=profile['retained_predecessors'][REVISION]
    if fault=='hash':prior['files']['panel/authority_reader.py']='f'*64
    elif fault=='missing':prior['files'].pop('panel/authority_reader.py')
    elif fault=='extra':prior['files']['foreign.py']='f'*64
    else:prior['files']['core/decision.py']='f'*64
    prior['source_sha256']=basis._closure(prior['files'])
    raw=encoded_profile(profile)
    path=tmp_path/'profile.json';path.write_bytes(raw)
    monkeypatch.setattr(basis,'PROFILE',path)
    monkeypatch.setattr(basis,'PROFILE_SHA256',hashlib.sha256(raw).hexdigest())
    with pytest.raises(ValueError,match='RETAINED_PREDECESSOR_CHANGED'):basis._profile()
