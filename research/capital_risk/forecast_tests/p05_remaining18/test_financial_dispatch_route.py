"""Actual finite lifecycle bindings only; abort before any financial operation."""
import pytest

def test_P05_dispatch_uses_v2_packet_gate_and_restores_all_hooks_on_abort(monkeypatch):
    import full_system_core
    import system_campaign_bounded_lifecycle_dispatch as dispatch
    import system_campaign_financial_resume as resume
    import system_campaign_p05_remaining_runtime_v2 as runtime
    import system_campaign_pending_cash_api as pending
    import system_campaign_retained_forward_cash as prior
    monkeypatch.setattr(full_system_core,'hosted',lambda:None)
    spec=resume.root_spec('P05');request=resume.expected_request()
    assert runtime.selected(spec,request)
    names=('preflight','financial_inputs','qualified_overlay','review_adoption','factual_overlay_needed')
    saved={n:getattr(resume,n) for n in names};old_parent,old_merge=pending.for_parent,prior.merge_terms
    with pytest.raises(RuntimeError,match='FIN338_EXPLICIT_SCOPE_ABORT'):
        with dispatch.entry(resume,spec,mode='economic'):
            assert resume.factual_overlay_needed(spec) is True
            assert resume.qualified_overlay is not saved['qualified_overlay']
            scope=resume.qualified_overlay.__globals__
            assert scope['copy_provider_from_preflight'] is runtime.copy_provider_from_preflight
            assert scope['gate_class'] is runtime.gate_class
            assert pending.for_parent is not old_parent and prior.merge_terms is not old_merge
            raise RuntimeError('FIN338_EXPLICIT_SCOPE_ABORT')
    assert all(getattr(resume,n) is v for n,v in saved.items())
    assert pending.for_parent is old_parent and prior.merge_terms is old_merge
