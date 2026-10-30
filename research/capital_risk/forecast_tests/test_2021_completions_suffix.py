"""Factual and lineage guards only; canonical probes must run hosted."""
import ast
from copy import deepcopy
import inspect
import json
from pathlib import Path
import pytest
import system_campaign_2021_completions_facts as module

PATH=Path(__file__).parents[1]/'system-campaign-2021-completions-terminal-facts.json'
def catalog():return json.loads(PATH.read_bytes())


def synthetic_alias(ticker):
    term=next(t for t in catalog()['terms'] if t['ticker']==ticker);p=term['provider_alias_proof']
    def row(action,ticker,name,other,other_name):
        return dict(date=p['session'],action=action,ticker=ticker,name=name,value='',contraticker=other,contraname=other_name)
    rows=[row('tickerchangeto',ticker,p['company'],ticker,'N/A'),
          row('tickerchangefrom',ticker,p['company'],p['original_ticker'],'N/A'),
          row('acquisitionby',ticker,p['company'],p['counterparty_ticker'],p['counterparty_name']),
          row('delisted',ticker,p['company'],'N/A','N/A'),
          row('acquisitionof',p['counterparty_ticker'],p['counterparty_name'],ticker,p['company'])]
    p['rows_sha256']=module.digest(rows);p['selected_row_sha256']=[module.digest(r) for r in rows]
    return term,rows


def test_eight_final_terms_include_separate_stock_and_cash_plus_stock_types():
    terms=module.CompletionFacts(PATH).catalog['terms']
    assert len(terms)==8
    assert (terms[0]['ticker'],terms[0]['added']['kind'],terms[0]['added']['exchange_ratio'])==('WPX','CONVERSION',0.5165)
    assert (terms[5]['ticker'],terms[5]['added']['kind'],terms[5]['added']['cash_per_share'],terms[5]['added']['exchange_ratio'])==('WORK','CASH_PLUS_STOCK',26.79,0.0776)
    assert all(t['last_trading_session']==t['native_session']<t['added']['session'] for t in terms)


@pytest.mark.parametrize('index,field,value',[(0,'kind','CASH_MERGER'),(0,'exchange_ratio',0.516),
    (0,'delivered_security_id','wrong'),(1,'cash_per_share',71.),(2,'session','2021-04-14'),
    (3,'cash_per_share',177.),(4,'cash_per_share',44.),(5,'kind','CONVERSION'),
    (5,'cash_per_share',27.79),(5,'exchange_ratio',0.077),(6,'cash_per_share',36.),
    (7,'session','2021-11-16'),(0,'cash_in_lieu_price_per_delivered_share',19.)])
def test_wrong_kind_consideration_date_or_unsourced_proxy_refuses(tmp_path,index,field,value):
    c=catalog();c['terms'][index]['added'][field]=value;p=tmp_path/'bad.json';p.write_text(json.dumps(c))
    with pytest.raises(ValueError):module.CompletionFacts(p)


@pytest.mark.parametrize('index', (1,7))
@pytest.mark.parametrize('field,value',[('issuer_id','SEC_CIK:invented'),('security_type_eligible','1')])
def test_alias_does_not_upgrade_unknown_ineligible_frozen_identity(tmp_path,index,field,value):
    c=catalog();c['terms'][index]['identity_witness'][field]=value;p=tmp_path/'bad.json';p.write_text(json.dumps(c))
    with pytest.raises(ValueError,match='ALIAS_WITHOUT_PROVIDER_METADATA_UPGRADE'):module.CompletionFacts(p)


@pytest.mark.parametrize('field,value',[('issuer_id','SEC_CIK:wrong'),('session','2021-01-06'),('security_id','wrong')])
def test_wrong_actual_delivery_identity_refuses(tmp_path,field,value):
    c=catalog();c['terms'][0]['delivered_identity_witness'][field]=value;p=tmp_path/'bad.json';p.write_text(json.dumps(c))
    with pytest.raises(ValueError,match='EXACT_FROZEN_DELIVERY_IDENTITY'):module.CompletionFacts(p)


@pytest.mark.parametrize('ticker',('BEAT1','TRIL1'))
@pytest.mark.parametrize('mutation',('counterparty','alias','missing_reciprocal'))
def test_original_alias_rows_and_real_guard_removal_falsifier(ticker,mutation):
    term,rows=synthetic_alias(ticker)
    module.require_alias_rows(rows,term)
    if mutation=='counterparty':next(r for r in rows if r['action']=='acquisitionby')['contraticker']='WRONG'
    elif mutation=='alias':next(r for r in rows if r['action']=='tickerchangefrom')['contraticker']='WRONG'
    else:rows=[r for r in rows if r['action']!='acquisitionof']
    with pytest.raises(ValueError,match='EXACT_ALIAS_AND_COUNTERPARTY_ROWS'):module.require_alias_rows(rows,term)
    node=ast.parse(inspect.getsource(module.require_alias_rows)).body[0];node.body=[ast.Pass()]
    scope=dict(module.__dict__);exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'<actual-alias-guard-removed>','exec'),scope)
    scope[node.name](rows,term)


def test_original_archive_is_authenticated_before_alias_parse():
    with pytest.raises(ValueError,match='EXACT_ORIGINAL_ALIAS_ARCHIVE'):module.require_alias_archive(b'untrusted')


def test_full_source_and_delivery_witness_bytes_are_required():
    row=dict(session='2021-01-07',security_id='DVN',issuer_id='frozen',raw_open='18')
    w={**{k:row[k] for k in ('session','security_id','issuer_id')},'source_observation_sha256':module.digest(row)}
    module.require_witness(row,w)
    with pytest.raises(ValueError,match='FROZEN_SOURCE_OR_DELIVERY_WITNESS'):module.require_witness({**row,'raw_open':'19'},w)
    with pytest.raises(ValueError,match='FROZEN_SOURCE_OR_DELIVERY_WITNESS'):module.require_witness({**row,'issuer_id':'wrong'},w)


@pytest.mark.parametrize('cursor',('2021-01-06','2021-02-08','2021-07-20'))
def test_consumed_dates_refuse_before_any_canonical_import(tmp_path,cursor):
    obj=module.CompletionFacts(PATH);obj.hydrated_sha='synthetic';obj.hydrated_digest=module.digest(obj.catalog)
    with pytest.raises(ValueError,match='ALL_DATES_UNCONSUMED'):obj.overlay(dict(source_cursor=cursor),tmp_path/'forbidden.json')
    assert not (tmp_path/'forbidden.json').exists()


@pytest.mark.parametrize('mutate',[False,True])
def test_adopted_autumn_compiler_is_immutable(tmp_path,monkeypatch,mutate):
    import system_campaign_autumn2020_cash_facts as prior
    old=tmp_path/'old';(old/'book/repairs').mkdir(parents=True);out=tmp_path/'out';out.mkdir();driver=tmp_path/'driver';driver.mkdir()
    (driver/'system-campaign-autumn2020-cash-terminal-facts.json').write_bytes(b'catalog')
    (driver/'system_campaign_autumn2020_cash_facts.py').write_bytes(b'compiler')
    (old/'hydrated-autumn2020-cash-terminal-catalog.json').write_bytes(b'witness')
    refs=[dict(reference=r,sha256=module.sha(b)) for r,b in ((prior.CATALOG,b'catalog'),(prior.COMPILER,b'compiler'),(prior.HYDRATED,b'witness'))]
    if mutate:refs[1]['sha256']='0'*64
    raw=json.dumps(dict(source_evidence=refs)).encode();h=module.sha(raw);(old/'book/repairs'/(h+'.json')).write_bytes(raw)
    monkeypatch.setattr(module,'Path',lambda v:driver/Path(v).name if str(v).startswith('/driver/') else Path(v))
    cp=dict(repairs=[dict(filename=h+'.json',sha256=h)])
    if mutate:
        with pytest.raises(ValueError,match='EXACT_COMMITTED_AUTUMN_FACTS'):module.preserve_autumn_cash(cp,old,out)
    else:
        module.preserve_autumn_cash(cp,old,out)
        assert (out/'hydrated-autumn2020-cash-terminal-catalog.json').read_bytes()==b'witness'


@pytest.mark.parametrize('mutate',[False,True])
def test_mixed_group_basis_binds_catalog_compiler_and_private_hydration(tmp_path,monkeypatch,mutate):
    import system_campaign_uncertainty_basis as basis
    root=tmp_path/'evidence';(root/'book/repairs').mkdir(parents=True);driver=tmp_path/'driver';driver.mkdir()
    (driver/'system-campaign-2021-completions-terminal-facts.json').write_bytes(b'catalog')
    (driver/'system_campaign_2021_completions_facts.py').write_bytes(b'compiler')
    (root/'hydrated-2021-completions-terminal-catalog.json').write_bytes(b'witness')
    refs=[dict(reference=r,sha256=module.sha(b)) for r,b in ((module.CATALOG,b'catalog'),(module.COMPILER,b'compiler'),(module.HYDRATED,b'witness'))]
    if mutate:refs[1]['sha256']='0'*64
    docs=[dict(schema='terminal-repair/1',source_evidence=refs),dict(schema='research.leadership-uncertainty-input/1',predecessor_checkpoint_sha256='0'*64,source_evidence=[])]
    cp=dict(repairs=[])
    for doc in docs:
        raw=json.dumps(doc).encode();h=module.sha(raw);(root/'book/repairs'/(h+'.json')).write_bytes(raw);cp['repairs'].append(dict(filename=h+'.json',sha256=h))
    monkeypatch.setattr(basis,'validate_input_commitment',lambda *a:'old-model')
    monkeypatch.setattr(basis,'ordinary_basis',lambda *a:('0'*64,dict(declared_fact_compilers={'old':'0'*64})))
    monkeypatch.setattr(basis,'Path',lambda v:driver if v=='/driver' else Path(v))
    if mutate:
        with pytest.raises(ValueError,match='COMPLETIONS2021_FACTUAL_COMMITMENTS'):basis.basis(root,cp)
    else:
        _,v=basis.basis(root,cp);assert set(v['factual_semantics']['declared_fact_compilers'])=={'old',module.CATALOG,module.COMPILER,module.HYDRATED}
