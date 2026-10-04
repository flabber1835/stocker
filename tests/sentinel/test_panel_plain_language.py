from datetime import datetime, timezone, timedelta
from types import SimpleNamespace

import pytest

from sentinel.panel import model, sources
from sentinel.panel.render import render

NOW = datetime(2026, 10, 4, 20, tzinfo=timezone.utc)


@pytest.mark.parametrize('status', [model.FAIL, model.UNKNOWN, model.WARN])
def test_clear_descriptions_preserve_failed_values_and_precise_reason(status):
    row = model.Row('feed', 'Feed', '2026-10-01', status,
                    'SOURCE_EXPORT_PENDING <unsafe>')
    html = render(model.Panel(rows=[row], now=NOW))
    assert 'Market data' in html
    assert 'latest trading day' in html
    assert f'data-status="{status}"' in html
    assert 'SOURCE_EXPORT_PENDING &lt;unsafe&gt;' in html
    assert '<unsafe>' not in html
    assert 'Technical details' in html
    assert '2026-10-01' in html


def test_decoration_is_inert_and_stale_portfolio_is_never_presented_as_current():
    row = model.Row('shadow_nav', 'Certified shadow NAV', '$53,000.00', model.OK,
                    'original financial evidence', NOW-timedelta(hours=1),
                    freshness=timedelta(minutes=1), required_current=True)
    html = render(model.Panel(rows=[row], now=NOW))
    assert 'Simulated portfolio value' in html
    assert '$53,000.00' in html
    assert 'data-key="shadow_nav" data-status="fail"' in html
    assert 'Attention needed' in html and 'STALE' in html
    assert 'This result is unverified' in html
    assert 'casino-stage" aria-hidden="true"' in html
    assert 'prefers-reduced-motion:reduce' in html
    assert 'animation:none!important' in html
    assert 'Disable notifications' in html
    assert '>Remove</button>' not in html


def test_shadow_source_reads_the_verified_strategy_without_touching_paper(monkeypatch):
    from sentinel import shadow_runtime
    from sentinel.feed import store
    conn = SimpleNamespace(close=lambda: None)
    monkeypatch.setattr(store, 'connect', lambda _: conn)
    monkeypatch.setattr(sources, '_set_statement_timeout', lambda *_: None)
    monkeypatch.setattr(shadow_runtime, 'verified_shadow_status', lambda *a, **k:
        SimpleNamespace(shadow_verdict='SHADOW_GO', verification='VERIFIED',
            session='2026-10-02', sessions_lag=0, strategy_nav='50000',
            strategy_cumulative_return='0'))
    def forbidden(*args, **kwargs):
        raise AssertionError('shadow mode must not read paper reconciliation')
    monkeypatch.setattr(sources, '_dual_paper_row', forbidden)
    rows, details, history, errors = sources._dual_authority_rows(
        'postgresql://panel@db/sentinel', now=NOW, include_paper=False)
    assert not errors and not details and not history
    assert [row.key for row in rows] == ['shadow_verification', 'shadow_nav', 'shadow_return']
    assert all(row.status == model.OK for row in rows)


def test_shadow_build_never_selects_legacy_trial_certificates(monkeypatch):
    monkeypatch.setenv('SENTINEL_REVIEWED_DEPLOYMENT_MODE', 'shadow')
    called=[]
    def selected(*args, **kwargs):
        called.append(kwargs)
        raise RuntimeError('selection reached')
    monkeypatch.setattr(sources, '_dual_authority_rows', selected)
    monkeypatch.setattr(sources, '_trial_rows', lambda *a, **k:
        pytest.fail('obsolete paper trial selected in shadow mode'))
    with pytest.raises(RuntimeError, match='selection reached'):
        sources.build_panel(state_dir=None, database_url='database', now=NOW)
    assert called == [{'now': NOW, 'include_paper': False}]


def test_slow_status_read_dates_document_at_completion_without_redating_facts(monkeypatch):
    clock = [NOW]
    class Clock:
        @staticmethod
        def now(tz):
            return clock[0]
    stale = model.Row('feed', 'Feed', '2026-10-02', model.OK, 'original fact',
                      NOW, freshness=timedelta(seconds=45), required_current=True)
    monkeypatch.setattr(sources, 'datetime', Clock)
    monkeypatch.setenv('SENTINEL_REVIEWED_DEPLOYMENT_MODE', 'shadow')
    def financial(*a, **k):
        clock[0] = NOW + timedelta(seconds=100)
        return [], {}, [], []
    monkeypatch.setattr(sources, '_dual_authority_rows', financial)
    monkeypatch.setattr(sources, '_ownership', lambda *a: model.Row('ownership', '', '', model.OK))
    monkeypatch.setattr(sources, '_feed_rows', lambda *a: ([stale], []))
    monkeypatch.setattr(sources, '_runtime_rows', lambda *a: ([], []))
    monkeypatch.setattr(sources, '_automation_rows', lambda *a:
        ([model.Row('automation', '', '', model.PENDING), model.Row('worker', '', '', model.PENDING)], []))
    monkeypatch.setattr(sources, '_operator_evidence_rows', lambda *a, **k: ([], []))
    panel = sources.build_panel(state_dir='/unused', database_url='database')
    assert panel.now == NOW + timedelta(seconds=100)
    assert panel.row('feed').as_of == NOW
    assert panel.operational == model.FAIL
    html = render(panel)
    assert 'data-generated-at="2026-10-04T20:01:40+00:00"' in html
    assert 'data-key="feed" data-status="fail"' in html
