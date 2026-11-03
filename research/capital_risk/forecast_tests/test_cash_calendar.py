"""Data/calendar/lineage guards only; no canonical or financial execution."""
from copy import deepcopy
import ast,json,hashlib
from pathlib import Path
import pytest
import system_campaign_cash_calendar as cash
import system_campaign_ordinary_registry as registry
from system_campaign_facts import sha

HERE=Path(__file__).resolve().parents[1]


def catalog():return json.loads((HERE/'system-campaign-cash-calendar-terminal-facts.json').read_bytes())


def test_actual_primary_calendar_keeps_same_native_preopen_and_explicit_conventions():
    terms=catalog()['terms'];assert len(terms)==8
    for t in terms:cash.validate_term(t)
    tbio=next(t for t in terms if t['ticker']=='TBIO1')
    assert tbio['native_session']==tbio['added']['session']=='2021-09-14'
    assert tbio['last_trading_session']=='2021-09-13'
    assert tbio['identity_witness']['issuer_id']=='SEC_UNKNOWN:'+tbio['security_id']
    assert tbio['identity_witness']['security_type_eligible']=='0'
    for ticker in ('CYBE','AMED'):
        t=next(t for t in terms if t['ticker']==ticker)
        assert t['recognition_rule']==cash.NEXT and not t['preopen_completion_confirmed']
        assert t['actual_completion_date']==t['native_session']<t['added']['session']


@pytest.mark.parametrize('kind',('invented_preopen','moved_last_trade','same_day_nonpreopen','zero_cash',
    'nan_cash','stock_component','tender_only','wrong_sid','wrong_reference','wrong_completion'))
def test_refuses_calendar_or_entitlement_economic_mutations(kind):
    t=deepcopy(catalog()['terms'][0])
    if kind=='invented_preopen':t['preopen_completion_confirmed']=False
    if kind=='moved_last_trade':t['last_trading_session']=t['added']['session']
    if kind=='same_day_nonpreopen':t.update(recognition_rule=cash.NEXT,preopen_completion_confirmed=False)
    if kind=='zero_cash':t['added']['cash_per_share']=0.
    if kind=='nan_cash':t['added']['cash_per_share']=float('nan')
    if kind=='stock_component':t['added']['exchange_ratio']=1.
    if kind=='tender_only':t['mandatory_common_share_completion_confirmed']=False
    if kind=='wrong_sid':t['added']['security_id']='1'
    if kind=='wrong_reference':t['added']['reference']='unsupported'
    if kind=='wrong_completion':t['actual_completion_date']='2021-09-15'
    with pytest.raises(ValueError):cash.validate_term(t)


def test_actual_loader_hash_and_registered_identity_are_required(monkeypatch):
    monkeypatch.setattr(registry,'registrations',lambda:json.loads((HERE/registry.REGISTRY).read_bytes())['groups'])
    x=catalog();obj=cash.CashCalendar(x);assert len(obj.patch()['add'])==8
    for key,value in (('loader_sha256','0'*64),('provider_metadata_upgraded',True)):
        wrong=deepcopy(x);wrong[key]=value
        with pytest.raises(ValueError):cash.CashCalendar(wrong)
    with pytest.raises(ValueError,match='HOSTED_CASH_CALENDAR'):obj.hydrate({},None,None)


def fixture(root,driver):
    e=json.loads((HERE/registry.REGISTRY).read_bytes())['groups'][0]
    driver.mkdir();root.mkdir();(root/'book/repairs').mkdir(parents=True)
    (driver/registry.REGISTRY).write_bytes((HERE/registry.REGISTRY).read_bytes())
    x=catalog();x['loader_sha256']=sha(b'loader')
    (driver/e['loader_file']).write_bytes(b'loader')
    (driver/e['catalog_file']).write_text(json.dumps(x))
    (root/e['private_file']).write_text(json.dumps({'catalog':x}))
    refs=registry.expected(e,root,driver)
    doc=dict(schema='terminal-repair/1',source_evidence=[dict(reference=k,sha256=v) for k,v in refs.items()])
    raw=json.dumps(doc).encode();h=sha(raw);p=root/'book/repairs'/(h+'.json');p.write_bytes(raw)
    return dict(repairs=[dict(filename=p.name,sha256=h)]),e,doc


def test_registry_requires_each_actual_byte_commitment(tmp_path):
    root,driver=tmp_path/'r',tmp_path/'d';cp,e,_=fixture(root,driver)
    assert len(registry.committed(root,cp,driver))==1
    (root/e['private_file']).write_bytes(b'{}')
    with pytest.raises(ValueError,match='EXACT_THREE'):registry.committed(root,cp,driver)


@pytest.mark.parametrize('kind',('missing','duplicate','unknown'))
def test_registry_cannot_drop_duplicate_or_hide_research_references(tmp_path,kind):
    root,driver=tmp_path/'r',tmp_path/'d';cp,e,doc=fixture(root,driver)
    if kind=='missing':doc['source_evidence'].pop()
    if kind=='duplicate':doc['source_evidence'].append(doc['source_evidence'][0])
    if kind=='unknown':doc['source_evidence'].append(dict(reference=registry.NAMESPACE+'unknown/1/catalog',sha256='0'*64))
    raw=json.dumps(doc).encode();h=sha(raw);(root/'book/repairs'/(h+'.json')).write_bytes(raw)
    cp['repairs']=[dict(filename=h+'.json',sha256=h)]
    with pytest.raises(ValueError):registry.committed(root,cp,driver)


def test_economic_guard_removal_falsifier_is_effective():
    # Execute only this pure metadata function, never a canonical module.
    source=Path(cash.__file__).read_text();tree=ast.parse(source)
    node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='validate_term')
    guard=next(n for n in node.body if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call)
               and isinstance(n.value.func,ast.Name) and n.value.func.id=='need')
    node.body.remove(guard)
    scope=dict(vars(cash));exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'<pure-guard-falsifier>','exec'),scope)
    wrong=deepcopy(catalog()['terms'][0]);wrong['added']['cash_per_share']=0.
    with pytest.raises(ValueError):cash.validate_term(wrong)
    scope['validate_term'](wrong)  # The same bad input succeeds only with guard removed.


def test_new_entrypoint_retains_latest_financial_and_original_amendment_boundaries():
    source=(HERE/'system_campaign_p02_calendar_run.py').read_text();ast.parse(source)
    assert "spec['selected_session']=='2021-08-31'" in source
    assert "old/'book/predecessor-checkpoints'/(OUTER+'.json.gz')" in source
    assert "with v1,spin,alder,idempotent_dispatch(alder),codec,amendment,certificate,observer:" in source
    assert "current['repairs'][:-1]==cp['repairs']" in source


def test_current_request_dependency_closure():
    from system_campaign_p02_uncertainty_job import SOURCES,expected_request
    from forecast_tests.test_basis_job_sources import dependencies
    assert not dependencies(SOURCES)-set(SOURCES)
    assert json.loads((HERE/'system-campaign-p02-uncertainty-request.json').read_bytes())==expected_request()


def test_larger_retained_export_keeps_original_authenticated_format(tmp_path,monkeypatch):
    import tarfile
    from seal import decrypt,sha256_file
    from system_campaign_evidence_export import seal
    monkeypatch.setenv('GITHUB_RUN_ID','123');monkeypatch.setenv('GITHUB_SHA','a'*40)
    root=tmp_path/'source';root.mkdir();(root/'marker').write_bytes(b'synthetic retention marker\n')
    request=tmp_path/'request.json';request.write_bytes(b'{}\n')
    target=tmp_path/'proof.crseal';test_key=bytes(range(32))
    result=seal(root,target,test_key,request,'P02',stage='campaign-factual-suffix',protocol_sha256='b'*64)
    plain=tmp_path/'authenticated.tar.gz';decrypt(target,plain,test_key,result['sha256'])
    with tarfile.open(plain) as archive:
        raw=archive.extractfile('manifest.json').read();m=json.loads(raw)
        assert sha(raw)==result['manifest_sha256'] and m['request_sha256']==sha256_file(request)
        assert archive.extractfile('marker').read()==(root/'marker').read_bytes()
    bad=bytearray(target.read_bytes());bad[-1]^=1;changed=tmp_path/'changed.crseal';changed.write_bytes(bad)
    with pytest.raises(Exception):decrypt(changed,tmp_path/'unpublished',test_key,sha256_file(changed))
    assert not (tmp_path/'unpublished').exists()
