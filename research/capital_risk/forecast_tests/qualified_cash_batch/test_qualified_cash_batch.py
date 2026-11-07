"""Nonempty source-bound input composition and cash guard falsifiers; DATA only."""
import ast
from copy import deepcopy
import importlib.abc
import json
from pathlib import Path
import sys

import pytest

C = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(C))
import system_campaign_financial_future as future
import system_campaign_qualified_cash_batch as batch


class Fence(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name.startswith(('research.pooled_', 'stock_strategy_shared', 'sentinel', 'numpy', 'pandas')):
            raise ImportError('QUALIFIED_CASH_BATCH_INPUT_ONLY:' + name)


@pytest.fixture(autouse=True)
def fence():
    guard = Fence()
    sys.meta_path.insert(0, guard)
    try:
        yield
    finally:
        sys.meta_path.remove(guard)


@pytest.fixture
def catalog():
    return json.loads((C / 'system-campaign-p05-seven-cash-inputs.json').read_bytes())


def test_actual_seven_inputs_keep_amounts_and_separate_clock_authority(catalog):
    assert batch.validate(catalog)
    terms = batch.QualifiedCashBatch(catalog).catalog['terms']
    assert [(t['ticker'], t['added']['cash_per_share'], t['added']['session']) for t in terms] == [
        ('CXP', 19.30, '2021-12-08'), ('HRC', 156., '2021-12-13'), ('MGLN', 95., '2022-01-04'),
        ('PAE', 10.05, '2022-02-15'), ('RRD', 10.85, '2022-02-25'), ('MCFE', 26., '2022-03-01'),
        ('NUAN', 56., '2022-03-04')]
    assert [t['ticker'] for t in terms if t['preopen_completion_confirmed']] == ['MGLN', 'PAE', 'MCFE']
    assert all(t['recognition_rule'] == future.RESEARCH_CASH for t in terms if not t['preopen_completion_confirmed'])
    assert catalog['historical_causality'] == 'UNVERIFIED'
    assert all(t['parent_positions'] == [] for t in terms)


def test_existing_supplemental_constructor_and_mdp_primary_compose_without_selector_changes(catalog):
    extra, sources = future.supplemental_selection('P05', '2021-11-30')
    primary = future.selected('P05', cursor='2021-11-30')[2]
    terms = future.merge_selected_terms(primary, extra)
    assert len(primary) == 1 and primary[0]['ticker'] == 'MDP'
    assert len(extra) == 7 and len(sources) == 1 and len(terms) == 8
    assert all(t['original_ordinary_source']['validator_file'] == Path(batch.__file__).name for t in extra)
    assert terms[0] == primary[0] and terms[1:] == extra
    terms[1]['added']['cash_per_share'] = 0.
    assert future.supplemental_selection('P05', '2021-11-30')[0][0]['added']['cash_per_share'] == 19.30


@pytest.mark.parametrize('change', ['authority', 'zero_authority', 'loader', 'root', 'cursor', 'outer', 'missing', 'duplicate',
    'order', 'native', 'native_date', 'identity', 'source_clock', 'cash', 'completion', 'primary_amount',
    'currency', 'preopen_claim', 'payment_plus_dividend', 'separate_dividend', 'frozen_dividend'])
def test_mutated_closed_source_or_primary_input_refuses(catalog, change):
    t = catalog['terms'][0]
    if change == 'authority': catalog['canonical_financial_source_changed'] = True
    elif change == 'zero_authority': catalog['production_contacted'] = 0
    elif change == 'loader': catalog['loader_sha256'] = '0'*64
    elif change == 'root': catalog['parent_root_admission_sha256'] = '0'*64
    elif change == 'cursor': catalog['parent_cursor'] = '2021-12-01'
    elif change == 'outer': catalog['parent_outer_sha256'] = '0'*64
    elif change == 'missing': catalog['terms'].pop()
    elif change == 'duplicate': catalog['terms'].append(deepcopy(t))
    elif change == 'order': catalog['terms'].reverse()
    elif change == 'native': t['native']['cash_per_share'] = 19.30
    elif change == 'native_date': t['native_session'] = '2021-12-08'
    elif change == 'identity': t['identity_witness']['issuer_id'] = 'OTHER'
    elif change == 'source_clock': t['source_capture']['run_id'] += 1
    elif change == 'cash': t['added']['cash_per_share'] = 17.13
    elif change == 'completion': t['added']['session'] = '2021-12-09'
    elif change == 'primary_amount': t['primary_extraction']['cash_per_share'] = '21.47'
    elif change == 'currency': t['primary_extraction']['cash_currency'] = 'CAD'
    elif change == 'preopen_claim': t['preopen_completion_confirmed'] = True
    elif change == 'payment_plus_dividend': t['tax_components']['total_payment'] = '21.47'
    elif change == 'separate_dividend': t['tax_components']['separate_dividend_to_add'] = True
    else: t['tax_components']['frozen_final_observations'][0]['dividend_per_share'] = '2.17'
    with pytest.raises((ValueError, KeyError)):
        batch.validate(catalog)


def test_one_payment_guard_removal_really_admits_double_count(catalog):
    t = catalog['terms'][0]
    t['tax_components']['separate_dividend_to_add'] = True
    with pytest.raises(ValueError, match='ONE_PAYMENT_WITHOUT_DUPLICATE_DIVIDEND'):
        batch.validate_tax_components(t)
    fn, = [n for n in ast.parse(Path(batch.__file__).read_bytes()).body
           if isinstance(n, ast.FunctionDef) and n.name == 'validate_tax_components']
    guard, = [n for n in fn.body if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
              and any(isinstance(v, ast.Constant) and v.value == 'CASH_BATCH_ONE_PAYMENT_WITHOUT_DUPLICATE_DIVIDEND'
                      for v in n.value.args)]
    fn.body.remove(guard)
    namespace = dict(vars(batch))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), '<removed-cash-components-guard>', 'exec'), namespace)
    namespace['validate_tax_components'](t)


def test_source_identity_authority_guard_removal_really_admits_financial_flag(catalog):
    proof = catalog['source_data']
    proof['review']['financial_authority'] = True
    proof['qualification']['review_sha256'] = batch.sha(batch.encoded(proof['review']))
    with pytest.raises(ValueError, match='SOURCE_IDENTITY_GRANTS_NO_FINANCIAL_AUTHORITY'):
        batch.source_binding(catalog)
    fn, = [n for n in ast.parse(Path(batch.__file__).read_bytes()).body
           if isinstance(n, ast.FunctionDef) and n.name == 'source_binding']
    guard, = [n for n in fn.body if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
              and any(isinstance(v, ast.Constant) and v.value == 'CASH_BATCH_SOURCE_IDENTITY_GRANTS_NO_FINANCIAL_AUTHORITY'
                      for v in n.value.args)]
    fn.body.remove(guard)
    namespace = dict(vars(batch))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), '<removed-source-authority-guard>', 'exec'), namespace)
    assert namespace['source_binding'](catalog)[1]['financial_authority'] is True


def test_hosted_request_closure_contains_the_new_supplemental_constructor_and_data():
    import system_campaign_financial_resume as resume
    request = resume.expected_request()
    assert request['sources'][Path(batch.__file__).name] == batch.sha(Path(batch.__file__).read_bytes())
    name = 'system-campaign-p05-seven-cash-inputs.json'
    assert request['sources'][name] == batch.sha((C / name).read_bytes())


@pytest.mark.parametrize('quantity', [82, 83])
def test_existing_cash_observer_uses_event_quantity_for_new_batch(catalog, quantity):
    t = catalog['terms'][0]['added']
    sid, price = t['security_id'], t['cash_per_share']
    before = dict(cash=500., episodes={'0':dict(security_id=sid, current_shares=quantity)}, slots={'0':dict(occupied_by=sid)})
    after = dict(cash=500.+quantity*price, episodes={}, slots={'0':dict(occupied_by=None)})
    event = dict(event_type='CASH_MERGER', security_id=sid, price=price, shares_delta=-quantity,
        cash_delta=quantity*price, fees=0., cash_before=500., cash_after=500.+quantity*price,
        detail=dict(shares=quantity, reference=t['reference']))
    proof = future.cash_postcondition(before, after, dict(events=[], receivables=[]),
        dict(events=[event], receivables=[]), t, dict(applied=True))
    assert proof == dict(actual_held=True, quantity=quantity, nominal_cash=quantity*price)


def test_literal_catalog_digest_cannot_be_bypassed_by_mutating_only_input_file(catalog, tmp_path, monkeypatch):
    name = 'system-campaign-p05-seven-cash-inputs.json'
    catalog['terms'][0]['added']['cash_per_share'] = 21.47
    (tmp_path / name).write_bytes(batch.encoded(catalog))
    monkeypatch.setattr(future, 'HERE', tmp_path)
    with pytest.raises(ValueError, match='EXACT_ORIGINAL_SOURCE_BYTES'):
        future.supplemental_selection('P05', '2021-11-30')


@pytest.mark.parametrize('prefix', ['research.pooled_', 'stock_strategy_shared', 'sentinel', 'numpy', 'pandas'])
def test_financial_import_fence(prefix):
    with pytest.raises(ImportError):
        Fence().find_spec(prefix)
