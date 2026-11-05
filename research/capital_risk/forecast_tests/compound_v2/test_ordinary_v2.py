"""Pure DATA tests of original nonempty ordinary activation and observer binding."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import pytest

ROOT=Path(__file__).parent/'fixtures';sys.path.insert(0,str(Path(__file__).parent))
import test_distribution_v2 as t
import system_campaign_financial_compound_ordinary_v2 as o
import system_campaign_cash_calendar as calendar
import system_campaign_ordinary_registry as registry
m=t.m
observer=o.original_observer()

@pytest.fixture(autouse=True)
def original_registry_fixture_path(monkeypatch):
    original=registry.registrations
    monkeypatch.setattr(registry,'registrations',lambda:original(ROOT))

def record():return t.data('P07-closed-source-input-v2-PROPOSAL.json')['records'][0]
def material():
    r=record();_,full,subset=o.select_original(r);a=t.data('VCRA-unadopted-original-input-evidence.json')
    return dict(schema=o.SCHEMA,arm='P07',record_sha256=m.digest(r),ordinary_activation=r['ordinary_activation'],
        selected_catalog=subset,full_catalog_sha256=m.sha(m.encoded(full)),
        original_private_payload=dict(schema='research.factual-cash-calendar-private-payload/1',catalog=subset,
            source_witnesses=[a['source_observation']],actual_alias_rows=0,source_metadata_unchanged=True,annual_scans=1),
        original_parent=dict(sha256=r['parent_outer_sha256'],source_cursor=r['parent_cursor'],base={'immutable':'original383'},
            run=dict(checkpoint_sha256=r['parent_inner_sha256'],input_sha256=r['parent_input_sha256']),
            repairs=[v['descriptor'] for v in a['all_original_repair_descriptors']]),
        inherited_input_proof={'synthetic_input_metadata_only':True},original_collision_preflight={'synthetic_input_metadata_only':True},
        terms=deepcopy(subset['terms']),original_observer_sha256=o.OBSERVER_SHA,financial_sessions_advanced=0,
        financial_authority=False,source_metadata_unchanged=True)

def test_genuine_original_subset_is_nonempty_and_full_bytes_stay_pinned():
    codec,full,selected=o.select_original(record());a=t.data('VCRA-unadopted-original-input-evidence.json')
    assert len(full['terms'])==3 and len(selected['terms'])==1 and selected['terms'][0]==a['term']
    assert codec.patch()['add']==[a['term']['added']] and a['term']['added']['cash_per_share']==79.25
    assert m.sha(m.encoded(full))==record()['ordinary_activation']['catalog_sha256']

@pytest.mark.parametrize('change',['catalog_sha','validator_sha','empty','unknown','duplicate'])
def test_original_selection_cannot_become_dummy_or_unpinned(change):
    r=record();p=r['ordinary_activation']
    if change=='catalog_sha':p['catalog_sha256']='0'*64
    elif change=='validator_sha':p['validator_sha256']='0'*64
    elif change=='empty':p['selected_tickers']=[]
    elif change=='unknown':p['selected_tickers']=['UNKNOWN']
    else:p['selected_tickers']=['VCRA','VCRA']
    with pytest.raises(ValueError):o.select_original(r)

def test_original_ordinary_document_keeps_actual_term_and_source_evidence():
    v=material();doc=o.ordinary_document(v);a=t.data('VCRA-unadopted-original-input-evidence.json')
    assert doc['add']==[a['term']['added']] and doc['suppress']==[dict(session='2022-02-22',security_id='576374012507208201',term_sha256='96d66e520046facaa9871daea03f370b8714e39c410e508854b7abaf72cdb649')]
    assert doc['predecessor_checkpoint_sha256']==record()['parent_inner_sha256']
    assert len({e['reference'] for e in doc['source_evidence']})==len(doc['source_evidence'])
    assert any(e['sha256']==record()['ordinary_activation']['catalog_sha256'] for e in doc['source_evidence'])
    assert any(e['sha256']==o.OBSERVER_SHA for e in doc['source_evidence'])
    assert doc['add'] and doc['suppress']

def test_original_parent_metadata_and_later_retention_prefix_are_exact():
    origin=material()['original_parent'];r=record();o.require_parent(origin,r,origin)
    later=deepcopy(origin);later['source_cursor']='2021-07-30';later['sha256']='a'*64;later['repairs'].append({'new':'input'})
    assert o.require_parent(later,r,origin) is None

@pytest.mark.parametrize('change',['base','outer','cursor','prefix','inner'])
def test_parent_metadata_and_original_input_prefix_substitutions_refuse(change):
    origin=material()['original_parent'];cp=deepcopy(origin);r=record()
    if change=='base':cp['base']={}
    elif change=='outer':cp['sha256']='a'*64
    elif change=='cursor':cp['source_cursor']='2021-04-29'
    elif change=='prefix':cp['repairs'][0]['sha256']='a'*64
    else:origin['run']['checkpoint_sha256']='a'*64
    with pytest.raises(ValueError):o.require_parent(cp,r,origin)

def inherited(root,*,adopted=False,branch_count=1):
    root.mkdir();(root/'book/repairs').mkdir(parents=True)
    rows=[dict(schema='terminal-repair/1',add=[],suppress=[])]
    if adopted:rows[0]['add']=[dict(security_id='576374012507208201',session='2022-02-23')]
    rows += [dict(schema='research.leadership-uncertainty-input/1',independent_branch=i) for i in range(branch_count)]
    descriptors=[]
    for v in rows:
        raw=m.encoded(v);h=m.sha(raw);(root/'book/repairs'/(h+'.json')).write_bytes(raw)
        descriptors.append(dict(filename=h+'.json',sha256=h,resume_session='2017-06-30',predecessor_checkpoint_sha256='f'*64))
    return dict(repairs=descriptors),descriptors[-1]['sha256']

def test_every_inherited_row_is_checked_before_original_branch_skip(tmp_path):
    root=tmp_path/'old';cp,b=inherited(root);called=[]
    def validate(p,c):called.append((p,c));return b
    proof=o.inherited_proof(cp,root,material()['selected_catalog'],branch_validator=validate)
    assert proof['ordinary_targets_unadopted'] is proof['original_branch_validated'] is True
    assert len(proof['retained_inputs'])==2 and called==[(root,cp)]

@pytest.mark.parametrize('change',['adopted','branch_count','branch_validation','raw','filename'])
def test_inherited_ordinary_input_collision_and_branch_binding_refuse(change,tmp_path):
    root=tmp_path/'old';cp,b=inherited(root,adopted=change=='adopted',branch_count=2 if change=='branch_count' else 1)
    if change=='raw':(root/'book/repairs'/cp['repairs'][0]['filename']).write_bytes(b'changed')
    if change=='filename':cp['repairs'][0]['filename']='different.json'
    with pytest.raises((ValueError,FileNotFoundError)):
        o.inherited_proof(cp,root,material()['selected_catalog'],branch_validator=lambda p,c:'0'*64 if change=='branch_validation' else b)

def test_inherited_no_duplicate_guard_removal_falsifier(tmp_path):
    root=tmp_path/'old';cp,b=inherited(root,adopted=True);subset=material()['selected_catalog']
    with pytest.raises(ValueError):o.inherited_proof(cp,root,subset,branch_validator=lambda p,c:b)
    assert t.drop(o,'inherited_proof','COMPOUND_V2_GENUINE_ORDINARY_TARGET_NOT_PREVIOUSLY_ADOPTED')(cp,root,subset,branch_validator=lambda p,c:b)['ordinary_targets_unadopted'] is True

def test_original_cash_observer_constructor_and_every_method_remain_original(tmp_path):
    v=material();cp=v['original_parent'];doc=o.ordinary_document(v)
    (tmp_path/o.MATERIAL).write_bytes(m.encoded(v));(tmp_path/'ordinary.json').write_bytes(m.encoded(doc))
    cls=o.bound_observer_type(observer,v,cp,overlay_name='ordinary.json');obj=cls(tmp_path,'P07',cp=cp)
    assert obj.terms=={('2022-02-23','576374012507208201'):doc['add'][0]} and obj.scopes==[]
    for name in ('terminal','advance','__enter__','__exit__','source_values'):
        assert getattr(cls,name) is getattr(observer.ActualEvents,name)
    assert cls.__init__.__code__.co_filename=='<unchanged-original-ordinary-observer-constructor>'

def test_mandatory_cash_only_observer_constructor_binding_cannot_hide_source_only(tmp_path):
    v=material();cp=v['original_parent'];doc=o.ordinary_document(v);v['terms'][0]['recognition_rule']='RETAINED_CLOSING_SOURCE_NOT_PORTFOLIO_COMPLETION'
    (tmp_path/o.MATERIAL).write_bytes(m.encoded(v));(tmp_path/'ordinary.json').write_bytes(m.encoded(doc))
    cls=o.bound_observer_type(observer,v,cp,overlay_name='ordinary.json')
    with pytest.raises(ValueError):cls(tmp_path,'P07',cp=cp)

def test_hosted_only_ordinary_hydration_and_financial_observer_cannot_run_locally(tmp_path):
    for call in (lambda:o.ordinary_input({},record(),tmp_path),lambda:o.ordinary_events(tmp_path,{})):
        with pytest.raises(ValueError):call()
    assert not [n for n in sys.modules if n.startswith(('stock_strategy_shared','sentinel','research.pooled_','numpy','pandas'))]

def cash_fixture():
    terms=material()['terms'][0]['added'];sid=terms['security_id']
    before=dict(cash=100.,episodes={'7':dict(security_id=sid,current_shares=3)},slots={'7':dict(occupied_by=sid)})
    after=dict(cash=337.75,episodes={},slots={'7':dict(occupied_by=None)})
    lb=dict(events=[],receivables=[]);la=dict(receivables=[],events=[dict(event_type='CASH_MERGER',security_id=sid,
        price=79.25,shares_delta=-3,cash_delta=237.75,detail=dict(shares=3,reference=terms['reference']),
        fees=0.,cash_before=100.,cash_after=337.75)])
    return before,after,lb,la,terms,dict(applied=True)

def test_original_cash_postcondition_remains_exact_for_genuine_ordinary_fact():
    args=cash_fixture();assert observer.cash_postcondition(*args)==dict(actual_held=True,quantity=3,nominal_cash=237.75)
    before,_,lb,_,terms,_=args;before['episodes']={}
    assert observer.cash_postcondition(before,before,lb,lb,terms,dict(reason='NOT_HELD'))==dict(actual_held=False,quantity=0,nominal_cash=0.)

@pytest.mark.parametrize('change',['cash','fee','quantity','reference','receivable'])
def test_original_cash_observer_economic_falsifiers(change):
    before,after,lb,la,terms,result=args=cash_fixture()
    if change=='cash':after['cash']+=1
    elif change=='fee':la['events'][0]['fees']=1.
    elif change=='quantity':la['events'][0]['shares_delta']=-2
    elif change=='reference':la['events'][0]['detail']['reference']='OTHER'
    else:la['receivables']=[dict(new='unexpected')]
    with pytest.raises(ValueError):observer.cash_postcondition(*args)
