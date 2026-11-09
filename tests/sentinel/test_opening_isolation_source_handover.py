from sentinel import runtime_admission as admission,url_selected_source_basis as basis

def test_exact_opening_predecessor_maps_and_narrow_operational_delta():
    p=basis._profile();previous=p['retained_predecessors'][basis.OPENING_OBSERVATION_PREDECESSOR_REVISION]['files']
    actual=admission._source_files(basis.PROFILE.parent)
    assert admission.source_closure(previous)=='cfd26b1b2fe1b6ec122d9f74f3c80ce9a34b2425fdb5827c2a52ff75249f63ee'
    assert len(previous)==len(actual)==464
    assert {n for n in actual if actual[n]!=previous[n]}=={'rolling_runtime.py','structural_verification.py',
      'paper/recovery.py','panel/model.py','panel/projection_service.py','panel/verification_service.py','panel/sources.py','url_selected_source_basis.py'}
    assert basis.predecessor_view(actual,previous=previous)==previous and p['authority_effect']=='NONE'
