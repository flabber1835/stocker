"""Sprint stock terms, frozen eligibility and source alias guards; synthetic only."""
import csv
import hashlib
import inspect
import io
import json
from pathlib import Path
import textwrap
import zipfile
import pytest
from system_campaign_sprint_facts import SprintFacts,alias_rows,preserve_prior_facts


def catalog():return json.loads((Path(__file__).parents[1]/'system-campaign-sprint-terminal-facts.json').read_bytes())


@pytest.mark.parametrize('field,value',[('session','2020-03-31'),('exchange_ratio','0.1'),
    ('kind','CASH_MERGER'),('cash_per_share',35.),('delivered_security_id','invented'),('entitlement_aggregation','VOLUNTARY')])
def test_wrong_stock_terms_or_date_refuse(tmp_path,field,value):
    c=catalog();c['added'][field]=value;p=tmp_path/'facts.json';p.write_text(json.dumps(c))
    with pytest.raises(ValueError):SprintFacts(p)


@pytest.mark.parametrize('field,value',[('issuer_id','SEC_CIK:101830'),('security_type_eligible','1')])
def test_snapshot_cannot_upgrade_frozen_source_identity(tmp_path,field,value):
    c=catalog();c['source_identity_witness'][field]=value;p=tmp_path/'facts.json';p.write_text(json.dumps(c))
    with pytest.raises(ValueError,match='INELIGIBILITY_UNCHANGED'):SprintFacts(p)


def alias_fixture(tmp_path,monkeypatch,*,wrong_digest):
    import system_campaign_sprint_facts as module
    rows=[dict(date='2020-03-31',action=a,ticker='S2',name='SPRINT CORP',contraticker=t,contraname=n)
        for a,t,n in [('acquisitionby','TMUS','T-MOBILE US INC'),('tickerchangefrom','S','N/A'),('tickerchangeto','S2','N/A'),('delisted','N/A','N/A')]]
    text=io.StringIO();writer=csv.DictWriter(text,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    raw=io.BytesIO()
    with zipfile.ZipFile(raw,'w') as z:z.writestr('actions.csv',text.getvalue())
    data=raw.getvalue();path=tmp_path/'source.zip';path.write_bytes(data)
    monkeypatch.setattr(module,'ALIAS_BYTES',len(data));monkeypatch.setattr(module,'ALIAS_SHA','0'*64 if wrong_digest else hashlib.sha256(data).hexdigest())
    return path,sorted(module.digest(v) for v in rows)


def test_original_alias_links_need_complete_source_hash_first(tmp_path,monkeypatch):
    path,expected=alias_fixture(tmp_path,monkeypatch,wrong_digest=False)
    assert len(alias_rows(path,expected))==4
    with pytest.raises(ValueError,match='EXACT_FOUR'):alias_rows(path,['0'*64]*4)


def test_actual_original_archive_hash_guard_removal_falsifier(tmp_path,monkeypatch):
    path,expected=alias_fixture(tmp_path,monkeypatch,wrong_digest=True)
    with pytest.raises(ValueError,match='BEFORE_PARSE'):alias_rows(path,expected)
    raw=inspect.getsource(alias_rows);bad=raw.replace('need(len(raw)==ALIAS_BYTES and sha(raw)==ALIAS_SHA,','need(True,',1);assert bad!=raw
    namespace={};exec(textwrap.dedent(bad),alias_rows.__globals__,namespace)
    assert len(namespace['alias_rows'](path,expected))==4


@pytest.mark.parametrize('mutate',[False,True])
def test_both_old_compilers_and_private_catalogs_retained(tmp_path,monkeypatch,mutate):
    import system_campaign_sprint_facts as module
    from system_campaign_medicines_facts import CATALOG as MC,COMPILER as MP,HYDRATED as MH
    from system_campaign_arqule_facts import CATALOG as AC,COMPILER as AP,HYDRATED as AH
    old=tmp_path/'old';folder=old/'book/repairs';folder.mkdir(parents=True);out=tmp_path/'out';out.mkdir();driver=tmp_path/'driver';driver.mkdir();refs=[]
    sha=lambda b:hashlib.sha256(b).hexdigest()
    for stem,keys in [('medicines',(MC,MP,MH)),('arqule',(AC,AP,AH))]:
        c=(stem+'-catalog').encode();p=(stem+'-compiler').encode();w=(stem+'-private').encode()
        (driver/('system-campaign-'+stem+'-terminal-facts.json')).write_bytes(c);(driver/('system_campaign_'+stem+'_facts.py')).write_bytes(p);(old/('hydrated-'+stem+'-terminal-catalog.json')).write_bytes(w)
        refs.extend([dict(reference=keys[0],sha256=sha(c)),dict(reference=keys[1],sha256='0'*64 if mutate and stem=='arqule' else sha(p)),dict(reference=keys[2],sha256=sha(w))])
    raw=json.dumps(dict(source_evidence=refs)).encode();h=sha(raw);(folder/(h+'.json')).write_bytes(raw);cp=dict(repairs=[dict(filename=h+'.json',sha256=h)])
    monkeypatch.setattr(module,'Path',lambda v:driver if v=='/driver' else Path(v))
    if mutate:
        with pytest.raises(ValueError,match='EXACT_RETAINED_ARQULE'):preserve_prior_facts(cp,old,out)
    else:
        preserve_prior_facts(cp,old,out)
        for stem in ('medicines','arqule'):assert (out/('hydrated-'+stem+'-terminal-catalog.json')).read_bytes()==(old/('hydrated-'+stem+'-terminal-catalog.json')).read_bytes()


@pytest.mark.parametrize('mutate',[False,True,'unknown'])
def test_common_basis_requires_all_new_sprint_compiler_bindings(monkeypatch,tmp_path,mutate):
    import system_campaign_uncertainty_basis as module
    from system_campaign_sprint_facts import CATALOG,COMPILER,HYDRATED
    root=tmp_path/'evidence';folder=root/'book/repairs';folder.mkdir(parents=True)
    driver=tmp_path/'driver';driver.mkdir()
    (driver/'system-campaign-sprint-terminal-facts.json').write_bytes(b'catalog')
    (driver/'system_campaign_sprint_facts.py').write_bytes(b'compiler')
    (root/'hydrated-sprint-terminal-catalog.json').write_bytes(b'private-witness')
    sha=lambda v:hashlib.sha256(v).hexdigest()
    refs=[dict(reference=CATALOG,sha256=sha(b'catalog')),dict(reference=COMPILER,sha256=sha(b'compiler')),
          dict(reference=HYDRATED,sha256=sha(b'private-witness'))]
    if mutate is True:refs[1]['sha256']='0'*64
    if mutate=='unknown':refs.append(dict(reference='research:system-optimization-002/sprint-undeclared/1',sha256='f'*64))
    documents=[dict(schema='terminal-repair/1',source_evidence=refs),
               dict(schema='research.leadership-uncertainty-input/1',predecessor_checkpoint_sha256='a'*64,source_evidence=[])]
    cp=dict(repairs=[])
    for document in documents:
        raw=json.dumps(document).encode();digest=sha(raw);(folder/(digest+'.json')).write_bytes(raw)
        cp['repairs'].append(dict(filename=digest+'.json',sha256=digest))
    monkeypatch.setattr(module,'validate_input_commitment',lambda *args:'synthetic-model')
    monkeypatch.setattr(module,'ordinary_basis',lambda *args:('f'*64,{'declared_fact_compilers':{'old':'f'*64}}))
    monkeypatch.setattr(module,'Path',lambda value:driver if value=='/driver' else Path(value))
    if mutate:
        with pytest.raises(ValueError,match='EXPLICIT_'):module.basis(root,cp)
    else:
        _,value=module.basis(root,cp)
        assert set(value['factual_semantics']['declared_fact_compilers'])=={'old',CATALOG,COMPILER,HYDRATED}


def test_actual_frozen_eligibility_guard_removal_falsifier(tmp_path):
    from types import SimpleNamespace
    c=catalog();c['source_identity_witness']['security_type_eligible']='1'
    path=tmp_path/'facts.json';path.write_text(json.dumps(c))
    with pytest.raises(ValueError,match='INELIGIBILITY_UNCHANGED'):SprintFacts(path)
    raw=inspect.getsource(SprintFacts.__init__)
    broken=raw.replace("need((w['session']","need(True or (w['session']",1);assert broken!=raw
    namespace={};exec(textwrap.dedent(broken),SprintFacts.__init__.__globals__,namespace)
    obj=SimpleNamespace();namespace['__init__'](obj,path)
    assert obj.catalog['source_identity_witness']['security_type_eligible']=='1'
