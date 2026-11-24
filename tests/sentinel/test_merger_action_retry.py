"""A selected-only source gap can reobserve actions without replaying a book."""
from contextlib import nullcontext
from datetime import timedelta

import pytest

from sentinel import rolling_runtime, shadow_budget
from sentinel.core.window_continuity import MergerActionPending
from sentinel.feed import calendar, rolling_go_inputs


SESSION = '2026-11-23'
CURSOR = '2026-11-20'


class _Connection:
    def __init__(self):
        self.rollbacks = 0

    def rollback(self):
        self.rollbacks += 1


def _service_case(monkeypatch, *, after_open=False):
    opened, _ = calendar.session_window(calendar.next_session(SESSION))
    conn = _Connection()
    marker = object()
    prepared = []
    commits = []
    monkeypatch.delenv('SENTINEL_FEED_SERVICE_MODE', raising=False)
    monkeypatch.setattr(shadow_budget, 'cutoff', lambda: opened + timedelta(hours=1))
    monkeypatch.setattr(shadow_budget, 'now', lambda: opened + timedelta(seconds=1)
                        if after_open else opened - timedelta(hours=1))
    monkeypatch.setattr(rolling_runtime, 'classify', lambda *_a, **_k:
                        {'status': 'ATTESTED_STRUCTURAL', 'latest_session': CURSOR})
    monkeypatch.setattr(rolling_runtime.initial, '_now', lambda _conn: opened - timedelta(hours=2))
    monkeypatch.setattr(rolling_runtime.initial, '_timing', lambda *_a, **_k: {})
    monkeypatch.setattr(rolling_runtime, 'prepare_adjacent', lambda *_a, **_k: {'snapshot_id': 'old'})
    monkeypatch.setattr(rolling_runtime.journal, 'writer_lock', lambda *_a, **_k: nullcontext())

    def reobserve(*_a, **kwargs):
        prepared.append(kwargs)
        return {'snapshot_id': 'corrected'}

    def commit(*_a, **kwargs):
        commits.append(kwargs['prepared_binding'])
        if len(commits) == 1:
            raise MergerActionPending(SESSION, 'old-id')
        return marker

    monkeypatch.setattr(rolling_go_inputs, '_prepare', reobserve)
    monkeypatch.setattr(rolling_runtime, 'advance', commit)
    return conn, marker, opened, prepared, commits


def test_selected_action_gap_reobserves_once_before_open(monkeypatch):
    conn, marker, opened, prepared, commits = _service_case(monkeypatch)
    result = rolling_runtime.service_advance(
        conn, through=SESSION, observation_id='test', starting_cash=100_000)
    assert result is marker
    assert commits == [{'snapshot_id': 'old'}, {'snapshot_id': 'corrected'}]
    assert len(prepared) == 1
    assert prepared[0]['target_session'] == SESSION
    assert prepared[0]['absolute_deadline'] == opened
    assert prepared[0]['continuation'] is True
    assert prepared[0]['force_action_reobserve'] is True
    assert conn.rollbacks >= 2


def test_selected_action_gap_cannot_reobserve_for_missed_open(monkeypatch):
    conn, _marker, _opened, prepared, commits = _service_case(monkeypatch, after_open=True)
    with pytest.raises(MergerActionPending, match='SELECTED_IDENTITY_ACTION_PENDING'):
        rolling_runtime.service_advance(
            conn, through=SESSION, observation_id='test', starting_cash=100_000)
    assert commits == [{'snapshot_id': 'old'}]
    assert prepared == []
