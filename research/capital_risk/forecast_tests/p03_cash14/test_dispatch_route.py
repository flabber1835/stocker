from contextlib import contextmanager
from types import SimpleNamespace
import pytest
import full_system_core
import system_campaign_financial_resume as resume
import system_campaign_bounded_lifecycle_dispatch as dispatch
import system_campaign_p03_cash14_runtime as cash14
import system_campaign_p03_thor_qualification_reuse as reuse
import system_campaign_bounded_sensor_runtime_v2 as dova

@pytest.mark.parametrize('mode',['preflight','economic','review'])
def test_new_profile_precedes_old_retained_refusal(monkeypatch,mode):
    monkeypatch.setattr(full_system_core,'hosted',lambda:None);calls=[]
    @contextmanager
    def outer(*a,**k):yield
    @contextmanager
    def selected(*a,**k):
        calls.append('new14')
        try:yield
        finally:calls.append('restored')
    monkeypatch.setattr(dova,'entry_context',outer)
    monkeypatch.setattr(cash14,'entry_context',selected)
    monkeypatch.setattr(reuse,'entry_context',lambda *a:pytest.fail('entered prior49 seed context'))
    module=SimpleNamespace(factual_overlay_needed=lambda target:False)
    with pytest.raises(RuntimeError,match='EXPLICIT_METADATA_ABORT'):
        with dispatch.entry(module,resume.root_spec('P03'),mode=mode):
            assert calls==['new14'];raise RuntimeError('EXPLICIT_METADATA_ABORT')
    assert calls==['new14','restored']
