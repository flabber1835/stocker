"""Factual metadata and refusal tests; no historical financial calculation."""
import ast,json
from pathlib import Path
import pytest
from system_campaign_spring_facts import SpringFacts
from system_campaign_facts import digest

CATALOG=Path(__file__).parents[1]/'system-campaign-spring-terminal-facts.json'


def test_mandatory_cash_stock_boundary_and_declared_private_proxy():
    f=SpringFacts(CATALOG);buff,mule=f.catalog['terms']
    assert buff['native_session']==buff['added']['session']=='2018-04-24'
    assert mule['native_session']=='2018-05-01' and mule['added']['session']=='2018-05-02'
    assert mule['added']['kind']=='CASH_PLUS_STOCK' and mule['added']['cash_per_share']==36.
    assert mule['added']['exchange_ratio']==.0711 and mule['added']['cash_in_lieu_price_per_delivered_share'] is None
    assert len(mule['proxy']['source_observation_sha256'])==64
    tree=ast.parse((CATALOG.parent/'system_campaign_spring_run.py').read_bytes())
    constants={n.targets[0].id:ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign)
        and isinstance(n.targets[0],ast.Name) and n.targets[0].id in ('WINTER','SPRING')}
    assert constants=={'WINTER':'research:system-optimization-002/corrected-winter-cash-catalog/1',
        'SPRING':'research:system-optimization-002/spring-terminal-catalog/1'}


def test_hydration_is_hosted_only(monkeypatch,tmp_path):
    monkeypatch.delenv('FULL_SYSTEM_HOSTED',raising=False);target=tmp_path/'absent.json'
    with pytest.raises(ValueError,match='HOSTED_SPRING_FACTS_ONLY'):SpringFacts(CATALOG).hydrate(target)
    assert not target.exists()


def test_consumed_first_event_refuses_before_financial_import(tmp_path):
    f=SpringFacts(CATALOG);f.hydrated_sha='a'*64;f.hydrated_digest=digest(f.catalog)
    target=tmp_path/'absent.json'
    with pytest.raises(ValueError,match='SPRING_ALL_TERMS_UNCONSUMED'):f.overlay({'source_cursor':'2018-04-24'},target)
    assert not target.exists()


def test_actual_date_guard_removal_falsifier(tmp_path):
    v=json.loads(CATALOG.read_bytes());v['terms'][1]['added']['session']='2018-05-01'
    p=tmp_path/'wrong-date.json';p.write_text(json.dumps(v))
    with pytest.raises(ValueError,match='SPRING_EXACT_PRIMARY_TERMS'):SpringFacts(p)
    tree=ast.parse(Path(SpringFacts.__init__.__code__.co_filename).read_bytes())
    node=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='SpringFacts')
    method=next(n for n in node.body if isinstance(n,ast.FunctionDef) and n.name=='__init__')
    method.body=[n for n in method.body if not any(isinstance(x,ast.Constant)
        and x.value=='SPRING_EXACT_PRIMARY_TERMS' for x in ast.walk(n))]
    scope=dict(SpringFacts.__init__.__globals__)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),
        '<removed-spring-date-guard>','exec'),scope)
    assert scope['SpringFacts'](p).catalog['terms'][1]['added']['session']=='2018-05-01'
