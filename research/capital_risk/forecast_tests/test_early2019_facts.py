"""Exact early2019 terms, own causal boundary and hosted-only handoff."""
import ast,json
from pathlib import Path
from types import SimpleNamespace
import pytest
from system_campaign_early2019_facts import Early2019Facts
from system_campaign_facts import digest

ROOT=Path(__file__).parents[1]
CATALOG=ROOT/'system-campaign-early2019-terminal-facts.json'


def test_stock_conversion_and_distinct_historical_cash_securities():
    terms=Early2019Facts(CATALOG).catalog['terms'];dm,loxo,ahl=terms
    assert dm['added']['kind']=='CONVERSION' and dm['added']['cash_per_share'] is None
    assert dm['added']['exchange_ratio']==.2492 and dm['added']['delivered_security_id']=='1100081557843370397'
    assert dm['added']['session']=='2019-01-28' and loxo['added']['cash_per_share']==235.
    assert loxo['native_session']==loxo['added']['session']=='2019-02-15'
    assert ahl['security_id']=='1144531901989620662' and ahl['added']['cash_per_share']==42.75


@pytest.mark.parametrize('index,field,bad',[(0,'cash_per_share',17.25),(0,'session','2019-01-25'),
    (0,'exchange_ratio',.2468),(1,'cash_per_share',234.),(2,'security_id','536735966830578103')])
def test_invented_cash_wrong_boundary_or_relisted_identity_refused(tmp_path,index,field,bad):
    v=json.loads(CATALOG.read_bytes());v['terms'][index]['added'][field]=bad;p=tmp_path/'bad';p.write_text(json.dumps(v))
    with pytest.raises(ValueError,match='EXACT_PRIMARY_TERMS'):Early2019Facts(p)


def test_actual_primary_terms_guard_removal(tmp_path):
    v=json.loads(CATALOG.read_bytes());v['terms'][0]['added']['cash_per_share']=17.25;p=tmp_path/'bad';p.write_text(json.dumps(v))
    with pytest.raises(ValueError,match='EXACT_PRIMARY_TERMS'):Early2019Facts(p)
    node=next(n for n in ast.parse(Path(Early2019Facts.__init__.__code__.co_filename).read_bytes()).body if isinstance(n,ast.ClassDef))
    method=next(n for n in node.body if isinstance(n,ast.FunctionDef) and n.name=='__init__')
    method.body=[n for n in method.body if not any(isinstance(x,ast.Constant) and x.value=='EARLY2019_EXACT_PRIMARY_TERMS' for x in ast.walk(n))]
    scope=dict(Early2019Facts.__init__.__globals__)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'<removed-native-cash-and-conversion-guard>','exec'),scope)
    assert scope['Early2019Facts'](p).catalog['terms'][0]['added']['cash_per_share']==17.25


def test_no_local_financial_operation_or_consumed_input(monkeypatch,tmp_path):
    monkeypatch.delenv('FULL_SYSTEM_HOSTED',raising=False);f=Early2019Facts(CATALOG);p=tmp_path/'absent'
    with pytest.raises(ValueError,match='HOSTED_EARLY2019'):f.hydrate(p)
    f.hydrated_sha='a'*64;f.hydrated_digest=digest(f.catalog)
    with pytest.raises(ValueError,match='ALL_TERMS_UNCONSUMED'):f.overlay({'source_cursor':'2019-01-25'},p)
    from system_campaign_early2019_run import run
    with pytest.raises(ValueError,match='HOSTED'):run(p,Path('/absent'),{})
    assert not p.exists()


def test_request_exact_own_december_predecessors_and_actual_main_handoff(monkeypatch,tmp_path):
    import system_campaign_early2019_job as job
    request=ROOT/'system-campaign-early2019-request.json';v=json.loads(request.read_bytes());assert v==job.expected_request(v['predecessors_file'])
    arms=json.loads((ROOT/v['predecessors_file']).read_bytes())['arms'];assert set(arms)=={'P01','P02','P07'}
    assert all(s['selected_session']=='2018-12-31' and s['run_id']==40991050898 for s in arms.values())
    monkeypatch.setattr(job,'check_context',lambda env:None);monkeypatch.setenv('GITHUB_RUN_ATTEMPT','1')
    with pytest.raises(FileNotFoundError):job.main(SimpleNamespace(request=request,staging=tmp_path/'absent',arm='P01'))


def test_source_closure_and_no_active_arm_in_workflow():
    from forecast_tests.test_basis_job_sources import dependencies
    from system_campaign_early2019_job import SOURCES
    from system_campaign_numeric_job import SOURCES as NUMERIC
    assert not dependencies(SOURCES)-set(SOURCES) and not dependencies(NUMERIC)-set(NUMERIC)
    workflow=(ROOT.parents[1]/'.github/workflows/capital-system-early2019-factual-suffix.yml').read_text()
    assert 'arm: [P01, P02, P07]' in workflow and 'P04' not in workflow and 'P00' not in workflow
