"""Factual input and inherited-provenance checks; zero financial replay."""
import ast,json
from pathlib import Path
import pytest
from system_campaign_followup_facts import FollowupFacts
from system_campaign_followup_run import spring_retained,SPRING
from system_campaign_facts import digest,sha

CATALOG=Path(__file__).parents[1]/'system-campaign-followup-terminal-facts.json'


def test_actual_boundaries_and_frozen_successor_identity():
    f=FollowupFacts(CATALOG);avxs,pnk,ks=f.catalog['terms']
    assert avxs['added']['session']=='2018-05-15' and avxs['added']['cash_per_share']==218.
    assert pnk['added']['session']=='2018-10-15' and pnk['added']['cash_per_share']==20.
    assert pnk['added']['exchange_ratio']==.42 and pnk['added']['delivered_issuer_id']=='SEC_CIK:921738'
    assert ks['added']['session']=='2018-11-05' and ks['added']['cash_per_share']==35.
    assert pnk['added']['cash_in_lieu_price_per_delivered_share'] is None


def test_local_hydration_and_consumed_first_day_refuse(monkeypatch,tmp_path):
    monkeypatch.delenv('FULL_SYSTEM_HOSTED',raising=False);f=FollowupFacts(CATALOG);p=tmp_path/'absent.json'
    with pytest.raises(ValueError,match='HOSTED_FOLLOWUP_FACTS_ONLY'):f.hydrate(p)
    f.hydrated_sha='a'*64;f.hydrated_digest=digest(f.catalog)
    with pytest.raises(ValueError,match='FOLLOWUP_ALL_TERMS_UNCONSUMED'):f.overlay({'source_cursor':'2018-05-15'},p)
    assert not p.exists()


def test_actual_boundary_guard_removal_falsifier(tmp_path):
    v=json.loads(CATALOG.read_bytes());v['terms'][0]['added']['session']='2018-05-16'
    p=tmp_path/'wrong-date.json';p.write_text(json.dumps(v))
    with pytest.raises(ValueError,match='FOLLOWUP_EXACT_PRIMARY_TERMS'):FollowupFacts(p)
    tree=ast.parse(Path(FollowupFacts.__init__.__code__.co_filename).read_bytes())
    node=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='FollowupFacts')
    method=next(n for n in node.body if isinstance(n,ast.FunctionDef) and n.name=='__init__')
    method.body=[n for n in method.body if not any(isinstance(x,ast.Constant)
        and x.value=='FOLLOWUP_EXACT_PRIMARY_TERMS' for x in ast.walk(n))]
    scope=dict(FollowupFacts.__init__.__globals__)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),
        '<removed-followup-boundary-guard>','exec'),scope)
    assert scope['FollowupFacts'](p).catalog['terms'][0]['added']['session']=='2018-05-16'


def test_retained_spring_provenance_and_actual_guard_removal(tmp_path):
    driver=tmp_path/'driver';driver.mkdir();old=tmp_path/'old';old.mkdir()
    files={SPRING:driver/'system-campaign-spring-terminal-facts.json',
        'research:system-optimization-002/spring-terminal-compiler/1':driver/'system_campaign_spring_facts.py',
        'research:system-optimization-002/spring-private-terminal-catalog/1':old/'hydrated-spring-terminal-catalog.json'}
    for n,p in enumerate(files.values()):p.write_text(str(n))
    refs=[{'reference':r,'sha256':sha(p.read_bytes())} for r,p in files.items()]
    assert spring_retained(refs,old,driver) and not spring_retained([],old,driver)
    refs[-1]['sha256']='0'*64
    with pytest.raises(ValueError,match='EXACT_RETAINED_SPRING'):spring_retained(refs,old,driver)
    node=next(n for n in ast.parse(Path(spring_retained.__code__.co_filename).read_bytes()).body
        if isinstance(n,ast.FunctionDef) and n.name=='spring_retained')
    node.body=[n for n in node.body if not any(isinstance(x,ast.Constant)
        and x.value=='FOLLOWUP_EXACT_RETAINED_SPRING' for x in ast.walk(n))]
    scope=dict(spring_retained.__globals__)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),
        '<removed-retained-spring-sha-guard>','exec'),scope)
    assert scope['spring_retained'](refs,old,driver)
