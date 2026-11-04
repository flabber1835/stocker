"""Confirmed cash rights and a later frozen-session convention; DATA only."""
import ast
from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import system_campaign_financial_future as f


def term():
    _, _, terms = f.selected('P04', cursor='2022-08-31')
    # Preserve the refused Oct3 convention's guards as a separate synthetic input.
    t = deepcopy(terms[0])
    t['recognition_rule'] = f.NEXT_COMPLETION
    t['primary_extraction']['recognition_convention'] = 'FIRST_FROZEN_SESSION_STRICTLY_AFTER_CONFIRMED_COMPLETION'
    t['added']['session'] = '2022-10-03'
    return t


def test_confirmed_ctrix_cash_right_has_explicit_later_session_not_preopen_assertion():
    t = term(); f.completion_cash_term(t)
    assert t['added']['cash_per_share'] == 104. and t['actual_completion_date'] == '2022-09-30'
    assert t['preopen_completion_confirmed'] is False and t['primary_extraction']['preopen_time_established'] is False
    assert t['added']['session'] == '2022-10-03' and t['recognition_rule'] == f.NEXT_COMPLETION
    assert t['source_capture']['run_id'] == 41798315426 and t['parent_positions'] == []
    assert f.suppressions(dict(source_cursor='2022-08-31'), [t]) == [dict(
        session='2022-09-29', security_id=t['security_id'], term_sha256=t['native_term_sha256'])]
    f.completion_session(t, ['2022-09-28', '2022-09-29', '2022-09-30', '2022-10-03'])


@pytest.mark.parametrize('change', ['cash', 'preopen', 'primary_preopen', 'completion', 'mandatory', 'delivery', 'kind'])
def test_wrong_cash_right_or_unproved_earlier_timing_refuses(change):
    t = term()
    if change == 'cash': t['added']['cash_per_share'] = 103.
    elif change == 'preopen': t['preopen_completion_confirmed'] = True
    elif change == 'primary_preopen': t['primary_extraction']['preopen_time_established'] = True
    elif change == 'completion': t['actual_completion_date'] = '2022-10-03'
    elif change == 'mandatory': t['mandatory_common_share_completion_confirmed'] = False
    elif change == 'delivery': t['added']['delivered_security_id'] = 'fabricated'
    else: t['added']['kind'] = 'CONVERSION'
    with pytest.raises(ValueError): f.completion_cash_term(t)


@pytest.mark.parametrize('change', ['same_day', 'skip', 'missing', 'unordered', 'duplicate', 'no_following'])
def test_effective_day_must_be_the_actual_next_frozen_session(change):
    t = term(); dates = ['2022-09-29', '2022-09-30', '2022-10-03', '2022-10-04']
    if change == 'same_day': t['added']['session'] = '2022-09-30'
    elif change == 'skip': t['added']['session'] = '2022-10-04'
    elif change == 'missing': dates.remove('2022-10-03')
    elif change == 'unordered': dates.reverse()
    elif change == 'duplicate': dates.insert(0, dates[0])
    else: dates = dates[:2]
    with pytest.raises(ValueError): f.completion_session(t, dates)


def broken_helper(name, label):
    fn = next(n for n in ast.parse(Path(f.__file__).read_bytes()).body if isinstance(n, ast.FunctionDef) and n.name == name)
    guard, = [n for n in fn.body if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
              and any(isinstance(a, ast.Constant) and a.value == label for a in n.value.args)]
    fn.body.remove(guard); ns = dict(vars(f))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), '<removed-completion-date-guard>', 'exec'), ns)
    return ns[name]


def test_removed_date_guard_accepts_same_day_open_without_preopen_proof():
    t = term(); t['added']['session'] = '2022-09-30'
    with pytest.raises(ValueError): f.completion_session(t, ['2022-09-30', '2022-10-03'])
    broken_helper('completion_session', 'OWN_INPUT_ACTUAL_FROZEN_FIRST_SESSION_AFTER_COMPLETION')(t, ['2022-09-30', '2022-10-03'])


def test_calendar_completion_need_not_be_a_trading_session():
    t=term();t['actual_completion_date']='2018-12-05';t['added']['session']='2018-12-06'
    dates=['2018-12-03','2018-12-04','2018-12-06','2018-12-07']
    f.completion_session(t,dates)
    t['actual_completion_date']='2018-12-04'
    f.completion_session(t,dates)


@pytest.mark.parametrize('change',['duplicate','unordered','early','skip','no_following'])
def test_off_axis_completion_keeps_exact_calendar_guard_with_removal_falsifier(change):
    t=term();t['actual_completion_date']='2018-12-05';t['added']['session']='2018-12-06'
    dates=['2018-12-03','2018-12-04','2018-12-06','2018-12-07']
    if change=='duplicate':dates.append(dates[-1])
    elif change=='unordered':dates.reverse()
    elif change=='early':t['added']['session']='2018-12-04'
    elif change=='skip':t['added']['session']='2018-12-07'
    else:dates=dates[:2]
    with pytest.raises(ValueError,match='ACTUAL_FROZEN_FIRST_SESSION_AFTER_COMPLETION'):f.completion_session(t,dates)
    broken_helper('completion_session','OWN_INPUT_ACTUAL_FROZEN_FIRST_SESSION_AFTER_COMPLETION')(t,dates)


def test_removed_right_guard_accepts_an_unproved_preopen_claim():
    t = term(); t['preopen_completion_confirmed'] = True
    with pytest.raises(ValueError): f.completion_cash_term(t)
    broken_helper('completion_cash_term', 'OWN_INPUT_EXACT_CONFIRMED_CASH_RIGHT_AND_LATER_SESSION_CONVENTION')(t)


def test_closed_four_term_generation_still_has_exact_original_bytes():
    codec, _, _ = f.selected('P00', cursor='2018-08-31')
    assert len(codec.catalog['terms']) == 4
    assert codec.catalog_sha == '629b3e64ab7cf6aae2cf54c733d65acc8c9cc3b2465d68b19a58b0918a09efe2'


def test_arii_own232_uses_closed_source230_and_exact_nontrading_completion():
    codec,catalog,terms=f.selected('P03',cursor='2018-11-30');t,=terms
    assert catalog==f.OWN_CASH_CATALOG and len(codec.catalog['terms'])==18
    assert codec.catalog_sha=='332a92d9dbfaea1b9154fbb2c2e0f397dbd5fa96686d148401d3607cce3a6a03'
    assert t['ticker']=='ARII' and t['added']['cash_per_share']==70.
    assert t['parent_positions']==[] and t['actual_completion_date']=='2018-12-05'
    assert t['added']['session']=='2018-12-06' and t['source_capture']['run_id']==41934413763
    f.completion_cash_term(t)
    f.completion_session(t,['2018-12-03','2018-12-04','2018-12-06','2018-12-07'])
    prior,_,_=f.selected('P05',cursor='2020-01-31')
    assert len(prior.catalog['terms'])==17 and prior.catalog_sha=='c93bb3e00a7990b25fe146ced63407ce582e1da9511c1b94c8039e8e04b90f89'
