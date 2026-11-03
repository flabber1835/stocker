"""Factual guards and serialization only; actual canonical probes run hosted."""
import ast
import hashlib
import inspect
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
import system_campaign_spring2020_cash_facts as module


def catalog():
    return json.loads((Path(__file__).parents[1]/'system-campaign-spring2020-cash-terminal-facts.json').read_bytes())


@pytest.mark.parametrize('index,field,value',[(0,'cash_per_share',23.8),(1,'session','2020-04-24'),
    (2,'cash_per_share',136.),(0,'kind','WRITE_OFF'),(1,'entitlement_aggregation','VOLUNTARY'),
    (2,'delivered_security_id','invented')])
def test_wrong_cash_timing_or_nonmandatory_term_refuses(tmp_path,index,field,value):
    c=catalog();c['terms'][index]['added'][field]=value;p=tmp_path/'facts.json';p.write_text(json.dumps(c))
    with pytest.raises(ValueError,match='EXACT_MANDATORY_COMMON_SHARE_TERMS'):module.CashCompletionFacts(p)


def test_same_date_CY_and_shifted_MLNX_WBC_are_explicit():
    obj=module.CashCompletionFacts(Path(__file__).parents[1]/'system-campaign-spring2020-cash-terminal-facts.json')
    c=obj.catalog['terms']
    assert c[0]['native_session']==c[0]['added']['session']=='2020-04-16'
    assert [(t['native_session'],t['added']['session']) for t in c[1:]]==[('2020-04-24','2020-04-27'),('2020-05-28','2020-05-29')]


def test_witness_metadata_upgrade_and_real_guard_removal():
    row=dict(session='2020-04-15',security_id='source',ticker='CY',issuer_id='SEC_UNKNOWN:source',security_type_eligible='0')
    witness={**row,'source_observation_sha256':module.digest(row)}
    module.require_witness(row,witness)
    bad={**witness,'security_type_eligible':'1','issuer_id':'SEC_CIK:791915'}
    with pytest.raises(ValueError,match='FROZEN_IDENTITY_WITNESS'):module.require_witness(row,bad)
    node=ast.parse(inspect.getsource(module.require_witness)).body[0];node.body=[ast.Pass()]
    scope=dict(module.__dict__);exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'<actual-witness-guard-removed>','exec'),scope)
    scope[node.name](row,bad)


@pytest.mark.parametrize('cursor',('2020-04-16','2020-04-24','2020-05-28'))
def test_no_catalog_may_reapply_consumed_dates_before_canonical_import(tmp_path,cursor):
    path=Path(__file__).parents[1]/'system-campaign-spring2020-cash-terminal-facts.json';obj=module.CashCompletionFacts(path)
    obj.hydrated_sha='synthetic';obj.hydrated_digest=module.digest(obj.catalog)
    with pytest.raises(ValueError,match='ALL_DATES_UNCONSUMED'):obj.overlay(dict(source_cursor=cursor),tmp_path/'forbidden.json')
    assert not (tmp_path/'forbidden.json').exists()


@pytest.mark.parametrize('mutate',[False,True])
def test_committed_sprint_bytes_and_all_three_commitments_are_required(tmp_path,monkeypatch,mutate):
    from system_campaign_sprint_facts import CATALOG,COMPILER,HYDRATED
    old=tmp_path/'old';(old/'book/repairs').mkdir(parents=True);out=tmp_path/'out';out.mkdir();driver=tmp_path/'driver';driver.mkdir()
    (driver/'system-campaign-sprint-terminal-facts.json').write_bytes(b'catalog');(driver/'system_campaign_sprint_facts.py').write_bytes(b'compiler')
    (old/'hydrated-sprint-terminal-catalog.json').write_bytes(b'witness')
    refs=[dict(reference=r,sha256=module.sha(b)) for r,b in ((CATALOG,b'catalog'),(COMPILER,b'compiler'),(HYDRATED,b'witness'))]
    if mutate:refs[1]['sha256']='0'*64
    raw=json.dumps(dict(source_evidence=refs)).encode();h=module.sha(raw);(old/'book/repairs'/(h+'.json')).write_bytes(raw)
    monkeypatch.setattr(module,'Path',lambda value:driver/Path(value).name if str(value).startswith('/driver/') else Path(value))
    if mutate:
        with pytest.raises(ValueError,match='EXACT_COMMITTED_SPRINT_FACTS'):module.preserve_sprint(dict(repairs=[dict(filename=h+'.json',sha256=h)]),old,out)
    else:
        module.preserve_sprint(dict(repairs=[dict(filename=h+'.json',sha256=h)]),old,out)
        assert (out/'hydrated-sprint-terminal-catalog.json').read_bytes()==b'witness'


@pytest.mark.parametrize('mutate',[False,True])
def test_new_group_basis_binds_exact_hyphenated_catalog_and_python_compiler(tmp_path,monkeypatch,mutate):
    import system_campaign_uncertainty_basis as basis
    root=tmp_path/'evidence';(root/'book/repairs').mkdir(parents=True);driver=tmp_path/'driver';driver.mkdir()
    (driver/'system-campaign-spring2020-cash-terminal-facts.json').write_bytes(b'catalog')
    (driver/'system_campaign_spring2020_cash_facts.py').write_bytes(b'compiler')
    (root/'hydrated-spring2020-cash-terminal-catalog.json').write_bytes(b'witness')
    refs=[dict(reference=r,sha256=module.sha(b)) for r,b in ((module.CATALOG,b'catalog'),(module.COMPILER,b'compiler'),(module.HYDRATED,b'witness'))]
    if mutate:refs[1]['sha256']='0'*64
    docs=[dict(schema='terminal-repair/1',source_evidence=refs),dict(schema='research.leadership-uncertainty-input/1',predecessor_checkpoint_sha256='0'*64,source_evidence=[])]
    cp=dict(repairs=[])
    for doc in docs:
        raw=json.dumps(doc).encode();h=module.sha(raw);(root/'book/repairs'/(h+'.json')).write_bytes(raw);cp['repairs'].append(dict(filename=h+'.json',sha256=h))
    monkeypatch.setattr(basis,'validate_input_commitment',lambda *a:'existing-model')
    monkeypatch.setattr(basis,'ordinary_basis',lambda *a:('0'*64,dict(declared_fact_compilers={'old':'0'*64})))
    monkeypatch.setattr(basis,'Path',lambda value:driver if value=='/driver' else Path(value))
    if mutate:
        with pytest.raises(ValueError,match='SPRING2020_CASH_FACTUAL_COMMITMENTS'):basis.basis(root,cp)
    else:
        _,v=basis.basis(root,cp);assert set(v['factual_semantics']['declared_fact_compilers'])=={'old',module.CATALOG,module.COMPILER,module.HYDRATED}
