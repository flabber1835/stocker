"""Numeric display ordering changes no financial implementation or predecessor."""
from sentinel import runtime_admission as admission,url_selected_source_basis as basis


def test_numeric_sequence_handoff_preserves_the_installed_architecture():
    profile=basis._profile();revision=basis.DISPLAY_SEQUENCE_PREDECESSOR_REVISION
    assert revision=='4c13138360be48ca67255cea3b363b7b9abdb7a4'
    before=profile['retained_predecessors'][revision]['files']
    assert len(before)==465 and admission.source_closure(before)==(
        '108be080769643dac94a1f092633adb38661b52c6776ef7a999df9ad51a7be05')
    # Qualify this historical edge against its retained exact successor. The
    # independently pinned close-trace successor is qualified separately.
    actual=profile['retained_predecessors'][basis.CLOSE_TRACE_PREDECESSOR_REVISION]['files']
    assert set(actual)==set(before)
    assert {n for n in actual if actual[n]!=before[n]}=={
        'panel/display_dependencies.py','url_selected_source_basis.py'}
    assert basis.predecessor_view(admission._source_files(basis.PROFILE.parent),previous=before)==before
    assert profile['authority_effect']=='NONE'
