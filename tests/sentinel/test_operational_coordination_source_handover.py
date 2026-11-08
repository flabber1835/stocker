"""Operational work never changes the installed financial implementation."""
from sentinel import url_selected_source_basis as basis,runtime_admission as admission

def test_exact_installed_predecessor_and_complete_operational_delta():
    profile=basis._profile()
    assert basis.WORK_COORDINATION_PREDECESSOR_REVISION=='4bca82da1daff430b4f087493e4f200d2e9719dd'
    prior=profile['retained_predecessors'][basis.WORK_COORDINATION_PREDECESSOR_REVISION]['files']
    actual=admission._source_files(basis.PROFILE.parent)
    assert len(prior)==460 and len(actual)==463
    assert admission.source_closure(prior)=='09c34f464748a92aaa11f6290b34d3fbd0fdf699f5b3e7372bb1b865b42d08f2'
    assert set(actual)-set(prior)=={'panel/composition.py','panel/dom_refresh.py','snapshot_scan_admission.py'}
    assert {name for name in prior if prior[name]!=actual[name]}=={
        'committed_read.py','rolling_runtime.py','paper/finalization.py','panel/projection_service.py',
        'panel/overview.py','panel/render.py','panel/styles.py','url_selected_source_basis.py'}
    assert basis.predecessor_view(actual,previous=prior)==prior
    assert profile['authority_effect']=='NONE'
