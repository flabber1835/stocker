"""Synthetic, noncanonical observation DTOs; actual books are never staged."""
import ast,json,sys
from copy import deepcopy
from pathlib import Path
import pytest

class Fence:
    def find_spec(self,fullname,path=None,target=None):
        if fullname.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):
            raise ImportError('RETAINED_CASH_V2_DATA_ONLY:'+fullname)
sys.meta_path.insert(0,Fence());sys.path.insert(0,str(Path(__file__).parent))
import system_campaign_retained_cash_v2 as data

def term(sid='SYNTHETIC_MSP',day='2099-06-23'):
    return dict(security_id=sid,ticker=sid,added=dict(security_id=sid,session=day,kind='CASH_MERGER'))

def test_union_keeps_full_metadata_and_repeated_identical_resources():
    a,b=term(),term('SYNTHETIC_SRRA','2099-07-01')
    assert data.union_terms([a],[deepcopy(a),b])==[a,b]
    result=data.union_terms([a]);result[0]['ticker']='CHANGED';assert a['ticker']=='SYNTHETIC_MSP'

@pytest.mark.parametrize('field',['ticker','added'])
def test_conflicting_full_terms_refuse(field):
    a=term();b=deepcopy(a)
    if field=='ticker':b[field]='WRONG'
    else:b['added']['cash_per_share']=999.
    with pytest.raises(ValueError,match='NO_CONFLICTING_FULL_TERM'):data.union_terms([a],[b])

def context_fixture(monkeypatch,out,*,stage_terms=None):
    import full_system_core
    import system_campaign_financial_future as future
    monkeypatch.setattr(full_system_core,'hosted',lambda:None)
    monkeypatch.setattr(data,'observer_initializer',lambda constructor,cp,arm:constructor)
    plan=dict(arm='P05')
    class Original:
        def __init__(self,target,arm,*,cp=None):self.terms={};self.scopes=[];self.original_cp=cp
        def advance(self,*a):pass
        def terminal(self,*a):pass
    monkeypatch.setattr(data.original,'selected',lambda cp,spec:[plan])
    monkeypatch.setattr(data.original,'observer_class',lambda p:Original)
    monkeypatch.setattr(data,'stage',lambda *a:stage_terms or [term()])
    monkeypatch.setattr(future,'ActualEvents',Original)
    return future,Original

@pytest.mark.parametrize('abort',[False,True])
def test_one_original_observer_methods_and_exact_restoration(monkeypatch,tmp_path,abort):
    future,Original=context_fixture(monkeypatch,tmp_path)
    try:
        with data.context('synthetic-root',{},tmp_path,{}):
            active=future.ActualEvents(tmp_path,'P05',cp={'synthetic':True})
            assert active.advance.__func__ is Original.advance and active.terminal.__func__ is Original.terminal
            assert active.terms=={('2099-06-23','SYNTHETIC_MSP'):term()['added']}
            assert active.original_cp=={'synthetic':True}
            if abort:raise RuntimeError('SYNTHETIC_ABORT')
    except RuntimeError:
        assert abort
    assert future.ActualEvents is Original

@pytest.mark.parametrize('change',['arm','target','wrapped'])
def test_wrong_observer_output_or_nested_wrapper_refuses(monkeypatch,tmp_path,change):
    future,Original=context_fixture(monkeypatch,tmp_path)
    if change=='wrapped':monkeypatch.setattr(future,'ActualEvents',type('Wrong',(Original,),{}))
    with pytest.raises(ValueError):
        with data.context('synthetic-root',{},tmp_path,{}):
            future.ActualEvents(tmp_path/'wrong' if change=='target' else tmp_path,'P06' if change=='arm' else 'P05')
    assert future.ActualEvents is Original or change=='wrapped'

def test_no_selected_observer_changes_nothing(monkeypatch):
    monkeypatch.setattr(data.original,'selected',lambda cp,spec:[])
    with data.context('unused',{},'unused',{}):pass

def test_stage_is_hosted_only_before_any_metadata_write(monkeypatch):
    import full_system_core
    def refuse():raise ValueError('SYNTHETIC_NOT_HOSTED')
    monkeypatch.setattr(full_system_core,'hosted',refuse)
    with pytest.raises(ValueError,match='NOT_HOSTED'):data.stage('unused',{},'unused',{})

def test_stage_keeps_original_resources_and_adds_exact_tail_metadata(monkeypatch,tmp_path):
    import full_system_core
    monkeypatch.setattr(full_system_core,'hosted',lambda:None)
    calls=[];monkeypatch.setattr(data.original,'stage',lambda *args:calls.append(args) or [term('ORIGINAL')])
    raw=b'{"synthetic_metadata":true}\n'
    monkeypatch.setattr(data,'full_inventory',lambda *a:dict(resources={'tail/overlay.json':raw},terms=[term()]))
    cp={'synthetic':True};plan={'synthetic':True}
    result=data.stage('synthetic-root',cp,tmp_path,plan)
    assert calls==[('synthetic-root',cp,tmp_path,plan)] and result==[term('ORIGINAL'),term()]
    assert (tmp_path/'tail/overlay.json').read_bytes()==raw
    assert not (tmp_path/'book').exists()

def test_review_passes_all_terms_and_all_logs_to_original_accounting_reviewer(monkeypatch,tmp_path):
    import system_campaign_uncertainty_review as review
    monkeypatch.setattr(data.original,'selected',lambda *a:[{'synthetic':True}])
    monkeypatch.setattr(data.original,'checked_resources',lambda *a:({},None,[term('ORIGINAL')]))
    monkeypatch.setattr(data,'full_inventory',lambda *a:dict(terms=[term()],full_input_count=15,entries=[{}]))
    raw=json.dumps({'synthetic_cash_record':True}).encode()
    monkeypatch.setattr(data.original,'committed_logs',lambda *a:{'2099-06-23':raw})
    monkeypatch.setattr(review,'committed_rows',lambda *a:[{'synthetic_accounting':True}])
    calls=[]
    monkeypatch.setattr(data.original,'verify_records',lambda *a:calls.append(a) or ['SYNTHETIC_CHECK'])
    cp=dict(source_cursor='2099-06-30',run=dict(state=dict(ledger=dict(events=['SYNTHETIC_EVENT']))))
    data.review('synthetic-evidence',tmp_path,{},cp)
    assert calls==[([{'synthetic_accounting':True}],['SYNTHETIC_EVENT'],{'2099-06-23':{'synthetic_cash_record':True}},
                    [term('ORIGINAL'),term()],'2099-06-30')]
    result=json.loads((tmp_path/'retained-forward-cash-review.json').read_bytes())
    assert result['retained_terms']==2 and result['full_tail_materials']==1 and result['all_committed_logs_required'] is True

def test_removing_conflict_guard_accepts_wrong_material_and_is_detected():
    tree=ast.parse(Path(data.__file__).read_bytes())
    fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='union_terms')
    class Remove(ast.NodeTransformer):
        hits=0
        def visit_Expr(self,n):
            if isinstance(n.value,ast.Call) and any(isinstance(x,ast.Constant) and x.value=='RETAINED_CASH_V2_NO_CONFLICTING_FULL_TERM' for x in n.value.args):
                self.hits+=1;return None
            return self.generic_visit(n)
    remove=Remove();fn=ast.fix_missing_locations(remove.visit(fn));assert remove.hits==1
    scope=dict(vars(data));exec(compile(ast.Module(body=[fn],type_ignores=[]),'<removed-guard-synthetic-only>','exec'),scope)
    a=term();b=deepcopy(a);b['ticker']='WRONG'
    with pytest.raises(ValueError):data.union_terms([a],[b])
    assert scope['union_terms']([a],[b])==[b]

@pytest.mark.parametrize('name',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_financial_import_fence(name):
    with pytest.raises(ImportError):Fence().find_spec(name)
