"""Validated catalog composition and sparse-input evidence; DATA/synthetic only."""
import ast,json,hashlib
from copy import deepcopy
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import system_campaign_financial_future as f


def material():
    selection,catalog,terms=f.selected('P07',cursor='2019-12-31')
    return dict(catalog=catalog,catalog_sha256=selection.catalog_sha,original_validator_sha256=selection.compiler_sha,
                selector_sha256='e'*64,composition=deepcopy(selection.composition),terms=terms)


def test_both_actual_catalogs_and_original_added_terms_are_preserved_without_mutation():
    value=material();before=deepcopy(value)
    for term,source in zip(value['terms'],value['composition']['sources']):
        raw=(f.HERE/source['catalog_file']).read_bytes();catalog=json.loads(raw)
        assert hashlib.sha256(raw).hexdigest()==source['catalog_sha256']
        assert hashlib.sha256((f.HERE/source['validator_file']).read_bytes()).hexdigest()==source['validator_sha256']
        assert term['added']==catalog['terms'][0]['added']
        assert term['identity_witness']==catalog['identity_witness']
        assert source['selected_tickers']==[term['ticker']]
    cp=dict(source_cursor='2019-12-31',run=dict(checkpoint_sha256='a'*64))
    doc=f.document(cp,value,'f'*64)
    assert doc['schema']=='terminal-repair/1' and doc['predecessor_checkpoint_sha256']=='a'*64
    assert [(v['session'],v['cash_per_share']) for v in doc['add']]==[('2020-01-06',85.),('2020-01-16',20.)]
    assert [v['session'] for v in doc['suppress']]==['2020-01-03','2020-01-15']
    refs={v['reference']:v['sha256'] for v in doc['source_evidence']}
    assert refs[f.REFERENCE+'/composition']==f.digest(value['composition'])
    for source in value['composition']['sources']:
        assert refs[f.REFERENCE+'/'+source['catalog_file']]==source['catalog_sha256']
        assert refs[f.REFERENCE+'/'+source['validator_file']]==source['validator_sha256']
    assert value==before


@pytest.mark.parametrize('change',['catalog_digest','validator_digest','source_digest','schema'])
def test_composition_evidence_mismatch_refuses(change):
    value=material()
    if change=='catalog_digest':value['catalog_sha256']='0'*64
    elif change=='validator_digest':value['original_validator_sha256']='0'*64
    elif change=='source_digest':value['composition']['sources'][0]['catalog_sha256']='0'*64
    else:value['composition']['schema']='unknown/1'
    with pytest.raises(ValueError):f.document(dict(source_cursor='2019-12-31',run=dict(checkpoint_sha256='a'*64)),value,'f'*64)


def test_duplicate_catalog_cannot_be_added_as_another_new_event():
    plan=f.PLANS['P07']
    with pytest.raises(ValueError,match='UNIQUE_COMPOSITION_SOURCES'):f.compose((plan,plan))


def synthetic_parts(monkeypatch):
    import importlib
    original=importlib.import_module
    def part(name):
        index=0 if name=='synthetic_one' else 1
        term=dict(ticker=('ONE','TWO')[index],security_id='same',native_session='2020-01-15',
                  added=dict(session='2020-01-16',security_id='same'))
        cls=lambda path:SimpleNamespace(catalog=dict(terms=[deepcopy(term)]),catalog_sha='a'*64,compiler_sha='b'*64)
        return SimpleNamespace(__file__=name+'.py',Facts=cls)
    monkeypatch.setattr(importlib,'import_module',lambda name:part(name) if name.startswith('synthetic_') else original(name))
    return (('synthetic_one','Facts','one.json',('ONE',)),('synthetic_two','Facts','two.json',('TWO',)))


def test_two_source_catalogs_cannot_target_the_same_security(monkeypatch):
    with pytest.raises(ValueError,match='DISJOINT_COMPOSITION_EVENTS'):f.compose(synthetic_parts(monkeypatch))


def test_disjoint_event_guard_removal_falsifier(monkeypatch):
    plans=synthetic_parts(monkeypatch)
    with pytest.raises(ValueError):f.compose(plans)
    fn=next(n for n in ast.parse(Path(f.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='compose')
    guard=next(n for n in fn.body if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and any(isinstance(a,ast.Constant) and a.value=='FUTURE_DISJOINT_COMPOSITION_EVENTS' for a in n.value.args))
    fn.body.remove(guard);ns=dict(vars(f));exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<removed-composition-event-guard>','exec'),ns)
    assert [v['security_id'] for v in ns['compose'](plans)[2]]==['same','same']


def test_top_level_witness_must_belong_to_the_exact_selected_security():
    codec=SimpleNamespace(catalog=dict(terms=[dict(ticker='T',security_id='right',native_session='2020-01-15',added=dict(session='2020-01-16'),exchange_source='primary')],identity_witness=dict(security_id='wrong')))
    with pytest.raises(ValueError,match='WITNESS_NORMALIZATION'):f.catalog_terms(codec,('T',))


def test_composition_digest_guard_removal_falsifier():
    value=material();value['catalog_sha256']='0'*64
    cp=dict(source_cursor='2019-12-31',run=dict(checkpoint_sha256='a'*64))
    with pytest.raises(ValueError):f.document(cp,value,'f'*64)
    fn=next(n for n in ast.parse(Path(f.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='document')
    first=next(n for n in fn.body if isinstance(n,ast.If));first.body=[n for n in first.body if not(isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and any(isinstance(a,ast.Constant) and a.value=='FUTURE_EXACT_COMPOSITION_EVIDENCE_DIGESTS' for a in n.value.args))]
    ns=dict(vars(f));exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<removed-composition-digest-guard>','exec'),ns)
    assert len(ns['document'](cp,value,'f'*64)['add'])==2
