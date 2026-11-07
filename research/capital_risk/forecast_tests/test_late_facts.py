"""Actual final terms/date boundaries, retained source identity and local refusal."""
import ast,json
from pathlib import Path
import pytest
from system_campaign_late_facts import LateFacts
from system_campaign_facts import digest

CATALOG=Path(__file__).parents[1]/'system-campaign-late-terminal-facts.json'


def test_final_terms_and_issuer_identities():
    f=LateFacts(CATALOG);a,o,p,v=f.catalog['terms']
    assert [(t['added']['session'],t['added']['cash_per_share'],t['added']['exchange_ratio']) for t in (a,o,p,v)]==[
        ('2018-11-29',145.,.8378),('2018-12-10',5.60,.0636),('2019-01-10',38.,None),('2019-10-07',53.,None)]
    assert a['added']['delivered_issuer_id']=='SEC_CIK:64803' and o['added']['delivered_issuer_id']=='SEC_CIK:1633978'
    assert f.catalog['FMSA_exact_cash_unproven'] and f.catalog['AAAP_mandatory_payment_unproven']


@pytest.mark.parametrize('index,field,bad',[(0,'session','2018-11-28'),(1,'exchange_ratio',.0635),(1,'cash_per_share',5.59),(2,'session','2019-01-09'),(2,'cash_per_share',37.),(3,'session','2019-10-04')])
def test_reject_wrong_legal_terms_or_consumed_boundaries(tmp_path,index,field,bad):
    v=json.loads(CATALOG.read_bytes());v['terms'][index]['added'][field]=bad
    p=tmp_path/'wrong';p.write_text(json.dumps(v))
    with pytest.raises(ValueError,match='LATE_EXACT_PRIMARY_TERMS'):LateFacts(p)


def test_actual_primary_guard_removal(tmp_path):
    v=json.loads(CATALOG.read_bytes());v['terms'][0]['added']['session']='2018-11-28';p=tmp_path/'wrong';p.write_text(json.dumps(v))
    with pytest.raises(ValueError,match='LATE_EXACT_PRIMARY_TERMS'):LateFacts(p)
    node=next(n for n in ast.parse(Path(LateFacts.__init__.__code__.co_filename).read_bytes()).body if isinstance(n,ast.ClassDef) and n.name=='LateFacts')
    method=next(n for n in node.body if isinstance(n,ast.FunctionDef) and n.name=='__init__')
    method.body=[n for n in method.body if not any(isinstance(x,ast.Constant) and x.value=='LATE_EXACT_PRIMARY_TERMS' for x in ast.walk(n))]
    scope=dict(LateFacts.__init__.__globals__)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'<removed-late-date>','exec'),scope)
    # Proxy guard independently prevents incompatible proxy dates; mutate both
    # to demonstrate that the removed primary-date guard was load-bearing.
    v['terms'][0]['proxy']['session']='2018-11-28';p.write_text(json.dumps(v))
    assert scope['LateFacts'](p).catalog['terms'][0]['added']['session']=='2018-11-28'


def test_local_and_consumed_scope_refused(monkeypatch,tmp_path):
    monkeypatch.delenv('FULL_SYSTEM_HOSTED',raising=False);f=LateFacts(CATALOG);p=tmp_path/'absent'
    with pytest.raises(ValueError,match='HOSTED_LATE_FACTS_ONLY'):f.hydrate(p)
    f.hydrated_sha='a'*64;f.hydrated_digest=digest(f.catalog)
    with pytest.raises(ValueError,match='ALL_TERMS_UNCONSUMED'):f.overlay({'source_cursor':'2018-11-28'},p)
    assert not p.exists()


def test_complete_driver_dependencies_and_os_ports():
    from forecast_tests.test_basis_job_sources import dependencies
    from system_campaign_late_job import SOURCES
    assert not dependencies(SOURCES)-set(SOURCES)
    node=ast.parse((CATALOG.parent/'system_campaign_late_job.py').read_bytes())
    attributes={n.attr for n in ast.walk(node) if isinstance(n,ast.Attribute) and isinstance(n.value,ast.Name) and n.value.id=='os'}
    assert attributes=={'environ','getuid','getgid','chmod'}


def test_seventh_retained_component_has_own_raw_sha_guard(monkeypatch,tmp_path):
    import system_campaign_midyear_run as old
    from system_campaign_late_run import retained
    monkeypatch.setattr(old,'retained',lambda *a:None)
    driver=tmp_path/'driver';source=tmp_path/'source';out=tmp_path/'out'
    for p in (driver,source,out):p.mkdir()
    from system_campaign_facts import sha
    refs=[]
    for name,p in [('midyear-terminal-catalog',driver/'system-campaign-midyear-terminal-facts.json'),('midyear-terminal-compiler',driver/'system_campaign_midyear_facts.py'),('midyear-private-terminal-catalog',source/'hydrated-midyear-terminal-catalog.json')]:
        p.write_bytes(name.encode());refs.append({'reference':'research:system-optimization-002/'+name+'/1','sha256':sha(p.read_bytes())})
    retained(refs,source,out,driver)
    assert (out/'hydrated-midyear-terminal-catalog.json').read_bytes()==(source/'hydrated-midyear-terminal-catalog.json').read_bytes()
    refs[-1]['sha256']='0'*64
    with pytest.raises(ValueError,match='EXACT_SEVENTH_RETAINED_COMPONENT'):retained(refs,source,out,driver)
