"""Exact factual metadata and pre-import refusals; no financial replay."""
import ast,json
from pathlib import Path
import pytest
from system_campaign_tgi_facts import TgiCash
from system_campaign_facts import digest

CATALOG=Path(__file__).parents[1]/'system-campaign-tgi-cash-facts.json'


def test_cash_only_boundary_no_proxy():
    f=TgiCash(CATALOG);t,=f.catalog['terms'];a=t['added']
    assert t['native_session']=='2025-07-24' and a['session']=='2025-07-25'
    assert a['cash_per_share']==26. and a['kind']=='CASH_MERGER'
    assert a['exchange_ratio'] is None and a['cash_in_lieu_price_per_delivered_share'] is None


def test_local_hydration_refuses_before_any_output(monkeypatch,tmp_path):
    monkeypatch.delenv('FULL_SYSTEM_HOSTED',raising=False);p=tmp_path/'absent.json'
    with pytest.raises(ValueError,match='HOSTED_TGI_ONLY'):TgiCash(CATALOG).hydrate(p)
    assert not p.exists()


def test_consumed_native_day_refuses_before_financial_import(tmp_path):
    f=TgiCash(CATALOG);f.hydrated_sha='a'*64;f.hydrated_digest=digest(f.catalog);p=tmp_path/'absent.json'
    with pytest.raises(ValueError,match='TGI_OWN_PRE_EVENT'):f.overlay({'source_cursor':'2025-07-24'},p)
    assert not p.exists()


def test_actual_next_session_guard_removal_falsifier(tmp_path):
    v=json.loads(CATALOG.read_bytes());v['terms'][0]['added']['session']='2025-07-24'
    p=tmp_path/'wrong-date.json';p.write_text(json.dumps(v))
    with pytest.raises(ValueError,match='TGI_EXACT_PRIMARY_TERMS'):TgiCash(p)
    tree=ast.parse(Path(TgiCash.__init__.__code__.co_filename).read_bytes())
    node=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='TgiCash')
    method=next(n for n in node.body if isinstance(n,ast.FunctionDef) and n.name=='__init__')
    method.body=[n for n in method.body if not any(isinstance(x,ast.Constant)
        and x.value=='TGI_EXACT_PRIMARY_TERMS' for x in ast.walk(n))]
    scope=dict(TgiCash.__init__.__globals__)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),
        '<removed-tgi-boundary-guard>','exec'),scope)
    assert scope['TgiCash'](p).catalog['terms'][0]['added']['session']=='2025-07-24'
