"""Cash metadata and pre-financial fences; no historical financial execution."""
import ast,copy,json
from pathlib import Path
import pytest
from system_campaign_march_facts import MarchCash
from system_campaign_facts import digest

CATALOG=Path(__file__).parents[1]/'system-campaign-march-cash-facts.json'


def test_primary_dates_terms_no_quote_and_no_aaap_payment():
    facts=MarchCash(CATALOG);terms={v['ticker']:v for v in facts.catalog['terms']}
    assert set(terms)=={'CUDA','JUNO','BIVV'}
    assert terms['CUDA']['native_session']=='2018-02-09' and terms['CUDA']['added']['session']=='2018-02-12'
    assert terms['JUNO']['native_session']=='2018-03-05' and terms['JUNO']['added']['session']=='2018-03-07'
    assert all(v['added']['delivered_security_id'] is None for v in terms.values())
    assert facts.catalog['AAAP_mandatory_payment_unproven']


def test_local_hydration_refuses_before_input_access_or_output(monkeypatch,tmp_path):
    monkeypatch.delenv('FULL_SYSTEM_HOSTED',raising=False);facts=MarchCash(CATALOG)
    target=tmp_path/'not-created.json'
    with pytest.raises(ValueError,match='HOSTED_MARCH_CASH_ONLY'):facts.hydrate(target)
    assert not target.exists()


def test_consumed_earliest_event_refuses_before_financial_import(tmp_path):
    facts=MarchCash(CATALOG);facts.hydrated_sha='a'*64;facts.hydrated_digest=digest(facts.catalog)
    with pytest.raises(ValueError,match='OWN_PRE_EVENT'):
        facts.overlay({'source_cursor':'2018-02-09'},tmp_path/'not-created.json')
    assert not (tmp_path/'not-created.json').exists()


def test_actual_cash_term_guard_removal_falsifier(tmp_path):
    v=json.loads(CATALOG.read_bytes());v['terms'][1]['added']['cash_per_share']=88.
    p=tmp_path/'wrong-cash.json';p.write_text(json.dumps(v))
    with pytest.raises(ValueError,match='EXACT_PRIMARY_TERMS'):MarchCash(p)
    tree=ast.parse(Path(MarchCash.__init__.__code__.co_filename).read_bytes())
    node=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='MarchCash')
    method=next(n for n in node.body if isinstance(n,ast.FunctionDef) and n.name=='__init__')
    method.body=[n for n in method.body if not any(isinstance(x,ast.Constant)
                 and x.value=='MARCH_CASH_EXACT_PRIMARY_TERMS' for x in ast.walk(n))]
    scope=dict(MarchCash.__init__.__globals__)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),
                 '<removed-cash-term-guard>','exec'),scope)
    assert scope['MarchCash'](p).catalog['terms'][1]['added']['cash_per_share']==88.
