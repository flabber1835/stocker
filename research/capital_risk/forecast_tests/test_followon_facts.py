"""Guard merger terms, frozen identity and disjoint hosted continuation scope."""
import ast,json
from pathlib import Path
import pytest
from system_campaign_followon_facts import FollowonFacts
from system_campaign_facts import digest

ROOT=Path(__file__).parents[1]
CATALOG=ROOT/'system-campaign-followon-terminal-facts.json'


def test_primary_terms_and_preserved_frozen_identity():
    f=FollowonFacts(CATALOG)
    assert [(t['ticker'],t['added']['session'],t['added']['cash_per_share']) for t in f.catalog['terms']]==[
        ('XOXO','2018-12-21',35.),('MB2','2019-02-15',36.5),('ESRX','2018-12-21',48.75)]
    assert f.catalog['terms'][2]['added']['exchange_ratio']==.2434
    assert all(w['issuer_id']=='SEC_UNKNOWN:599899221506959001' and w['security_type_eligible']=='0'
               for w in f.catalog['identity_witnesses'])


@pytest.mark.parametrize('index,field,bad',[(0,'session','2018-12-20'),(1,'session','2019-02-14'),
    (1,'cash_per_share',35.),(2,'exchange_ratio',.25)])
def test_wrong_term_or_vote_date_refused(tmp_path,index,field,bad):
    v=json.loads(CATALOG.read_bytes());v['terms'][index]['added'][field]=bad;p=tmp_path/'bad';p.write_text(json.dumps(v))
    with pytest.raises(ValueError,match='FOLLOWON_EXACT_PRIMARY_TERMS'):FollowonFacts(p)


def test_actual_date_guard_removal_falsifier(tmp_path):
    v=json.loads(CATALOG.read_bytes());v['terms'][1]['added']['session']='2019-02-14';p=tmp_path/'bad';p.write_text(json.dumps(v))
    with pytest.raises(ValueError,match='FOLLOWON_EXACT_PRIMARY_TERMS'):FollowonFacts(p)
    node=next(n for n in ast.parse(Path(FollowonFacts.__init__.__code__.co_filename).read_bytes()).body
              if isinstance(n,ast.ClassDef) and n.name=='FollowonFacts')
    method=next(n for n in node.body if isinstance(n,ast.FunctionDef) and n.name=='__init__')
    method.body=[n for n in method.body if not any(isinstance(x,ast.Constant) and x.value=='FOLLOWON_EXACT_PRIMARY_TERMS' for x in ast.walk(n))]
    scope=dict(FollowonFacts.__init__.__globals__)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'<removed-merger-date-guard>','exec'),scope)
    assert scope['FollowonFacts'](p).catalog['terms'][1]['added']['session']=='2019-02-14'


def test_no_issuer_upgrade_and_exact_old_ci_identity(tmp_path):
    for which in ('MB2','CI'):
        v=json.loads(CATALOG.read_bytes())
        if which=='MB2':v['identity_witnesses'][0]['issuer_id']='SEC_CIK:1458962'
        else:v['terms'][2]['added']['delivered_issuer_id']='SEC_CIK:1739940'
        p=tmp_path/which;p.write_text(json.dumps(v))
        with pytest.raises(ValueError,match='FOLLOWON_(NO_ISSUER|EXACT_STORED_IDENTITY)'):FollowonFacts(p)


def test_no_local_or_consumed_financial_operation(monkeypatch,tmp_path):
    monkeypatch.delenv('FULL_SYSTEM_HOSTED',raising=False);f=FollowonFacts(CATALOG);p=tmp_path/'absent'
    with pytest.raises(ValueError,match='HOSTED_FOLLOWON_FACTS_ONLY'):f.hydrate(p)
    f.hydrated_sha='a'*64;f.hydrated_digest=digest(f.catalog)
    with pytest.raises(ValueError,match='ALL_TERMS_UNCONSUMED'):f.overlay({'source_cursor':'2018-12-20'},p)
    from system_campaign_followon_run import run
    with pytest.raises(ValueError,match='HOSTED'):run(p,Path('/absent'),{})
    assert not p.exists()


def test_complete_source_closure_and_workflow_only_stopped_arms():
    from forecast_tests.test_basis_job_sources import dependencies
    from system_campaign_followon_job import SOURCES
    from system_campaign_numeric_job import SOURCES as NUMERIC
    assert not dependencies(SOURCES)-set(SOURCES) and not dependencies(NUMERIC)-set(NUMERIC)
    workflow=(ROOT.parents[1]/'.github/workflows/capital-system-followon-factual-suffix.yml').read_text()
    assert 'arm: [P01, P02, P04, P07]' in workflow and 'arm: [P00' not in workflow
    assert "paths: ['research/capital_risk/system-campaign-followon-request.json']" in workflow
    tree=ast.parse((ROOT/'system_campaign_followon_run.py').read_bytes())
    values={n.value for n in ast.walk(tree) if isinstance(n,ast.Constant) and isinstance(n.value,str)}
    assert '2018-11-30' in values and 'FOLLOWON_OWN_EXACT_PRE_EVENT_BOUNDARY' in values
    assert 'source_conversion' in values and 'new_origin' in values


def test_frozen_request_binds_exact_own_reviewed_predecessors():
    from system_campaign_followon_job import expected_request
    request=json.loads((ROOT/'system-campaign-followon-request.json').read_bytes())
    assert request==expected_request()
    arms=json.loads((ROOT/request['predecessors_file']).read_bytes())['arms']
    assert set(arms)=={'P01','P02','P04','P07'}
    assert all(s['selected_session']=='2018-11-30' and s['run_id']==40986345436 for s in arms.values())
    assert all(s['receipt_name']=='campaign-factual-'+a+'.json' for a,s in arms.items())
    assert request['source_archive_limit_bytes']==1024**3


def test_actual_main_request_handoff_without_staging_or_financial_work(monkeypatch,tmp_path):
    from types import SimpleNamespace
    import system_campaign_followon_job as job
    monkeypatch.setattr(job,'check_context',lambda env:None)
    monkeypatch.setenv('GITHUB_RUN_ATTEMPT','1')
    args=SimpleNamespace(request=ROOT/'system-campaign-followon-request.json',staging=tmp_path/'absent-staging',arm='P01')
    with pytest.raises(FileNotFoundError):job.main(args)
    # The exact former zero-argument function fails at this same real handoff.
    original=job.expected_request
    monkeypatch.setattr(job,'expected_request',lambda:original())
    with pytest.raises(TypeError,match='positional'):job.main(args)


def test_parsley_is_stock_conversion_not_cash_or_fitbit(tmp_path,monkeypatch):
    from system_campaign_parsley_facts import ParsleyFacts
    p=ROOT/'system-campaign-parsley-terminal-facts.json';f=ParsleyFacts(p);term,=f.catalog['terms']
    assert term['ticker']=='PE' and term['added']['kind']=='CONVERSION'
    assert term['added']['cash_per_share'] is None and term['added']['exchange_ratio']==.1252
    assert term['added']['session']=='2021-01-13' and term['added']['delivered_security_id']=='276044719892003870'
    for field,bad in [('cash_per_share',7.35),('kind','CASH_MERGER'),('session','2021-01-12')]:
        v=json.loads(p.read_bytes());v['terms'][0]['added'][field]=bad;wrong=tmp_path/field;wrong.write_text(json.dumps(v))
        with pytest.raises(ValueError,match='EXACT_PRIMARY_STOCK_CONVERSION'):ParsleyFacts(wrong)
    monkeypatch.delenv('FULL_SYSTEM_HOSTED',raising=False)
    with pytest.raises(ValueError,match='HOSTED_PARSLEY'):f.hydrate(tmp_path/'absent')
