"""Exact five-event batch, explicit prior-component registry, and P02-only handoff."""
import ast,hashlib,json
from pathlib import Path
from types import SimpleNamespace
import pytest
from system_campaign_tableau_facts import TableauFacts
from system_campaign_facts import digest
import system_campaign_p02_continue_run as runner

ROOT=Path(__file__).parents[1];CATALOG=ROOT/'system-campaign-tableau-terminal-facts.json'


def test_exact_stock_cash_and_retained_boundary_conventions():
    ts=TableauFacts(CATALOG).catalog['terms']
    assert [t['ticker'] for t in ts]==['DATA','TCF1','CTRL','UQM','BKS']
    assert ts[0]['added']['cash_per_share'] is None and ts[0]['added']['exchange_ratio']==1.103
    assert ts[1]['added']['exchange_ratio']==.5081 and ts[1]['added']['delivered_security_id']=='707661213264749628'
    assert ts[2]['added']['session']=='2019-08-02' and ts[3]['added']['session']=='2019-08-01'
    assert ts[4]['added']['session']=='2019-08-07' and ts[4]['added']['cash_per_share']==6.5


@pytest.mark.parametrize('i,k,v',[(0,'cash_per_share',1.),(0,'exchange_ratio',1.1),(0,'session','2019-07-31'),
    (1,'exchange_ratio',1.),(2,'session','2019-08-01'),(3,'cash_per_share',1.7),(4,'cash_per_share',6.49)])
def test_wrong_terms_and_conventions_refuse(tmp_path,i,k,v):
    value=json.loads(CATALOG.read_bytes());value['terms'][i]['added'][k]=v;p=tmp_path/'bad';p.write_text(json.dumps(value))
    with pytest.raises(ValueError,match='BATCH_EXACT_PRIMARY_TERMS'):TableauFacts(p)


def test_old_issuer_mapping_and_common_preferred_not_interchanged(tmp_path):
    v=json.loads(CATALOG.read_bytes());v['terms'][1]['added']['delivered_issuer_id']='SEC_CIK:19612';p=tmp_path/'bad';p.write_text(json.dumps(v))
    with pytest.raises(ValueError,match='EXACT_DELIVERED_IDENTITY'):TableauFacts(p)
    v=json.loads(CATALOG.read_bytes());v['terms'][1]['added']['security_id']='884451527437425797';p.write_text(json.dumps(v))
    with pytest.raises(ValueError,match='BATCH_EXACT_PRIMARY_TERMS'):TableauFacts(p)


def test_actual_primary_terms_guard_removal_falsifier(tmp_path):
    v=json.loads(CATALOG.read_bytes());v['terms'][0]['added']['exchange_ratio']=1.1;p=tmp_path/'bad';p.write_text(json.dumps(v))
    with pytest.raises(ValueError,match='BATCH_EXACT_PRIMARY_TERMS'):TableauFacts(p)
    node=next(n for n in ast.parse(Path(TableauFacts.__init__.__code__.co_filename).read_bytes()).body if isinstance(n,ast.ClassDef))
    init=next(n for n in node.body if isinstance(n,ast.FunctionDef) and n.name=='__init__')
    init.body=[n for n in init.body if not any(isinstance(x,ast.Constant) and x.value=='TABLEAU_BATCH_EXACT_PRIMARY_TERMS_AND_BOUNDARIES' for x in ast.walk(n))]
    scope=dict(TableauFacts.__init__.__globals__);exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'<actual-primary-batch-guard-removed>','exec'),scope)
    assert scope['TableauFacts'](p).catalog['terms'][0]['added']['exchange_ratio']==1.1


def test_no_local_financial_operation_or_consumed_event(monkeypatch,tmp_path):
    f=TableauFacts(CATALOG);p=tmp_path/'absent';monkeypatch.delenv('FULL_SYSTEM_HOSTED',raising=False)
    with pytest.raises(ValueError,match='HOSTED_TABLEAU'):f.hydrate(p)
    f.hydrated_sha='a'*64;f.hydrated_digest=digest(f.catalog)
    with pytest.raises(ValueError,match='UNCONSUMED_EVENT'):f.overlay({'source_cursor':'2019-07-31'},p)
    with pytest.raises(ValueError,match='HOSTED'):runner.run(p,Path('/absent'),{})
    assert not p.exists()


def test_actual_prior_array_hydration_required(monkeypatch,tmp_path):
    driver=tmp_path/'driver';old=tmp_path/'old';out=tmp_path/'out'
    for p in (driver,old,out):p.mkdir()
    monkeypatch.setattr(runner,'retained_thirteen',lambda *args:None)
    c=runner.COMPONENTS[0];refs=[]
    for suffix,path in [('terminal-catalog',driver/c['catalog']),('terminal-compiler',driver/c['compiler']),('private-terminal-catalog',old/c['hydrated'])]:
        raw=suffix.encode();path.write_bytes(raw);refs.append({'reference':'research:system-optimization-002/array-'+suffix+'/1','sha256':hashlib.sha256(raw).hexdigest()})
    runner.retained_components(refs,old,out,1,driver);assert (out/c['hydrated']).read_bytes()==(old/c['hydrated']).read_bytes()
    (old/c['hydrated']).unlink()
    with pytest.raises(ValueError,match='ALL_ORDINARY_COMPONENTS_RETAINED'):runner.retained_components(refs,old,out,1,driver)


def test_explicit_registry_and_actual_main_handoff(monkeypatch,tmp_path):
    import system_campaign_p02_continue_job as job
    p=ROOT/'system-campaign-p02-continuation-request.json';v=json.loads(p.read_bytes())
    assert v==job.expected_request(v['predecessors_file'],v['new_component']) and v['new_component']=='alder'
    assert runner.component('tableau')[1]['packet_checks']==10
    with pytest.raises(ValueError,match='EXPLICIT_COMPONENT_REGISTRY'):runner.component('invented')
    with pytest.raises(ValueError,match='EXPLICIT_NEXT_COMPONENT'):job.expected_request(new_component='array')
    arms=json.loads((ROOT/v['predecessors_file']).read_bytes())['arms'];assert set(arms)=={'P02'} and arms['P02']['new_component']=='alder'
    assert arms['P02']['run_id']==41013907113 and arms['P02']['outer_sha256']=='daa13136da1356bbf43cdcbf1114f2887a23ab5ddc9796b8b5b558d17b75c733'
    monkeypatch.setattr(job,'check_context',lambda env:None);monkeypatch.setenv('GITHUB_RUN_ATTEMPT','1')
    with pytest.raises(ValueError,match='P02_ONLY_OWNER_SELECTED'):job.main(SimpleNamespace(request=p,staging=tmp_path/'absent',arm='P01'))
    with pytest.raises(FileNotFoundError):job.main(SimpleNamespace(request=p,staging=tmp_path/'absent',arm='P02'))


def test_source_closure_and_same_single_writer_concurrency_group():
    from forecast_tests.test_basis_job_sources import dependencies
    from system_campaign_p02_continue_job import SOURCES
    from system_campaign_numeric_job import SOURCES as NUMERIC
    assert not dependencies(SOURCES)-set(SOURCES) and not dependencies(NUMERIC)-set(NUMERIC)
    w=(ROOT.parents[1]/'.github/workflows/capital-system-p02-continue.yml').read_text()
    assert 'matrix' not in w and '--arm P02' in w and 'group: system-optimization-002-p02-only' in w
