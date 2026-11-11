"""Receipt overlays and current plan adoption keep their original proof bounds."""
from dataclasses import replace
from datetime import date, datetime, timedelta
import inspect

import pytest

from sentinel.panel import model, postclose_feed_wait, presentation
from tests.sentinel.test_panel_closing_preparation_health import verified_calculation_panel
from tests.sentinel.test_panel_closing_data_wait import NOW, OPEN
from tests.sentinel.test_panel_historical_mirror_schedule import changed_history_panel
from tests.sentinel.test_panel_postclose_feed_wait import facts, feed


def test_receipt_overlay_reprojects_the_same_feed_dependency_without_renewing_clocks():
    rows, worker = facts()
    raw = feed()
    ingest = model.Row('ingest', 'Ingest', 'PUBLISHED', model.OK)
    instant = worker.as_of
    page = model.Panel(rows=[*rows, worker, raw, ingest], now=instant)
    projected = postclose_feed_wait.reproject(page, now=instant)
    waiting = projected.row('feed')
    assert waiting.status == model.WARN and waiting.recovery.phase == 'POST_CLOSE_SOURCE_WAIT'
    assert waiting.as_of == raw.as_of and waiting.valid_until <= raw.valid_until
    assert postclose_feed_wait.reproject(projected, now=instant) == projected
    broken = replace(projected, rows=[replace(row, status=model.UNKNOWN) if row.key == 'shadow_worker'
                                     else row for row in projected.rows])
    withdrawn = postclose_feed_wait.reproject(broken, now=instant).row('feed')
    assert withdrawn.status == model.FAIL and withdrawn.recovery is None
    assert withdrawn.as_of == waiting.as_of and withdrawn.valid_until == waiting.valid_until
    for negative in [feed(ready=False), replace(raw, status=model.UNKNOWN)]:
        broken = replace(page, rows=[negative if row.key == 'feed' else row for row in page.rows])
        assert postclose_feed_wait.reproject(broken, now=instant).row('feed') == negative


def test_removed_feed_dependency_projection_has_an_executed_falsifier(monkeypatch):
    monkeypatch.setattr(postclose_feed_wait, '_project_frontier', lambda row, *a, **kw: row)
    with pytest.raises(AssertionError):
        test_receipt_overlay_reprojects_the_same_feed_dependency_without_renewing_clocks()


def adoption_page(phase):
    page = verified_calculation_panel()
    active = phase == 'REFRESHING_DATA'
    wake = None if active else NOW+timedelta(seconds=1)
    cycle = model.automation_cycle_row(installed=True, enabled=True, cycle_id='close-cycle',
        state='REFRESHING_DATA' if active else 'RETRY_WAIT', decision_session='2026-10-22',
        effective_session='2026-10-23', updated_at=NOW, execution_open_at=OPEN,
        next_wake_at=wake, retry_phase=None if active else phase,
        availability_retry_unbounded=None if active else True,
        callback_failure=None if active else 'TRANSIENT_INFRASTRUCTURE',
        exception_type=None if active else 'sentinel.automation.model.TransientInfrastructureFailure',
        phase_attempt_count=None if active else 3)
    return replace(page, rows=[cycle if row.key == cycle.key else row for row in page.rows])


@pytest.mark.parametrize('phase', ['REFRESHING_DATA', 'REFRESH', 'PREPARE'])
def test_verified_new_decision_waits_for_adoption_without_hiding_its_cycle_warning(phase):
    page = adoption_page(phase)
    health = presentation.dashboard_health(page)
    assert health['active_conditions'] == [] and health['color'] == 'amber'
    assert 'automation_cycle' in health['review_conditions']
    assert health['plan_readiness'] == 'pending'
    assert page.row('exposure').operational_fact.state == 'NOT_ADOPTED'
    assert page.row('exposure').effective_status(NOW) == model.FAIL
    assert page.operational == model.FAIL
    if phase != 'REFRESHING_DATA':
        assert datetime.fromisoformat(health['valid_until']) <= NOW+timedelta(seconds=1)
        due = replace(page, now=NOW+timedelta(seconds=1))
        assert 'exposure' in presentation.health_facts(due)['active']


@pytest.mark.parametrize('defect', ['source_session', 'actual_failure', 'unknown', 'clock', 'owner', 'state'])
def test_unproved_adoption_wait_preserves_the_negative(defect):
    page = adoption_page('REFRESH')
    row = page.row('exposure')
    cycle = page.row('automation_cycle')
    if defect == 'source_session':
        wrong = page.row('feed').operational_fact.model_copy(update={'session':date(2026, 10, 21)})
        page = changed_history_panel(page, 'feed', operational_fact=wrong)
    elif defect in {'actual_failure', 'unknown'}:
        page = changed_history_panel(page, row.key, status=model.FAIL if defect == 'actual_failure' else model.UNKNOWN)
    elif defect == 'clock':
        page = changed_history_panel(page, cycle.key, recovery=replace(cycle.recovery, deadline=OPEN))
    elif defect == 'owner':
        page = changed_history_panel(page, 'automation_leader', status=model.UNKNOWN)
    else:
        page = changed_history_panel(page, cycle.key,
            operational_fact=model.OperationalFact(kind='AUTOMATION_CYCLE', state='PREPARING'))
    assert 'exposure' in presentation.health_facts(page)['active']


def test_removed_adoption_source_binding_has_an_executed_falsifier(monkeypatch):
    body = inspect.getsource(presentation._deferred_adoption_boundary)
    guard = 'or not _current_input_session(panel, session)'
    assert body.count(guard) == 1
    namespace = dict(vars(presentation))
    exec(compile(body.replace(guard, 'or False'), '<removed adoption source identity>', 'exec'), namespace)
    monkeypatch.setattr(presentation, '_deferred_adoption_boundary', namespace['_deferred_adoption_boundary'])
    with pytest.raises(AssertionError):
        test_unproved_adoption_wait_preserves_the_negative('source_session')
