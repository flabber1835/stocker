"""Primary cash unit/date guards; hosted source closure and no local execution."""
import ast,json
from pathlib import Path
import pytest
from system_campaign_yearend_facts import YearendFacts
from system_campaign_facts import digest

CATALOG=Path(__file__).parents[1]/'system-campaign-yearend-terminal-facts.json'


def test_exact_ads_cash_and_preopen_dates():
    rows=YearendFacts(CATALOG).catalog['terms']
    assert [(t['ticker'],t['added']['session'],t['added']['cash_per_share']) for t in rows]==[
        ('MZOR','2018-12-20',58.5),('TSRO','2019-01-22',75.),('ZAYO','2020-03-09',35.)]
    assert all(t['proxy'] is None for t in rows)


@pytest.mark.parametrize('index,field,bad',[(0,'cash_per_share',29.25),(0,'session','2018-12-19'),(1,'session','2019-01-23'),(2,'session','2020-03-06')])
def test_wrong_ads_unit_or_administrative_date_refuses(tmp_path,index,field,bad):
    v=json.loads(CATALOG.read_bytes());v['terms'][index]['added'][field]=bad;p=tmp_path/'wrong';p.write_text(json.dumps(v))
    with pytest.raises(ValueError,match='YEAREND_EXACT_PRIMARY_TERMS'):YearendFacts(p)


def test_actual_ads_unit_guard_removal(tmp_path):
    v=json.loads(CATALOG.read_bytes());v['terms'][0]['added']['cash_per_share']=29.25;p=tmp_path/'wrong';p.write_text(json.dumps(v))
    with pytest.raises(ValueError,match='YEAREND_EXACT_PRIMARY_TERMS'):YearendFacts(p)
    node=next(n for n in ast.parse(Path(YearendFacts.__init__.__code__.co_filename).read_bytes()).body if isinstance(n,ast.ClassDef) and n.name=='YearendFacts')
    method=next(n for n in node.body if isinstance(n,ast.FunctionDef) and n.name=='__init__')
    method.body=[n for n in method.body if not any(isinstance(x,ast.Constant) and x.value=='YEAREND_EXACT_PRIMARY_TERMS' for x in ast.walk(n))]
    scope=dict(YearendFacts.__init__.__globals__);exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'<removed-ads-unit-guard>','exec'),scope)
    assert scope['YearendFacts'](p).catalog['terms'][0]['added']['cash_per_share']==29.25


def test_local_and_consumed_boundary_refusals(monkeypatch,tmp_path):
    monkeypatch.delenv('FULL_SYSTEM_HOSTED',raising=False);f=YearendFacts(CATALOG);p=tmp_path/'absent'
    with pytest.raises(ValueError,match='HOSTED_YEAREND_FACTS_ONLY'):f.hydrate(p)
    f.hydrated_sha='a'*64;f.hydrated_digest=digest(f.catalog)
    with pytest.raises(ValueError,match='ALL_TERMS_UNCONSUMED'):f.overlay({'source_cursor':'2018-12-19'},p)
    from system_campaign_yearend_run import run
    with pytest.raises(ValueError,match='HOSTED'):run(p,Path('/absent'),{})
    assert not p.exists()


def test_complete_yearend_and_numeric_dependencies():
    from forecast_tests.test_basis_job_sources import dependencies
    from system_campaign_yearend_job import SOURCES
    from system_campaign_numeric_job import SOURCES as N
    assert not dependencies(SOURCES)-set(SOURCES) and not dependencies(N)-set(N)
    attributes={n.attr for n in ast.walk(ast.parse((CATALOG.parent/'system_campaign_yearend_job.py').read_bytes()))
        if isinstance(n,ast.Attribute) and isinstance(n.value,ast.Name) and n.value.id=='os'}
    assert attributes=={'environ','getuid','getgid','chmod'}
