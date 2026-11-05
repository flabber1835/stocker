"""Factual guards only; actual canonical packets qualify on hosted compute."""
import ast
from copy import deepcopy
import inspect,json
from pathlib import Path
import pytest
import system_campaign_following_completions_facts as module

PATH=Path(__file__).parents[1]/'system-campaign-following-completions-terminal-facts.json'
def catalog():return json.loads(PATH.read_bytes())

def test_six_exact_terms_preserve_null_cash_and_positive_mixed_cash():
    t=module.FollowingFacts(PATH).catalog['terms']
    assert [v['ticker'] for v in t]==['ACIA','APHA','CATM','AZPN1','REGI','PLAN']
    assert t[1]['added']['kind']=='CONVERSION' and t[1]['added']['cash_per_share'] is None
    assert (t[3]['added']['kind'],t[3]['added']['cash_per_share'],t[3]['added']['exchange_ratio'])==('CASH_PLUS_STOCK',87.69,.42)

@pytest.mark.parametrize('index,field,value',[(0,'cash_per_share',114.),(0,'session','2021-02-26'),
    (1,'cash_per_share',0.),(1,'exchange_ratio',.838),(1,'delivered_issuer_id','WRONG'),
    (2,'cash_per_share',40.),(3,'kind','CONVERSION'),(3,'cash_per_share',87.),(3,'exchange_ratio',.4),
    (4,'cash_per_share',61.),(5,'cash_per_share',63.),(1,'cash_in_lieu_price_per_delivered_share',20.)])
def test_wrong_term_refuses_before_canonical_import(tmp_path,index,field,value):
    c=catalog();c['terms'][index]['added'][field]=value;p=tmp_path/'bad.json';p.write_text(json.dumps(c))
    with pytest.raises(ValueError):module.FollowingFacts(p)

@pytest.mark.parametrize('field,value',[('issuer_id','SEC_CIK:929940'),('security_type_eligible','1')])
def test_aspen_source_unknown_ineligible_is_never_upgraded(tmp_path,field,value):
    c=catalog();c['terms'][3]['identity_witness'][field]=value;p=tmp_path/'bad.json';p.write_text(json.dumps(c))
    with pytest.raises(ValueError,match='FROZEN_ISSUER_LIMITATION'):module.FollowingFacts(p)

def test_aspen_delivered_actual_issuer_cannot_replace_frozen_issuer(tmp_path):
    c=catalog();t=c['terms'][3];t['added']['delivered_issuer_id']='SEC_CIK:1897982';t['delivered_identity_witness']['issuer_id']='SEC_CIK:1897982'
    p=tmp_path/'bad.json';p.write_text(json.dumps(c))
    with pytest.raises(ValueError,match='EXACT_FROZEN_DELIVERY_IDENTITY'):module.FollowingFacts(p)

def synthetic_rows():
    rows=[dict(date='2022-05-16',action=a,ticker=t,name='ASPEN TECHNOLOGY INC',value='',contraticker=c,contraname=n) for a,t,c,n in [
        ('delisted','AZPN1','N/A','N/A'),('tickerchangeto','AZPN1','AZPN1','N/A'),
        ('tickerchangefrom','AZPN1','AZPN','N/A'),('mergerto','AZPN1','AZPN','ASPEN TECHNOLOGY INC'),
        ('mergerfrom','AZPN','AZPN1','ASPEN TECHNOLOGY INC')]]
    term=deepcopy(catalog()['terms'][3]);rebind(rows,term);return rows,term

def rebind(rows,term):
    p=term['provider_alias_proof'];p['rows_sha256']=module.digest(rows);p['selected_row_sha256']=[module.digest(v) for v in rows]

@pytest.mark.parametrize('mutation',('unrelated','missing_reciprocal','wrong_alias','wrong_date'))
def test_actual_aspen_predicates_and_guard_removal(tmp_path,mutation):
    rows,term=synthetic_rows();module.require_aspen_rows(rows,term)
    if mutation=='unrelated':next(v for v in rows if v['action']=='mergerto')['contraticker']='EMR'
    elif mutation=='missing_reciprocal':rows=[v for v in rows if v['action']!='mergerfrom']
    elif mutation=='wrong_alias':next(v for v in rows if v['action']=='tickerchangefrom')['contraticker']='WRONG'
    else:rows[0]['date']='2022-05-17'
    rebind(rows,term)  # Test semantic predicates, not just mismatching hashes.
    with pytest.raises(ValueError,match='EXACT_ASPEN_ALIAS'):module.require_aspen_rows(rows,term)
    node=ast.parse(inspect.getsource(module.require_aspen_rows)).body[0];node.body=[ast.Pass()]
    scope=dict(module.__dict__);exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'<actual-alias-guard-removed>','exec'),scope)
    scope[node.name](rows,term)

@pytest.mark.parametrize('cursor',('2021-02-26','2021-04-30','2022-05-16'))
def test_consumed_native_date_refuses_before_any_canonical_import(tmp_path,cursor):
    o=module.FollowingFacts(PATH);o.hydrated_sha='synthetic';o.hydrated_digest=module.digest(o.catalog)
    with pytest.raises(ValueError,match='ALL_DATES_UNCONSUMED'):o.overlay(dict(source_cursor=cursor),tmp_path/'forbidden.json')
    assert not (tmp_path/'forbidden.json').exists()

@pytest.mark.parametrize('mutate',(False,True))
def test_newly_adopted_2021_group_is_preserved_exactly(tmp_path,monkeypatch,mutate):
    import system_campaign_2021_completions_facts as prior
    old=tmp_path/'old';(old/'book/repairs').mkdir(parents=True);out=tmp_path/'out';out.mkdir();driver=tmp_path/'driver';driver.mkdir()
    (driver/'system-campaign-2021-completions-terminal-facts.json').write_bytes(b'catalog')
    (driver/'system_campaign_2021_completions_facts.py').write_bytes(b'compiler')
    (old/'hydrated-2021-completions-terminal-catalog.json').write_bytes(b'witness')
    refs=[dict(reference=r,sha256=module.sha(b)) for r,b in ((prior.CATALOG,b'catalog'),(prior.COMPILER,b'compiler'),(prior.HYDRATED,b'witness'))]
    if mutate:refs[1]['sha256']='0'*64
    raw=json.dumps(dict(source_evidence=refs)).encode();h=module.sha(raw);(old/'book/repairs'/(h+'.json')).write_bytes(raw)
    monkeypatch.setattr(module,'Path',lambda v:driver/Path(v).name if str(v).startswith('/driver/') else Path(v))
    cp=dict(repairs=[dict(filename=h+'.json',sha256=h)])
    if mutate:
        with pytest.raises(ValueError,match='EXACT_COMMITTED_COMPLETIONS2021_FACTS'):module.preserve_completions2021(cp,old,out)
    else:
        module.preserve_completions2021(cp,old,out)
        assert (out/'hydrated-2021-completions-terminal-catalog.json').read_bytes()==b'witness'

@pytest.mark.parametrize('mutate',(False,True))
def test_following_common_basis_binds_exact_three_new_references(tmp_path,monkeypatch,mutate):
    import system_campaign_uncertainty_basis as basis
    root=tmp_path/'evidence';(root/'book/repairs').mkdir(parents=True);driver=tmp_path/'driver';driver.mkdir()
    (driver/'system-campaign-following-completions-terminal-facts.json').write_bytes(b'catalog')
    (driver/'system_campaign_following_completions_facts.py').write_bytes(b'compiler')
    (root/'hydrated-following-completions-terminal-catalog.json').write_bytes(b'witness')
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
        with pytest.raises(ValueError,match='FOLLOWING_COMPLETIONS_FACTUAL_COMMITMENTS'):basis.basis(root,cp)
    else:
        _,value=basis.basis(root,cp);assert set(value['factual_semantics']['declared_fact_compilers'])=={'old',module.CATALOG,module.COMPILER,module.HYDRATED}
