"""Metadata, source reuse and independent arithmetic only; no canonical execution."""
import ast
from copy import deepcopy
from fractions import Fraction
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import system_campaign_pxd_basis as basis
import system_campaign_pxd_facts as facts
import system_campaign_pxd_gate as gate
import system_campaign_pxd_review as review


def document():
    return json.loads((facts.HERE/facts.CONTRACT).read_bytes())


def test_exact_contract_sources_and_reused_bodies_compile_without_execution():
    value=facts.contract()
    assert len(value['inherited_sources'])==263
    assert value['event']['added']['exchange_ratio']=='2.3234'
    assert len(facts.IMPLEMENTATIONS)==6 and all((facts.HERE/n).is_file() for n in facts.IMPLEMENTATIONS)
    hydration=facts.copy_body(facts.original.hydrate,contract=facts.contract,
        validate_payload=facts.validate_payload,PRIVATE=facts.PRIVATE)
    assert hydration.__code__ is facts.original.hydrate.__code__
    gate.qualification_body();review.review_body()


@pytest.mark.parametrize('field,value',[('exchange_ratio',2.3234),('exchange_ratio','25.4503'),
    ('cash_per_share',0.),('cash_in_lieu_price_per_delivered_share',116.),
    ('delivered_issuer_id','SEC_CIK:1038357'),('kind','CASH_PLUS_STOCK')])
def test_wrong_cash_ratio_note_terms_or_delivery_refuse(field,value):
    doc=document();doc['event']['added'][field]=value
    with pytest.raises(ValueError):facts.validate_contract(doc)


def test_native_hash_guard_removal_falsifier():
    doc=document();doc['event']['native']['reference']='wrong native preimage'
    doc['event']['native_term_sha256']=facts.digest(doc['event']['native'])
    with pytest.raises(ValueError,match='EXACT_INCOMPLETE_NATIVE_CANONICAL_DICTIONARY'):
        facts.validate_contract(doc)
    node,=[n for n in ast.parse(Path(facts.__file__).read_bytes()).body
           if isinstance(n,ast.FunctionDef) and n.name=='validate_contract']
    removed=[]
    for n in node.body:
        if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and any(
            isinstance(a,ast.Constant) and a.value=='PXD_FACTS_EXACT_INCOMPLETE_NATIVE_CANONICAL_DICTIONARY'
            for a in n.value.args):removed.append(n)
    assert len(removed)==1
    node.body=[n for n in node.body if n not in removed]
    namespace=dict(vars(facts))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),
        '<actual-native-preimage-guard-removed>','exec'),namespace)
    assert namespace['validate_contract'](doc)==doc


def test_source_only_provider_summary_cannot_omit_physical_counterparty_row():
    doc=document();provider=doc['provider_rows_proof']
    assert provider['physical_rows_selected']==3
    provider['selected_row_sha256']=provider['selected_row_sha256'][1:]
    provider['physical_rows_selected']=2
    with pytest.raises(ValueError,match='COMPLETE_PHYSICAL_SOURCE_AND_COUNTERPARTY_EVIDENCE'):
        facts.validate_contract(doc)
    node,=[n for n in ast.parse(Path(facts.__file__).read_bytes()).body
           if isinstance(n,ast.FunctionDef) and n.name=='validate_contract']
    removed=[n for n in node.body if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call)
        and any(isinstance(a,ast.Constant) and a.value=='PXD_FACTS_COMPLETE_PHYSICAL_SOURCE_AND_COUNTERPARTY_EVIDENCE'
            for a in n.value.args)]
    assert len(removed)==1;node.body=[n for n in node.body if n not in removed]
    namespace=dict(vars(facts))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),
        '<actual-counterparty-completeness-guard-removed>','exec'),namespace)
    assert namespace['validate_contract'](doc)==doc


def descriptors(tmp_path,pxd=True):
    four=basis.previous.previous.previous.original_preflight
    schemas=four.MODELS|{basis.previous.previous.previous.SCHEMA,basis.previous.previous.SCHEMA,
                        basis.previous.SCHEMA,'terminal-repair/1'}
    if pxd:schemas|={basis.SCHEMA}
    directory=tmp_path/'book/repairs';directory.mkdir(parents=True)
    cp=dict(base={'inert':True},repairs=[],run={})
    for schema in sorted(schemas):
        raw=json.dumps(dict(schema=schema)).encode();h=facts.sha(raw)
        descriptor=dict(filename=h+'.json',sha256=h)
        (directory/descriptor['filename']).write_bytes(raw);cp['repairs'].append(descriptor)
    cp['run']['input_sha256']=facts.digest(dict(base=cp['base'],repairs=cp['repairs']))
    return cp


@pytest.mark.parametrize('pxd',[False,True])
def test_all_seven_or_eight_real_descriptors_retained(tmp_path,pxd):
    cp=descriptors(tmp_path,pxd);old=deepcopy(cp)
    result=basis.documents(tmp_path,cp)
    assert len(result)==8+int(pxd) and cp==old
    assert len({v['schema'] for _,v in result})==len(result)


@pytest.mark.parametrize('change',['unknown','body','input','filename','duplicate'])
def test_no_hidden_input_projection_or_undeclared_bytes(tmp_path,change):
    cp=descriptors(tmp_path);descriptor=cp['repairs'][0]
    if change=='unknown':
        raw=json.dumps(dict(schema='undeclared/1')).encode();h=facts.sha(raw)
        descriptor.update(filename=h+'.json',sha256=h)
        (tmp_path/'book/repairs'/descriptor['filename']).write_bytes(raw)
    elif change=='body':(tmp_path/'book/repairs'/descriptor['filename']).write_bytes(b'changed')
    elif change=='input':cp['run']['input_sha256']='0'*64
    elif change=='filename':descriptor['filename']='other.json'
    else:
        descriptor=next(d for d in cp['repairs'] if json.loads(
            (tmp_path/'book/repairs'/d['filename']).read_bytes())['schema']==basis.SCHEMA)
        cp['repairs'].append(deepcopy(descriptor))
    if change!='input':cp['run']['input_sha256']=facts.digest(dict(base=cp['base'],repairs=cp['repairs']))
    with pytest.raises(ValueError):basis.documents(tmp_path,cp)


def arithmetic():
    expected=float(Fraction('2.3234')*Fraction('116')*Fraction('101')/Fraction('269.62'))
    row=dict(session='2024-05-03',state_sha256='after',input_sha256='inert-input')
    certificate=dict(session='2024-05-03',next_state_sha256='after',input_sha256='inert-input',
        material=dict(rows=[dict(security_id='276044719892003870',current=[expected,expected])]))
    return expected,certificate,row,('2024-05-02',269.62,101.)


def test_actual_ordinary_stock_notional_uses_exact_ratio_and_source_price_domain():
    expected,c,row,anchor=arithmetic()
    actual=review.require_closing_notional(c,row,'276044719892003870',anchor,116.,'2024-05-03','2024-05-02')
    assert actual['signal_consideration']==expected


@pytest.mark.parametrize('change',['economic','input','state','date','anchor','delivery'])
def test_mutated_committed_economic_or_chain_value_refuses(change):
    _,c,row,anchor=arithmetic();delivered=116.
    if change=='economic':c['material']['rows'][0]['current'][0]+=.01
    elif change=='input':c['input_sha256']='other'
    elif change=='state':row['state_sha256']='other'
    elif change=='date':c['session']='2024-05-06'
    elif change=='anchor':anchor=('2024-05-01',269.62,101.)
    else:delivered=115.
    with pytest.raises(ValueError):review.require_closing_notional(
        c,row,'276044719892003870',anchor,delivered,'2024-05-03','2024-05-02')


def test_new_scope_cannot_change_old_seven_model_or_factual_semantics(monkeypatch):
    doc=document();obj=SimpleNamespace(canonical_repair=dict(suppress=[dict(session='2024-05-02',
        security_id=doc['event']['security_id'],term_sha256='f'*64)],add=[doc['event']['added']]))
    before=dict(schema='inert-old',factual_semantics=dict(suppress=[],add=[],declared_fact_compilers={}),
        factual_semantics_sha256='inert',model_semantics=[dict(identity=i,value=i) for i in range(7)])
    new_scope={'inert_new_scope':True};monkeypatch.setattr(basis,'evidence',lambda root:[])
    monkeypatch.setattr(basis,'common_scope',lambda root:new_scope)
    after=basis.append_semantics(before,obj,{},new_scope)
    assert basis.require_exact_delta(before,after,obj,Path('.'))
    changed=deepcopy(after);changed['model_semantics'][0]['value']+=1
    with pytest.raises(ValueError):basis.require_exact_delta(before,changed,obj,Path('.'))
    changed=deepcopy(after);changed['factual_semantics']['add'][0]['exchange_ratio']='2.32'
    with pytest.raises(ValueError):basis.require_exact_delta(before,changed,obj,Path('.'))
