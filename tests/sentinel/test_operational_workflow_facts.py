"""Formatting cannot create, invalidate or substitute native workflow facts."""
from dataclasses import replace
from datetime import date

import pytest

from sentinel.panel import model, observer_codec, presentation
from tests.sentinel.test_panel_historical_mirror_schedule import healthy_history_panel
from tests.sentinel.test_panel_completed_history_health import completed_panel
from tests.sentinel.test_panel_closing_preparation_health import verified_calculation_panel


@pytest.mark.parametrize('factory', [healthy_history_panel, completed_panel, verified_calculation_panel])
def test_all_typed_workflow_copy_can_change_without_changing_health(factory):
    page = factory()
    before = presentation.dashboard_health(page)
    assert before['color'] == 'green'
    changed = replace(page, rows=[replace(row, value='Compatible renderer wording',
        detail='Original typed facts and clocks retained.') if row.operational_fact else row
        for row in page.rows])
    assert presentation.health_facts(changed) == presentation.health_facts(page)
    assert presentation.dashboard_health(changed) == before


@pytest.mark.parametrize('key', ['automation', 'feed', 'shadow_verification',
                                 'automation_cycle', 'automation_step_open'])
def test_familiar_copy_without_fact_cannot_earn_current_scheduled_health(key):
    page = healthy_history_panel()
    changed = replace(page, rows=[replace(row, operational_fact=None) if row.key == key else row
                                  for row in page.rows])
    assert presentation.dashboard_health(changed)['color'] != 'green'


def test_removed_source_fact_requirement_has_an_executed_falsifier(monkeypatch):
    monkeypatch.setattr(presentation, '_current_input_session', lambda *args: True)
    with pytest.raises(AssertionError):
        test_familiar_copy_without_fact_cannot_earn_current_scheduled_health('feed')


@pytest.mark.parametrize('payload', [
    dict(kind='MARKET_DATA', state='WAITING_OPEN', session='2026-10-30', sessions_behind=0),
    dict(kind='MARKET_DATA', state='READY', session='2026-10-30'),
    dict(kind='MARKET_DATA', state='READY', session='2026-10-30', sessions_behind=-1),
    dict(kind='SHADOW_VERIFICATION', state='VERIFIED'),
    dict(kind='AUTOMATION_POLICY', state='ENABLED_RELEASED', session='2026-10-30'),
    dict(kind='PAPER_VERIFICATION', state='READY'),
    dict(kind='CONTROLLER_DECISION', state='NOT_ADOPTED', session='2026-10-30', exposure='1.10'),
    dict(kind='CONTROLLER_DECISION', state='NOT_ADOPTED', session='2026-10-30', exposure='0.1234567890123'),
    dict(kind='PAPER_VERIFICATION', state='CHECKING', arbitrary=True),
])
def test_unknown_or_incoherent_operational_facts_refuse(payload):
    with pytest.raises(ValueError):
        model.OperationalFact.model_validate(payload)


def test_native_fact_roundtrip_and_legacy_missing_fact_are_distinct():
    page = healthy_history_panel()
    row = page.row('feed')
    packed = observer_codec.pack([row], [], observed_at=page.now)['rows'][0]
    assert packed['operational_fact']['session'] == '2026-10-30'
    assert observer_codec.row_from_observation(packed) == row
    packed.pop('operational_fact')
    legacy = observer_codec.row_from_observation(packed)
    assert legacy.operational_fact is None
    assert legacy.value == row.value and legacy.status == row.status


def test_foreign_row_or_retyped_model_cannot_claim_another_producers_fact():
    fact = model.OperationalFact(kind='MARKET_DATA', state='READY',
                                 session=date(2026,10,30), sessions_behind=0)
    with pytest.raises(ValueError, match='another row'):
        model.Row('book', 'Book', 'VERIFIED', operational_fact=fact)
    with pytest.raises(ValueError):
        model.Row('feed', 'Feed', 'READY',
                  operational_fact=fact.model_copy(update={'state':'WAITING_OPEN'}))
