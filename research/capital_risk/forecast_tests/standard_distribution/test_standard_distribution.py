"""Portable pure input, actual-descriptor and DATA-oracle tests. No finance."""
import ast
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict,dataclass,replace
from datetime import date
from decimal import Decimal
from fractions import Fraction
import hashlib
import importlib.abc
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from typing import Literal

import pytest
from pydantic import BaseModel,ConfigDict,Field,PrivateAttr,model_validator

HERE=Path(__file__).resolve().parents[2]if Path(__file__).parent.name=='standard_distribution'else Path(__file__).parent
class Fence(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname.startswith(('stock_strategy_shared','sentinel','research.pooled_','numpy','pandas')):
            raise AssertionError('FORBIDDEN_STANDARD_DISTRIBUTION_CANONICAL_IMPORT:'+fullname)
sys.meta_path.insert(0,Fence());sys.path.insert(0,str(HERE))
import system_campaign_financial_distribution_standard as s
import system_campaign_financial_distribution_standard_runtime as runtime
import system_campaign_financial_compound_input_v2 as model

def data(name):
    path=HERE/name
    if not path.exists():path=Path(__file__).parent/'fixtures'/name.removeprefix('fixtures/')
    raw=path.read_bytes()
    pins={'P11-original10-input-only.json':'a5983b0653a86841e02063464cecd615fd995a5d8bf05c3393fc5efc16d8e8a3',
          'pure-original-nonempty-input-codec.json':'fb5b4da4b84afcc9985000723efcee5b4ab2e9884e8bebbca4f0c670d487533e',
          'five-original-ordinary-fullrows.json':'7bc36f48e1b39b6ffc0a153b9f6734b4506f49cd6c6687d00f6e591827511df3',
          'five-original-ordinary-native-preimages.json':'19f51a21adb1e00fbbd1d91cd613494ed095f71bb573b111bd53fc7bf5b77a7a'}
    if path.name in pins:assert hashlib.sha256(raw).hexdigest()==pins[path.name]
    return json.loads(raw)
def record():return s.qualified_record('P11')
def binding():
    r=record();b=s.build_terms(r['research_assumption'],data('fixtures/P11-closed-source243-payload.json'),
        child_security_id=r['child_security_id'],reference=r['reference'],source_proof=r['source_proof'])
    b['canonical_profile']=deepcopy(r['canonical_profile']);return b

@dataclass(frozen=True)
class Spin:
    session:str;parent_ticker:str;parent_security_id:str;child_ticker:str|None;child_security_id:str|None;source_row_id:str;value_evidence:str|None
    child_shares_per_parent:str|None=None;child_price:str|None=None;cash_in_lieu_price:str|None=None;policy:str='REQUIRE_REVIEWED_CHILD_OWNERSHIP'
@dataclass(frozen=True)
class Bar:
    session:str;security_id:str;ticker:str;raw_close:float;raw_open:float;volume:float
    split_ratio:float=1.;dividend_per_share:float=0.;tradeable:bool=True;unresolved_corporate_action:bool=False;signal_close:float|None=None
@dataclass(frozen=True)
class Packet:
    day:str;bars:tuple;terminal:tuple;spins:tuple;other:str='unrelated input preserved'
def vendor(row):return Bar(row['session'],row['security_id'],row['ticker'],float(row['raw_close']),float(row['raw_open']),float(row['raw_compatible_volume']),
    float(row['split_ratio']),float(row['dividend_per_share']),row['tradeable']=='1',False,float(row['signal_close']))

def pure_source():
    value=data('fixtures/pure-original-nonempty-input-codec.json')
    assert value['original_module_sha256']=='1112f91ab01c6b633fd6e7b2c089aa02367d2fc7fbc152a654da6620d753b152'
    assert value['no_financial_runtime_or_book_material']is True
    for item in value['functions'].values():
        assert s.sha(item['source'].encode())==item['source_sha256']
        assert s.sha(ast.dump(ast.parse(item['source']).body[0],include_attributes=False).encode())==item['ast_sha256']
    raw='\n'.join(value['functions'][n]['source']for n in('_session','_digest','_apply_spinoff_repair','Repair','_loaded')).encode()
    assert s.sha(raw)==value['container_sha256']=='532d8114df672562d8e7604babacb858a50263bd7d3c632632b18ce82a2739cd'
    return raw

@pytest.fixture(autouse=True)
def pure_compiler(monkeypatch):
    import system_campaign_distribution_facts as compiler
    monkeypatch.setattr(compiler,'REPAIR_SHA',s.sha(pure_source()))

def projection():
    b=binding();raw=pure_source();nodes=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef)and n.name in('_digest','_session')]
    ns=dict(asdict=asdict,replace=replace,Decimal=Decimal,date=date,json=json,hashlib=hashlib)
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes,type_ignores=[])),'<frozen-pure-input-helper>','exec'),ns)
    p=s.EventSessionProjection(b,parent_bar=vendor(b['original_rows'][b['spin']['parent_security_id']]),
        child_bar=vendor(b['original_rows'][b['spin']['child_security_id']]),source_raw=raw,source_namespace=ns,spin_factory=Spin)
    packet=Packet(b['spin']['session'],tuple(vendor(r)for r in b['original_rows'].values()),('unrelated terminal',),p.originals)
    return p,packet

def synthetics():
    b=binding();p=s.consideration(b,36,10);sid=b['spin']['parent_security_id'];child=b['spin']['child_security_id']
    ep=dict(security_id=sid,ticker='GE',slot_id=11,current_shares=36,entry_date='2023-08-11',entry_split_adjusted_price=100.,
        episode_peak_split_adjusted_close=180.12,research_stop_floor=162.108,research_stop_cursor='2024-03-28',source_lots=[])
    before=dict(cash=1000.,episodes={'11':ep,'2':dict(security_id='UNRELATED',preserved='exact')},slots={'11':dict(occupied_by=sid,reserved_for=None)})
    after=deepcopy(before);after['cash']+=p['child_cash'];a=after['episodes']['11']
    po=float(b['original_rows'][sid]['raw_open']);co=float(b['spin']['cash_in_lieu_price'])
    scale=po/(po+float(Fraction(b['spin']['child_shares_per_parent'])*Fraction(str(co))))
    a['entry_split_adjusted_price']*=scale;a['episode_peak_split_adjusted_close']*=scale;a['research_stop_floor']*=scale
    a['source_lots']=[dict(kind='SPINOFF_CHILD_LIQUIDATION',session=b['spin']['session'],source_row_id=b['spin']['source_row_id'],
        parent_security_id=sid,child_security_id=child,child_ticker='GEV',child_shares_per_parent='1/4',child_open=co,reference_scale=scale)]
    lb=dict(events=[dict(old='preserved')],receivables=[]);la=deepcopy(lb)
    la['events'] += [dict(event_type='SPINOFF_RECEIPT',security_id=child,session=b['spin']['session'],shares_delta=9,
        detail=dict(fractional_entitlement='0'),cash_before=1000.,cash_after=1000.),
        dict(event_type='SPINOFF_LIQUIDATION',security_id=child,session=b['spin']['session'],shares_delta=-9,cash_before=1000.,
             cash_delta=p['child_cash'],cash_after=after['cash'],price=co,fees=9*co-p['child_whole_proceeds'])]
    audit=[dict(parent_security_id=sid,child_security_id=child,whole_child_shares=9,fractional_child_shares='0',cash_proceeds=p['child_cash'])]
    return b,before,after,lb,la,audit

def without_guard(fn,code):
    tree=ast.parse((HERE/'system_campaign_financial_distribution_standard.py').read_bytes());node=next(n for n in tree.body if isinstance(n,ast.FunctionDef)and n.name==fn.__name__)
    hits=[]
    class Remove(ast.NodeTransformer):
        def visit_Expr(self,n):
            if isinstance(n.value,ast.Call)and isinstance(n.value.func,ast.Name)and n.value.func.id=='need'and len(n.value.args)==2 and isinstance(n.value.args[1],ast.Constant)and n.value.args[1].value==code:
                hits.append(n);return ast.Pass()
            return self.generic_visit(n)
    node=Remove().visit(node);assert len(hits)==1
    ns=dict(vars(s));exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'<meaningful-removed-standard-guard>','exec'),ns)
    return ns[fn.__name__]

def install_original_inputs(tmp_path):
    fixture=data('fixtures/P11-original10-input-only.json');root=tmp_path/'root';repairs=root/'book/repairs';repairs.mkdir(parents=True)
    for v in fixture['repairs']:(repairs/v['descriptor']['filename']).write_bytes(v['raw_utf8'].encode())
    subset=dict(terms=[next(t for t in data('system-campaign-unconsumed2024-cash-calendar-terminal-facts.json')['terms']if t['ticker']=='SWAV')])
    return root,deepcopy(fixture['parent']),subset

def test_actual_record_source_closure_and_exact_original_SWAV():
    r=record();b=binding();assert r['inherited_ordinary_count']==10 and r['ordinary_activation']['selected_tickers']==['ALPN','SWAV','DCPH','EVBG','PRFT']
    assert b['terminal']is None and b['parent_positions']==[dict(slot_id=11,ticker='GE',quantity=36,entry_date='2023-08-11')]
    p=s.consideration(b,36,10);assert p['child_whole']==9 and p['child_fraction']=='0'and p['exact_total_inflow']=='25687287/20000'
    assert p['suppressed_cash_proxy_is_additional_cash']is False
    assert r['canonical_profile']['spinoffs_sha256']=='e82ec8a35e10218fdf02c58ac4051321dbc1553f5282e5fb99d70f860202558e'
    assert data('P11-original-primitive-text-derivation.json')==r['canonical_profile']['derivation']

def test_actual_ten_inputs_no_branch_and_SWAV_unadopted(tmp_path):
    root,cp,subset=install_original_inputs(tmp_path);before=deepcopy(cp)
    proof=s.inherited_proof(cp,root,subset,expected_count=10)
    assert len(proof['retained_inputs'])==10 and proof['standard_ordinary_only']is True and cp==before

def test_actual_original_five_term_batch_is_future_and_unadopted(tmp_path):
    root,cp,subset=install_original_inputs(tmp_path)
    full=data('system-campaign-unconsumed2024-cash-calendar-terminal-facts.json');subset['terms']=full['terms']
    assert [t['ticker']for t in subset['terms']]==record()['ordinary_activation']['selected_tickers']
    assert all(cp['source_cursor']<min(t['native_session'],t['added']['session'])for t in subset['terms'])
    proof=s.inherited_proof(cp,root,subset,expected_count=10)
    assert proof['ordinary_targets_unadopted']is True and len(proof['retained_inputs'])==10

def test_original_registered_CashCalendar_selects_exact_five_terms(monkeypatch):
    import system_campaign_ordinary_registry as registry
    original=registry.registrations;monkeypatch.setattr(registry,'registrations',lambda driver=HERE:original(HERE))
    codec,full,subset=s.select_original(record())
    assert subset['terms']==full['terms'] and len(codec.catalog['terms'])==5
    assert [t['ticker']for t in subset['terms']]==['ALPN','SWAV','DCPH','EVBG','PRFT']

@pytest.mark.parametrize('bad',['B19','legacy','unknown','bytes','count','SWAV'])
def test_actual_inherited_inputs_strict_falsifiers(tmp_path,bad):
    root,cp,subset=install_original_inputs(tmp_path);d=cp['repairs'][0];path=root/'book/repairs'/d['filename'];value=json.loads(path.read_bytes())
    if bad=='count':cp['repairs'].pop()
    elif bad=='bytes':path.write_bytes(path.read_bytes()+b' ')
    else:
        if bad=='B19':value['schema']='research.leadership-branch-uncertainty-input/1'
        elif bad=='legacy':value['schema']='research.leadership-uncertainty-input/1'
        elif bad=='unknown':value['schema']='unknown/1'
        else:value['add'].append(subset['terms'][0]['added'])
        raw=s.encoded(value);d['sha256']=s.sha(raw);d['filename']=d['sha256']+'.json';(root/'book/repairs'/d['filename']).write_bytes(raw)
    with pytest.raises(ValueError):s.inherited_proof(cp,root,subset,expected_count=10)

def test_unknown_schema_guard_removal_is_meaningful(tmp_path):
    root,cp,subset=install_original_inputs(tmp_path);d=cp['repairs'][0];v=json.loads((root/'book/repairs'/d['filename']).read_bytes());v['schema']='unknown/1'
    raw=s.encoded(v);d['sha256']=s.sha(raw);d['filename']=d['sha256']+'.json';(root/'book/repairs'/d['filename']).write_bytes(raw)
    with pytest.raises(ValueError):s.inherited_proof(cp,root,subset,expected_count=10)
    mutant=without_guard(s.inherited_proof,'STANDARD_ALL_ORDINARY_BYTES_NO_BRANCH_OR_UNKNOWN_SCHEMA')
    assert mutant(cp,root,subset,expected_count=10)['standard_ordinary_only']is True

def test_source_projection_exact_two_representations_one_child_no_cash():
    p,packet=projection();before=deepcopy(packet);fixed=p.apply(packet,p.descriptor)
    assert packet==before and fixed.terminal==packet.terminal and len(fixed.spins)==1
    assert fixed.spins[0].child_shares_per_parent=='1/4'and fixed.spins[0].cash_in_lieu_price=='142.85'
    parent=next(v for v in fixed.bars if v.ticker=='GE');assert parent.dividend_per_share==0.
    assert next(v for v in packet.bars if v.ticker=='GE').dividend_per_share==34.68074

@pytest.mark.parametrize('bad',['quote','proxy','native_duplicate','native_missing','identity','wrong_day'])
def test_projection_source_falsifiers(bad):
    p,packet=projection()
    if bad=='quote':packet=replace(packet,bars=tuple(replace(v,raw_open=v.raw_open+.01)if v.ticker=='GEV'else v for v in packet.bars))
    elif bad=='proxy':packet=replace(packet,bars=tuple(replace(v,dividend_per_share=0.)if v.ticker=='GE'else v for v in packet.bars))
    elif bad=='native_duplicate':packet=replace(packet,spins=packet.spins+packet.spins[:1])
    elif bad=='native_missing':packet=replace(packet,spins=packet.spins[:1])
    elif bad=='identity':packet=replace(packet,bars=tuple(replace(v,ticker='OTHER')if v.ticker=='GEV'else v for v in packet.bars))
    else:packet=replace(packet,day='2024-04-03')
    with pytest.raises(ValueError):p.apply(packet,p.descriptor)

def test_other_session_same_parent_unrelated_native_delegates_unchanged():
    p,packet=projection();other=replace(p.originals[0],session='2024-04-03',source_row_id='f'*64)
    packet=replace(packet,day='2024-04-03',spins=(other,));assert p.apply(packet,p.descriptor)is packet

def test_exact_original_floor_rebase_and_no_other_mutation():
    values=synthetics();original=deepcopy(values);out=s.spin_postcondition(*values,10)
    assert values==original and out['canonical_reference_rebase'][0]['before']==162.108
    assert out['canonical_reference_rebase'][0]['after']==162.108*out['canonical_reference_rebase'][0]['reference_scale']
    assert s.review_spin_result(values[0],out)

@pytest.mark.parametrize('bad',['floor_unchanged','floor_arbitrary','cursor','factor','parent_units','other_parent_field','other_episode','cash','fee','proxy_cash','child_retained'])
def test_floor_oracle_and_unchanged_original_economic_guards(bad):
    b,before,after,lb,la,audit=synthetics()
    if bad=='floor_unchanged':after['episodes']['11']['research_stop_floor']=162.108
    elif bad=='floor_arbitrary':after['episodes']['11']['research_stop_floor']+=.01
    elif bad=='cursor':after['episodes']['11']['research_stop_cursor']='2024-04-02'
    elif bad=='factor':after['episodes']['11']['source_lots'][0]['reference_scale']+=.01
    elif bad=='parent_units':after['episodes']['11']['current_shares']-=1
    elif bad=='other_parent_field':after['episodes']['11']['entry_date']='2023-08-12'
    elif bad=='other_episode':after['episodes']['2']['preserved']='changed'
    elif bad=='cash':after['cash']+=.01
    elif bad=='fee':la['events'][-1]['fees']+=.01
    elif bad=='proxy_cash':la['events'].append(dict(event_type='DIVIDEND_ACCRUED',security_id=b['spin']['parent_security_id']))
    else:after['episodes']['10']=dict(security_id=b['spin']['child_security_id'])
    with pytest.raises((ValueError,KeyError)):s.spin_postcondition(b,before,after,lb,la,audit,10)

def test_floor_guard_removal_demonstrably_accepts_wrong_floor():
    values=list(synthetics());values[2]['episodes']['11']['research_stop_floor']+=.01
    with pytest.raises(ValueError):s.spin_postcondition(*values,10)
    mutant=without_guard(s.spin_postcondition,'STANDARD_EXACT_ORIGINAL_FLOOR_TIMES_OBSERVED_REFERENCE_SCALE')
    assert mutant(*values,10)['canonical_reference_rebase'][0]['before']==162.108

def test_original_P07_oracle_refuses_real_variant_change():
    values=synthetics()
    with pytest.raises(ValueError,match='REFERENCE_REBASE_AND_LOT'):s.original_spin_postcondition(*values,10)
    assert s.spin_postcondition(*values,10)

def harmless_source_profile():
    spin=b'# harmless synthetic primitive module\n'
    risk=b'def rebase_floor(ep,scale):\n ep.research_stop_floor=ep.research_stop_floor*scale\n'
    fn=ast.parse(risk).body[0]
    p=dict(spinoffs_sha256=s.sha(spin),capital_risk_sha256=s.sha(risk),rebase_floor_AST_sha256=s.sha(ast.dump(fn,include_attributes=False).encode()))
    sources={'sentinel/core/spinoffs.py':s.sha(spin),'shared/stock_strategy_shared/wealth_core/capital_risk.py':s.sha(risk)}
    return p,sources,spin,risk

def test_actual_source_hash_and_rebase_AST_verifier():
    p,sources,spin,risk=harmless_source_profile();assert s.verify_primitive_sources(p,sources,spinoffs_raw=spin,capital_risk_raw=risk)

@pytest.mark.parametrize('bad',['spin','risk','AST','source_epoch'])
def test_source_and_floor_primitive_falsifiers(bad):
    p,sources,spin,risk=harmless_source_profile()
    if bad=='spin':spin+=b'#changed'
    elif bad=='risk':risk+=b'#changed'
    elif bad=='AST':p['rebase_floor_AST_sha256']='f'*64
    else:sources['sentinel/core/spinoffs.py']='f'*64
    with pytest.raises(ValueError):s.verify_primitive_sources(p,sources,spinoffs_raw=spin,capital_risk_raw=risk)

def test_source_hash_guard_removal_is_meaningful():
    p,sources,spin,risk=harmless_source_profile();risk+=b'# changed module\n'
    with pytest.raises(ValueError):s.verify_primitive_sources(p,sources,spinoffs_raw=spin,capital_risk_raw=risk)
    mutant=without_guard(s.verify_primitive_sources,'STANDARD_ACTUAL_ORIGINAL_VARIANT_PRIMITIVE_SOURCES')
    assert mutant(p,sources,spinoffs_raw=spin,capital_risk_raw=risk)

def test_retained_actual_event_requires_committed_floor_proof(tmp_path):
    b,before,after,lb,la,audit=synthetics();result=s.spin_postcondition(b,before,after,lb,la,audit,10)
    p=dict(binding=b,ordinary_material=dict(terms=[]));current=dict(source_cursor='2024-04-02')
    with pytest.raises(ValueError):runtime.review_actual(p,tmp_path,current)
    value=dict(passed=True,session='2024-04-02',order=['SPINOFF'],spin=result,
        proxy_cash=dict(parent_proxy_cash_accrued=False,parent_proxy_cash_paid=False,child_retained=False))
    path=tmp_path/runtime.ACTUAL;path.write_bytes(s.encoded(value));runtime.review_actual(p,tmp_path,current)
    value['spin']['canonical_reference_rebase'][0]['after']+=.01;path.write_bytes(s.encoded(value))
    with pytest.raises(ValueError):runtime.review_actual(p,tmp_path,current)

def test_uncommitted_tail_proof_ignored_and_not_retained(tmp_path):
    p=dict(binding=binding(),ordinary_material=dict(terms=[]));(tmp_path/runtime.ACTUAL).write_bytes(b'malformed uncommitted tail')
    cp=dict(source_cursor='2024-04-01');runtime.review_actual(p,tmp_path,cp)
    assert runtime.retained_observation_files(p,tmp_path,cp)==()

def test_committed_ordinary_proofs_all_paths_preserved(tmp_path):
    p=dict(binding=binding(),ordinary_material=dict(terms=[dict(added=dict(session='2024-05-31'))]))
    for rel in(Path('actual-future-event-2024-05-31.json'),Path(runtime.RETAINED_OBSERVATION)/'actual-future-event-2024-05-31.json'):
        (tmp_path/rel).parent.mkdir(parents=True,exist_ok=True);(tmp_path/rel).write_bytes(b'committed-proof')
    names=runtime.retained_observation_files(p,tmp_path,dict(source_cursor='2024-06-03'))
    assert len(names)==3 and Path(runtime.ACTUAL)in names

@pytest.mark.parametrize('name',['stock_strategy_shared','sentinel','research.pooled_vacancy_funding','numpy','pandas'])
def test_financial_import_fence(name):
    with pytest.raises(AssertionError):__import__(name)

def test_activated_v2_generation_unchanged_and_standard_AST_delegates_exact():
    assert s.sha((HERE/runtime.FROZEN_V2_FILE).read_bytes())==runtime.FROZEN_V2_SHA
    assert s.sha((HERE/s.ORDINARY_V2_FILE).read_bytes())==s.ORDINARY_V2_SHA
    assert not any(n.startswith(('stock_strategy_shared','sentinel','research.pooled_','numpy','pandas'))for n in sys.modules)


@pytest.mark.parametrize('bad',['DATA','qualification','native_count','native_hash','fullrow','ratio','authority','cash_proxy_semantics'])
def test_closed_source_and_model_guards_stay_active(bad):
    r=record();w=data('fixtures/P11-closed-source243-payload.json');proof=deepcopy(r['source_proof']);assumption=deepcopy(r['research_assumption'])
    if bad=='DATA':proof['independent_DATA_passed']=False
    elif bad=='qualification':proof['independent_qualification_passed']=False
    elif bad=='native_count':w['native_distributions'].append(deepcopy(w['native_distributions'][0]))
    elif bad=='native_hash':w['native_distributions'][0]['native_distribution_sha256']='f'*64
    elif bad=='fullrow':w['additional_rows'][0]['source_row']['issuer_id']='UPGRADED'
    elif bad=='ratio':assumption['child_shares_per_original_parent']='1/3'
    elif bad=='authority':w['financial_authority']=True
    else:assumption['source_cash_proxy_semantics']='ADDITIONAL_CASH'
    with pytest.raises(ValueError):s.build_terms(assumption,w,child_security_id=r['child_security_id'],reference=r['reference'],source_proof=proof)


def pure_repair_type():
    class Strict(BaseModel):model_config=ConfigDict(extra='forbid',strict=True)
    class Evidence(Strict):
        reference:str;description:str;sha256:str|None=None
    class Suppression(Strict):
        session:str;security_id:str;term_sha256:str
    class Added(BaseModel):
        model_config=ConfigDict(extra='allow',strict=True)
        session:str;security_id:str
    ns=dict(__name__=__name__,_Strict=Strict,Literal=Literal,Field=Field,PrivateAttr=PrivateAttr,
        model_validator=model_validator,Digest=str,SourceEvidence=Evidence,Suppression=Suppression,AddedTerm=Added)
    fixture=data('fixtures/pure-original-nonempty-input-codec.json')
    node=ast.parse(fixture['functions']['Repair']['source']).body[0]
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'<actual-original-pure-Repair-class>','exec'),ns)
    cls=ns['Repair'];cls.model_rebuild(_types_namespace=ns);return cls


def material_and_payload():
    r=record();full=data('system-campaign-unconsumed2024-cash-calendar-terminal-facts.json');subset=deepcopy(full)
    origin=data('fixtures/P11-original10-input-only.json')['parent']
    material=dict(schema=s.SCHEMA,arm='P11',ordinary_activation=deepcopy(r['ordinary_activation']),selected_catalog=subset,
        original_private_payload=dict(source_witnesses=[],actual_alias_rows=0),original_parent=origin,terms=subset['terms'],
        financial_sessions_advanced=0,financial_authority=False)
    return material,dict(binding=binding(),ordinary_material=material,original_parent=origin)


def original_loaded_document(path,doc,*,cursor=None):
    cls=pure_repair_type();obj=cls.model_validate(doc)
    obj._file_sha256=s.sha(path.read_bytes());obj._resume_session=cursor or record()['parent_cursor'];obj._document_sha256=s.digest(obj.model_dump(mode='json',by_alias=True))
    return obj


def test_actual_original_nonempty_Repair_minimum_view_preserves_every_field(tmp_path):
    material,p=material_and_payload();doc=s.ordinary_document(material);path=tmp_path/'input.json';path.write_bytes(s.encoded(doc))
    loaded=original_loaded_document(path,doc);assert loaded.earliest_affected_session=='2024-05-17'
    before=deepcopy(loaded.model_dump(mode='json',by_alias=True));private=deepcopy(loaded.__pydantic_private__)
    a=s.activation_descriptor(loaded,p['binding'],record()['source_proof']);view=s.qualified_loaded_view(loaded,p['binding'],record()['source_proof'],a)
    assert view.earliest_affected_session=='2024-04-02' and loaded.earliest_affected_session=='2024-05-17'
    assert view.model_dump(mode='json',by_alias=True)==before and view.__pydantic_private__==private
    assert view.add[0].session=='2024-05-20' and view.suppress[0].session=='2024-05-17'and len(view.add)==len(view.suppress)==5
    empty=deepcopy(doc);empty['add']=[];empty['suppress']=[]
    with pytest.raises(ValueError,match='empty terminal repair'):pure_repair_type().model_validate(empty)


@pytest.mark.parametrize('bad',['fields','private_document','cursor','source','boundary'])
def test_loaded_minimum_view_falsifiers(tmp_path,bad):
    material,p=material_and_payload();doc=s.ordinary_document(material);path=tmp_path/'input.json';path.write_bytes(s.encoded(doc))
    loaded=original_loaded_document(path,doc);proof=deepcopy(record()['source_proof']);a=s.activation_descriptor(loaded,p['binding'],proof)
    if bad=='fields':loaded.add[0].session='2024-06-03'
    elif bad=='private_document':loaded._document_sha256='f'*64
    elif bad=='cursor':loaded._resume_session='2024-04-02'
    elif bad=='source':proof['independent_DATA_passed']=False
    else:a['earliest_affected_session']='2024-04-03'
    with pytest.raises(ValueError):s.qualified_loaded_view(loaded,p['binding'],proof,a)


def context_fixture(tmp_path,monkeypatch):
    material,p=material_and_payload();p['base']=dict(sources={});raw=s.encoded(p)
    path=tmp_path/runtime.OVERLAY;path.write_bytes(s.encoded(runtime.document(p,raw)))
    source=tmp_path/'pure-original-input-codec.py';source.write_bytes(pure_source());ns=dict(asdict=asdict,replace=replace,Decimal=Decimal,date=date,json=json,hashlib=hashlib)
    nodes=[n for n in ast.parse(pure_source()).body if isinstance(n,ast.FunctionDef)and n.name in('_digest','_session')]
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes,type_ignores=[])),'<pure-input-functions>','exec'),ns)
    def load(actual_path,*,resume_session,predecessor_checkpoint_sha256):
        doc=json.loads(Path(actual_path).read_bytes())
        if doc['predecessor_checkpoint_sha256']!=predecessor_checkpoint_sha256:raise ValueError('original predecessor differs')
        obj=original_loaded_document(Path(actual_path),doc,cursor=resume_session)
        if obj.earliest_affected_session<=resume_session:raise ValueError('original consumed input')
        return obj
    apply=lambda packet,obj:packet
    backtest=SimpleNamespace(load_repair=load,apply_repair=apply)
    repair=SimpleNamespace(__file__=str(source),**ns)
    api=SimpleNamespace(backtest=backtest,repair=repair,vendor=vendor,spin_factory=Spin)
    monkeypatch.setattr(runtime,'hosted',lambda:None)
    ctx=runtime.ProjectionContext(tmp_path,payload=(p,raw),api=api)
    return ctx,path,backtest,load,apply,p


def test_actual_context_load_apply_clock_and_cleanup(tmp_path,monkeypatch):
    ctx,path,backtest,load,apply,p=context_fixture(tmp_path,monkeypatch)
    projected,packet=projection()
    with ctx:
        loaded=backtest.load_repair(path,resume_session=p['original_parent']['source_cursor'],
            predecessor_checkpoint_sha256=p['original_parent']['run']['checkpoint_sha256'])
        assert loaded.earliest_affected_session=='2024-04-02'
        fixed=backtest.apply_repair(packet,loaded)
        assert len(fixed.spins)==1 and next(v for v in fixed.bars if v.ticker=='GE').dividend_per_share==0.
        with pytest.raises(ValueError):backtest.load_repair(path,resume_session='2024-03-29',
            predecessor_checkpoint_sha256=p['original_parent']['run']['checkpoint_sha256'])
        foreign=load(path,resume_session=p['original_parent']['source_cursor'],predecessor_checkpoint_sha256=p['original_parent']['run']['checkpoint_sha256'])
        with pytest.raises(ValueError):backtest.apply_repair(packet,foreign)
    assert backtest.load_repair is load and backtest.apply_repair is apply


def test_initial_context_one_gate_original_ordinary_and_child_observer(tmp_path,monkeypatch):
    calls=[];_,p=material_and_payload();monkeypatch.setattr(runtime,'hosted',lambda:None)
    class Ctx:
        def __init__(self,name):self.name=name;self.payload=p
        def __enter__(self):calls.append(self.name+' enter');return self
        def __exit__(self,*args):calls.append(self.name+' exit')
    # Replace the import binding only, never financial calls or original code.
    node=next(n for n in ast.parse((HERE/'system_campaign_financial_distribution_standard_runtime.py').read_bytes()).body if isinstance(n,ast.FunctionDef)and n.name=='initial_context')
    node.body=[ast.Assign(targets=[ast.Name(id='AdoptionGate',ctx=ast.Store())],value=ast.Name(id='GateStub',ctx=ast.Load()))if isinstance(n,ast.ImportFrom)and n.module=='system_campaign_financial_resume'else n for n in node.body]
    ns=dict(vars(runtime),GateStub=lambda*args:Ctx('gate'),ProjectionContext=lambda*out:Ctx('projection'),
        Observer=lambda*out:Ctx('child'),ordinary_events=lambda*out:Ctx('ordinary'))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'<original-standard-initial-context-only-import-binding>','exec'),ns)
    loaded=SimpleNamespace(sha256='a'*64,earliest_affected_session='2024-04-02')
    import system_campaign_ordinary_registry as registry
    original_registry=registry.registrations
    with ns['initial_context']({},tmp_path,dict(arm='P11'),loaded):
        assert len(registry.registrations(HERE))==8
        calls.append('financial caller')
    assert registry.registrations is original_registry
    assert calls==['projection enter','gate enter','child enter','ordinary enter','financial caller','ordinary exit','child exit','gate exit','projection exit']


def test_unchanged_actual_ordinary_observer_constructor_binds_five_genuine_terms(tmp_path):
    material,p=material_and_payload();doc=s.ordinary_document(material)
    (tmp_path/runtime.OVERLAY).write_bytes(s.encoded(doc));(tmp_path/s.MATERIAL).write_bytes(s.encoded(material))
    original=s.original_observer();cp=data('fixtures/P11-original10-input-only.json')['parent']
    cls=s.bound_observer_type(original,material,cp,overlay_name=runtime.OVERLAY)
    observer=cls(tmp_path,'P11',cp=cp)
    assert len(observer.terms)==5 and observer.scopes==[]
    assert set(v['cash_per_share']for v in observer.terms.values())=={65.,335.,25.6,35.,76.}
    wrong=deepcopy(material);wrong['financial_authority']=True;(tmp_path/s.MATERIAL).write_bytes(s.encoded(wrong))
    with pytest.raises(ValueError):cls(tmp_path,'P11',cp=cp)


def actual_observer_fixture(tmp_path,monkeypatch):
    b,before,after,lb,la,audit=synthetics();profile,sources,spinraw,riskraw=harmless_source_profile()
    b['canonical_profile'].update(profile);kernelraw=b'# synthetic caller module, no financial implementation\n';runtimeraw=b'# synthetic advance module\n'
    spinfile=tmp_path/'synthetic-spin.py';spinfile.write_bytes(spinraw);riskfile=tmp_path/'synthetic-risk.py';riskfile.write_bytes(riskraw)
    kernelfile=tmp_path/'synthetic-kernel.py';kernelfile.write_bytes(kernelraw);runtimefile=tmp_path/'synthetic-runtime.py';runtimefile.write_bytes(runtimeraw)
    calls=[]
    class Box:
        def __init__(self,value):self.value=deepcopy(value)
        def to_dict(self):return deepcopy(self.value)
    def primitive(state,distributions,*,bars,ledger,config):
        calls.append(tuple(distributions));state.value=deepcopy(after);ledger.value=deepcopy(la);return deepcopy(audit)
    spin=SimpleNamespace(__file__=str(spinfile),apply_supported_entitlements=primitive)
    def advance_session(state,distributions,*,bars,ledger,config,pending):
        return spin.apply_supported_entitlements(state,distributions,bars=bars,ledger=ledger,config=config)
    kernel=SimpleNamespace(__file__=str(kernelfile),advance_session=advance_session)
    def advance(run,publication):
        state=Box(run.state.wealth_core);ledger=Box(run.state.ledger)
        kernel.advance_session(state,publication.spinoff_distributions,bars=publication.bars,ledger=ledger,
            config=SimpleNamespace(transaction_cost_bps=10),pending=run.state.pending)
        return SimpleNamespace(state=SimpleNamespace(wealth_core=state.to_dict(),ledger=ledger.to_dict()))
    rt=SimpleNamespace(__file__=str(runtimefile),advance=advance)
    sources.update({'sentinel/core/kernel.py':s.sha(kernelraw),'research/pooled_vacancy_funding/runtime.py':s.sha(runtimeraw)})
    p=dict(binding=b,base=dict(sources=sources))
    api=SimpleNamespace(runtime=rt,kernel=kernel,spinoffs=spin,capital_risk=SimpleNamespace(__file__=str(riskfile)))
    parent=b['spin']['parent_security_id'];bars=tuple(replace(vendor(v),dividend_per_share=0.)if v['security_id']==parent else vendor(v)for v in b['original_rows'].values())
    publication=SimpleNamespace(session='2024-04-02',bars=bars,spinoff_distributions=(Spin(**b['spin']),))
    run=SimpleNamespace(state=SimpleNamespace(wealth_core=deepcopy(before),ledger=deepcopy(lb),pending=[]))
    monkeypatch.setattr(runtime,'hosted',lambda:None)
    return runtime.Observer(tmp_path,p,api=api),api,run,publication,calls,primitive,advance


def test_actual_child_observer_uses_real_synthetic_caller_and_original_delegation(tmp_path,monkeypatch):
    observer,api,run,pub,calls,primitive,advance=actual_observer_fixture(tmp_path,monkeypatch)
    with observer:
        result=api.runtime.advance(run,pub)
        assert len(calls)==1 and calls[0]==pub.spinoff_distributions
        proof=json.loads((tmp_path/runtime.ACTUAL).read_bytes())
        assert proof['order']==['SPINOFF']and proof['spin']['canonical_reference_rebase'][0]['before']==162.108
        assert proof['proxy_cash']['parent_proxy_cash_paid']is False
    assert api.spinoffs.apply_supported_entitlements is primitive and api.runtime.advance is advance


@pytest.mark.parametrize('bad',['foreign_caller','pending_parent','double_child','nonzero_proxy'])
def test_actual_child_observer_caller_role_and_publication_falsifiers(tmp_path,monkeypatch,bad):
    observer,api,run,pub,calls,primitive,advance=actual_observer_fixture(tmp_path,monkeypatch)
    with observer:
        if bad=='foreign_caller':
            observer.current=dict(order=[],spin=None)
            with pytest.raises(ValueError):api.spinoffs.apply_supported_entitlements(SimpleNamespace(),pub.spinoff_distributions,bars=pub.bars,ledger=None,config=None)
        else:
            if bad=='pending_parent':run.state.pending=[dict(security_id=observer.binding['spin']['parent_security_id'])]
            elif bad=='double_child':pub.spinoff_distributions*=2
            else:pub.bars=tuple(replace(v,dividend_per_share=34.68074)if v.ticker=='GE'else v for v in pub.bars)
            with pytest.raises(ValueError):api.runtime.advance(run,pub)
    assert calls==[]and api.spinoffs.apply_supported_entitlements is primitive and api.runtime.advance is advance


def test_retention_three_generations_carries_all_committed_proofs(tmp_path,monkeypatch):
    material,p=material_and_payload();b,before,after,lb,la,audit=synthetics();p['binding']=b
    # Isolate one genuine event to exercise repeated proof-path retention; full
    # five-term selection is independently covered above and by the pure loader.
    material['terms']=[t for t in material['terms']if t['ticker']=='SWAV']
    root=tmp_path/'g1';root.mkdir();out=tmp_path/'g2';out.mkdir();out2=tmp_path/'g3';out2.mkdir()
    for name in(runtime.PAYLOAD,s.MATERIAL,runtime.QUALIFICATION,runtime.ORDINARY_QUALIFICATION):(root/name).write_bytes(b'committed input proof\n')
    child=dict(passed=True,session='2024-04-02',order=['SPINOFF'],spin=s.spin_postcondition(b,before,after,lb,la,audit,10),
        proxy_cash=dict(parent_proxy_cash_accrued=False,parent_proxy_cash_paid=False,child_retained=False))
    (root/runtime.ACTUAL).write_bytes(s.encoded(child))
    ordinary=dict(passed=True,session='2024-05-31',cash=[dict(security_id=material['terms'][0]['security_id'],session='2024-05-31',
        actual_context_call=True,source_only_noop=False,postcondition=dict(quantity=0,nominal_cash=0.))])
    for rel in(Path('actual-future-event-2024-05-31.json'),Path(runtime.RETAINED_OBSERVATION)/'actual-future-event-2024-05-31.json'):
        (root/rel).parent.mkdir(exist_ok=True);(root/rel).write_bytes(s.encoded(ordinary))
    @contextmanager
    def projection():yield SimpleNamespace(payload=p)
    class Projection:
        payload=p
        def __enter__(self):return self
        def __exit__(self,*args):pass
    monkeypatch.setattr(runtime,'retained_activation',lambda root,cp:Projection())
    cp=dict(source_cursor='2024-06-03')
    import system_campaign_ordinary_registry as registry
    original_registry=registry.registrations
    with runtime.retained_context(root,cp,out):assert len(registry.registrations(HERE))==8
    assert registry.registrations is original_registry
    with runtime.retained_context(out,cp,out2):assert len(registry.registrations(HERE))==8
    assert registry.registrations is original_registry
    for path in root.rglob('*'):
        if path.is_file():assert (out2/path.relative_to(root)).read_bytes()==path.read_bytes()
    runtime.review_actual(p,out2,cp)


def test_original_constructor_refuses_unregistered_group_before_scoped_view(monkeypatch):
    import system_campaign_ordinary_registry as registry
    original=registry.registrations;monkeypatch.setattr(registry,'registrations',lambda driver=HERE:original(HERE))
    with pytest.raises(ValueError,match='REGISTERED_GROUP'):s._select_original(record())
    codec,_,subset=s.select_original(record());assert len(codec.catalog['terms'])==len(subset['terms'])==5


def test_registry_view_seven_unchanged_nested_once_and_restored_even_error():
    import system_campaign_ordinary_registry as registry
    original=registry.registrations;before=original(HERE);raw=(HERE/registry.REGISTRY).read_bytes()
    with pytest.raises(RuntimeError):
        with s.registry_context(record())as proof:
            view=registry.registrations(HERE)
            assert view[:7]==before and len(view)==8 and view[-1]==record()['ordinary_activation']['registry_extension']['group']
            assert proof['original_registry_sha256']==s.sha(raw)and proof['financial_authority']is False
            bound=registry.registrations
            with s.registry_context(record()):assert registry.registrations is bound and len(registry.registrations(HERE))==8
            raise RuntimeError('exit guard')
    assert registry.registrations is original and(HERE/registry.REGISTRY).read_bytes()==raw


@pytest.mark.parametrize('bad',['changed','unknown','duplicate','shadow'])
def test_registry_original_group_corruption_and_unknown_entries_refused(monkeypatch,bad):
    import system_campaign_ordinary_registry as registry
    original=registry.registrations;groups=original(HERE)
    if bad=='changed':groups[0]['private_file']='changed.json'
    elif bad=='unknown':groups.append(dict(groups[0],reference_stem='research:system-optimization-002/ordinary-catalog/unknown/1/'))
    elif bad=='duplicate':groups.append(deepcopy(groups[0]))
    else:groups[0]=deepcopy(record()['ordinary_activation']['registry_extension']['group'])
    fake=lambda driver=HERE:deepcopy(groups);monkeypatch.setattr(registry,'registrations',fake)
    with s.registry_context(record()):
        with pytest.raises(ValueError):registry.registrations(HERE)
    assert registry.registrations is fake


def test_registry_old_entries_guard_removal_meaningful(monkeypatch):
    import system_campaign_ordinary_registry as registry
    original=registry.registrations;groups=original(HERE);groups[0]['private_file']='changed.json'
    monkeypatch.setattr(registry,'registrations',lambda driver=HERE:deepcopy(groups))
    with s.registry_context(record()):
        with pytest.raises(ValueError):registry.registrations(HERE)
    mutant=without_guard(s.registry_context,'STANDARD_ALL_SEVEN_ORIGINAL_REGISTRY_ENTRIES_EXACT_UNCHANGED')
    with mutant(record()):assert registry.registrations(HERE)[0]['private_file']=='changed.json'


@dataclass(frozen=True)
class IncompleteTerminal:
    session:str;security_id:str;kind:str;cash_per_share:float|None;delivered_security_id:str|None;delivered_ticker:str|None
    delivered_issuer_id:str|None;exchange_ratio:str|None;cash_in_lieu_price_per_delivered_share:str|None;reference:str;entitlement_aggregation:str
    def completeness(self,quantity):return False,('MISSING_CASH_PER_SHARE',)


def original_hydrator(*,bad=None):
    """Exact original hydrate AST; only frozen inputs/imports/mount are bound."""
    import system_campaign_cash_calendar as calendar
    import system_campaign_ordinary_registry as registry
    raw=Path(calendar.__file__).read_bytes();assert s.sha(raw)=='183c548f7ddf95e277446f9704c5ffa2537ea9807a3305abbecbaae3d4ea262f'
    cls=next(n for n in ast.parse(raw).body if isinstance(n,ast.ClassDef)and n.name=='CashCalendar')
    method=next(n for n in cls.body if isinstance(n,ast.FunctionDef)and n.name=='hydrate')
    source=data('fixtures/five-original-ordinary-fullrows.json');assert source['no_financial_state_or_engine']is True
    rows=deepcopy(source['rows']);native=data('fixtures/five-original-ordinary-native-preimages.json')['native']
    if bad=='fullrow':rows[0]['issuer_id']='CHANGED'
    if bad=='missingrow':rows.pop()
    if bad=='native':native[0]['reference']+='CHANGED'
    actions=SimpleNamespace(terminal={n['session']:(IncompleteTerminal(**n),)for n in native})
    terms=data('system-campaign-unconsumed2024-cash-calendar-terminal-facts.json')['terms']
    dates=sorted({day for t in terms for day in(t['last_trading_session'],t['added']['session'])})
    if bad=='axis':dates.remove(terms[0]['added']['session'])
    def archive_rows(archive,name):
        assert name=='observations-2024.csv.gz'
        assert len(registry.registrations(HERE))==8,'qualified registry must cover hydration, not only construction'
        return deepcopy(rows)
    class Archive:
        def __init__(self,path):assert str(path)=='/frozen/archive/corpus.zip'
        def __enter__(self):return self
        def __exit__(self,*args):pass
    imports=0;mounts=0;body=[]
    for node in method.body:
        if isinstance(node,ast.ImportFrom)and node.module=='research.pooled_input_support':
            body.append(ast.Assign(targets=[ast.Name(id='inputs',ctx=ast.Store())],value=ast.Name(id='inputs_stub',ctx=ast.Load())));imports+=1
        elif isinstance(node,ast.ImportFrom)and node.module=='research.pooled_input_support.bundle':
            body.append(ast.Assign(targets=[ast.Name(id='axis',ctx=ast.Store())],value=ast.Name(id='axis_stub',ctx=ast.Load())));imports+=1
        else:
            if isinstance(node,ast.Expr)and isinstance(node.value,ast.Call)and len(node.value.args)==2 and isinstance(node.value.args[1],ast.Constant)and node.value.args[1].value=='HOSTED_CASH_CALENDAR_HYDRATION_ONLY':
                node.value.args[0]=ast.Constant(True);mounts+=1
            body.append(node)
    assert imports==2 and mounts==1;method.body=body
    ns=dict(vars(calendar),inputs_stub=SimpleNamespace(load_actions=lambda path:actions,_archive_rows=archive_rows),
        axis_stub=lambda:dates,zipfile=SimpleNamespace(ZipFile=Archive))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[method],type_ignores=[])),'<exact-original-hydrate-with-data-only-import-and-mount-bindings>','exec'),ns)
    return ns['hydrate']


def test_original_all_five_hydration_and_collision_check_inside_registry_view(tmp_path):
    root,cp,subset=install_original_inputs(tmp_path);out=tmp_path/'hydrate';out.mkdir()
    with s.registry_context(record()):
        codec,_,subset=s.select_original(record());private=original_hydrator()(codec,cp,root,out)
    assert len(private['source_witnesses'])==5 and private['catalog']['terms']==subset['terms']
    collision=json.loads((out/'cash-calendar-collision-preflight.json').read_bytes())
    assert collision['selected_session']=='2024-03-28'and collision['status']=='DISJOINT_UNCONSUMED'
    assert collision['retained_ordinary_repairs']==10 and collision['requested_events']==5 and collision['conflicts']==[]
    assert {r['ticker']for r in private['source_witnesses']}=={'ALPN','SWAV','DCPH','EVBG','PRFT'}


@pytest.mark.parametrize('bad',['fullrow','missingrow','native','axis','collision'])
def test_original_five_term_hydration_source_native_axis_and_collision_falsifiers(tmp_path,bad):
    root,cp,subset=install_original_inputs(tmp_path);out=tmp_path/'hydrate';out.mkdir()
    if bad=='collision':
        d=cp['repairs'][0];v=json.loads((root/'book/repairs'/d['filename']).read_bytes());v['add'].append(data('system-campaign-unconsumed2024-cash-calendar-terminal-facts.json')['terms'][0]['added'])
        raw=s.encoded(v);d['sha256']=s.sha(raw);d['filename']=d['sha256']+'.json';(root/'book/repairs'/d['filename']).write_bytes(raw)
    with s.registry_context(record()):
        codec,_,_=s.select_original(record())
        with pytest.raises((ValueError,AssertionError)):original_hydrator(bad=bad)(codec,cp,root,out)


@pytest.mark.parametrize('phase',['prepare','review','qualify'])
def test_full_runtime_phases_hold_same_registration_view_and_restore(monkeypatch,phase):
    import system_campaign_ordinary_registry as registry
    original=registry.registrations
    def inside(*args):assert len(registry.registrations(HERE))==8;return 'scoped'
    if phase=='prepare':
        monkeypatch.setattr(runtime,'_prepare',inside);assert runtime.prepare({},Path('.'),'P11')=='scoped'
    elif phase=='review':
        monkeypatch.setattr(runtime,'_review',inside);assert runtime.review({},Path('.'),'P11')=='scoped'
    else:
        monkeypatch.setattr(runtime,'_qualify',inside);monkeypatch.setattr(runtime,'verify_actual_primitive_modules',lambda p:True)
        assert runtime.qualify({},Path('.'),dict(ordinary_material=dict(arm='P11')),None,None)=='scoped'
    assert registry.registrations is original
