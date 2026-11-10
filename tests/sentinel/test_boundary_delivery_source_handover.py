"""The display-only boundary change preserves exact installed financial code."""
from sentinel import runtime_admission as admission,url_selected_source_basis as basis


def test_boundary_delivery_has_only_the_documented_panel_delta():
    profile=basis._profile()
    revision=basis.BOUNDARY_DISPLAY_PREDECESSOR_REVISION
    assert revision=='953351dc005b49db768d8462f727f92ffb77b58f'
    before=profile['retained_predecessors'][revision]['files']
    assert len(before)==464 and admission.source_closure(before)=='a8e082c1ae48ad56927d8a1a1c867eec25e59a1b67546685f71a4bb5b751969d'
    actual=profile['retained_predecessors'][basis.DISPLAY_DEPENDENCY_PREDECESSOR_REVISION]['files']
    assert set(actual)==set(before)
    assert {n for n in actual if actual[n]!=before[n]}=={'panel/app.py','panel/delivery.py',
        'panel/model.py','panel/operational_snapshot.py','panel/overview.py',
        'panel/projection_service.py','panel/serialization.py','url_selected_source_basis.py'}
    assert basis.predecessor_view(admission._source_files(basis.PROFILE.parent),previous=before)==before
    assert profile['authority_effect']=='NONE' and len(profile['retained_predecessors'])==40
