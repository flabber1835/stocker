import copy
from decimal import Decimal

import pytest

from research.slow15_replay.model import digest, helper, oracle, update_metrics, validate_resume


def test_only_slow_duration_changes():
    ns, _ = helper()
    current, slow = (ns['ProbeController'](n) for n in ('current', 'slow_earlier'))
    a, b = current.Native.step.__globals__, slow.Native.step.__globals__
    for name in ('ORD_DD', 'FAST', 'LDRC_DD', 'LDRC_R20', 'LDRC_CEIL', 'LDRC_REC'):
        assert a[name] == b[name]
    assert a['SLOW'] == b['SLOW'] | {'dur': 30}
    assert b['SLOW']['dur'] == 15
    assert current.identity != slow.identity
    with pytest.raises(ValueError, match='identity'):
        slow.restore(current.snapshot())


def test_slow_response_on_fifteenth_qualifying_close_and_restart():
    ns, _ = helper()
    current, slow = (ns['ProbeController'](n) for n in ('current', 'slow_earlier'))
    for i in range(15):
        observation = dict(zip(ns['FIELDS'], (-.2, -.01, -.02, -.03, -.1, .9, .1, 0., -.02, 0., 0, 100. if i == 0 else 97.)))
        row = dict(observation=observation, leadership=dict(recent_r20=-.1, recent_r40=-.1))
        before = slow.snapshot()
        result = slow.step(row)
        assert current.step(row)['target'] == 1.
        restored = ns['ProbeController']('slow_earlier')
        restored.restore(before)
        assert restored.step(row) == result
        assert restored.snapshot() == slow.snapshot()
        assert result['target'] == (0. if i == 14 else 1.)


def test_exit_pays_for_overnight_loss_before_selling():
    previous = dict(strategy_nav='100', last_session='2006-07-31', pending_allocation='0', held_allocation='1', parent_core_close_equity='100')
    result = dict(parent_core_open_equity='80', parent_core_close_equity='120',
                  bil_open_adjusted='1.01', bil_close_adjusted='1.0302', bil_previous_close_adjusted_current_publication='1')
    assert oracle(previous, result) == Decimal('81.5184')
    result['parent_core_close_equity'] = '40'
    assert oracle(previous, result) == Decimal('81.5184')


def test_first_close_does_not_earn_a_past_return():
    assert oracle(dict(strategy_nav='100000', last_session=None), {}) == Decimal('100000')


def test_measurement_uses_july_close_not_january_capital():
    assert update_metrics({}, '2006-07-28', '92500') == {}
    m = update_metrics({}, '2006-07-31', '90000')
    m = update_metrics(m, '2026-07-31', '180000')
    assert Decimal(m['multiple']) == 2
    assert m['cagr'] == pytest.approx(2**(365.2425/7305)-1)
    with pytest.raises(ValueError, match='baseline'):
        update_metrics({}, '2006-08-01', '100000')


def fixture():
    row = dict(binding={'rule': 'slow15'}, cursor='2006-07-31', economics={'last_session': '2006-07-31'})
    row['sha256'] = digest(row)
    return row


def test_resume_binding_and_cursor_and_commitment():
    row = fixture()
    assert validate_resume(row, {'rule': 'slow15'}, '2006-07-31') == row
    with pytest.raises(ValueError, match='binding'):
        validate_resume(row, {'rule': 'current'}, '2006-07-31')
    with pytest.raises(ValueError, match='cursor'):
        validate_resume(row, row['binding'], '2006-08-01')
    changed = copy.deepcopy(row)
    changed['economics']['strategy_nav'] = '200000'
    with pytest.raises(ValueError, match='commitment'):
        validate_resume(changed, row['binding'], row['cursor'])
