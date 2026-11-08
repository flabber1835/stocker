"""Synthetic price paths only; no local replay of financial evidence."""
from fractions import Fraction
import json
from pathlib import Path

import pytest

import core_entry_stop_diagnostic as study
import core_entry_stop_job as job


def path(*values):
    return [('D'+str(i).zfill(2), study.number(v)/100) for i, v in enumerate(values)]


def test_initial_stop_is_inclusive_and_armed_from_first_owned_close():
    signal = study.stop_signal(path(100, 95, 90), True)
    assert signal['day'] == 'D02' and signal['floor'] == Fraction('.90')
    assert study.stop_signal(path(80, 75), True) is None


def test_widening_never_lowers_the_actual_floor():
    signal = study.stop_signal(path(100, 109, 110, 120, 97), True)
    assert signal['day'] == 'D04' and signal['floor'] == Fraction('.981')
    assert [v['width'] for v in signal['widths']] == [Fraction('.10'), Fraction('.20'), Fraction('.30')]


def test_stages_use_owned_peak_and_do_not_reset_after_pullback():
    signal = study.stop_signal(path(100, 120, 110, 109, 99, 89), True)
    assert signal['day'] == 'D05' and signal['floor'] == Fraction('.90')
    assert signal['widths'][-1]['width'] == Fraction('.30')


def test_baseline_is_constant_thirty_percent():
    assert study.stop_signal(path(100, 109, 90, 77), False) is None
    assert study.stop_signal(path(100, 110, 77), False)['day'] == 'D02'


def test_next_open_is_strictly_after_signal_and_can_wait_for_an_observed_quote():
    signal = study.stop_signal(path(100, 89), True)
    assert study.next_open(signal, [('D01', Fraction('.95')), ('D04', Fraction('.80'))]) == ('D04', Fraction('.80'))
    assert study.next_open(signal, [('D01', Fraction('.95'))]) is None


def test_splits_are_neutral_and_missing_close_does_not_become_a_signal():
    buy = dict(security_id='S', session='D00', shares_delta=10, price=100)
    snap = dict(wealth_core={'episodes': {'0': dict(security_id='S', entry_date='D00', current_shares=20)}},
                prices={'S': dict(status='CURRENT', raw_price=55)})
    assert study.position_value(snap, buy) == Fraction('1.10')
    snap['prices']['S']['status'] = 'CARRIED'
    assert study.position_value(snap, buy) is None
    assert study.position_value(snap, buy, allow_carried=True) == Fraction('1.10')


@pytest.mark.parametrize('value', (float('nan'), float('inf'), True))
def test_unusable_arithmetic_refuses(value):
    with pytest.raises(ValueError):
        study.number(value)


def test_committed_reader_ignores_uncommitted_tail_and_rejects_corruption(tmp_path):
    raw = b'{"row":1}\n'
    p = tmp_path/'daily.jsonl'
    p.write_bytes(raw+b'UNCOMMITTED')
    cp = {'journals': {'daily': dict(bytes=len(raw), prefix_sha256=study.sha(raw))}}
    assert study.committed(tmp_path, cp, 'daily') == [{'row': 1}]
    p.write_bytes(b'{"row":2}\n')
    with pytest.raises(ValueError, match='DIAGNOSTIC_COMMITTED_PREFIX'):
        study.committed(tmp_path, cp, 'daily')


def test_transport_cannot_promote_diagnostic_to_financial_root():
    from core_volatility_admit import extract
    with pytest.raises(ValueError, match='REVIEWED_STATUS_ONLY'):
        extract(None, None, None, {'status': study.STATUS})


def test_data_probe_and_exact_parameter_refusal(tmp_path):
    value = job.expected_request()
    p = tmp_path/'request.json'
    p.write_bytes(json.dumps(value).encode())
    assert job.probe(p)['canonical_runtime_executed'] is False
    value['widths'] = ['0.05', '0.20', '0.30']
    p.write_bytes(json.dumps(value).encode())
    with pytest.raises(ValueError, match='EXACT_STOP_DIAGNOSTIC_SOURCE_CLOSURE'):
        job.probe(p)


def test_actual_replay_job_is_hosted_only(tmp_path):
    with pytest.raises(ValueError, match='REFUSED_CONTEXT'):
        job.run(tmp_path/'request.json', tmp_path/'output.json')


def test_direct_actual_replay_is_hosted_only(tmp_path):
    with pytest.raises(ValueError, match='REFUSED_CONTEXT'):
        study.replay(tmp_path/'not-a-book')
