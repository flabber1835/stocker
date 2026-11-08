"""Concrete finite scopes restore on abort; no financial work is invoked."""
from contextlib import contextmanager
from types import SimpleNamespace
import json
import pytest

@pytest.fixture(autouse=True)
def financial_generation(monkeypatch,tmp_path):
    import system_campaign_financial_resume as resume
    import system_campaign_bounded_lifecycle_dispatch as dispatch
    import system_campaign_financial_partial as partial
    original=partial.root_spec
    def historical(arm,admission_sha256=None):
        if arm=='P03' and admission_sha256 is None:
            admission_sha256='4c56c4240f1e5f36c91e76f5033ba9748d1217879043885e415727894b67fad1'
        if arm=='P06' and admission_sha256 is None:
            admission_sha256='28c768af0d50047f04ddd6924c1500bf768cc138f41808cd1c0a0b5321eb64b8'
        return original(arm,admission_sha256)
    # Preserve this earlier three-arm financial-generation regression after
    # P03's separate read-only admission; its later restart is not selected.
    monkeypatch.setattr(partial,'root_spec',historical)
    monkeypatch.setattr(resume,'root_spec',historical)
    monkeypatch.setattr(resume,'EXECUTION_MODE','OWN_ADMITTED_FINANCIAL_CONTINUATION')
    monkeypatch.setattr(resume,'SELECTED_ARMS',('P03','P06','P07'))
    request=resume.expected_request()
    (tmp_path/'system-campaign-factual-request.json').write_text(json.dumps(request))
    monkeypatch.setattr(dispatch,'HERE',tmp_path)
    return request

def test_vivo_financial_transport_precedes_full_model_scope_and_keeps_overlay(monkeypatch,financial_generation):
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
        assert kwargs['request']==financial_generation
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
