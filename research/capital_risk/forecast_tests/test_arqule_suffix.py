"""ArQule primary fact guards and retained MDCO commitments; synthetic only."""
import hashlib
import inspect
import json
from pathlib import Path
import textwrap
import pytest
from system_campaign_arqule_facts import ArQuleFacts,preserve_medicines


def catalog():
    return json.loads((Path(__file__).parents[1]/'system-campaign-arqule-terminal-facts.json').read_bytes())


@pytest.mark.parametrize('field,value',[('session','2020-01-15'),('cash_per_share',19.),
    ('delivered_security_id','invented'),('entitlement_aggregation','VOLUNTARY')])
def test_wrong_date_price_or_voluntary_terms_refuse(tmp_path,field,value):
    doc=catalog();doc['terms'][0]['added'][field]=value
    path=tmp_path/'catalog.json';path.write_text(json.dumps(doc))
    with pytest.raises(ValueError):ArQuleFacts(path)


def test_mandatory_cash_preserves_january15_trading(tmp_path):
    path=tmp_path/'catalog.json';path.write_text(json.dumps(catalog()))
    facts=ArQuleFacts(path);t=facts.catalog['terms'][0]
    assert (t['ticker'],t['native_session'],t['added']['session'],t['added']['cash_per_share'])==('ARQL','2020-01-15','2020-01-16',20.)


def retained_fixture(tmp_path,monkeypatch,*,mutate):
    import system_campaign_arqule_facts as module
    from system_campaign_medicines_facts import CATALOG,COMPILER,HYDRATED
    source=tmp_path/'old';(source/'book/repairs').mkdir(parents=True)
    out=tmp_path/'out';out.mkdir();driver=tmp_path/'driver';driver.mkdir()
    (driver/'system-campaign-medicines-terminal-facts.json').write_bytes(b'old-catalog')
    (driver/'system_campaign_medicines_facts.py').write_bytes(b'old-compiler')
    (source/'hydrated-medicines-terminal-catalog.json').write_bytes(b'old-private')
    sha=lambda b:hashlib.sha256(b).hexdigest()
    refs=[dict(reference=CATALOG,sha256=sha(b'old-catalog')),dict(reference=COMPILER,sha256=sha(b'old-compiler')),
          dict(reference=HYDRATED,sha256=sha(b'old-private'))]
    if mutate is True:refs[1]['sha256']='0'*64
    if mutate=='unknown':refs.append(dict(reference='research:system-optimization-002/arqule-undeclared/1',sha256='f'*64))
    raw=json.dumps(dict(source_evidence=refs)).encode();digest=sha(raw)
    (source/'book/repairs'/(digest+'.json')).write_bytes(raw)
    cp=dict(repairs=[dict(filename=digest+'.json',sha256=digest)])
    monkeypatch.setattr(module,'Path',lambda p:driver/p.removeprefix('/driver/') if p.startswith('/driver/') else Path(p))
    return cp,source,out


def test_retained_private_catalog_copied_exactly(tmp_path,monkeypatch):
    cp,source,out=retained_fixture(tmp_path,monkeypatch,mutate=False)
    preserve_medicines(cp,source,out)
    assert (source/'hydrated-medicines-terminal-catalog.json').read_bytes()==(out/'hydrated-medicines-terminal-catalog.json').read_bytes()==b'old-private'


def test_actual_retained_compiler_guard_removal_falsifier(tmp_path,monkeypatch):
    cp,source,out=retained_fixture(tmp_path,monkeypatch,mutate=True)
    with pytest.raises(ValueError,match='EXACT_RETAINED_MEDICINES'):preserve_medicines(cp,source,out)
    raw=inspect.getsource(preserve_medicines)
    bad=raw.replace("need(len(found)==3 and {v['reference']:v['sha256'] for v in found}==expected,","need(True,",1)
    assert bad!=raw
    namespace={};exec(textwrap.dedent(bad),preserve_medicines.__globals__,namespace)
    namespace['preserve_medicines'](cp,source,out)


@pytest.mark.parametrize('mutate',[False,True,'unknown'])
def test_common_basis_requires_all_new_arq_compiler_bindings(monkeypatch,tmp_path,mutate):
    import system_campaign_uncertainty_basis as module
    from system_campaign_arqule_facts import CATALOG,COMPILER,HYDRATED
    root=tmp_path/'evidence';folder=root/'book/repairs';folder.mkdir(parents=True)
    driver=tmp_path/'driver';driver.mkdir()
    (driver/'system-campaign-arqule-terminal-facts.json').write_bytes(b'catalog')
    (driver/'system_campaign_arqule_facts.py').write_bytes(b'compiler')
    (root/'hydrated-arqule-terminal-catalog.json').write_bytes(b'private-witness')
    sha=lambda v:hashlib.sha256(v).hexdigest()
    refs=[dict(reference=CATALOG,sha256=sha(b'catalog')),dict(reference=COMPILER,sha256=sha(b'compiler')),
          dict(reference=HYDRATED,sha256=sha(b'private-witness'))]
    if mutate is True:refs[1]['sha256']='0'*64
    if mutate=='unknown':refs.append(dict(reference='research:system-optimization-002/arqule-undeclared/1',sha256='f'*64))
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
