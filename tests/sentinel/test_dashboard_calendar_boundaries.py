"""Calendar instants retain their deadlines when entering the UTC wire contract."""
from dataclasses import replace
from datetime import date, timedelta, timezone
import inspect

import pytest

from sentinel.feed import calendar
from sentinel.panel import model, operational_snapshot as snapshots, presentation
from sentinel.paper_plan_preview import PlanPreview

CONTEXT = 'a' * 64
SUBJECTS = {'SHADOW': 'b' * 64, 'PAPER': 'c' * 64}


@pytest.fixture(autouse=True)
def signing_key(monkeypatch):
    monkeypatch.setenv('SENTINEL_PUBLICATION_RECEIPT_KEY', 'private-calendar-qualification-' + 'x' * 40)


def published_page(day):
    opened, _ = calendar.session_window(day)
    opened_utc = opened.astimezone(timezone.utc)
    now = opened_utc - timedelta(seconds=10)
    created = now - timedelta(hours=16)
    work = model.PreparationWork(job_id='closed-data', decision_session=date.fromisoformat(day)-timedelta(days=1),
        effective_session=date.fromisoformat(day), state='PUBLISHED', rows_done=10, components_done=1,
        created_at=created, updated_at=created, last_progress_at=created, observed_at=now,
        deadline=opened_utc+timedelta(hours=7), owner_registered=False, fence=0)
    page = model.Panel(now=now, rows=[model.Row('ingest', 'Data', 'PUBLISHED', model.OK,
        as_of=now, valid_until=now+timedelta(seconds=45), required_current=True, preparation=work)])
    return page, opened_utc


@pytest.mark.parametrize('day', ['2026-11-06', '2026-06-01'])
def test_published_preparation_keeps_exact_open_in_utc(day):
    page, opened = published_page(day)
    boundary = presentation.dashboard_health(page)['valid_until']
    assert boundary == opened.isoformat()
    expiry = snapshots.original_boundary(page)
    assert expiry == opened and expiry.utcoffset() == timedelta(0)
    value, signed = snapshots.encode(page, context_sha256=CONTEXT, subjects=SUBJECTS, valid_until=expiry)
    assert value['valid_until'] == opened.isoformat()
    current = snapshots.decode(value, signed, context_sha256=CONTEXT, now=opened-timedelta(microseconds=1))
    assert current.valid_until == opened
    with pytest.raises(snapshots.SnapshotUnavailable, match='EXPIRED'):
        snapshots.decode(value, signed, context_sha256=CONTEXT, now=opened)


def test_nested_market_time_plan_cannot_make_non_utc_expiry():
    page, opened = published_page('2026-11-06')
    market_open, _ = calendar.session_window('2026-11-06')
    intent = PlanPreview(cycle_id='cycle', plan_id='plan', decision_session=date(2026,11,5),
        effective_session=date(2026,11,6), execute_at=market_open, created_at=page.now-timedelta(hours=16),
        observation_at=page.now-timedelta(hours=16), legs=[])
    page = replace(page, rows=[model.Row('paper_plan', 'Plan', 'SAVED', paper_plan=intent)])
    expiry = snapshots.original_boundary(page)
    assert expiry == opened and expiry.utcoffset() == timedelta(0)
    value, _ = snapshots.encode(page, context_sha256=CONTEXT, subjects=SUBJECTS, valid_until=expiry)
    assert value['valid_until'] == opened.isoformat()


def test_output_conversion_does_not_admit_non_utc_input_rows():
    page, _ = published_page('2026-11-06')
    market_open, _ = calendar.session_window('2026-11-06')
    page = replace(page, rows=[replace(page.rows[0], as_of=market_open-timedelta(seconds=10))])
    with pytest.raises(snapshots.SnapshotUnavailable, match='ROW_CLOCK'):
        snapshots.encode(page, context_sha256=CONTEXT, subjects=SUBJECTS)


@pytest.mark.parametrize('module,name,oracle,args', [
    (presentation, 'dashboard_health', test_published_preparation_keeps_exact_open_in_utc, ('2026-11-06',)),
    (snapshots, 'original_boundary', test_nested_market_time_plan_cannot_make_non_utc_expiry, ()),
])
def test_removed_utc_output_conversion_is_detected(monkeypatch, module, name, oracle, args):
    body = inspect.getsource(getattr(module, name))
    guard = '.astimezone(timezone.utc)'
    assert body.count(guard) == 1
    namespace = {}
    exec(compile(body.replace(guard, ''), '<removed-calendar-utc-conversion>', 'exec'), vars(module), namespace)
    monkeypatch.setattr(module, name, namespace[name])
    with pytest.raises(AssertionError):
        oracle(*args)
