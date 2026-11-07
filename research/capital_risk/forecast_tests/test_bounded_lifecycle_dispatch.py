"""Whole legacy mode wrappers and exact selected metadata, without replay."""
import ast,sys
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import pytest
import system_campaign_bounded_lifecycle_dispatch as data
import system_campaign_financial_resume as resume
from system_campaign_financial_partial import root_spec

def test_financial_request_is_three_distinct_qualified_input_histories(monkeypatch):
    # This regression is the original three-arm initial-generation request.
    import system_campaign_financial_partial as partial
    original=partial.root_spec
    def historical(arm,admission_sha256=None):
        if arm=='P03' and admission_sha256 is None:admission_sha256='2dfc5b30f486d40f97ab4f93c21ae75862714f0d0b410bd56228b137370329d0'
        if arm=='P06' and admission_sha256 is None:admission_sha256='947662b7b86089285e5d7360221ff3a6d931173bccbce6ac8884341d396c763e'
        if arm=='P07' and admission_sha256 is None:admission_sha256='475af771e38bc5bb9600bdf0031fbb1036304a5e36348dc82cf8fbac4497098d'
        return original(arm,admission_sha256) if admission_sha256 is not None else original(arm)
    monkeypatch.setattr(partial,'root_spec',historical);monkeypatch.setattr(resume,'root_spec',historical)
    monkeypatch.setattr(resume,'EXECUTION_MODE','OWN_ADMITTED_FINANCIAL_CONTINUATION')
    monkeypatch.setattr(resume,'SELECTED_ARMS',('P03','P06','P07'))
    value=resume.expected_request()
    assert value['maximum_parallel_financial_workers']==3
    assert set(value['selected_bounded_models'])=={'P03'}
    assert set(value['selected_abmd_bounded_inputs'])=={'P06','P07'}
    assert value['selected_abmd_bounded_inputs']['P06']['prior_seed_rows']==0
    assert value['selected_abmd_bounded_inputs']['P07']['old_models_and_784_source_proofs_preserved']
    assert len(value['sources'])==653 and len(data.source_names())==len(set(data.source_names()))

@pytest.mark.parametrize('change',['root','outer','count','cursor','input'])
def test_p06_declaration_has_no_unregistered_or_truncated_source(change):
    value=deepcopy(root_spec('P06','947662b7b86089285e5d7360221ff3a6d931173bccbce6ac8884341d396c763e'))
    if change=='root':value['root_admission_sha256']='0'*64
    elif change=='outer':value['outer_sha256']='0'*64
    elif change=='count':value['measured_closes']+=1
    elif change=='cursor':value['selected_session']='2022-12-01'
    else:value['repairs'].pop()
    with pytest.raises(ValueError):data.p06_declaration(value)

def test_source_pin_replacement_falsifier_detects_removed_new_guard(monkeypatch):
    # Exercise the closure guard without invoking another arm's legacy admission route.
    monkeypatch.setattr(resume,'EXECUTION_MODE','OWN_ADMITTED_FINANCIAL_CONTINUATION')
    monkeypatch.setattr(resume,'SELECTED_ARMS',('P03',))
    import system_campaign_bounded_sensor_runtime_v2 as dova
    def original():
        result=resume.legacy_expected_request()
        result['sources'][Path(data.__file__).name]='0'*64
        return result
    kwargs=dict(execution_mode=resume.EXECUTION_MODE,selected_arms=resume.SELECTED_ARMS)
    with pytest.raises(ValueError,match='NO_SOURCE_PIN_REPLACEMENT'):data.expected_request(original,**kwargs)
    tree=ast.parse(Path(data.__file__).read_bytes());fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='expected_request')
    class Remove(ast.NodeTransformer):
        hits=0
        def visit_Expr(self,node):
            if 'BOUNDED_DISPATCH_NO_SOURCE_PIN_REPLACEMENT' in ast.unparse(node):self.hits+=1;return None
            return self.generic_visit(node)
    removal=Remove();fn=ast.fix_missing_locations(removal.visit(fn));assert removal.hits==1
    namespace=dict(vars(data));exec(compile(ast.Module(body=[fn],type_ignores=[]),'<removed-closure-pin-guard>','exec'),namespace)
    value=namespace['expected_request'](original,**kwargs)
    assert value['sources'][Path(data.__file__).name]!='0'*64

@pytest.mark.parametrize('arm',['P03','P06','P07'])
@pytest.mark.parametrize('mode',['preflight','economic','review'])
def test_outer_entry_spans_call_and_restores_hooks_on_error(monkeypatch,tmp_path,arm,mode):
    import full_system_core
    import system_campaign_bounded_sensor_runtime_v2 as dova
    import system_campaign_p06_abmd_lifecycle as p06
    import system_campaign_p07_abmd_lifecycle as p07
    monkeypatch.setattr(full_system_core,'hosted',lambda:None)
    # Preserve the original financial-generation regression independently of
    # the active readonly repair request.
    captured=Path('C:/Users/mbron/.codex/visualizations/2026/11/05/01a1ac36-4c96-7aa1-82ca-4efb70a86ea8/financial324-source-snapshot/system-campaign-factual-request.json')
    (tmp_path/'system-campaign-factual-request.json').write_bytes(captured.read_bytes())
    monkeypatch.setattr(data,'HERE',tmp_path)
    calls=[]
    @contextmanager
    def scope(*a,**k):
        calls.append(('enter',a,k))
        try:yield
        finally:calls.append(('exit',a,k))
    monkeypatch.setattr(dova,'entry_context',scope);monkeypatch.setattr(p06,'entry_context',scope);monkeypatch.setattr(p07,'entry',scope)
    monkeypatch.setattr(p07,'selected',lambda spec:spec.get('arm')=='P07')
    old=lambda spec:False;module=SimpleNamespace(factual_overlay_needed=old);spec=root_spec(arm,dova.INITIAL) if arm=='P03' else root_spec(arm,'947662b7b86089285e5d7360221ff3a6d931173bccbce6ac8884341d396c763e') if arm=='P06' else root_spec(arm,'475af771e38bc5bb9600bdf0031fbb1036304a5e36348dc82cf8fbac4497098d')
    with pytest.raises(RuntimeError,match='SYNTHETIC_ABORT'):
        with data.entry(module,spec,mode=mode,evidence='DATA_EVIDENCE',out='DATA_OUT'):
            assert module.factual_overlay_needed(spec) and calls[0][0]=='enter'
            if arm=='P06':assert calls[0][2]['evidence_root']==('DATA_EVIDENCE' if mode=='review' else None)
            raise RuntimeError('SYNTHETIC_ABORT')
    assert [v[0] for v in calls]==['enter','exit'] and module.factual_overlay_needed is old

def test_entry_refuses_before_local_financial_import(monkeypatch):
    import full_system_core
    def refuse():raise ValueError('NOT_HOSTED')
    monkeypatch.setattr(full_system_core,'hosted',refuse)
    with pytest.raises(ValueError,match='NOT_HOSTED'):
        with data.entry(None,None,mode='economic'):pass
