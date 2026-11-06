"""The concrete new financial overlay remains active inside the DOVA scope."""
from contextlib import contextmanager
from types import SimpleNamespace
import pytest
def test_THOR_facade_runs_after_generic_overlay_and_restores_both_worker_hooks(monkeypatch):
    import full_system_core
    import system_campaign_bounded_lifecycle_dispatch as dispatch
    import system_campaign_bounded_sensor_runtime_v2 as typed
    import system_campaign_financial_uncertainty as uncertainty
    import system_campaign_financial_resume as resume
    from system_campaign_financial_partial import root_spec
    monkeypatch.setattr(full_system_core,'hosted',lambda:None)
    calls=[]
    @contextmanager
    def context(*args,**kwargs):
        calls.append('enter')
        try:yield
        finally:calls.append('exit')
    monkeypatch.setattr(typed,'entry_context',context)
    spec=root_spec('P03','4c56c4240f1e5f36c91e76f5033ba9748d1217879043885e415727894b67fad1')
    request=resume.expected_request();assert request['selected_p03_thor_ordinary17']['P03']['old_committed_proof_rows']==49
    overlay=lambda _:False;module=SimpleNamespace(factual_overlay_needed=overlay)
    old_run,old_review=uncertainty.run,uncertainty.review
    with pytest.raises(RuntimeError,match='EXPLICIT_THOR_ABORT'):
        with dispatch.entry(module,spec,mode='economic'):
            assert module.factual_overlay_needed(spec) is True and calls==['enter']
            assert uncertainty.run is not old_run and uncertainty.review is not old_review
            raise RuntimeError('EXPLICIT_THOR_ABORT')
    assert calls==['enter','exit'] and module.factual_overlay_needed is overlay
    assert uncertainty.run is old_run and uncertainty.review is old_review
