"""Sparse MDCO input and exact failed-review admission contracts, synthetic only."""
import hashlib
import inspect
import json
from pathlib import Path
import textwrap

import pytest

from system_campaign_medicines_facts import MedicinesFacts
from system_campaign_factual_admit import prove_review_refusal
from system_campaign_uncertainty_archive import preserve
from forecast_tests.test_uncertainty_archive import fixture as archive_fixture


def catalog():
    return json.loads((Path(__file__).parents[1]/'system-campaign-medicines-terminal-facts.json').read_bytes())


@pytest.mark.parametrize('field,value', [('session','2020-01-03'),('cash_per_share',84.),
                                       ('delivered_security_id','invented'),('entitlement_aggregation','VOLUNTARY')])
def test_wrong_date_price_or_voluntary_terms_refuse(tmp_path,field,value):
    doc=catalog();doc['terms'][0]['added'][field]=value
    path=tmp_path/'catalog.json';path.write_text(json.dumps(doc))
    with pytest.raises(ValueError):MedicinesFacts(path)


def test_correct_catalog_preserves_last_trade_and_remaining_share_cash(tmp_path):
    path=tmp_path/'catalog.json';path.write_text(json.dumps(catalog()))
    facts=MedicinesFacts(path)
    assert facts.catalog['terms'][0]['native_session']=='2020-01-03'
    assert facts.catalog['terms'][0]['added']['session']=='2020-01-06'
    assert facts.catalog['terms'][0]['added']['cash_per_share']==85.


def refusal(root,*,prefix=True):
    directory=root/'independent-review-stop';directory.mkdir()
    log=directory/'worker.log'
    log.write_text("FileNotFoundError: [Errno 2] No such file or directory: '/evidence/book/pre-event/2019-10-22.json.gz'\n")
    outer='994874c1abcbb5bb406d1ea76c9f0c6c751a5e500b073bf0134c6b00bc7912cb'
    proof=dict(all_prefixes_verified=prefix,all_daily_factors_and_chains_verified=True,
        checkpoint_sha256=outer,counts={'formation':126,'daily':503},accounting_snapshots=1258,complete=False)
    path=directory/'core-review.json';path.write_text(json.dumps(proof))
    sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    return dict(review_refusal='UNCERTAINTY_ARCHIVE_NAME',receipt_schema='research.system-p02-uncertainty-suffix-receipt/1',
        arm='P02',run_id=41069193936,selected_session='2019-12-31',outer_sha256=outer,
        review_log_sha256=sha(log),review_sha256=sha(path),inspections={
            'economic-worker-inspect.json':dict(exit_code=1),
            'independent-review-stop/worker-inspect.json':dict(exit_code=1)})


def test_admission_preserves_failed_status_and_requires_actual_financial_proof(tmp_path):
    spec=refusal(tmp_path);prove_review_refusal(spec,{},tmp_path)
    spec['inspections']['independent-review-stop/worker-inspect.json']['exit_code']=0
    with pytest.raises(ValueError,match='FAILED_STOPS_NOT_RELABELED'):prove_review_refusal(spec,{},tmp_path)


def test_actual_prefix_guard_removal_falsifier(tmp_path):
    spec=refusal(tmp_path,prefix=False)
    with pytest.raises(ValueError,match='PASSED_COMMITTED_FINANCIAL_PREFIX'):prove_review_refusal(spec,{},tmp_path)
    raw=inspect.getsource(prove_review_refusal)
    old="need(proof['all_prefixes_verified'] and proof['all_daily_factors_and_chains_verified']"
    broken=raw.replace(old,"need(True and proof['all_daily_factors_and_chains_verified']",1)
    assert broken!=raw
    namespace={};exec(textwrap.dedent(broken),prove_review_refusal.__globals__,namespace)
    namespace['prove_review_refusal'](spec,{},tmp_path)


def test_hash_named_event_origin_is_carried_without_relabeling(tmp_path):
    source=tmp_path/'source';target=tmp_path/'target';target.mkdir()
    original,_,raw=archive_fixture(source)
    copied=preserve(source,target)
    assert copied.name==original.name and copied.read_bytes()==raw and original.read_bytes()==raw
    assert not (target/'book/pre-event/2019-10-22.json.gz').exists()


@pytest.mark.parametrize('mutate',[False,True])
def test_common_basis_requires_all_new_mdco_compiler_bindings(monkeypatch,tmp_path,mutate):
    import system_campaign_uncertainty_basis as module
    from system_campaign_medicines_facts import CATALOG,COMPILER,HYDRATED
    root=tmp_path/'evidence';folder=root/'book/repairs';folder.mkdir(parents=True)
    driver=tmp_path/'driver';driver.mkdir()
    (driver/'system-campaign-medicines-terminal-facts.json').write_bytes(b'catalog')
    (driver/'system_campaign_medicines_facts.py').write_bytes(b'compiler')
    (root/'hydrated-medicines-terminal-catalog.json').write_bytes(b'private-witness')
    sha=lambda v:hashlib.sha256(v).hexdigest()
    refs=[dict(reference=CATALOG,sha256=sha(b'catalog')),dict(reference=COMPILER,sha256=sha(b'compiler')),
          dict(reference=HYDRATED,sha256=sha(b'private-witness'))]
    if mutate:refs[1]['sha256']='0'*64
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
        with pytest.raises(ValueError,match='EXPLICIT_MEDICINES'):module.basis(root,cp)
    else:
        _,value=module.basis(root,cp)
        assert set(value['factual_semantics']['declared_fact_compilers'])=={'old',CATALOG,COMPILER,HYDRATED}
