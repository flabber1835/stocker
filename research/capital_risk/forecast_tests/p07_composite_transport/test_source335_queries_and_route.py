"""Exact two source batches and transport-before-codec routing, metadata only."""
import ast,sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
import pytest
C=Path(__file__).resolve().parents[2];sys.path.insert(0,str(C))
import system_campaign_p03_forward_source_queries as original
import system_campaign_p07_forward_source_queries as query
import system_campaign_p07_fin326_requalified_parent as composite
from system_campaign_financial_partial import root_spec
def test_whole_original_P07_query_module_AST_undo_only_three_finite_literals():
    before=Path(original.__file__).read_text();after=Path(query.__file__).read_text()
    for old,new in [(query.CATALOG,original.CATALOG),(query.CATALOG_SHA,original.CATALOG_SHA),("arm:Literal['P07']","arm:Literal['P03']")]:
        assert after.count(old)==1;after=after.replace(old,new,1)
    assert ast.dump(ast.parse(before))==ast.dump(ast.parse(after))
def test_actual1259_full24_scope_retains84_VIVO_and103_SGFY_without_future_roles():
    record,=query.registry().queries;spec=root_spec('P07')
    assert record.root_admission_sha256==composite.ROOT_SHA and (record.parent_completed,record.parent_input_count)==(1259,24)
    assert len(record.scope.terms)==128 and record.scope.additional_rows==[]
    held={t.ticker:[p.model_dump() for p in t.parent_positions] for t in record.scope.terms if t.parent_positions}
    assert held=={'VIVO1':[dict(slot_id=1,ticker='VIVO1',quantity=84,entry_date='2022-07-11')],
        'SGFY':[dict(slot_id=5,ticker='SGFY',quantity=103,entry_date='2022-11-07')]}
    selected=query.selected_scopes({},['P07'],enabled=True,root_lookup=lambda _:spec)
    assert selected['P07']==record.scope.model_dump()
def test_two_distinct_source_declarations_and_zero_financial_workers():
    import system_campaign_financial_resume as resume
    request=resume.expected_request()
    assert request['arms']==['P06','P07'] and request['maximum_parallel_financial_workers']==0 and request['maximum_parallel_readonly_workers']==2
    assert set(request['selected_p06_admitted_source_bridges'])=={'P06'}
    assert set(request['selected_p07_composite_source_bridges'])=={'P07'}
    assert all(len(request['source_witness_scopes'][arm]['terms'])==128 for arm in request['arms'])
def test_outer_dispatch_enters_composite_transport_before_original_full24_codec_and_restores(monkeypatch):
    import full_system_core
    import system_campaign_bounded_lifecycle_dispatch as dispatch
    import system_campaign_p07_abmd_lifecycle as lifecycle
    monkeypatch.setattr(full_system_core,'hosted',lambda:None)
    calls=[]
    @contextmanager
    def transport(module,spec,**kwargs):
        calls.append('enter-transport')
        try:yield
        finally:calls.append('exit-transport')
    @contextmanager
    def model(spec):
        calls.append('enter-full24')
        try:yield
        finally:calls.append('exit-full24')
    monkeypatch.setattr(composite,'source_context',transport);monkeypatch.setattr(lifecycle,'entry',model)
    spec=root_spec('P07');original_overlay=lambda _:True;module=SimpleNamespace(factual_overlay_needed=original_overlay)
    with pytest.raises(RuntimeError,match='EXPLICIT_METADATA_ABORT'):
        with dispatch.entry(module,spec,mode='preflight'):
            assert calls==['enter-transport','enter-full24'] and module.factual_overlay_needed(spec) is False
            raise RuntimeError('EXPLICIT_METADATA_ABORT')
    assert calls==['enter-transport','enter-full24','exit-full24','exit-transport']
    assert module.factual_overlay_needed is original_overlay
