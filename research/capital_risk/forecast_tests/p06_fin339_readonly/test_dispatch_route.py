"""Current exact request and dispatch seams; no canonical runtime execution."""
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
import json
import pytest
import full_system_core
import system_campaign_bounded_lifecycle_dispatch as dispatch
import system_campaign_p06_fin339_readonly_recovery_v2 as recovery
import system_campaign_financial_resume as resume

CAPTURE=Path('C:/Users/mbron/.codex/visualizations/2026/11/05/01a1ac36-4c96-7aa1-82ca-4efb70a86ea8/review342-source-snapshot/system-campaign-factual-request.json')
def historical_request():return json.loads(CAPTURE.read_bytes())

def test_captured_request_is_exact_failed_transport_review_only():
    request=historical_request();assert request['schema']=='research.system-campaign-accurate-resume-request/208' and len(request['sources'])==630
    assert request['arms']==['P06'] and request['maximum_parallel_financial_workers']==0
    assert request['maximum_parallel_readonly_workers']==1 and recovery.selected_request(request)
    assert resume.root_spec('P06')['measured_closes']==1383
    assert recovery.target()['measured_closes']==1426 and recovery.target()['prior_stops']['reviewer']['exit_code']==1

@pytest.mark.parametrize('mode',['preflight','review'])
def test_qualified_recovery_owns_dispatch_and_restores_on_abort(monkeypatch,tmp_path,mode):
    (tmp_path/'system-campaign-factual-request.json').write_bytes(CAPTURE.read_bytes());monkeypatch.setattr(dispatch,'HERE',tmp_path)
    monkeypatch.setattr(full_system_core,'hosted',lambda:None);calls=[]
    module=SimpleNamespace(factual_overlay_needed=lambda spec:False)
    @contextmanager
    def scope(request,**kwargs):
        calls.append(kwargs)
        try:yield
        finally:calls.append('RESTORED')
    monkeypatch.setattr(recovery,'context',scope)
    with pytest.raises(RuntimeError,match='EXPLICIT_METADATA_ABORT'):
        with dispatch.entry(module,recovery.target(),mode=mode,out=Path('/out'),evidence=Path('/evidence')):
            assert len(calls)==1 and calls[0]['mode']==mode and calls[0]['module'] is module
            raise RuntimeError('EXPLICIT_METADATA_ABORT')
    assert calls[-1]=='RESTORED'

def test_original_recovery_context_refuses_economic_before_hooks(monkeypatch):
    monkeypatch.setattr(full_system_core,'hosted',lambda:None)
    with pytest.raises(ValueError,match='ECONOMIC_MODE_FORBIDDEN'):
        with recovery.context(historical_request(),spec=recovery.target(),mode='economic'):pytest.fail('entered economic')
