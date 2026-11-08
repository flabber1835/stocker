"""P02 selection, exact mandatory cash and causal input boundaries."""
import ast,json
from pathlib import Path
from types import SimpleNamespace
import pytest
from system_campaign_array_facts import ArrayFacts
from system_campaign_facts import digest

ROOT=Path(__file__).parents[1]
CATALOG=ROOT/'system-campaign-array-terminal-facts.json'


def test_mandatory_same_day_cash_no_stock_or_metadata_upgrade():
    f=ArrayFacts(CATALOG);t=f.catalog['terms'][0]
    assert t['added']['cash_per_share']==48. and t['native_session']==t['added']['session']=='2019-07-30'
    assert t['security_id']=='331866698645518730' and t['added']['delivered_security_id'] is None
    assert f.catalog['identity_witness']['issuer_id']=='SEC_UNKNOWN:331866698645518730'


@pytest.mark.parametrize('field,bad',[('cash_per_share',49.),('session','2019-07-31'),
    ('security_id','1820721'),('exchange_ratio',1.),('cash_in_lieu_price_per_delivered_share',0.)])
def test_wrong_primary_amount_boundary_and_unused_stock_fields_refuse(tmp_path,field,bad):
    v=json.loads(CATALOG.read_bytes());v['terms'][0]['added'][field]=bad;p=tmp_path/'bad';p.write_text(json.dumps(v))
    with pytest.raises(ValueError,match='EXACT_PRIMARY_SAME_DAY_CASH_TERMS'):ArrayFacts(p)


def test_actual_cash_guard_removal_falsifier(tmp_path):
    v=json.loads(CATALOG.read_bytes());v['terms'][0]['added']['cash_per_share']=49.;p=tmp_path/'bad';p.write_text(json.dumps(v))
    with pytest.raises(ValueError,match='EXACT_PRIMARY_SAME_DAY_CASH_TERMS'):ArrayFacts(p)
    node=next(n for n in ast.parse(Path(ArrayFacts.__init__.__code__.co_filename).read_bytes()).body if isinstance(n,ast.ClassDef))
    init=next(n for n in node.body if isinstance(n,ast.FunctionDef) and n.name=='__init__')
    init.body=[n for n in init.body if not any(isinstance(v,ast.Constant) and v.value=='ARRAY_EXACT_PRIMARY_SAME_DAY_CASH_TERMS' for v in ast.walk(n))]
    scope=dict(ArrayFacts.__init__.__globals__)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'<actual-48USD-cash-guard-removed>','exec'),scope)
    assert scope['ArrayFacts'](p).catalog['terms'][0]['added']['cash_per_share']==49.


def test_no_local_financial_operation_or_consumed_event(monkeypatch,tmp_path):
    f=ArrayFacts(CATALOG);p=tmp_path/'absent';monkeypatch.delenv('FULL_SYSTEM_HOSTED',raising=False)
    with pytest.raises(ValueError,match='HOSTED_ARRAY'):f.hydrate(p)
    f.hydrated_sha='a'*64;f.hydrated_digest=digest(f.catalog)
    with pytest.raises(ValueError,match='UNCONSUMED_EVENT'):f.overlay({'source_cursor':'2019-07-30'},p)
    from system_campaign_p02_run import run
    with pytest.raises(ValueError,match='HOSTED'):run(p,Path('/absent'),{})
    assert not p.exists()


def test_actual_p02_only_handoff_and_other_candidate_fence(monkeypatch,tmp_path):
    import system_campaign_p02_job as job
    p=ROOT/'system-campaign-p02-request.json';v=json.loads(p.read_bytes())
    assert v==job.expected_request(v['predecessors_file']) and v['owner_candidate_priority']=='P02'
    assert v['concurrent_candidate_limit']==1
    arms=json.loads((ROOT/v['predecessors_file']).read_bytes())['arms'];assert set(arms)=={'P02'}
    assert arms['P02']['selected_session']=='2019-06-28' and arms['P02']['run_id']==41000113747
    monkeypatch.setattr(job,'check_context',lambda env:None);monkeypatch.setenv('GITHUB_RUN_ATTEMPT','1')
    with pytest.raises(ValueError,match='P02_ONLY_OWNER_SELECTED'):job.main(SimpleNamespace(request=p,staging=tmp_path/'absent',arm='P07'))
    with pytest.raises(FileNotFoundError):job.main(SimpleNamespace(request=p,staging=tmp_path/'absent',arm='P02'))


def test_source_closure_and_single_candidate_workflow():
    from forecast_tests.test_basis_job_sources import dependencies
    from system_campaign_p02_job import SOURCES
    from system_campaign_numeric_job import SOURCES as NUMERIC
    assert not dependencies(SOURCES)-set(SOURCES) and not dependencies(NUMERIC)-set(NUMERIC)
    w=(ROOT.parents[1]/'.github/workflows/capital-system-p02-only.yml').read_text()
    assert 'matrix' not in w and '--arm P02' in w and 'cancel-in-progress: false' in w
