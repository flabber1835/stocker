"""Pure input classification/collision falsifiers; no canonical runtime."""
import ast
from copy import deepcopy
import json
from pathlib import Path

import pytest

import system_campaign_spring2023_preflight as preflight
import system_campaign_action_preflight as strict


def store(root, value):
    raw = json.dumps(value, sort_keys=True).encode()
    h = preflight.sha(raw)
    p = root / 'book/repairs' / (h + '.json')
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(raw)
    return dict(filename=h + '.json', sha256=h, resume_session='2022-01-03',
                predecessor_checkpoint_sha256='1' * 64)


def fixture(tmp_path):
    body = dict(schema=preflight.ORDINARY, suppress=[dict(session='2023-04-27', security_id='CARRIED-ORDINARY')], add=[])
    values = [dict(schema=preflight.ORDINARY, suppress=[], add=[]),
              *[dict(schema=s, **({'canonical_repair': body} if s == preflight.COMPLETION else {}))
                for s in sorted(preflight.MODELS)]]
    descriptors = [store(tmp_path, value) for value in values]
    cp = dict(sha256='2' * 64, source_cursor='2023-03-31', base={}, repairs=descriptors,
              run=dict(input_sha256=preflight.digest(dict(base={}, repairs=descriptors)), state={'cash': 100}))
    # Fixture starts AFTER model admission. Hosted integration must call every
    # real original parser on the full actual CP; these tests make no such claim.
    adapter = preflight.FourModelCalendarPreflight.__new__(preflight.FourModelCalendarPreflight)
    adapter.root = tmp_path.resolve()
    adapter.binding = preflight.binding(cp)
    adapter.models = {v['schema']: d['sha256'] for d, v in zip(descriptors, values) if v['schema'] in preflight.MODELS}
    adapter.body = body
    adapter.model_ids = {'ALDR', 'ZGNX', 'ABMD'}
    adapter.visit = preflight.compile_visitor(Path(strict.__file__).read_bytes())
    catalog = dict(terms=[dict(ticker='NEW', security_id='NEW', native_session='2023-04-27',
                             added=dict(session='2023-04-28', security_id='NEW'))])
    return cp, catalog, adapter


def test_full_four_schema_visitor_preserves_actual_cp_and_strict_default(tmp_path):
    cp, catalog, adapter = fixture(tmp_path)
    before = deepcopy(cp)
    with pytest.raises(ValueError, match='DECLARED_ORDINARY_SCHEMA'):
        strict.analyze_new_catalog(cp, tmp_path, catalog)
    result = adapter.analyze(cp, tmp_path, catalog)
    strict.require_disjoint(result)
    assert cp == before and result['retained_ordinary_repairs'] == 1
    assert len(result['validated_nonordinary_input_sha256']) == 4
    assert result['guarded_canonical_keys_checked'] == 1
    assert result['descriptor_or_financial_checkpoint_projection'] is False
    with pytest.raises(ValueError, match='DECLARED_ORDINARY_SCHEMA'):
        strict.analyze_new_catalog(cp, tmp_path, catalog)


def test_every_descriptor_and_full_input_commitment_stay_bound(tmp_path):
    cp, catalog, adapter = fixture(tmp_path)
    cp['run']['input_sha256'] = '0' * 64
    with pytest.raises(ValueError, match='FULL_ACTUAL_INPUT_COMMITMENT'):
        preflight.documents(tmp_path, cp)
    cp['run']['input_sha256'] = preflight.digest(dict(base=cp['base'], repairs=cp['repairs']))
    p = tmp_path / 'book/repairs' / cp['repairs'][-1]['filename']
    p.write_bytes(p.read_bytes() + b' ')
    with pytest.raises(ValueError, match='EVERY_ORIGINAL_DESCRIPTOR_BYTES'):
        adapter.analyze(cp, tmp_path, catalog)


def test_cp_financial_mutation_and_root_switch_refuse(tmp_path):
    cp, catalog, adapter = fixture(tmp_path)
    cp['run']['state']['cash'] += 1
    with pytest.raises(ValueError, match='FULL_VALIDATED_CHECKPOINT'):
        adapter.analyze(cp, tmp_path, catalog)
    cp['run']['state']['cash'] -= 1
    with pytest.raises(ValueError, match='FULL_VALIDATED_CHECKPOINT'):
        adapter.analyze(cp, tmp_path / 'other', catalog)


@pytest.mark.parametrize('mutation', ['unknown', 'missing', 'duplicate'])
def test_unknown_missing_or_duplicate_model_cannot_be_classified_away(tmp_path, mutation):
    cp, _, _ = fixture(tmp_path)
    if mutation == 'unknown':
        cp['repairs'].append(store(tmp_path, dict(schema='unsupported/fifth-model')))
    elif mutation == 'missing':
        cp['repairs'].pop()
    else:
        cp['repairs'].append(cp['repairs'][-1])
    cp['run']['input_sha256'] = preflight.digest(dict(base=cp['base'], repairs=cp['repairs']))
    with pytest.raises(ValueError, match='NO_UNDECLARED_SCHEMA|FOUR_DISTINCT_RETAINED_MODELS'):
        preflight.documents(tmp_path, cp)


def test_guarded_body_checks_all_carried_ordinary_keys_and_cross_fields(tmp_path):
    cp, catalog, adapter = fixture(tmp_path)
    term = catalog['terms'][0]
    term['security_id'] = term['added']['security_id'] = 'CARRIED-ORDINARY'
    with pytest.raises(ValueError, match='GUARDED_BODY_KEYS_DISJOINT'):
        adapter.analyze(cp, tmp_path, catalog)
    # A requested ADD also cannot collide with a retained SUPPRESS key.
    term['native_session'] = '2023-04-26'
    term['added']['session'] = '2023-04-27'
    with pytest.raises(ValueError, match='GUARDED_BODY_KEYS_DISJOINT'):
        adapter.analyze(cp, tmp_path, catalog)


def test_independent_modeled_identity_overlap_refuses(tmp_path):
    cp, catalog, adapter = fixture(tmp_path)
    catalog['terms'][0]['security_id'] = catalog['terms'][0]['added']['security_id'] = 'ABMD'
    with pytest.raises(ValueError, match='GUARDED_BODY_KEYS_DISJOINT'):
        adapter.analyze(cp, tmp_path, catalog)


def test_original_ordinary_collision_and_consumed_session_guards_remain(tmp_path):
    cp, catalog, adapter = fixture(tmp_path)
    catalog['terms'][0]['native_session'] = '2023-03-31'
    with pytest.raises(ValueError, match='DISJOINT_UNCONSUMED_NEW_ACTIONS'):
        strict.require_disjoint(adapter.analyze(cp, tmp_path, catalog))
    catalog['terms'][0]['native_session'] = '2023-04-27'
    cp['repairs'][0] = store(tmp_path, dict(schema=preflight.ORDINARY,
        suppress=[dict(session='2023-04-27', security_id='NEW')], add=[]))
    cp['run']['input_sha256'] = preflight.digest(dict(base=cp['base'], repairs=cp['repairs']))
    adapter.binding = preflight.binding(cp)
    with pytest.raises(ValueError, match='DISJOINT_UNCONSUMED_NEW_ACTIONS'):
        strict.require_disjoint(adapter.analyze(cp, tmp_path, catalog))


def test_source_hash_and_context_restoration(tmp_path):
    import system_campaign_cash_calendar as cash
    cp, catalog, adapter = fixture(tmp_path)
    with pytest.raises(ValueError, match='ORIGINAL_ORDINARY_VISITOR_SOURCE'):
        preflight.compile_visitor(Path(strict.__file__).read_bytes() + b'\n')
    original = cash.analyze_new_catalog
    with pytest.raises(RuntimeError):
        with adapter:
            strict.require_disjoint(cash.analyze_new_catalog(cp, tmp_path, catalog))
            raise RuntimeError('fixture')
    assert cash.analyze_new_catalog is original is strict.analyze_new_catalog


def test_actual_guard_removal_breaks_carried_ordinary_collision_test(tmp_path):
    cp, catalog, adapter = fixture(tmp_path)
    t = catalog['terms'][0]
    t['security_id'] = t['added']['security_id'] = 'CARRIED-ORDINARY'
    tree = ast.parse(Path(preflight.__file__).read_bytes())
    cls, = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'FourModelCalendarPreflight']
    fn, = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'analyze']
    guard, = [n for n in fn.body if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
              and any(isinstance(a, ast.Constant) and a.value == 'SPRING2023_ALL_VALIDATED_MODEL_AND_GUARDED_BODY_KEYS_DISJOINT'
                      for a in n.value.args)]
    fn.body.remove(guard)
    namespace = dict(vars(preflight))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])),
                 '<actual-carried-body-guard-removed>', 'exec'), namespace)
    with pytest.raises(ValueError):
        adapter.analyze(cp, tmp_path, catalog)
    assert namespace['analyze'](adapter, cp, tmp_path, catalog)['status'] == 'DISJOINT_UNCONSUMED'
