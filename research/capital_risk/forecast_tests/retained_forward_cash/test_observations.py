"""Read-only actual evidence and synthetic observation DTO falsifiers."""
import ast,gzip,importlib,json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import sys
import pytest

class Fence:
    def find_spec(self,fullname,path=None,target=None):
        if fullname.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):
            raise ImportError('RETAINED_CASH_DATA_ONLY:'+fullname)
sys.meta_path.insert(0,Fence());sys.path.insert(0,str(Path(__file__).parent))
import system_campaign_retained_forward_cash as data
import system_campaign_financial_future as future

ROOT=None

@pytest.fixture(scope='module')
def actual(tmp_path_factory):
    # Deliberately incomplete, noncanonical metadata DTOs. No financial state,
    # canonical serializer, restore, packet or economic runtime is involved.
    global ROOT
    ROOT=tmp_path_factory.mktemp('synthetic-observation-documents')
    plan=deepcopy(data.plans()[0]);origin=dict(sha256='a'*64,base=dict(synthetic_observation_only=True),
        repairs=[dict(synthetic_input=i) for i in range(13)],source_cursor='2022-03-31')
    terms=[];logs={};rows=[dict(session='2022-04-01',evidence=dict(research_entry_audit=dict(closing_accounting=dict(wealth_core=dict(episodes={})))))]
    days=['2022-04-07','2022-05-25','2022-05-13','2022-05-19']
    for i in range(26):
        day=days[i] if i<4 else '2023-07-'+str(i-3).zfill(2)
        sid=str(1000+i);ticker=['HMHC','ANAT','XENT','MIME'][i] if i<4 else 'SYNTHETIC_'+sid
        added=dict(session=day,security_id=sid,kind='CASH_MERGER',cash_per_share=1.,reference='synthetic:only')
        terms.append(dict(ticker=ticker,security_id=sid,added=added))
        if i<4:
            logs[day]=dict(passed=True,financial_source_changed=False,session=day,source=[],stock=[],risk=[],engine_calls=0,
                cash=[dict(session=day,security_id=sid,actual_context_call=True,source_only_noop=False,
                    postcondition=dict(actual_held=False,quantity=0,nominal_cash=0.))],order=['CASH:'+sid])
            accounting=dict(wealth_core=dict(episodes={}),pending=[])
            rows.append(dict(session=day,evidence=dict(research_entry_audit=dict(opening_accounting=accounting,closing_accounting=accounting))))
    rows.sort(key=lambda r:r['session'])
    doc=dict(schema='synthetic-observation-document/1',add=[t['added'] for t in terms]);overlay=data.encoded(doc)
    desc=dict(plan['descriptor'],sha256=data.sha(overlay),filename=data.sha(overlay)+'.json')
    cp=dict(sha256='b'*64,base=deepcopy(origin['base']),repairs=origin['repairs']+[desc],source_cursor='2022-05-31',
        run=dict(state=dict(ledger=dict(events=[]))))
    origin_raw=gzip.compress(data.encoded(origin),mtime=0)
    material=data.encoded(dict(arm='P05',parent_outer_sha256=origin['sha256'],terms=terms))
    plan.update(descriptor=desc,material_file=future.hydration_name(origin),material_sha256=data.sha(material),
        origin_outer_sha256=origin['sha256'],parent_gzip=dict(bytes=len(origin_raw),sha256=data.sha(origin_raw)))
    paths={plan['ordinary_overlay']:overlay,plan['material_file']:material,
        'book/predecessor-checkpoints/'+origin['sha256']+'.json.gz':origin_raw,'book/repairs/'+desc['filename']:overlay}
    for day,value in logs.items():paths['actual-future-event-'+day+'.json']=data.encoded(value)
    for name,raw in paths.items():
        p=ROOT/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
    resources,read_origin,read_terms=data.checked_resources(ROOT,cp,plan)
    assert read_origin==origin and read_terms==terms
    return cp,plan,resources,origin,terms,rows,logs

def test_synthetic_full26_resources_original_methods_and_four_committed_events(actual):
    cp,plan,resources,origin,terms,rows,logs=actual
    assert len(terms)==26 and len(resources)==3 and len(cp['repairs'])==14
    Original=data.observer_class(plan);event=Original(ROOT,'P05',cp=origin)
    assert event.scopes==[] and len(event.terms)==26
    assert event.advance.__func__ is future.ActualEvents.advance and event.terminal.__func__ is future.ActualEvents.terminal
    result=data.verify_records(rows,cp['run']['state']['ledger']['events'],logs,terms,cp['source_cursor'])
    assert [r['ticker'] for r in result]==['HMHC','ANAT','XENT','MIME']
    assert sum(t['added']['session']>cp['source_cursor'] for t in terms)==22

@pytest.mark.parametrize('change',['prefix','base','cursor','input_hash','material_hash','observer_hash'])
def test_actual_resource_and_whole_source_mutations_refuse(actual,change):
    cp,plan,*_=actual;cp=deepcopy(cp);plan=deepcopy(plan)
    if change=='prefix':cp['repairs'][0]['sha256']='0'*64
    elif change=='base':cp['base']['synthetic_observation_only']=False
    elif change=='cursor':cp['source_cursor']='2022-01-31'
    elif change=='input_hash':plan['descriptor']['sha256']='0'*64
    elif change=='material_hash':plan['material_sha256']='0'*64
    else:plan['original_observer_ast']['ActualEvents']='0'*64
    with pytest.raises(ValueError):
        data.checked_resources(ROOT,cp,plan);data.observer_class(plan)

def removed(name,label):
    fn=next(n for n in ast.parse(Path(data.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name==name)
    class Remove(ast.NodeTransformer):
        hits=0
        def visit_Expr(self,node):
            if isinstance(node.value,ast.Call) and any(isinstance(v,ast.Constant) and v.value==label for v in node.value.args):
                self.hits+=1;return None
            return self.generic_visit(node)
    adapter=Remove();fn=ast.fix_missing_locations(adapter.visit(fn));assert adapter.hits==1
    scope=dict(vars(data));exec(compile(ast.Module(body=[fn],type_ignores=[]),'<removed-observation-guard-DATA-only>','exec'),scope)
    return scope[name]

def test_removing_resource_guard_really_accepts_wrong_material_commitment(actual):
    cp,plan,*_=actual;plan=deepcopy(plan);plan['material_sha256']='0'*64
    with pytest.raises(ValueError):data.checked_resources(ROOT,cp,plan)
    result=removed('checked_resources','RETAINED_CASH_EXACT_ADOPTED_SOURCE_RESOURCES')(ROOT,cp,plan)
    assert len(result[2])==26

def test_removing_whole_observer_source_guard_really_accepts_wrong_AST(actual):
    _,plan,*_=actual;plan=deepcopy(plan);plan['original_observer_ast']['ActualEvents']='0'*64
    with pytest.raises(ValueError):data.observer_class(plan)
    assert removed('observer_class','RETAINED_CASH_WHOLE_ORIGINAL_OBSERVER_AND_HELPERS')(plan) is future.ActualEvents

def fixture_two_cash():
    day='2022-10-19';terms=[];cash=[];episodes={};events=[]
    for index,(sid,price,quantity) in enumerate([('101',.1,59),('102',31.25,17)]):
        term=dict(ticker='SYNTHETIC_'+sid,security_id=sid,added=dict(session=day,security_id=sid,kind='CASH_MERGER',cash_per_share=price,reference='synthetic:cash'))
        terms.append(term);amount=quantity*price
        episodes[str(index)]=dict(security_id=sid,current_shares=quantity)
        cash.append(dict(session=day,security_id=sid,actual_context_call=True,source_only_noop=False,
            postcondition=dict(actual_held=True,quantity=quantity,nominal_cash=amount)))
        events.append(dict(session=day,security_id=sid,event_type='CASH_MERGER',cash_delta=amount,shares_delta=-quantity,
            price=price,fees=0.,detail=dict(reference='synthetic:cash')))
    before=dict(wealth_core=dict(episodes=episodes));opened=dict(wealth_core=dict(episodes={}),pending=[])
    rows=[dict(session='2022-10-18',evidence=dict(research_entry_audit=dict(closing_accounting=before))),
          dict(session=day,evidence=dict(research_entry_audit=dict(opening_accounting=opened)))]
    record=dict(passed=True,financial_source_changed=False,session=day,source=[],stock=[],risk=[],engine_calls=0,
        cash=cash,order=['CASH:101','CASH:102'])
    return rows,events,{day:record},terms,day

def test_two_actions_on_one_day_preserve_both_and_original_float_operation_order():
    args=fixture_two_cash();result=data.verify_records(*args)
    assert len(result)==2 and [r['quantity'] for r in result]==[59,17]
    assert result[0]['nominal_cash']==str(59*.1)

@pytest.mark.parametrize('change',['missing','extra','duplicate','foreign_sid','false_call','missing_cash','ledger_price','ledger_amount','held_quantity','stock','engine','order'])
def test_synthetic_same_day_mutations_refuse(change):
    rows,events,observed,terms,day=fixture_two_cash();r=observed[day]
    if change=='missing':observed={}
    elif change=='extra':observed['2022-10-18']=deepcopy(r)
    elif change=='duplicate':r['cash'][1]=deepcopy(r['cash'][0])
    elif change=='foreign_sid':r['cash'][0]['security_id']='103'
    elif change=='false_call':r['cash'][0]['actual_context_call']=False
    elif change=='missing_cash':r['cash'].pop()
    elif change=='ledger_price':events[0]['price']=.2
    elif change=='ledger_amount':events[0]['cash_delta']+=1.
    elif change=='held_quantity':rows[0]['evidence']['research_entry_audit']['closing_accounting']['wealth_core']['episodes']['0']['current_shares']+=1
    elif change=='stock':r['stock']=[dict(applied=True)]
    elif change=='engine':r['engine_calls']=1
    else:r['order']=['CASH:101','CASH:101']
    with pytest.raises(ValueError):data.verify_records(rows,events,observed,terms,day)

@pytest.mark.parametrize('label,change',[('RETAINED_CASH_COMPLETE_COMMITTED_EVENT_AXIS','extra'),('RETAINED_CASH_EXACT_WHOLE_DAILY_CALL_SET','order')])
def test_removed_review_guards_really_accept_foreign_or_duplicate_daily_evidence(label,change):
    rows,events,observed,terms,day=fixture_two_cash()
    if change=='extra':observed['2022-10-18']=deepcopy(observed[day])
    else:observed[day]['order']=['CASH:101','CASH:101']
    with pytest.raises(ValueError):data.verify_records(rows,events,observed,terms,day)
    assert len(removed('verify_records',label)(rows,events,observed,terms,day))==2

def test_actual_missing_committed_log_refuses(actual):
    cp,_,_,_,terms,rows,observed=actual;observed=deepcopy(observed);observed.pop('2022-05-25')
    with pytest.raises(ValueError,match='COMPLETE_COMMITTED_EVENT_AXIS'):
        data.verify_records(rows,cp['run']['state']['ledger']['events'],observed,terms,cp['source_cursor'])

def test_constructor_union_has_no_runtime_method_wrapper_and_exact_restoration(actual,tmp_path,monkeypatch):
    _,plan,_,_,terms,*_=actual
    # Only synthetic constructor DTOs run; no actual checkpoint/resource copying.
    import full_system_core
    monkeypatch.setattr(full_system_core,'hosted',lambda:None)
    class Synthetic:
        def __init__(self,out,arm,*,cp=None):self.terms={};self.scopes=[]
        def advance(self,*args):return 'one_advance'
        def terminal(self,*args):return 'one_terminal'
    monkeypatch.setattr(future,'ActualEvents',Synthetic)
    monkeypatch.setattr(data,'observer_class',lambda p:Synthetic)
    monkeypatch.setattr(data,'stage',lambda *args:terms)
    monkeypatch.setattr(data,'selected',lambda *args:[plan])
    with pytest.raises(RuntimeError,match='SYNTHETIC_EXIT'):
        with data.context(tmp_path,{},tmp_path,dict(arm='P05')):
            event=future.ActualEvents(tmp_path,'P05',cp={})
            assert len(event.terms)==26 and event.advance.__func__ is Synthetic.advance
            assert event.terminal.__func__ is Synthetic.terminal
            raise RuntimeError('SYNTHETIC_EXIT')
    assert future.ActualEvents is Synthetic

def test_existing_term_conflict_and_source_only_scope_refuse(actual):
    terms=actual[4];first=terms[0]['added'];key=first['session'],first['security_id']
    with pytest.raises(ValueError):data.merge_terms(SimpleNamespace(terms={key:dict(first,cash_per_share=999.)},scopes=[]),terms)
    with pytest.raises(ValueError):data.merge_terms(SimpleNamespace(terms={},scopes=[dict(source_only=True)]),terms)

@pytest.mark.parametrize('name',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_runtime_import_fence(name):
    with pytest.raises(ImportError):Fence().find_spec(name)
