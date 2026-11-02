"""Metadata collision and unchanged-byte guards; no financial runtime calls."""
import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

import system_campaign_mixed_preflight as mixed
import system_campaign_action_preflight as strict


def stored(root, document):
    raw = json.dumps(document).encode(); h = hashlib.sha256(raw).hexdigest()
    path = root / 'book/repairs' / (h + '.json'); path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)
    return dict(filename=h + '.json', sha256=h, resume_session='2022-02-28', predecessor_checkpoint_sha256='1' * 64)


def fixture(tmp_path):
    descriptors = [stored(tmp_path, dict(schema='terminal-repair/1', suppress=[], add=[])),
                   stored(tmp_path, dict(schema='research.leadership-uncertainty-input/1')),
                   stored(tmp_path, dict(schema=mixed.ZSCHEMA))]
    cp = dict(sha256='2' * 64, source_cursor='2022-09-30', base={}, repairs=descriptors,
              run={'input_sha256': mixed.digest(dict(base={}, repairs=descriptors))})
    catalog = {'terms': [dict(ticker='NEW', security_id='NEW', native_session='2022-10-13',
                            added=dict(session='2022-10-14', security_id='NEW'))]}
    # This fixture tests the visitor after model admission. The private actual-
    # 27-input regression separately uses both original strict model parsers.
    adapter = mixed.MixedCalendarPreflight.__new__(mixed.MixedCalendarPreflight)
    adapter.binding = mixed.binding(cp); adapter.root = tmp_path.resolve()
    adapter.models = [(descriptors[1]['sha256'], mixed.ALDER_SID), (descriptors[2]['sha256'], mixed.ZSID)]
    adapter.visit = mixed.compile_visitor(Path(strict.__file__).read_bytes())
    return cp, catalog, adapter


def test_original_refusal_and_explicit_mixed_visitor(tmp_path):
    cp, catalog, adapter = fixture(tmp_path); before = deepcopy(cp)
    with pytest.raises(ValueError, match='DECLARED_ORDINARY_SCHEMA'):
        strict.analyze_new_catalog(cp, tmp_path, catalog)
    proof = adapter.analyze(cp, tmp_path, catalog); strict.require_disjoint(proof)
    assert proof['retained_ordinary_repairs'] == 1 and proof['full_actual_input_commitment_verified']
    assert not proof['descriptor_or_financial_checkpoint_projection'] and cp == before
    with pytest.raises(ValueError, match='DECLARED_ORDINARY_SCHEMA'):
        strict.analyze_new_catalog(cp, tmp_path, catalog)


def test_unknown_schema_and_changed_original_bytes_still_refuse(tmp_path):
    cp, catalog, adapter = fixture(tmp_path)
    unknown = stored(tmp_path, {'schema': 'undeclared/model'})
    cp['repairs'].append(unknown); adapter.binding = mixed.binding(cp)
    with pytest.raises(ValueError, match='DECLARED_ORDINARY_SCHEMA'):
        adapter.analyze(cp, tmp_path, catalog)
    cp['repairs'].pop(); adapter.binding = mixed.binding(cp)
    path = tmp_path / 'book/repairs' / cp['repairs'][0]['filename']; path.write_bytes(b'{}')
    with pytest.raises(ValueError, match='EXACT_RETAINED_BYTES'):
        adapter.analyze(cp, tmp_path, catalog)


def test_modeled_identity_and_actual_binding_are_not_hidden(tmp_path):
    cp, catalog, adapter = fixture(tmp_path)
    catalog['terms'][0]['security_id'] = catalog['terms'][0]['added']['security_id'] = mixed.ZSID
    with pytest.raises(ValueError, match='NO_MODELED_SECURITY_OVERLAP'):
        adapter.analyze(cp, tmp_path, catalog)
    cp['source_cursor'] = '2022-10-03'
    with pytest.raises(ValueError, match='EXACT_VALIDATED_ACTUAL_CHECKPOINT'):
        adapter.analyze(cp, tmp_path, catalog)


def test_original_source_hash_and_full_input_commitment_are_required(tmp_path):
    with pytest.raises(ValueError, match='EXACT_ORIGINAL_VISITOR_SOURCE'):
        mixed.compile_visitor(Path(strict.__file__).read_bytes() + b'\n')
    with pytest.raises(ValueError, match='FULL_ACTUAL_INPUT_COMMITMENT'):
        mixed.validate_models(tmp_path, dict(base={}, repairs=[], run={'input_sha256': '0' * 64}))


def test_context_restores_the_strict_cash_binding_on_failure(tmp_path):
    import system_campaign_cash_calendar as cash
    cp, catalog, adapter = fixture(tmp_path); original = cash.analyze_new_catalog
    with pytest.raises(RuntimeError, match='fixture'):
        with adapter:
            strict.require_disjoint(cash.analyze_new_catalog(cp, tmp_path, catalog))
            raise RuntimeError('fixture')
    assert cash.analyze_new_catalog is original is strict.analyze_new_catalog


def test_overlap_guard_removal_falsifier(tmp_path):
    cp, catalog, adapter = fixture(tmp_path)
    catalog['terms'][0]['security_id'] = catalog['terms'][0]['added']['security_id'] = mixed.ZSID
    tree = ast.parse(Path(mixed.__file__).read_bytes())
    cls, = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'MixedCalendarPreflight']
    fn, = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'analyze']
    guard, = [n for n in fn.body if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
              and any(isinstance(a, ast.Constant) and a.value == 'MIXED_PREFLIGHT_NO_MODELED_SECURITY_OVERLAP'
                      for a in n.value.args)]
    fn.body.remove(guard); namespace = dict(vars(mixed))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), '<removed-model-overlap-guard>', 'exec'), namespace)
    with pytest.raises(ValueError): adapter.analyze(cp, tmp_path, catalog)
    # Removing the real guard breaks the overlapping-modeled-security test.
    assert namespace['analyze'](adapter, cp, tmp_path, catalog)['status'] == 'DISJOINT_UNCONSUMED'


def equivalence_fixture(tmp_path, monkeypatch):
    proof = json.loads((mixed.HERE / mixed.EQUIVALENCE).read_bytes())
    for i, name in enumerate(proof['exact_unchanged_members']):
        path = tmp_path / name; path.parent.mkdir(parents=True, exist_ok=True); raw = ('fixture-' + str(i)).encode(); path.write_bytes(raw)
        proof['exact_unchanged_members'][name] = dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    driver = tmp_path / 'driver'; driver.mkdir(); raw = json.dumps(proof).encode(); (driver / mixed.EQUIVALENCE).write_bytes(raw)
    monkeypatch.setattr(mixed, 'HERE', driver)
    spec = dict(run_id=41151496224, outer_sha256=proof['financial_parent_outer_sha256'],
                selected_session='2022-09-30', selected_file=proof['exact_unchanged_members']['book/checkpoint.json.gz'])
    return spec, {'prior_unadvanced_equivalence_sha256': hashlib.sha256(raw).hexdigest()}


def test_full_journals_and_unsent_tail_bytes_are_rechecked(tmp_path, monkeypatch):
    spec, request = equivalence_fixture(tmp_path, monkeypatch)
    assert mixed.verify_unchanged_attempt(tmp_path, spec, request)['new_model_not_adopted']
    with (tmp_path / 'book/watch.jsonl').open('ab') as stream: stream.write(b'new-unsent-tail')
    with pytest.raises(ValueError, match='ACTUAL_SOURCE_EQUALS_FAILED_FINANCIAL_PREFIX'):
        mixed.verify_unchanged_attempt(tmp_path, spec, request)
    with pytest.raises(ValueError, match='FAILURE_RECORD_BYTES'):
        mixed.verify_unchanged_attempt(tmp_path, spec, {'prior_unadvanced_equivalence_sha256': '0' * 64})


def test_complete_tail_hash_guard_removal_falsifier(tmp_path, monkeypatch):
    spec, request = equivalence_fixture(tmp_path, monkeypatch)
    with (tmp_path / 'book/watch.jsonl').open('ab') as stream: stream.write(b'changed-unsent-tail')
    tree = ast.parse(Path(mixed.__file__).read_bytes())
    fn, = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'verify_unchanged_attempt']
    loop, = [n for n in fn.body if isinstance(n, ast.For)]
    guard, = [n for n in loop.body if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
              and any(isinstance(a, ast.Constant) and a.value == 'MIXED_PREFLIGHT_ACTUAL_SOURCE_EQUALS_FAILED_FINANCIAL_PREFIX'
                      for a in n.value.args)]
    loop.body.remove(guard); namespace = dict(vars(mixed))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), '<removed-complete-tail-hash-guard>', 'exec'), namespace)
    with pytest.raises(ValueError): mixed.verify_unchanged_attempt(tmp_path, spec, request)
    assert namespace['verify_unchanged_attempt'](tmp_path, spec, request)['new_model_not_adopted']
