"""The operational renewal protocol retains the exact installed financial source."""
from copy import deepcopy
import hashlib
import json

import pytest

from sentinel import runtime_admission as admission,url_selected_source_basis as basis
from tests.support.source_history import expanded_profile,encoded_profile

REVISION='2714afbb25fd169295358e035cefff59db2bf67d'
CLOSURE='ec90eb9779d0ea2b0b3c7a65dd4e2219347c9809c54a610a08e6f2716dc4f4a5'
ORIGINAL_REVISIONS = (
    basis.STARTUP_PROFILE_PREDECESSOR_REVISION, basis.PANEL_PRESENTATION_PREDECESSOR_REVISION,
    basis.WORK_COORDINATION_PREDECESSOR_REVISION, basis.IDENTITY_AVAILABILITY_PREDECESSOR_REVISION,
    basis.LIVENESS_PREDECESSOR_REVISION, basis.READ_COST_PREDECESSOR_REVISION,
    basis.ROOT_CAUSE_PREDECESSOR_REVISION, basis.DIAGNOSTIC_PREDECESSOR_REVISION,
    basis.EFFICIENCY_PREDECESSOR_REVISION, basis.STARTUP_PREDECESSOR_REVISION,
    basis.FEED_DISPLAY_PREDECESSOR_REVISION, basis.CHECKPOINT_ACCESS_PREDECESSOR_REVISION,
    basis.PREPARATION_PREDECESSOR_REVISION, basis.LOCAL_PROBE_PREDECESSOR_REVISION,
    basis.PATCH_PREDECESSOR_REVISION, basis.OPERATIONAL_PREDECESSOR_REVISION,
    basis.VERIFIER_PREDECESSOR_REVISION, basis.PAPER_RELEASE_PREDECESSOR_REVISION,
    basis.DASHBOARD_PREDECESSOR_REVISION, basis.RETAINED_REVISION, basis.PREVIOUS_BASE_REVISION,
    basis.REVIEWED_PREDECESSOR_REVISION, basis.INSTALLED_PREDECESSOR_REVISION,
)


def test_two_module_operational_successor_preserves_all_original_source_maps():
    profile=basis._profile()
    assert basis.ACTIVATION_HEALTH_PREDECESSOR_REVISION==REVISION
    prior=profile['retained_predecessors'][REVISION]['files']
    endpoint=profile['retained_predecessors'][basis.PLAN_WORK_PREDECESSOR_REVISION]['files']
    actual=admission._source_files(basis.PROFILE.parent)
    assert len(prior)==len(endpoint)==463 and set(prior)==set(endpoint)
    assert admission.source_closure(prior)==CLOSURE
    assert prior['url_selected_source_basis.py']=='504ef51e6961dae121d4da55fa4bc1ab760ab83541888389e7ed0cab113f231a'
    assert {name for name in prior if endpoint[name]!=prior[name]}=={
        'shadow_health_projection.py','url_selected_source_basis.py'}
    assert basis.predecessor_view(actual,previous=endpoint)==endpoint
    assert basis.predecessor_view(actual,previous=prior)==prior
    originals={r:profile['retained_predecessors'][r] for r in ORIGINAL_REVISIONS}
    assert len(originals)==23
    assert hashlib.sha256(json.dumps(originals,sort_keys=True,separators=(',',':')).encode()).hexdigest()==(
        '99374ec7ea4bffb2fd880f9e76831446b81400ae941fcdb271800f63b4352037')
    assert profile['authority_effect']=='NONE'


@pytest.mark.parametrize('fault',['changed','missing','extra','checker'])
def test_repinning_cannot_replace_the_original_installed_source(tmp_path,monkeypatch,fault):
    value=expanded_profile();prior=value['retained_predecessors'][REVISION]
    if fault=='changed':prior['files']['shadow_health_projection.py']='f'*64
    elif fault=='missing':prior['files'].pop('shadow_health_projection.py')
    elif fault=='extra':prior['files']['unreviewed.py']='f'*64
    else:prior['files']['url_selected_source_basis.py']='f'*64
    prior['source_sha256']=basis._closure(prior['files'])
    raw=encoded_profile(value);path=tmp_path/'forged-profile.json';path.write_bytes(raw)
    monkeypatch.setattr(basis,'PROFILE',path)
    monkeypatch.setattr(basis,'PROFILE_SHA256',hashlib.sha256(raw).hexdigest())
    with pytest.raises(ValueError,match='RETAINED_PREDECESSOR_CHANGED'):basis._profile()


def test_removing_the_independent_installed_pin_fails_the_repinning_regression(tmp_path,monkeypatch):
    prior=deepcopy(basis._profile()['retained_predecessors'][REVISION])
    prior['files']['shadow_health_projection.py']='f'*64
    monkeypatch.setitem(basis.RETAINED_PREDECESSORS,REVISION,
        (len(prior['files']),basis._closure(prior['files'])))
    with pytest.raises(pytest.fail.Exception,match='DID NOT RAISE'):
        test_repinning_cannot_replace_the_original_installed_source(tmp_path,monkeypatch,'changed')
