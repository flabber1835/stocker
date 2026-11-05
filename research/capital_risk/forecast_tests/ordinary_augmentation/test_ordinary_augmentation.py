"""DATA-only full-checkpoint, immutable-source and restart falsifiers."""
import ast
from copy import deepcopy
import importlib
import json
from pathlib import Path
import sys
import pytest


class Fence:
    def find_spec(self,fullname,path=None,target=None):
        if fullname.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):
            raise ImportError('AUGMENTATION_DATA_ONLY:'+fullname)


sys.meta_path.insert(0,Fence())
import system_campaign_ordinary_augmentation_data as data
import system_campaign_ordinary_augmentation_runtime as runtime


def input_hash(base,descriptors):return data.original.digest([base,descriptors])


def document(root,doc):
    raw = data.encoded(doc);pin = data.sha(raw)
    d = dict(filename=pin+'.json',sha256=pin,resume_session='2022-09-30',
             predecessor_checkpoint_sha256=doc['predecessor_checkpoint_sha256'])
    p = root/'book/repairs'/d['filename'];p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
    return d,raw


def sample(tmp_path,monkeypatch):
    """Synthetic DTOs only: these are never canonical book/checkpoint serializations."""
    descriptors = []
    for i in range(22):
        d,_ = document(tmp_path,dict(schema='terminal-repair/1',predecessor_checkpoint_sha256=str(i).zfill(64),
                                     source_evidence=[],add=[],suppress=[]))
        descriptors.append(d)
    plan = dict(parent_descriptors=descriptors,parent_outer_sha256='a'*64,parent_completed=1196,
                parent_cursor='2022-09-30',parent_root_admission_sha256='b'*64,literal_sources=[])
    expected = []
    for i,ticker in enumerate(('GBT','TRQ')):
        term = dict(native_session='2022-10-04',security_id=str(i),native_term_sha256='c'*64,
                    added=dict(session='2022-10-05',kind='CASH_MERGER',security_id=str(i),cash_per_share=68.5+i))
        name=ticker+'.json';(tmp_path/name).write_bytes(data.encoded(dict(terms=[term])))
        plan['literal_sources'].append(dict(catalog_file=name));expected.append(term)
    monkeypatch.setattr(data,'HERE',tmp_path)
    (tmp_path/data.CATALOG).write_bytes(data.encoded(plan))
    cp = dict(sha256='d'*64,completed=1196,source_cursor='2022-09-30',base=dict(synthetic_DTO=True),
              repairs=deepcopy(descriptors),run=dict(input_sha256=''))
    new,raw=document(tmp_path,dict(schema='terminal-repair/1',predecessor_checkpoint_sha256='e'*64,
        source_evidence=[],add=[t['added'] for t in expected],suppress=[dict(session=t['native_session'],
        security_id=t['security_id'],term_sha256=t['native_term_sha256']) for t in expected]))
    cp['repairs'].append(new);cp['run']['input_sha256']=input_hash(cp['base'],cp['repairs'])
    q=dict(passed=True,packet_checks=4,only_terminal_field_changed=True,
        complete_terms_and_canonical_notional_verified=True,original_incomplete_guard_retained=True,
        wrong_predecessor_and_consumed_date_refused=True,wrong_native_and_delivery_witness_refused=True,
        financial_sessions_advanced=0)
    files={data.OVERLAY:raw,data.DIRECTORY+'/future-financial-overlay.json':raw,
        data.DIRECTORY+'/parent-checkpoint.json.gz':b'SYNTHETIC DATA RESOURCE - NO CHECKPOINT',
        data.DIRECTORY+'/future-input-qualification.json':data.encoded(q),
        data.ADOPTION+'/checkpoint.json.gz':b'SYNTHETIC BOUNDARY RESOURCE',
        data.ADOPTION+'/proof.json':b'{}\n',data.ADOPTION+'-correlation-inputs.jsonl.gz':b'SYNTHETIC OBSERVATION RESOURCE'}
    for name,value in files.items():
        p=tmp_path/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(value)
    receipt=dict(schema=data.SCHEMA,passed=True,catalog_sha256=data.sha((tmp_path/data.CATALOG).read_bytes()),
        parent_root_admission_sha256=plan['parent_root_admission_sha256'],parent_outer_sha256=plan['parent_outer_sha256'],
        parent_inner_sha256='e'*64,parent_descriptors=descriptors,adopted_descriptors=cp['repairs'],new_descriptor=new,
        financial_state_unchanged=True,financial_sessions_advanced=0,canonical_financial_source_changed=False,
        adopted_input_sha256=cp['run']['input_sha256'],input_files={k:data.sha(v) for k,v in files.items()})
    (tmp_path/data.RECEIPT).write_bytes(data.encoded(receipt))
    return plan,cp,receipt


def test_actual_catalog_and_two_source_literals_are_qualified():
    plan=data.catalog()
    import system_campaign_financial_partial as partial
    phase=data.original.phase(partial.root_spec('P07'))
    future=runtime.future_api(plan,data.validator(plan),phase)
    before=importlib.import_module('system_campaign_financial_future').SUPPLEMENTAL_PHASES.copy()
    _,_,terms=future['selected']('P07',cursor='2022-09-30')
    extra,sources=future['supplemental_selection']('P07','2022-09-30')
    assert [t['ticker'] for t in terms+extra] == ['GBT','TRQ']
    assert extra[0]['added']['cash_per_share'].hex() == '0x1.f936b43dcf596p+4'
    assert extra[0]['parent_positions'] == []
    assert importlib.import_module('system_campaign_financial_future').SUPPLEMENTAL_PHASES == before


def test_full23_receipt_and_retained_restart_are_readonly(tmp_path,monkeypatch):
    plan,cp,receipt=sample(tmp_path,monkeypatch);before=deepcopy(cp)
    assert data.validated_receipt(tmp_path,cp,plan,input_hash=input_hash)==receipt
    assert data.validated_receipt(tmp_path,cp,plan,input_hash=input_hash)==receipt
    assert cp==before and len(cp['repairs'])==23


@pytest.mark.parametrize('mutation',['old_descriptor','unregistered24','dropped22','hash','wrong_new_kind',
    'wrong_amount','native','resource','missing_receipt','receipt_flag','bool_sessions','missing_boundary',
    'qualification_flag','qualification_count','qualification_bool'])
def test_full_checkpoint_and_input_mutations_refused(tmp_path,monkeypatch,mutation):
    plan,cp,value=sample(tmp_path,monkeypatch)
    if mutation=='old_descriptor':cp['repairs'][0]['resume_session']='2022-08-31'
    elif mutation=='unregistered24':cp['repairs'].append(deepcopy(cp['repairs'][-1]))
    elif mutation=='dropped22':cp['repairs'].pop(20)
    elif mutation=='hash':cp['run']['input_sha256']='0'*64
    elif mutation in ('wrong_new_kind','wrong_amount','native'):
        p=tmp_path/data.OVERLAY;doc=json.loads(p.read_bytes())
        if mutation=='wrong_new_kind':doc['add'][0]['kind']='CONVERSION'
        elif mutation=='wrong_amount':doc['add'][0]['cash_per_share']=29
        else:doc['suppress'][0]['term_sha256']='0'*64
        new,raw=document(tmp_path,doc);cp['repairs'][-1]=new;p.write_bytes(raw)
        cp['run']['input_sha256']=input_hash(cp['base'],cp['repairs'])
        value.update(adopted_descriptors=cp['repairs'],new_descriptor=new,adopted_input_sha256=cp['run']['input_sha256'])
        value['input_files'][data.OVERLAY]=data.sha(raw)
        (tmp_path/data.DIRECTORY/'future-financial-overlay.json').write_bytes(raw)
        value['input_files'][data.DIRECTORY+'/future-financial-overlay.json']=data.sha(raw)
    elif mutation=='resource':(tmp_path/data.DIRECTORY/'future-financial-overlay.json').write_bytes(b'changed')
    elif mutation=='missing_receipt':(tmp_path/data.RECEIPT).unlink()
    elif mutation=='receipt_flag':value['financial_state_unchanged']=False
    elif mutation=='bool_sessions':value['financial_sessions_advanced']=False
    elif mutation=='missing_boundary':del value['input_files'][data.ADOPTION+'/proof.json']
    else:
        p=tmp_path/data.DIRECTORY/'future-input-qualification.json';q=json.loads(p.read_bytes())
        if mutation=='qualification_flag':q['wrong_native_and_delivery_witness_refused']=False
        elif mutation=='qualification_count':q['packet_checks']=2
        else:q['financial_sessions_advanced']=False
        p.write_bytes(data.encoded(q));value['input_files'][data.DIRECTORY+'/future-input-qualification.json']=data.sha(p.read_bytes())
    if mutation!='missing_receipt':(tmp_path/data.RECEIPT).write_bytes(data.encoded(value))
    with pytest.raises((ValueError,FileNotFoundError)):data.validated_receipt(tmp_path,cp,plan,input_hash=input_hash)


def test_unchanged22_requires_exact_original_parent_and_no_orphan_receipt(tmp_path,monkeypatch):
    plan,cp,value=sample(tmp_path,monkeypatch);cp['repairs']=deepcopy(plan['parent_descriptors']);cp['sha256']=plan['parent_outer_sha256']
    with pytest.raises(ValueError,match='NO_UNCOMMITTED_RECEIPT'):data.validated_receipt(tmp_path,cp,plan,input_hash=input_hash)
    (tmp_path/data.RECEIPT).unlink()
    assert data.validated_receipt(tmp_path,cp,plan,input_hash=input_hash) is None
    cp['sha256']='0'*64
    with pytest.raises(ValueError,match='EXACT_FULL_PARENT'):data.validated_receipt(tmp_path,cp,plan,input_hash=input_hash)


def test_model_visitor_ast_undo_restores_entire_original():
    raw=Path(data.original.__file__).read_bytes();fn=data.model_tree(raw)
    assert ast.unparse(fn.body.pop(1))=='validate_tail(root, cp, input_hash=input_hash)'
    found,=[n for n in ast.walk(fn) if isinstance(n,ast.Subscript) and ast.unparse(n)=="cp['repairs'][21:22]"]
    found.slice.upper=None
    assert ast.dump(fn,include_attributes=False)==ast.dump(data.original.function(raw,'validate_models'),include_attributes=False)


def test_runtime_ast_undo_restores_every_original_financial_statement():
    import system_campaign_financial_additional_sensor_runtime as original
    raw=Path(original.__file__).read_bytes();tree=data.runtime_tree(raw);nodes={n.name:n for n in tree.body}
    n=nodes['verify_qualification']
    data.replace_exact(n,"second['repairs'] == cp['repairs'][:22]","second['repairs'] == cp['repairs']",'undo')
    class UndoHash(ast.NodeTransformer):
        def visit_Call(self,node):
            if ast.unparse(node)=='original_boundary_hash(second, cp)':return ast.parse("second['run']['input_sha256'] == cp['run']['input_sha256']",mode='eval').body
            return self.generic_visit(node)
    UndoHash().visit(n)
    n=nodes['run_retained'];site,=[i for i,x in enumerate(n.body) if ast.unparse(x).startswith('adopted = adopt_ordinary(')];n.body.pop(site)
    data.replace_exact(n,"actual['repairs'] == adopted['repairs']","actual['repairs'] == cp['repairs']",'undo')
    data.replace_exact(n,"actual['run']['input_sha256'] == adopted['run']['input_sha256']","actual['run']['input_sha256'] == cp['run']['input_sha256']",'undo')
    class UndoReview(ast.NodeTransformer):
        def visit_Call(self,node):
            if ast.unparse(node)=='review_ordinary(parent, current, evidence, out, spec)':return ast.parse("parent['repairs'] == current['repairs']",mode='eval').body
            return self.generic_visit(node)
    UndoReview().visit(nodes['review']);nodes['inherited_ordinary_observers'].name='ordinary_observers'
    expected=ast.Module(body=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef)],type_ignores=[])
    assert ast.dump(tree,include_attributes=False)==ast.dump(expected,include_attributes=False)


def test_pause_ast_undo_keeps_original_neutral_financial_guards():
    import system_campaign_financial_uncertainty as u
    fn=data.pause_tree(u.__file__)
    assignment,=[n for n in fn.body if isinstance(n,ast.Assign) and ast.unparse(n.targets[0])=='names']
    assert assignment.value.keys.pop().value==data.ADOPTION and assignment.value.values.pop().value==data.OVERLAY
    assert ast.dump(fn,include_attributes=False)==ast.dump(data.original.function(Path(u.__file__).read_bytes(),'paused_own_adoption'),include_attributes=False)


@pytest.mark.parametrize('name',['research.pooled_vacancy_funding','stock_strategy_shared.wealth_core','sentinel.controller','numpy','pandas'])
def test_canonical_import_fences(name):
    with pytest.raises(ImportError,match='DATA_ONLY'):importlib.import_module(name)


def test_receipt_full_input_guard_is_necessary(tmp_path,monkeypatch):
    plan,cp,value=sample(tmp_path,monkeypatch);cp['run']['input_sha256']='0'*64
    with pytest.raises(ValueError,match='FULL_CANONICAL_INPUT_HASH'):data.validated_receipt(tmp_path,cp,plan,input_hash=input_hash)
    fn=data.original.function(Path(data.__file__).read_bytes(),'validated_receipt')
    fn.body=[n for n in fn.body if not (isinstance(n,ast.Expr) and isinstance(n.value,ast.Call)
        and any(isinstance(a,ast.Constant) and a.value=='AUGMENTATION_FULL_CANONICAL_INPUT_HASH' for a in n.value.args))]
    namespace=dict(vars(data));exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<guard-removal-data-falsifier>','exec'),namespace)
    assert namespace['validated_receipt'](tmp_path,cp,plan,input_hash=input_hash)==value


def test_private_runtime_build_has_no_global_bindings_or_financial_execution(tmp_path,monkeypatch):
    import system_campaign_financial_partial as partial
    import system_campaign_financial_additional_sensor_runtime as original
    monkeypatch.setattr(runtime,'hosted',lambda:None)
    before=dict(vars(original));data_before=dict(vars(data.original))
    spec=partial.root_spec('P07')
    api=runtime.api(tmp_path,dict(synthetic_DTO=True),spec)
    assert callable(api.run_retained) and callable(api.retained_models)
    assert api.data.validate_models is not data.original.validate_models
    assert api.ordinary_observers is not original.ordinary_observers
    assert vars(original)==before and vars(data.original)==data_before


def test_cash_reviewer_complete_ast_undo():
    raw=(data.HERE/'system_campaign_ordinary_augmentation_cash_v1.py').read_bytes();fn=data.cash_tree(raw)
    assignment,=[n for n in fn.body if isinstance(n,ast.Assign) and ast.unparse(n.targets[0])=='amount']
    assignment.value=ast.parse('D(quantity) * price',mode='eval').body
    data.replace_exact(fn,"D(str(sum((e['cash_delta'] for e in paid)))) == amount",
        "sum((D(str(e['cash_delta'])) for e in paid), D(0)) == amount",'undo')
    data.replace_exact(fn,"D(str(e['cash_delta'])) == D(str(-e['shares_delta'] * term['added']['cash_per_share']))",
        "D(str(e['cash_delta'])) == -D(str(e['shares_delta'])) * price",'undo')
    assert ast.dump(fn,include_attributes=False)==ast.dump(data.original.function(raw,'verify_event'),include_attributes=False)


def cash_sample(ticker,quantities):
    plan=data.catalog();source=next(s for s in plan['literal_sources'] if s['selected_tickers']==[ticker])
    term=json.loads((data.HERE/source['catalog_file']).read_bytes())['terms'][0]
    sid,day=term['security_id'],term['added']['session'];price=term['added']['cash_per_share']
    before=dict(wealth_core=dict(episodes={str(i):dict(security_id=sid,current_shares=q) for i,q in enumerate(quantities)}))
    opened=dict(wealth_core=dict(episodes={}),pending=[])
    rows=[dict(session='2022-10-01',evidence=dict(research_entry_audit=dict(closing_accounting=before))),
          dict(session=day,evidence=dict(research_entry_audit=dict(opening_accounting=opened)))]
    events=[dict(session=day,security_id=sid,event_type='CASH_MERGER',cash_delta=q*price,price=price,
        shares_delta=-q,fees=0.,detail=dict(reference=term['added']['reference'])) for q in quantities]
    record=dict(passed=True,financial_source_changed=False,session=day,source=[],stock=[],risk=[],engine_calls=0,
        order=['CASH:'+sid],cash=[dict(session=day,security_id=sid,actual_context_call=True,source_only_noop=False,
        postcondition=dict(actual_held=bool(quantities),quantity=sum(quantities),nominal_cash=sum(q*price for q in quantities)))])
    return plan,term,rows,events,{day:record},day


@pytest.mark.parametrize('ticker,quantities',[('GBT',[]),('GBT',[82]),('TRQ',[]),('TRQ',[82]),('TRQ',[43,39])])
def test_actual_literal_cash_operations_with_dynamic_quantities(ticker,quantities):
    plan,term,rows,events,observed,through=cash_sample(ticker,quantities)
    result=data.verify_cash_events(rows,events,observed,[term],through,plan)
    assert result[0]['quantity']==sum(quantities)


@pytest.mark.parametrize('mutation',['cash','quantity','missing','context','ledger','clearance','extra_event'])
def test_cash_review_refuses_economic_and_context_mutations(mutation):
    plan,term,rows,events,observed,through=cash_sample('TRQ',[82]);record=observed[through]
    if mutation=='cash':record['cash'][0]['postcondition']['nominal_cash']+=1
    elif mutation=='quantity':record['cash'][0]['postcondition']['quantity']=81
    elif mutation=='missing':observed.clear()
    elif mutation=='context':record['cash'][0]['actual_context_call']=False
    elif mutation=='ledger':events[0]['cash_delta']+=1
    elif mutation=='clearance':rows[1]['evidence']['research_entry_audit']['opening_accounting']['pending']=[dict(security_id=term['security_id'])]
    else:observed['2022-10-06']=deepcopy(record)
    with pytest.raises(ValueError):data.verify_cash_events(rows,events,observed,[term],through,plan)


def without_guard(name,label):
    fn=data.original.function(Path(data.__file__).read_bytes(),name);count=0
    for i in reversed(range(len(fn.body))):
        n=fn.body[i]
        if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and any(
            isinstance(a,ast.Constant) and a.value==label for a in n.value.args):
            fn.body.pop(i);count+=1
    assert count==1
    namespace=dict(vars(data));exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<meaningful-data-guard-removal>','exec'),namespace)
    return namespace[name]


@pytest.mark.parametrize('mutation',['prefix','amount','packet'])
def test_new_data_guards_are_necessary(tmp_path,monkeypatch,mutation):
    plan,cp,value=sample(tmp_path,monkeypatch)
    if mutation=='prefix':
        cp['repairs'][0]['resume_session']='2022-08-31'
        value['adopted_descriptors']=deepcopy(cp['repairs'])
        cp['run']['input_sha256']=input_hash(cp['base'],cp['repairs']);value['adopted_input_sha256']=cp['run']['input_sha256']
        name,label='suffix','AUGMENTATION_COMPLETE_UNCHANGED_ORIGIN_PREFIX'
    elif mutation=='amount':
        doc=json.loads((tmp_path/data.OVERLAY).read_bytes());doc['add'][0]['cash_per_share']=29
        descriptor,raw=document(tmp_path,doc);cp['repairs'][-1]=descriptor
        value.update(adopted_descriptors=deepcopy(cp['repairs']),new_descriptor=descriptor)
        cp['run']['input_sha256']=input_hash(cp['base'],cp['repairs']);value['adopted_input_sha256']=cp['run']['input_sha256']
        for n in (data.OVERLAY,data.DIRECTORY+'/future-financial-overlay.json'):
            (tmp_path/n).write_bytes(raw);value['input_files'][n]=data.sha(raw)
        name,label='validated_receipt','AUGMENTATION_EXACT_QUALIFIED_CASH_TERMS_AND_NATIVE_PREIMAGES'
    else:
        n=data.DIRECTORY+'/future-input-qualification.json';q=json.loads((tmp_path/n).read_bytes());q['original_incomplete_guard_retained']=False
        raw=data.encoded(q);(tmp_path/n).write_bytes(raw);value['input_files'][n]=data.sha(raw)
        name,label='validated_receipt','AUGMENTATION_EXACT_ZERO_FINANCIAL_PACKET_QUALIFICATION'
    (tmp_path/data.RECEIPT).write_bytes(data.encoded(value))
    with pytest.raises(ValueError,match=label):data.validated_receipt(tmp_path,cp,plan,input_hash=input_hash)
    broken=without_guard(name,label)
    if name=='suffix':
        monkeypatch.setattr(data,'suffix',broken)
        assert data.validated_receipt(tmp_path,cp,plan,input_hash=input_hash)==value
    else:assert broken(tmp_path,cp,plan,input_hash=input_hash)==value


def test_retained23_never_reprepares_or_readopts(tmp_path,monkeypatch):
    plan,cp,value=sample(tmp_path,monkeypatch)
    monkeypatch.setattr(runtime,'hosted',lambda:None)
    monkeypatch.setattr(runtime,'canonical_hash',lambda:input_hash)
    def forbidden(*args,**kwargs):raise AssertionError('REPLAY_OR_READOPTION')
    monkeypatch.setattr(runtime,'prepare',forbidden);monkeypatch.setattr(runtime,'pause',forbidden)
    before=deepcopy(cp)
    assert runtime.adopt(cp,tmp_path,None,None,None,None,None,plan,None) is cp
    assert cp==before
