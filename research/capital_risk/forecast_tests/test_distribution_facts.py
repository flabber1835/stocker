"""Synthetic term/causal guards; hosted qualification supplies actual packets."""
import ast,hashlib,json
from pathlib import Path
from types import SimpleNamespace
import pytest
import system_campaign_distribution_facts as module
from system_campaign_distribution_facts import DistributionFacts
from system_campaign_facts import digest

ROOT=Path(__file__).parents[1]
CATALOG=ROOT/'system-campaign-distribution-facts.json'


def hydrated():
    f=DistributionFacts(CATALOG);f.hydrated_sha='a'*64;f.hydrated_digest=digest(f.catalog)
    refs=[SimpleNamespace(**v) for v in f.evidence()]
    return f,SimpleNamespace(source_evidence=refs,_resume_session='2019-03-29')


def test_exact_spins_and_distinct_zero_fractional_contract():
    f=DistributionFacts(CATALOG);a,b=f.catalog['spins'];lll,apha=f.catalog['terms']
    assert a['added']['child_shares_per_parent']=='0.2' and b['added']['child_shares_per_parent']=='1'
    assert len(a['native'])==len(b['native'])==2
    assert lll['added']['cash_in_lieu_price_per_delivered_share'] is None
    assert apha['added']['cash_in_lieu_price_per_delivered_share']==0.
    assert apha['proxy']['convention']=='CONTRACTUAL_ZERO_FRACTIONAL_CONSIDERATION'


@pytest.mark.parametrize('group,index,field,value,code',[
    ('spins',0,'child_security_id','3545','SPIN_IDENTITIES'),
    ('spins',0,'session','2019-04-08','SPIN_IDENTITIES'),
    ('spins',1,'child_shares_per_parent','2','SPIN_IDENTITIES'),
    ('spins',1,'policy','HOLD_CHILD','NO_DUPLICATE_CASH'),
    ('terms',0,'cash_per_share',35.,'NO_INVENTED_CASH'),
    ('terms',1,'cash_in_lieu_price_per_delivered_share',15.,'NO_INVENTED_CASH'),
    ('terms',1,'session','2021-04-30','NO_INVENTED_CASH'),
    ('terms',0,'delivered_issuer_id','SEC_CIK:202058','NO_INVENTED_CASH')])
def test_wrong_identity_boundary_policy_and_fractional_cash_refuse(tmp_path,group,index,field,value,code):
    v=json.loads(CATALOG.read_bytes());v[group][index]['added'][field]=value;p=tmp_path/'bad';p.write_text(json.dumps(v))
    with pytest.raises(ValueError,match=code):DistributionFacts(p)


def test_bound_compound_earliest_spin_not_just_later_terminal():
    f,loaded=hydrated();assert f._bound(loaded)
    loaded._resume_session='2019-04-09'
    with pytest.raises(ValueError,match='EARLIEST_SPIN_UNCONSUMED'):f._bound(loaded)
    loaded._resume_session='2019-03-29';loaded.source_evidence.pop()
    with pytest.raises(ValueError,match='EXACT_IMMUTABLE_COMMITMENTS'):f._bound(loaded)
    assert not f._bound(SimpleNamespace(source_evidence=[],_resume_session='2026-07-31'))


def test_actual_consumed_spin_guard_removal_falsifier():
    f,loaded=hydrated();loaded._resume_session='2019-04-09'
    with pytest.raises(ValueError,match='EARLIEST_SPIN_UNCONSUMED'):f._bound(loaded)
    node=next(n for n in ast.parse(Path(module.__file__).read_bytes()).body if isinstance(n,ast.ClassDef))
    method=next(n for n in node.body if isinstance(n,ast.FunctionDef) and n.name=='_bound')
    method.body=[n for n in method.body if not any(isinstance(v,ast.Constant) and v.value=='DISTRIBUTION_EARLIEST_SPIN_UNCONSUMED' for v in ast.walk(n))]
    scope=dict(vars(module));exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'<removed-earliest-spin-causal-guard>','exec'),scope)
    altered=scope['DistributionFacts'](CATALOG);altered.hydrated_sha=f.hydrated_sha;altered.hydrated_digest=digest(altered.catalog)
    assert altered._bound(loaded)


def test_no_local_historical_financial_operation_or_consumed_overlay(monkeypatch,tmp_path):
    f,loaded=hydrated();p=tmp_path/'absent';monkeypatch.delenv('FULL_SYSTEM_HOSTED',raising=False)
    with pytest.raises(ValueError,match='HOSTED_DISTRIBUTION'):f.hydrate(p)
    with pytest.raises(ValueError,match='EARLIEST_SPIN_UNCONSUMED'):f.overlay({'source_cursor':'2019-04-09'},p)
    from system_campaign_distribution_run import run
    with pytest.raises(ValueError,match='HOSTED'):run(p,Path('/absent'),{})
    assert not p.exists()


def test_source_bound_pure_codec_only_five_literal_sites(monkeypatch):
    raw=b'def _apply_spinoff_repair(packet, repair):\n return ("224580439420294771","224580439420294771","37439132904117100","GE","GEV")\n'
    monkeypatch.setattr(module,'REPAIR_SHA',hashlib.sha256(raw).hexdigest())
    ids={'224580439420294771':'P','37439132904117100':'C','GE':'PT','GEV':'CT'}
    fn=module.compile_spin_function(raw,{},ids);assert fn(None,None)==('P','P','C','PT','CT')
    with pytest.raises(ValueError,match='FROZEN_PACKET_FUNCTION'):module.compile_spin_function(raw+b'\n',{},ids)
    altered=raw.replace(b'"GEV"',b'"OTHER"');monkeypatch.setattr(module,'REPAIR_SHA',hashlib.sha256(altered).hexdigest())
    with pytest.raises(ValueError,match='EXACT_LITERAL_SITES'):module.compile_spin_function(altered,{},ids)


def test_exact_request_and_actual_main_handoff_not_just_arithmetic(monkeypatch,tmp_path):
    import system_campaign_distribution_job as job
    request=ROOT/'system-campaign-distribution-request.json';v=json.loads(request.read_bytes())
    # This selected request belongs to immutable published head74d6359d.
    assert hashlib.sha256(request.read_bytes()).hexdigest()=='875b8f43c86cef9677a66582ef2c114402e754f38c87cafecdb08dbc6f5371f9'
    arms=json.loads((ROOT/v['predecessors_file']).read_bytes())['arms'];assert set(arms)=={'P01','P02','P04','P07'}
    assert all(s['selected_session']==('2018-12-31' if a=='P04' else '2019-03-29') for a,s in arms.items())
    monkeypatch.setattr(job,'check_context',lambda env:None);monkeypatch.setenv('GITHUB_RUN_ATTEMPT','1')
    current=tmp_path/'synthetic-current-request.json';current.write_text(json.dumps(job.expected_request()))
    with pytest.raises(FileNotFoundError):job.main(SimpleNamespace(request=current,staging=tmp_path/'absent',arm='P01'))


def test_source_closure_and_no_running_reference_duplicate():
    from forecast_tests.test_basis_job_sources import dependencies
    from system_campaign_distribution_job import SOURCES
    from system_campaign_numeric_job import SOURCES as NUMERIC
    assert not dependencies(SOURCES)-set(SOURCES) and not dependencies(NUMERIC)-set(NUMERIC)
    w=(ROOT.parents[1]/'.github/workflows/capital-system-distribution-factual-suffix.yml').read_text()
    assert 'arm: [P01, P02, P04, P07]' in w and 'P00' not in w
