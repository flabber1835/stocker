"""Input metadata and independent arithmetic only; never canonical execution."""
from copy import deepcopy
from fractions import Fraction
import ast
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import system_campaign_close_basis as basis
import system_campaign_close_facts as facts
import system_campaign_close_review as review


def test_contract_preserves_all_adopted_bytes_and_exact_intraday_scope():
    value = facts.contract();event = value['event']
    assert len(value['inherited_sources']) == 247
    assert event['added']['exchange_ratio'] == '0.03002'
    assert event['added']['cash_per_share'] == 30.
    assert event['added']['cash_in_lieu_price_per_delivered_share'] is None
    assert event['preopen_completion_claimed'] is False
    assert event['exact_effective_clock_claimed'] is False
    assert len(facts.IMPLEMENTATIONS) == 5
    assert all((facts.HERE / name).is_file() for name in facts.IMPLEMENTATIONS)


def descriptors(tmp_path, *, close=True):
    schemas = basis.previous.previous.original_preflight.MODELS | {
        basis.previous.previous.SCHEMA, basis.previous.SCHEMA, 'terminal-repair/1'}
    if close: schemas |= {basis.SCHEMA}
    directory = tmp_path / 'book/repairs';directory.mkdir(parents=True)
    cp = dict(base={'inert': True}, repairs=[], run={})
    for schema in sorted(schemas):
        raw = json.dumps(dict(schema=schema)).encode();sha = facts.sha(raw)
        descriptor = dict(filename=sha + '.json', sha256=sha)
        (directory / descriptor['filename']).write_bytes(raw)
        cp['repairs'].append(descriptor)
    cp['run']['input_sha256'] = facts.digest(dict(base=cp['base'], repairs=cp['repairs']))
    return cp


@pytest.mark.parametrize('close', [False, True])
def test_full_real_descriptor_admission_retains_six_or_seven_models(tmp_path, close):
    cp = descriptors(tmp_path, close=close);before = deepcopy(cp)
    actual = basis.documents(tmp_path, cp)
    assert len(actual) == 7 + int(close) and cp == before
    assert {v['schema'] for _, v in actual} == {
        basis.previous.previous.SCHEMA, basis.previous.SCHEMA, 'terminal-repair/1',
        *basis.previous.previous.original_preflight.MODELS,
        *({basis.SCHEMA} if close else set())}


@pytest.mark.parametrize('change', ['unknown', 'body', 'input', 'filename', 'duplicate'])
def test_full_descriptor_admission_cannot_hide_mutated_or_undeclared_inputs(tmp_path, change):
    cp = descriptors(tmp_path)
    descriptor = cp['repairs'][0]
    if change == 'unknown':
        raw = json.dumps(dict(schema='undeclared/1')).encode();sha = facts.sha(raw)
        descriptor.update(filename=sha + '.json', sha256=sha)
        (tmp_path / 'book/repairs' / descriptor['filename']).write_bytes(raw)
    elif change == 'body':
        (tmp_path / 'book/repairs' / descriptor['filename']).write_bytes(b'{}')
    elif change == 'filename': descriptor['filename'] = 'unbound.json'
    elif change == 'duplicate': cp['repairs'].append(deepcopy(descriptor))
    if change != 'input':
        cp['run']['input_sha256'] = facts.digest(dict(base=cp['base'], repairs=cp['repairs']))
    else: cp['run']['input_sha256'] = '0'*64
    with pytest.raises(ValueError): basis.documents(tmp_path, cp)


def test_semantic_dispatch_changes_only_declared_schema_classification():
    old = basis.previous.original_semantic_visitor();new = basis.semantic_visitor()
    assert new.__code__.co_code == old.__code__.co_code
    assert new.__code__.co_consts == old.__code__.co_consts
    assert new.__globals__['ADDITIONAL_SCHEMAS'] == old.__globals__['ADDITIONAL_SCHEMAS'] | {basis.SCHEMA}


def test_new_fact_delta_preserves_every_prior_semantic_value():
    old = dict(schema='old', factual_semantics=dict(suppress=[], add=[], declared_fact_compilers={}),
        factual_semantics_sha256='old', model_semantics=[{'old': i} for i in range(6)])
    before = deepcopy(old)
    model = SimpleNamespace(canonical_repair=dict(suppress=[dict(session='2023-11-06', security_id='TWNK')],
        add=[dict(session='2023-11-07', security_id='TWNK', cash_per_share=30., exchange_ratio='0.03002')]))
    refs = {'new-source': '1'*64};scope = {'scope': basis.SCOPE}
    new = basis.append_semantics(old, model, refs, scope)
    assert old == before and new['model_semantics'] == [*before['model_semantics'], scope]
    assert new['factual_semantics']['declared_fact_compilers'] == refs
    assert new['factual_semantics_sha256'] == facts.digest(new['factual_semantics'])
    with pytest.raises(ValueError): basis.append_semantics(new, model, refs, scope)


def arithmetic_fixture():
    # Inert invented prices, independently evaluated without any account runtime.
    expected = float((Fraction(30) + Fraction('0.03002')*Fraction('110.25')) * Fraction('0.9'))
    certificate = dict(session='2023-11-07', next_state_sha256='1'*64, input_sha256='2'*64,
        material=dict(rows=[dict(security_id='TWNK', current=[expected, expected])]))
    row = dict(session='2023-11-07', state_sha256='1'*64, input_sha256='2'*64)
    return certificate, row, ['2023-11-06', 100., 90.]


def check(certificate, row, anchor):
    return review.require_closing_notional(certificate, row, 'TWNK', anchor, 110.25, '2023-11-07', '2023-11-06')


def test_independent_exact_fraction_arithmetic():
    certificate, row, anchor = arithmetic_fixture()
    actual = check(certificate, row, anchor)
    assert actual['signal_consideration'] == certificate['material']['rows'][0]['current'][0]


@pytest.mark.parametrize('change', ['cash', 'upper', 'input', 'state', 'day', 'anchor', 'missing', 'duplicate'])
def test_independent_notional_rejects_value_and_binding_mutations(change):
    certificate, row, anchor = arithmetic_fixture()
    items = certificate['material']['rows']
    if change == 'cash': items[0]['current'][0] += .01
    elif change == 'upper': items[0]['current'][1] += .01
    elif change == 'input': certificate['input_sha256'] = '0'*64
    elif change == 'state': certificate['next_state_sha256'] = '0'*64
    elif change == 'day': certificate['session'] = '2023-11-08'
    elif change == 'anchor': anchor[0] = '2023-11-03'
    elif change == 'missing': items.clear()
    else: items.append(deepcopy(items[0]))
    with pytest.raises(ValueError): check(certificate, row, anchor)


@pytest.mark.parametrize('count', [0, 1, 2])
def test_streamed_certificate_requires_exactly_one_actual_session(tmp_path, count):
    certificate, _, _ = arithmetic_fixture();path = tmp_path / 'certificate.jsonl'
    rows = [dict(session='2023-11-06'), *[certificate for _ in range(count)], dict(session='2023-11-08')]
    path.write_text(''.join(json.dumps(v)+'\n' for v in rows), encoding='utf8')
    if count == 1: assert review.certificate_for(path, '2023-11-07') == certificate
    else:
        with pytest.raises(ValueError): review.certificate_for(path, '2023-11-07')


def without_guard(module, function, label):
    node, = [v for v in ast.parse(Path(module.__file__).read_bytes()).body
             if isinstance(v, ast.FunctionDef) and v.name == function]
    class Remove(ast.NodeTransformer):
        count = 0
        def visit_Expr(self, value):
            if isinstance(value.value, ast.Call) and any(isinstance(v, ast.Constant)
                    and v.value == label for v in value.value.args):
                self.count += 1
                return ast.Pass()
            return self.generic_visit(value)
    change = Remove();node = change.visit(node);assert change.count == 1
    namespace = dict(vars(module))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])),
                 '<actual-close-guard-removal-falsifier>', 'exec'), namespace)
    return namespace[function]


def test_actual_notional_guard_removal_admits_mutated_economic_value():
    certificate, row, anchor = arithmetic_fixture()
    certificate['material']['rows'][0]['current'][0] += .01
    with pytest.raises(ValueError): check(certificate, row, anchor)
    broken = without_guard(review, 'require_closing_notional',
        'CLOSE_REVIEW_ACTUAL_COMMITTED_EXACT_CLOSING_NOTIONAL')
    assert broken(certificate, row, 'TWNK', anchor, 110.25, '2023-11-07', '2023-11-06')


def test_actual_filename_guard_prevents_any_undeclared_path_read(tmp_path, monkeypatch):
    cp = descriptors(tmp_path);cp['repairs'][0]['filename'] = '../escape.json'
    old = Path.read_bytes
    def read(path):
        if path.name == 'escape.json': raise RuntimeError('UNDECLARED_PATH_WAS_READ')
        return old(path)
    monkeypatch.setattr(Path, 'read_bytes', read)
    with pytest.raises(ValueError, match='EXACT_DESCRIPTOR_FILENAME_BEFORE_READ'):
        basis.documents(tmp_path, cp)
    broken = without_guard(basis, 'documents', 'CLOSE_BASIS_EXACT_DESCRIPTOR_FILENAME_BEFORE_READ')
    with pytest.raises(RuntimeError, match='UNDECLARED_PATH_WAS_READ'): broken(tmp_path, cp)
