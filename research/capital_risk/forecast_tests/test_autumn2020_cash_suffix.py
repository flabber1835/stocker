"""Factual compiler and predecessor retention; canonical cases remain hosted."""
import ast
import inspect
import json
from pathlib import Path
import pytest
import system_campaign_autumn2020_cash_facts as module

PATH=Path(__file__).parents[1]/'system-campaign-autumn2020-cash-terminal-facts.json'


@pytest.mark.parametrize('index,field,value',[(0,'cash_per_share',52.),(1,'session','2020-10-12'),
    (2,'session','2020-10-26'),(3,'cash_per_share',224.),(4,'session','2021-02-12'),
    (0,'kind','WRITE_OFF'),(4,'entitlement_aggregation','VOLUNTARY')])
def test_incorrect_common_cash_or_administrative_date_refuses(tmp_path,index,field,value):
    c=json.loads(PATH.read_bytes());c['terms'][index]['added'][field]=value
    p=tmp_path/'bad.json';p.write_text(json.dumps(c))
    with pytest.raises(ValueError,match='EXACT_MANDATORY_COMMON_SHARE_TERMS'):module.CashCompletionFacts(p)


def test_exact_five_preopen_events_preserve_last_trading_days():
    c=module.CashCompletionFacts(PATH).catalog['terms']
    assert len(c)==5 and [(t['ticker'],t['added']['session']) for t in c]==[
        ('MNTA','2020-10-01'),('AIMT','2020-10-13'),('IMMU','2020-10-23'),
        ('MYOK','2020-11-17'),('VRTU','2021-02-11')]
    assert all(t['native_session']==t['last_trading_session']<t['added']['session'] for t in c)


@pytest.mark.parametrize('index',range(5))
def test_consumed_date_refuses_before_canonical_import(tmp_path,index):
    obj=module.CashCompletionFacts(PATH);obj.hydrated_sha='synthetic';obj.hydrated_digest=module.digest(obj.catalog)
    with pytest.raises(ValueError,match='ALL_DATES_UNCONSUMED'):
        obj.overlay(dict(source_cursor=obj.catalog['terms'][index]['native_session']),tmp_path/'bad.json')
    assert not (tmp_path/'bad.json').exists()


def test_source_witness_upgrade_refuses_and_actual_guard_removal_is_detected():
    row=dict(session='2020-09-29',security_id='source',ticker='MNTA',issuer_id='SEC_UNKNOWN:source',security_type_eligible='0')
    witness={**row,'source_observation_sha256':module.digest(row)};module.require_witness(row,witness)
    bad={**witness,'issuer_id':'SEC_CIK:1235010','security_type_eligible':'1'}
    with pytest.raises(ValueError,match='FROZEN_IDENTITY_WITNESS'):module.require_witness(row,bad)
    node=ast.parse(inspect.getsource(module.require_witness)).body[0];node.body=[ast.Pass()]
    scope=dict(module.__dict__);exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'<actual-guard-removed>','exec'),scope)
    scope[node.name](row,bad)


@pytest.mark.parametrize('mutate',[False,True])
def test_retained_spring_compiler_cannot_change(tmp_path,monkeypatch,mutate):
    import system_campaign_spring2020_cash_facts as old_module
    old=tmp_path/'old';(old/'book/repairs').mkdir(parents=True);out=tmp_path/'out';out.mkdir();driver=tmp_path/'driver';driver.mkdir()
    (driver/'system-campaign-spring2020-cash-terminal-facts.json').write_bytes(b'catalog')
    (driver/'system_campaign_spring2020_cash_facts.py').write_bytes(b'compiler')
    (old/'hydrated-spring2020-cash-terminal-catalog.json').write_bytes(b'witness')
    refs=[dict(reference=r,sha256=module.sha(b)) for r,b in (
        (old_module.CATALOG,b'catalog'),(old_module.COMPILER,b'compiler'),(old_module.HYDRATED,b'witness'))]
    if mutate:refs[1]['sha256']='0'*64
    raw=json.dumps(dict(source_evidence=refs)).encode();h=module.sha(raw)
    (old/'book/repairs'/(h+'.json')).write_bytes(raw)
    monkeypatch.setattr(module,'Path',lambda value:driver/Path(value).name if str(value).startswith('/driver/') else Path(value))
    if mutate:
        with pytest.raises(ValueError,match='EXACT_COMMITTED_SPRING_CASH_FACTS'):
            module.preserve_spring_cash(dict(repairs=[dict(filename=h+'.json',sha256=h)]),old,out)
    else:
        module.preserve_spring_cash(dict(repairs=[dict(filename=h+'.json',sha256=h)]),old,out)
        assert (out/'hydrated-spring2020-cash-terminal-catalog.json').read_bytes()==b'witness'


@pytest.mark.parametrize('mutate',[False,True])
def test_new_group_basis_exact_three_commitments(tmp_path,monkeypatch,mutate):
    import system_campaign_uncertainty_basis as basis
    root=tmp_path/'evidence';(root/'book/repairs').mkdir(parents=True);driver=tmp_path/'driver';driver.mkdir()
    (driver/'system-campaign-autumn2020-cash-terminal-facts.json').write_bytes(b'catalog')
    (driver/'system_campaign_autumn2020_cash_facts.py').write_bytes(b'compiler')
    (root/'hydrated-autumn2020-cash-terminal-catalog.json').write_bytes(b'witness')
    refs=[dict(reference=r,sha256=module.sha(b)) for r,b in ((module.CATALOG,b'catalog'),(module.COMPILER,b'compiler'),(module.HYDRATED,b'witness'))]
    if mutate:refs[1]['sha256']='0'*64
    docs=[dict(schema='terminal-repair/1',source_evidence=refs),
          dict(schema='research.leadership-uncertainty-input/1',predecessor_checkpoint_sha256='0'*64,source_evidence=[])]
    cp=dict(repairs=[])
    for doc in docs:
        raw=json.dumps(doc).encode();h=module.sha(raw);(root/'book/repairs'/(h+'.json')).write_bytes(raw)
        cp['repairs'].append(dict(filename=h+'.json',sha256=h))
    monkeypatch.setattr(basis,'validate_input_commitment',lambda *a:'existing-model')
    monkeypatch.setattr(basis,'ordinary_basis',lambda *a:('0'*64,dict(declared_fact_compilers={'old':'0'*64})))
    monkeypatch.setattr(basis,'Path',lambda value:driver if value=='/driver' else Path(value))
    if mutate:
        with pytest.raises(ValueError,match='AUTUMN2020_CASH_FACTUAL_COMMITMENTS'):basis.basis(root,cp)
    else:
        _,v=basis.basis(root,cp)
        assert set(v['factual_semantics']['declared_fact_compilers'])=={'old',module.CATALOG,module.COMPILER,module.HYDRATED}
