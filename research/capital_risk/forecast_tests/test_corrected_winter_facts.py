"""Corrected primary event boundaries and pre-financial fences."""
import ast,json
from pathlib import Path
import pytest
from system_campaign_winter_facts import WinterCash
from system_campaign_facts import digest

CATALOG=Path(__file__).parents[1]/'system-campaign-corrected-winter-facts.json'


def test_complete_primary_boundaries_and_no_unproved_payment():
    facts=WinterCash(CATALOG);terms={v['ticker']:v for v in facts.catalog['terms']}
    assert set(terms)=={'CUDA','SCMP','JUNO','BIVV','CSRA'}
    assert terms['JUNO']['added']['session']=='2018-03-06'
    assert terms['SCMP']['added']['session']=='2018-02-13'
    assert terms['CSRA']['native_session']=='2018-04-03' and terms['CSRA']['added']['session']=='2018-04-04'
    assert all(v['added']['cash_in_lieu_price_per_delivered_share'] is None for v in terms.values())
    assert facts.catalog['AAAP_mandatory_payment_unproven']


def test_local_hydration_refuses_before_access_or_output(monkeypatch,tmp_path):
    monkeypatch.delenv('FULL_SYSTEM_HOSTED',raising=False);target=tmp_path/'not-created.json'
    with pytest.raises(ValueError,match='HOSTED_WINTER_CASH_ONLY'):WinterCash(CATALOG).hydrate(target)
    assert not target.exists()


def test_consumed_earliest_event_refuses_before_financial_import(tmp_path):
    facts=WinterCash(CATALOG);facts.hydrated_sha='a'*64;facts.hydrated_digest=digest(facts.catalog)
    with pytest.raises(ValueError,match='OWN_PRE_EVENT'):facts.overlay({'source_cursor':'2018-02-09'},tmp_path/'not-created')
    assert not (tmp_path/'not-created').exists()


def test_actual_effective_date_guard_removal_falsifier(tmp_path):
    v=json.loads(CATALOG.read_bytes());v['terms'][1]['added']['session']='2018-03-07'
    p=tmp_path/'wrong-date.json';p.write_text(json.dumps(v))
    with pytest.raises(ValueError,match='EXACT_PRIMARY_TERMS'):WinterCash(p)
    tree=ast.parse(Path(WinterCash.__init__.__code__.co_filename).read_bytes())
    node=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='WinterCash')
    method=next(n for n in node.body if isinstance(n,ast.FunctionDef) and n.name=='__init__')
    method.body=[n for n in method.body if not any(isinstance(x,ast.Constant)
                 and x.value=='WINTER_CASH_EXACT_PRIMARY_TERMS' for x in ast.walk(n))]
    scope=dict(WinterCash.__init__.__globals__)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),
                 '<removed-effective-date-guard>','exec'),scope)
    assert scope['WinterCash'](p).catalog['terms'][1]['added']['session']=='2018-03-07'
