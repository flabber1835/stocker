"""Primary term guards and absence of a fabricated Fairmount payment."""
import ast,json
from pathlib import Path
import pytest
from system_campaign_midyear_facts import MidyearFacts
from system_campaign_facts import digest

CATALOG=Path(__file__).parents[1]/'system-campaign-midyear-terminal-facts.json'


def test_primary_terms_provider_identity_and_unresolved_fmsas_cash():
    facts=MidyearFacts(CATALOG);fmi,col=facts.catalog['terms']
    assert fmi['added']['session']=='2018-07-31' and fmi['added']['cash_per_share']==137.
    assert col['added']['session']=='2018-11-27' and col['added']['cash_per_share']==93.33
    assert col['added']['exchange_ratio']==.37525 and col['added']['delivered_ticker']=='RTX'
    assert col['added']['delivered_issuer_id']=='SEC_UNKNOWN:148187321807650528'
    assert facts.catalog['FMSA_exact_cash_unproven'] and all(t['ticker']!='FMSA' for t in facts.catalog['terms'])


def test_local_and_consumed_boundary_refusals(monkeypatch,tmp_path):
    monkeypatch.delenv('FULL_SYSTEM_HOSTED',raising=False);facts=MidyearFacts(CATALOG);p=tmp_path/'absent'
    with pytest.raises(ValueError,match='HOSTED_MIDYEAR_FACTS_ONLY'):facts.hydrate(p)
    facts.hydrated_sha='a'*64;facts.hydrated_digest=digest(facts.catalog)
    with pytest.raises(ValueError,match='ALL_TERMS_UNCONSUMED'):facts.overlay({'source_cursor':'2018-07-31'},p)
    assert not p.exists()


def test_actual_primary_boundary_guard_removal(tmp_path):
    value=json.loads(CATALOG.read_bytes());value['terms'][1]['added']['session']='2018-11-26'
    p=tmp_path/'wrong';p.write_text(json.dumps(value))
    with pytest.raises(ValueError,match='EXACT_PRIMARY_TERMS'):MidyearFacts(p)
    node=next(n for n in ast.parse(Path(MidyearFacts.__init__.__code__.co_filename).read_bytes()).body
        if isinstance(n,ast.ClassDef) and n.name=='MidyearFacts')
    method=next(n for n in node.body if isinstance(n,ast.FunctionDef) and n.name=='__init__')
    method.body=[n for n in method.body if not any(isinstance(x,ast.Constant)
        and x.value=='MIDYEAR_EXACT_PRIMARY_TERMS' for x in ast.walk(n))]
    scope=dict(MidyearFacts.__init__.__globals__)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'<removed-midyear-date>','exec'),scope)
    assert scope['MidyearFacts'](p).catalog['terms'][1]['added']['session']=='2018-11-26'


def test_midyear_complete_driver_dependencies_and_os_ports():
    from forecast_tests.test_basis_job_sources import dependencies
    from system_campaign_midyear_job import SOURCES
    assert not dependencies(SOURCES)-set(SOURCES)
    driver=CATALOG.parent/'system_campaign_midyear_job.py'
    nodes=ast.walk(ast.parse(driver.read_bytes()))
    attributes={n.attr for n in nodes if isinstance(n,ast.Attribute) and isinstance(n.value,ast.Name) and n.value.id=='os'}
    assert attributes=={'environ','getuid','getgid','chmod'}


def test_retained_six_components_require_actual_catalog_compiler_and_hydration(tmp_path):
    from system_campaign_midyear_run import retained
    from system_campaign_basis import CATALOG_REF,COMPILER_REF,HYDRATED_REF
    driver=tmp_path/'driver';old=tmp_path/'old';out=tmp_path/'out'
    for p in (driver,old,out):p.mkdir()
    # Derive the declared tuples from the implementation's static data; ensure
    # the v1 references equal the immutable compiler's actual public constants.
    tree=ast.parse(Path(retained.__code__.co_filename).read_bytes())
    node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='retained')
    groups=ast.literal_eval(next(n.value for n in node.body if isinstance(n,ast.Assign)))
    assert len(groups)==6
    prefix='research:system-optimization-002/'
    assert [prefix+groups[0][i]+'/1' for i in (0,4,5)]==[CATALOG_REF,COMPILER_REF,HYDRATED_REF]
    refs=[]
    import hashlib
    for catalog,data,compiler,hydration,compiler_ref,hydrated_ref in groups:
        for name,path in ((catalog,driver/data),(compiler_ref,driver/compiler),(hydrated_ref,old/hydration)):
            path.write_bytes(name.encode());refs.append({'reference':prefix+name+'/1','sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
    retained(refs,old,out,driver)
    refs[-1]['sha256']='0'*64
    with pytest.raises(ValueError,match='ALL_RETAINED_FACT_COMPONENTS'):retained(refs,old,out,driver)
