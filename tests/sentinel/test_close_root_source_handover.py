"""The close patch preserves every economic contributor and historical edge."""
import pytest

from sentinel import runtime_admission as admission, url_selected_source_basis as basis


def test_close_patch_is_exact_nonfinancial_successor_of_installed_application():
    profile=basis._profile()
    revision=basis.CLOSE_TRACE_PREDECESSOR_REVISION
    assert revision=='69c4d175356c1b4fffa680a39f886fa29f9053e1'
    before=profile['retained_predecessors'][revision]['files']
    assert len(before)==465 and admission.source_closure(before)==(
        'cf1c4270e33e79725188018aa7b15a6b27a0c814d86784c1a9050bc5140866b3')
    actual=profile['retained_predecessors'][basis.ACCOUNT_CLOCK_PREDECESSOR_REVISION]['files']
    assert set(actual)-set(before)=={'panel/readiness_handoff.py'}
    assert not set(before)-set(actual)
    assert {n for n in actual if actual[n]!=before.get(n)}=={
        'feed/acquisition_parts.py','panel/dom_refresh.py','panel/operational_snapshot.py',
        'panel/postclose_feed_wait.py','panel/projection_service.py','panel/publication_wait.py',
        'panel/readiness_handoff.py','panel/render.py','panel/sources.py','url_selected_source_basis.py'}
    assert basis.predecessor_view(admission._source_files(basis.PROFILE.parent),previous=before)==before
    assert len(set(profile['retained_predecessors']) - {basis.MARKET_BUY_PREDECESSOR_REVISION, basis.CLOSE_RELIABILITY_PREDECESSOR_REVISION}) == 43 and profile['authority_effect']=='NONE'


def test_partial_or_changed_candidate_cannot_translate_into_old_authority():
    actual=admission._source_files(basis.PROFILE.parent)
    before=basis._profile()['retained_predecessors'][basis.CLOSE_TRACE_PREDECESSOR_REVISION]['files']
    changed=dict(actual);changed['panel/readiness_handoff.py']='0'*64
    assert basis.predecessor_view(changed,previous=before)==changed
    partial=dict(actual);partial.pop('panel/readiness_handoff.py')
    assert basis.predecessor_view(partial,previous=before)==partial
