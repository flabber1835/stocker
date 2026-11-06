"""Concrete finite scopes restore on abort; no financial work is invoked."""
from contextlib import contextmanager
from types import SimpleNamespace
import pytest

def test_vivo_financial_transport_precedes_full_model_scope_and_keeps_overlay(monkeypatch):
    import full_system_core
    import system_campaign_bounded_lifecycle_dispatch as dispatch
    import system_campaign_financial_resume as resume
    import system_campaign_p07_vivo_profile as vivo
    import system_campaign_p07_abmd_lifecycle as lifecycle
    import system_campaign_p07_fin326_requalified_parent as composite
    monkeypatch.setattr(full_system_core,'hosted',lambda:None)
    calls=[]
    @contextmanager
    def transport(spec,**kwargs):
        assert kwargs['request']==resume.expected_request()
        calls.append('financial-transport')
        try:yield
        finally:calls.append('restore-transport')
    @contextmanager
    def model(spec):
        calls.append('full-model')
        try:yield
        finally:calls.append('restore-model')
    monkeypatch.setattr(vivo,'transport_context',transport)
    monkeypatch.setattr(lifecycle,'entry',model)
    monkeypatch.setattr(composite,'source_context',lambda *a,**k:pytest.fail('financial route entered SOURCE-only context'))
    spec=resume.root_spec('P07');old_api=lifecycle.api;overlay=lambda _:False
    module=SimpleNamespace(factual_overlay_needed=overlay)
    with pytest.raises(RuntimeError,match='FIN337_EXPLICIT_SCOPE_ABORT'):
        with dispatch.entry(module,spec,mode='economic'):
            assert calls==['financial-transport','full-model']
            assert module.factual_overlay_needed(spec) is True and lifecycle.api is not old_api
            raise RuntimeError('FIN337_EXPLICIT_SCOPE_ABORT')
    assert calls==['financial-transport','full-model','restore-model','restore-transport']
    assert lifecycle.api is old_api and module.factual_overlay_needed is overlay

def test_BBIG_hook_wraps_generic_overlay_and_restores_original_callbacks(monkeypatch):
    import full_system_core
    import system_campaign_bounded_lifecycle_dispatch as dispatch
    import system_campaign_financial_resume as resume
    import system_campaign_financial_uncertainty as uncertainty
    import system_campaign_financial_partial as partial
    monkeypatch.setattr(full_system_core,'hosted',lambda:None)
    spec=resume.root_spec('P06');overlay=lambda _:False
    module=SimpleNamespace(factual_overlay_needed=overlay)
    old=(uncertainty.run,uncertainty.review,partial.retained_models,partial.model_context)
    with pytest.raises(RuntimeError,match='FIN337_EXPLICIT_BBIG_ABORT'):
        with dispatch.entry(module,spec,mode='economic'):
            assert module.factual_overlay_needed(spec) is True
            assert uncertainty.run is not old[0] and uncertainty.review is not old[1]
            raise RuntimeError('FIN337_EXPLICIT_BBIG_ABORT')
    assert (uncertainty.run,uncertainty.review,partial.retained_models,partial.model_context)==old
    assert module.factual_overlay_needed is overlay
