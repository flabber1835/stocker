"""Segment caveats preserve the complete current operational evidence."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from sentinel.panel import model, segment_disclosure as disclosure


@pytest.mark.parametrize('failed', [False, True])
def test_disclosure_preserves_local_mode_and_all_original_row_boundaries(monkeypatch, failed):
    from sentinel.feed import store
    from sentinel.panel import sources
    now = datetime(2031, 4, 21, 20, tzinfo=timezone.utc)
    row = model.Row('shadow_nav', 'NAV', '100', model.OK, as_of=now,
                    valid_until=now+timedelta(seconds=7), required_current=True)
    page = model.Panel(rows=[row], now=now, local_paper_mode=True,
                       trial_details={'original': True}, trial_history=[{'verdict': 'NOT_VERIFIED'}])
    class Connection:
        def close(self): pass
    monkeypatch.setenv('SENTINEL_REVIEWED_DEPLOYMENT_MODE', 'dual')
    monkeypatch.setattr(store, 'connect', lambda *_: Connection())
    monkeypatch.setattr(sources, '_set_statement_timeout', lambda *_: None)
    def segment(*_):
        if failed: raise ValueError('qualification refusal')
        return SimpleNamespace(index=1, first_session='2031-04-21', reason='causal outage',
                               predecessor_session='2031-04-18', marker_sha256='a'*64)
    monkeypatch.setattr(disclosure.shadow_segments, 'active_segment', segment)
    result = disclosure.disclose(page, 'dbname=qualification')
    assert result.local_paper_mode and result.now == now
    assert result.trial_details == page.trial_details and result.trial_history == page.trial_history
    observed = result.row('shadow_nav')
    assert observed.as_of == row.as_of and observed.valid_until == row.valid_until
    assert observed.required_current == row.required_current
    assert bool(result.source_errors) == failed
    if not failed:
        assert result.row('shadow_segment') is not None and 'NOT trial-to-date' in observed.detail
