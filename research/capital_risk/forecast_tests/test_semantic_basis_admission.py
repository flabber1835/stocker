"""Synthetic proof bindings must refuse incorrect or unreviewed reuse."""
import ast,gzip,hashlib,json
from pathlib import Path
import pytest
import system_campaign_basis_admit as module


def fixture(tmp_path,monkeypatch):
    core=tmp_path/'core';proof=tmp_path/'proof';core.mkdir();proof.mkdir()
    (proof/'book').mkdir();(proof/'independent-review-stop').mkdir()
    source=tmp_path/'proof-source.py';source.write_bytes(b'SYNTHETIC-PROOF-SOURCE')
    monkeypatch.setattr(module,'PROOF_SOURCE',source)
    for p in (core,proof):(p/'source-bindings.json').write_bytes(b'SYNTHETIC-SOURCE-BINDING')
    complete={'sha256':'old','completed':2156,'source_cursor':'2026-07-31','base':{'input':'frozen'}}
    cp={'sha256':'new','source_cursor':'2019-04-30','base':complete['base'],'run':{'state_sha256':'state'}}
    (proof/'book/checkpoint.json.gz').write_bytes(gzip.compress(json.dumps(cp).encode()))
    common={'synthetic':'semantic-basis'};common_sha=hashlib.sha256(json.dumps(common).encode()).hexdigest()
    frozen_common=json.dumps(common)
    monkeypatch.setattr(module,'basis',lambda root,cp:(common_sha,json.loads(frozen_common)))
    worker={'schema':'research.system-campaign-basis-equivalence/1','independent_review_required':True,
        'old_complete_checkpoint_sha256':'old','new_cutoff_checkpoint_sha256':'new',
        'canonical_state_sha256':'state','cutoff':'2019-04-30','complete_recurrence_state_exact':True,
        'all_remaining_inputs_unchanged_by_finite_date_support':True,'old_physical_lineage_relabelled':False,
        'old_complete_physical_lineage_unchanged':True,'common_factual_basis_sha256':common_sha}
    certificate={**worker,'independent_review_required':False,'independent_review_passed':True,
        'source_file_sha256':hashlib.sha256(source.read_bytes()).hexdigest()}
    values={'spec.json':{'arm':'P00','complete_outer_sha256':'old'},'basis-equivalence-worker.json':worker,
        'common-factual-basis.json':common,'independent-review-stop/basis-equivalence-review.json':certificate,
        'independent-review-stop/core-review.json':{'checkpoint_sha256':'new','all_prefixes_verified':True,
            'all_daily_factors_and_chains_verified':True}}
    for n,v in values.items():(proof/n).write_text(json.dumps(v))
    return core,proof,complete,values


def test_physical_default_and_separate_certificate_do_not_rewrite_complete(tmp_path,monkeypatch):
    core,proof,complete,values=fixture(tmp_path,monkeypatch);old=dict(complete)
    a=module.admitted_basis(core,complete);b=module.admitted_basis(core,complete,proof)
    assert a[:2]==b[:2] and a[2]['mode']=='PHYSICAL_COMMON_FACTUAL_BASIS'
    assert b[2]['mode']=='INDEPENDENTLY_REVIEWED_BOUNDED_EQUIVALENCE' and not b[2]['full_corrected_physical_rerun_claimed']
    assert complete==old


@pytest.mark.parametrize('mutation',('predecessor','unreviewed','source','state','future','prefix','basis'))
def test_actual_admission_rejects_wrong_bindings(tmp_path,monkeypatch,mutation):
    core,proof,complete,values=fixture(tmp_path,monkeypatch)
    if mutation=='predecessor':complete['sha256']='wrong'
    elif mutation=='source':(proof/'source-bindings.json').write_bytes(b'WRONG')
    else:
        name='independent-review-stop/basis-equivalence-review.json'
        if mutation=='unreviewed':values[name]['independent_review_passed']=False
        if mutation=='state':values[name]['canonical_state_sha256']='wrong'
        if mutation=='future':values[name]['all_remaining_inputs_unchanged_by_finite_date_support']=False
        if mutation=='prefix':name='independent-review-stop/core-review.json';values[name]['all_prefixes_verified']=False
        if mutation=='basis':name='common-factual-basis.json';values[name]['synthetic']='wrong'
        (proof/name).write_text(json.dumps(values[name]))
    with pytest.raises(ValueError,match='SEMANTIC_PROOF'):module.admitted_basis(core,complete,proof)


def test_actual_predecessor_guard_removal_falsifier(tmp_path,monkeypatch):
    core,proof,complete,values=fixture(tmp_path,monkeypatch)
    values['spec.json']['complete_outer_sha256']='wrong';(proof/'spec.json').write_text(json.dumps(values['spec.json']))
    with pytest.raises(ValueError,match='EXACT_COMPLETE_DEFAULT_PREDECESSOR'):module.admitted_basis(core,complete,proof)
    node=next(n for n in ast.parse(Path(module.admitted_basis.__code__.co_filename).read_bytes()).body
        if isinstance(n,ast.FunctionDef) and n.name=='admitted_basis')
    node.body=[n for n in node.body if not any(isinstance(x,ast.Constant)
        and x.value=='SEMANTIC_PROOF_EXACT_COMPLETE_DEFAULT_PREDECESSOR' for x in ast.walk(n))]
    scope=dict(module.admitted_basis.__globals__)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'<removed-predecessor-guard>','exec'),scope)
    assert scope['admitted_basis'](core,complete,proof)[2]['mode']=='INDEPENDENTLY_REVIEWED_BOUNDED_EQUIVALENCE'


def test_numeric_request_dependency_closure():
    from forecast_tests.test_basis_job_sources import dependencies
    from system_campaign_numeric_job import SOURCES
    assert not dependencies(SOURCES)-set(SOURCES)
