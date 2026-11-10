"""Display dependency handoff keeps every predecessor and financial byte exact."""
from sentinel import runtime_admission as admission,url_selected_source_basis as basis


def test_dependency_handoff_preserves_the_exact_installed_source_and_only_panel_delta():
    profile=basis._profile();revision=basis.DISPLAY_DEPENDENCY_PREDECESSOR_REVISION
    assert revision=='7d267e004b894b4d98ccad977bbbc041dcf4b11c'
    previous=profile['retained_predecessors'][revision]['files']
    assert len(previous)==464 and admission.source_closure(previous)==(
        'e9bbe9e5df9acd4d8c0397112d8b5ec9ea7640ff70d926b4a8ee1ba6f609cdf2')
    actual=profile['retained_predecessors'][basis.DISPLAY_SEQUENCE_PREDECESSOR_REVISION]['files']
    assert set(actual)==set(previous)|{'panel/display_dependencies.py'}
    assert {n for n in actual if actual[n]!=previous.get(n)}=={
        'panel/app.py','panel/composition.py','panel/delivery.py','panel/display_dependencies.py',
        'panel/model.py','panel/operational_snapshot.py','panel/presentation.py',
        'panel/projection_service.py','panel/read_projection.py','panel/render.py',
        'panel/serialization.py','panel/styles.py','url_selected_source_basis.py'}
    assert basis.predecessor_view(admission._source_files(basis.PROFILE.parent),previous=previous)==previous
    assert len(profile['retained_predecessors'])==37 and profile['authority_effect']=='NONE'
