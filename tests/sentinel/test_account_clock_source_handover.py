"""Forward repair preserves the unfinished candidate and economic identity."""
from sentinel import runtime_admission as admission, url_selected_source_basis as basis


def test_account_clock_repair_changes_only_observation_presentation():
    profile=basis._profile();revision=basis.ACCOUNT_CLOCK_PREDECESSOR_REVISION
    assert revision=='4c90f4eebb660ee31947739d149a461f7576bcb9'
    previous=profile['retained_predecessors'][revision]['files']
    assert len(previous)==466 and admission.source_closure(previous)==(
        'f24c3543ce5b2f25d63d409b5d9b174b4273ec6fafe6fc4a817c4a9952f33332')
    actual=profile['retained_predecessors'][basis.INTEGRITY_WORK_PREDECESSOR_REVISION]['files']
    assert set(actual)==set(previous)
    assert {name for name in actual if actual[name]!=previous[name]}=={
        'panel/sources.py','url_selected_source_basis.py'}
    assert basis.predecessor_view(admission._source_files(basis.PROFILE.parent),previous=previous)==previous
    assert len(profile['retained_predecessors'])==40 and profile['authority_effect']=='NONE'


def test_changed_or_partial_repair_does_not_translate_to_failed_candidate():
    previous=basis._profile()['retained_predecessors'][basis.ACCOUNT_CLOCK_PREDECESSOR_REVISION]['files']
    actual=admission._source_files(basis.PROFILE.parent)
    broken=dict(actual);broken['panel/sources.py']='0'*64
    assert basis.predecessor_view(broken,previous=previous)==broken
    partial=dict(actual);partial.pop('panel/sources.py')
    assert basis.predecessor_view(partial,previous=previous)==partial
