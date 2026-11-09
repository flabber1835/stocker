"""Synthetic unit economics only; real replay remains GitHub-hosted."""
from fractions import Fraction
import json
from pathlib import Path

import pytest

import core_entry_sizing_diagnostic as study
import core_entry_sizing_job as job


def example(**changes):
    values = dict(entry='D0', notional=1000, buy_fee=1, raw_entry=100,
        closes=[('D0', 1), ('D1', '.95'), ('D2', '.80')],
        openings=[('D1', '.97', 97), ('D2', '.85', 85)],
        terminal_ratio='.70', exit_fee_rate='.001', dividends=[],
        owned_days=['D0', 'D1', 'D2'], exit_day='D3')
    values.update(changes)
    return study.staged_trade(**values)


def test_failed_start_without_confirmation_has_one_fifth_of_loss_and_fees():
    r = example()
    assert r['baseline_profit'] == Fraction('-301.70')
    assert r['staged_profit'] == Fraction('-60.34')
    assert r['unused_budget'] == Fraction('800.80')
    assert r['staged_capital_days']/r['baseline_capital_days'] == Fraction('.20')
    assert r['staged_buy_fee'] == Fraction('.20') and len(r['tranches']) == 1


def test_actual_next_open_gap_cost_is_not_replaced_by_confirmation_price():
    r = example(buy_fee=0, exit_fee_rate=0, terminal_ratio=4,
        closes=[('D0', 1), ('D1', '1.10'), ('D2', '1.20'), ('D3', 2)],
        openings=[('D1', '1.05', 105), ('D2', 2, 200), ('D3', 2, 200)],
        owned_days=['D0', 'D1', 'D2', 'D3'], exit_day='D4')
    assert [t['day'] for t in r['tranches']] == ['D0', 'D2', 'D3']
    assert r['staged_profit'] == 1400 and r['baseline_profit'] == 3000
    assert r['staged_capital_days'] == 1900 and r['baseline_capital_days'] == 4000


def test_both_gates_can_fill_together_at_one_actual_following_open():
    r = example(closes=[('D0', '1.30'), ('D1', 2)], openings=[('D1', '2.14', 214)],
                owned_days=['D0', 'D1'], exit_day='D2', terminal_ratio=3)
    assert [t['day'] for t in r['tranches']] == ['D0', 'D1', 'D1']
    assert r['terminal_units'] == Fraction('.20')+Fraction('.80')/Fraction('2.14')
    assert r['invested_fraction'] == 1


def test_no_addition_on_an_original_exit_day():
    r = example(closes=[('D0', 1), ('D1', '1.10')], openings=[('D2', '1.11', 111)],
                owned_days=['D0', 'D1'], exit_day='D2')
    assert len(r['tranches']) == 1 and r['unfilled'][0]['signal_day'] == 'D1'


def test_additions_are_not_entitled_to_same_day_ex_dividend():
    r = example(closes=[('D0', '1.10'), ('D1', '1.20'), ('D2', '1.20')],
        openings=[('D1', '1.10', 110), ('D2', '1.20', 120)],
        dividends=[('D1', 10), ('D2', 10)])
    assert r['baseline_dividends'] == 20
    assert r['staged_dividends'] == Fraction(74, 11)


def test_buying_all_tranches_at_same_price_reproduces_full_budget_result():
    r = example(closes=[('D0', '1.30'), ('D1', '1.30'), ('D2', '1.50')],
        openings=[('D1', 1, 100)], terminal_ratio='1.50', dividends=[('D2', 10)])
    assert r['invested_fraction'] == r['terminal_units'] == 1
    assert r['baseline_profit'] == r['staged_profit']


def test_fractional_screen_discloses_starter_that_cannot_buy_one_whole_share():
    r = example(raw_entry=1000)
    assert r['starter_one_share_unaffordable'] and r['one_share_unaffordable'] == 1


def test_split_neutral_normalized_units_match_actual_raw_share_purchase():
    r = example(closes=[('D0', '1.10'), ('D1', '1.10'), ('D2', '1.10')],
                openings=[('D1', '1.10', 55)])
    added = r['tranches'][1]
    assert added['fraction']/added['ratio']*20 == Fraction(300, 55)


def test_open_cutoff_close_cannot_generate_a_fill_after_the_window():
    r = example(closes=[('D0', 1), ('D1', 1), ('D2', '1.25')],
                openings=[('D1', 1, 100), ('D2', 1, 100)], exit_day=None)
    assert len(r['tranches']) == 1 and all(t['signal_day'] == 'D2' for t in r['unfilled'])


def test_original_reader_source_is_still_exactly_pinned():
    assert study.sha(Path(study.reader.__file__).read_bytes()) == study.READER_SHA


def test_data_contract_cannot_change_sizes_or_resume_financial_books(tmp_path):
    value = job.expected_request()
    assert value['cumulative_budget_fractions'] == ['0.20', '0.50', '1.00']
    assert value['trailing_stop_unchanged'] == '0.30' and not value['original_backtests_changed']
    assert value['diagnostic_only'] and not value['financial_continuation_authorized']
    p = tmp_path/'request.json'
    p.write_bytes(json.dumps(value).encode())
    assert job.probe(p)['canonical_runtime_executed'] is False
    value['cumulative_budget_fractions'][0] = '0.50'
    p.write_bytes(json.dumps(value).encode())
    with pytest.raises(ValueError, match='EXACT_SIZING_DIAGNOSTIC_SOURCE_CLOSURE'):
        job.probe(p)


def test_new_status_cannot_be_promoted_to_financial_artifact_authority():
    from core_volatility_admit import extract
    with pytest.raises(ValueError, match='REVIEWED_STATUS_ONLY'):
        extract(None, None, None, {'status': study.STATUS})


def test_actual_replay_is_hosted_only(tmp_path):
    with pytest.raises(ValueError, match='REFUSED_CONTEXT'):
        study.replay(tmp_path/'not-a-financial-book')


def test_actual_job_is_hosted_only(tmp_path):
    with pytest.raises(ValueError, match='REFUSED_CONTEXT'):
        job.run(tmp_path/'request.json', tmp_path/'output.json')
