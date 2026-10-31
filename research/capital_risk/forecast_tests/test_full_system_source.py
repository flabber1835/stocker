"""Pure source/serialization tests only; no historical portfolio transition."""
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import pytest

HERE=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('full_source_test',HERE/'full_system_source.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


def test_pool_is_deterministic_balanced_and_not_claimed_exhaustive():
    a=module.proposals();assert a==module.proposals() and len(a)==4 and a[0]['parameters']==module.BASELINE
    for key,values in module.LEVELS.items():assert sorted(p['parameters'][key] for p in a[1:])==sorted(values)


def test_replacement_guard_detects_missing_and_duplicate_economic_sites():
    assert module.replace('x=1','x=1','x=2')=='x=2'
    for raw in ('x=0','x=1\nx=1'):
        with pytest.raises(ValueError,match='SOURCE_SITE'):module.replace(raw,'x=1','x=2')
    source=(HERE/'full_system_source.py').read_text()
    broken=source.replace("if text.count(old)!=count:raise ValueError('REFUSED_FULL_SOURCE_SITE:'+old[:80])",'pass',1)
    assert broken!=source
    ns={'__name__':'guard_removed'};exec(compile(broken,'guard_removed','exec'),ns)
    assert ns['replace']('x=1\nx=1','x=1','x=2')=='x=2\nx=2'


def test_standard_json_spelling_matches_retained_chunk_encoder_on_synthetic_values():
    # Parse only the serialization helper; no strategy module is imported.
    source=Path('C:/Users/mbron/.codex/visualizations/2026/10/25/01a1737f-f4e0-7cf1-990e-82ae645d665b/zero-share-2008-20261026/source-fixed/sentinel/core/session.py')
    if not source.is_file():pytest.skip('Frozen source available in owner workspace only; hosted actual checkpoint hashes are mandatory.')
    tree=ast.parse(source.read_bytes());node,=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_canonical_chunks']
    ns={'json':json};exec(compile(ast.Module(body=[node],type_ignores=[]),'frozen-json-only','exec'),ns)
    cases=[None,True,0,-0.,1.125,'café',{str(i):[i,i+.125,None,'z'] for i in range(100)},
        {'nested':[[{'value':n,'span':tuple(range(20))}] for n in range(280)]}, {'huge':2**200}]
    for value in cases:
        expected=''.join(ns['_canonical_chunks'](value))
        actual=json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)
        assert actual==expected
    for value in (float('nan'),float('inf'),{'bad':float('-inf')}):
        with pytest.raises(ValueError):''.join(ns['_canonical_chunks'](value))
        with pytest.raises(ValueError):json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)
    cyclic=[];cyclic.append(cyclic)
    with pytest.raises(ValueError):''.join(ns['_canonical_chunks'](cyclic))
    with pytest.raises(ValueError):json.dumps(cyclic,sort_keys=True,separators=(',',':'),allow_nan=False)
