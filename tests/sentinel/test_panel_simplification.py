"""Shared display policies retain their boundaries across every consumer."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import inspect
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from sentinel.panel import app, authority_reader, model, observer_codec, overview, retry_status, sources
from sentinel.panel.render import render
from tests.sentinel.test_panel_plan_first_render import example_panel, NOW, EXECUTE


def cycle(**changes):
    opened = datetime(2026, 10, 23, 13, 30, tzinfo=timezone.utc)
    value = dict(cycle_id='cycle', plan_id='plan', state='RETRY_WAIT',
        decision_session='2026-10-22', effective_session='2026-10-23',
        retry_phase='EXECUTE', phase_attempt_count=2, attempt_count=7,
        phase_max_attempts=4, next_wake_at=opened+timedelta(minutes=2),
        execution_open_at=opened, execute_at=opened+timedelta(minutes=1),
        original_execution_deadline_at=opened+timedelta(minutes=10),
        execution_close_at=opened+timedelta(hours=6, minutes=30),
        failure_code='TEMPORARY', failure_detail='bounded original retry',
        updated_at=opened, failure_domain='BROKER')
    value.update(changes)
    return value


def views(value):
    summary = model.automation_cycle_row(installed=True, enabled=True,
        **{key: item for key, item in value.items()
           if key in sources._AUTOMATION_CYCLE_ROW_FIELDS})
    steps = model.automation_step_rows(installed=True, enabled=True, cycle=value)
    return summary, steps[4], sources._cycle_recovery(value)


def test_generic_retry_is_projected_once_with_same_bounds_and_phase():
    summary, step, source = views(cycle())
    assert summary.recovery == step.recovery == source
    assert source.phase == 'AUTOMATION_EXECUTE'
    assert (source.attempt, source.maximum_attempts) == (2, 4)
    assert source.next_attempt_at == cycle()['next_wake_at']
    assert source.deadline is None


def test_legacy_count_fallback_remains_explicit_and_is_not_lent_to_sources():
    value = cycle(phase_attempt_count=None, attempt_count=2)
    summary, step, source = views(value)
    assert summary.recovery.attempt == step.recovery.attempt == 2
    assert source.attempt is None
    assert not source.active(value['updated_at'])


def test_clean_execution_uses_only_original_cutoff_and_domain_filters_still_apply():
    value = cycle(failure_code=None, failure_detail=None, phase_max_attempts=None)
    summary, step, source = views(value)
    assert summary.recovery == step.recovery == source
    assert source.phase == 'CLEAN_RECOVERY_EXECUTION_WAKE'
    assert source.deadline == value['original_execution_deadline_at']
    assert not source.active(source.deadline+timedelta(microseconds=1))
    assert sources._cycle_recovery(value, phases=('PREPARE',)) is None
    assert sources._cycle_recovery(value, failure_domains=('BACKUP',)) is None
    domain = sources._cycle_recovery(value, failure_domains=('BROKER',))
    assert domain.phase == 'AUTOMATION_EXECUTE' and domain.deadline is None
    invalid = views({**value, 'original_execution_deadline_at': value['execution_close_at']})
    assert all(item.deadline is None for item in (invalid[0].recovery, invalid[1].recovery, invalid[2]))


def malformed_availability():
    return cycle(retry_phase='PREPARE', availability_retry_unbounded=True,
        callback_failure='SOFTWARE_DEFECT', exception_type='builtins.RuntimeError',
        phase_attempt_count=1, phase_max_attempts=8, failure_code=None, failure_detail=None)


def test_typed_refusal_cannot_fall_through_to_positive_day_or_generic_wait(monkeypatch):
    value = malformed_availability()
    wait = SimpleNamespace(plan_id=value['plan_id'], effective_session=value['effective_session'],
        observed_at=value['updated_at'], deadline=value['execution_close_at'], commands=('order',))
    monkeypatch.setattr(retry_status, 'protected_day_wait', lambda *args: wait)
    summary, step, source = views(value)
    # PREPARE is the detailed current step for this deliberately contradictory fixture.
    step = model.automation_step_rows(installed=True, enabled=True, cycle=value)[2]
    assert summary.recovery == step.recovery == source
    assert source.phase == 'AUTOMATION_PREPARE_AVAILABILITY_REFUSED'
    assert source.operator_required and not source.active(value['updated_at'])
    assert retry_status.project_cycle_recovery(value).protected_wait is None


def test_removing_typed_refusal_is_detected_by_its_regression(monkeypatch):
    original = inspect.getsource(retry_status.project_cycle_recovery)
    assert original.count('if refused is not None:') == 1
    namespace = dict(vars(retry_status))
    exec(original.replace('if refused is not None:', 'if False:', 1), namespace)
    monkeypatch.setattr(retry_status, 'project_cycle_recovery', namespace['project_cycle_recovery'])
    monkeypatch.setattr(model, 'project_cycle_recovery', namespace['project_cycle_recovery'])
    with pytest.raises(AssertionError):
        test_typed_refusal_cannot_fall_through_to_positive_day_or_generic_wait(monkeypatch)


@pytest.mark.parametrize('phase', ['EXECUTE', 'RECOVER', 'prepare', 'CORRUPT', None])
def test_explicit_availability_flag_cannot_borrow_another_phase_allowance(phase):
    value = cycle(retry_phase=phase, availability_retry_unbounded=True,
        callback_failure='SOURCE_DATA_PENDING', exception_type='sentinel.automation.model.SourceDataPending',
        failure_code=None, failure_detail=None, phase_max_attempts=None)
    projection = retry_status.project_cycle_recovery(value)
    assert projection.availability_refused
    assert projection.evidence.operator_required
    assert not projection.evidence.active(value['updated_at'])
    assert not projection.clean_execution_wait


def test_restricting_refusal_to_historical_phases_is_detected(monkeypatch):
    original = inspect.getsource(retry_status.availability_refusal)
    needle = "and cycle.get('availability_retry_unbounded') is True):"
    assert original.count(needle) == 1
    namespace = dict(vars(retry_status))
    exec(original.replace(needle, "and cycle.get('availability_retry_unbounded') is True and cycle.get('retry_phase') in ('REFRESH', 'PREPARE')):"), namespace)
    monkeypatch.setattr(retry_status, 'availability_refusal', namespace['availability_refusal'])
    with pytest.raises(AssertionError):
        test_explicit_availability_flag_cannot_borrow_another_phase_allowance('EXECUTE')


def payload(monkeypatch, panel):
    monkeypatch.setattr(app, '_config', lambda: (Path('.'), ''))
    monkeypatch.setattr(app, '_read_panel', lambda: panel)
    monkeypatch.setattr(app, '_shadow_segment_disclosure', lambda value, _: value)
    return {row['key']: row for row in json.loads(app.panel_json().body)['rows']}


@pytest.mark.parametrize('negative', ['fail', 'expired', 'future-row', 'future-payload'])
@pytest.mark.parametrize('key,field,withheld', [
    ('paper_plan', 'paper_plan', 'data-security-id="PANW"'),
    ('alpaca_account', 'paper_account', '$9,635.82')])
def test_html_and_json_withdraw_the_same_plan_and_account(monkeypatch, key, field, withheld, negative):
    panel = example_panel()
    row = panel.row(key)
    if negative == 'fail':
        changed = replace(row, status=model.FAIL)
    elif negative == 'expired':
        changed = replace(row, valid_until=NOW-timedelta(microseconds=1))
    elif negative == 'future-row':
        changed = replace(row, as_of=NOW+model.MAXIMUM_FUTURE_SKEW+timedelta(microseconds=1))
    else:
        clock = 'created_at' if key == 'paper_plan' else 'observed_at'
        changed = replace(row, **{field: getattr(row, field).model_copy(
            update={clock: NOW+model.MAXIMUM_FUTURE_SKEW+timedelta(microseconds=1)})})
    panel = replace(panel, rows=[changed if item.key == key else item for item in panel.rows])
    assert payload(monkeypatch, panel)[key][field] is None
    assert withheld not in overview.overview_html(panel)


def test_saved_plan_is_withdrawn_from_both_surfaces_at_execution_start(monkeypatch):
    panel = replace(example_panel(), now=EXECUTE)
    assert payload(monkeypatch, panel)['paper_plan']['paper_plan'] is None
    assert 'data-security-id="PANW"' not in overview.overview_html(panel)


def test_order_outcomes_keep_original_clock_and_shared_future_guard(monkeypatch):
    panel = example_panel()
    row = panel.row('paper_plan')
    original = row.order_outcomes[0]
    future = original.model_copy(update={'observed_at': NOW+model.MAXIMUM_FUTURE_SKEW+timedelta(microseconds=1)})
    row = replace(row, order_outcomes=[future])
    panel = replace(panel, rows=[row if item.key == row.key else item for item in panel.rows])
    assert row.visible_order_outcomes(NOW) == []
    assert payload(monkeypatch, panel)[row.key]['order_outcomes'] == []
    assert 'Previous buy ended unfilled' not in overview.overview_html(panel)
    assert original.observed_at == example_panel().row('paper_plan').order_outcomes[0].observed_at


def test_missing_monitor_withdraws_authority_without_starting_an_http_observer(monkeypatch):
    from sentinel.panel.verification_monitor import monitor
    monkeypatch.setattr(monitor, 'read', lambda *args, **kwargs: None)
    monkeypatch.setattr(authority_reader.Reader, 'read', lambda *args, **kwargs:
        pytest.fail('HTTP must not start another financial observer'))
    rows, _, _, errors = sources._bounded_dual_authority_rows('fixture', now=NOW)
    assert errors and 'not initialized' in errors[0]
    assert {row.key for row in rows} == {'shadow_verification', 'shadow_nav', 'shadow_return',
        'paper_reconciliation', 'exposure', 'book', 'terminals'}
    assert not any(row.status == model.OK for row in rows)


def test_composition_records_receipt_error_ownership_without_text_guessing(monkeypatch):
    from sentinel.panel.verification_monitor import monitor

    monkeypatch.setenv('SENTINEL_REVIEWED_DEPLOYMENT_MODE', 'dual')
    owned = {'SHADOW': ['same text'], 'PAPER': ['same text']}
    def financial(_database_url, *, include_paper, with_error_scopes):
        assert include_paper and with_error_scopes
        return ([model.Row('shadow_verification', 'Shadow', 'UNKNOWN', model.UNKNOWN)],
                {}, [], ['same text', 'same text'], owned)
    monkeypatch.setattr(monitor, 'read', financial)
    monkeypatch.setattr(sources, '_ownership', lambda *_: model.Row('ownership', 'Ownership', 'CURRENT'))
    monkeypatch.setattr(sources, '_shadow_worker_row',
                        lambda *_args, **_kwargs: model.Row('shadow_worker', 'Worker', 'CURRENT'))
    monkeypatch.setattr(sources, '_feed_rows', lambda *_args: ([], []))
    monkeypatch.setattr(sources, '_runtime_rows', lambda *_args: ([], []))
    monkeypatch.setattr(sources, '_automation_rows', lambda *_args: ([
        model.Row('automation', 'Automation', 'CURRENT'),
        model.Row('automation_leader', 'Leader', 'CURRENT')], []))
    monkeypatch.setattr(sources, '_operator_evidence_rows', lambda *_args, **_kwargs: ([], []))
    page = sources.build_panel(state_dir=Path('/private'), database_url='fixture', now=NOW)
    assert page.financial_source_errors == owned
    assert page.source_errors == ['same text', 'same text']


def test_shared_observer_codec_round_trip_preserves_bounds_and_dated_book():
    row = example_panel().row('book')
    raw = observer_codec.pack([row], [], observed_at=NOW)
    observer_codec.validate_envelope(raw, {'book'})
    restored = observer_codec.row_from_observation(raw['rows'][0])
    assert restored == row and restored.as_of == row.as_of
    assert restored.shadow_book.session == row.shadow_book.session
    with pytest.raises(ValueError, match='exceeds bound'):
        observer_codec.pack([replace(row, detail='x'*(observer_codec.MAX_BYTES+1))], [], observed_at=NOW)
    with pytest.raises(ValueError, match='shape is incomplete'):
        observer_codec.validate_envelope({**raw, 'rows': raw['rows']*2}, {'book'})


def test_atomic_styles_keep_push_controller_and_remove_unused_animation():
    from sentinel.panel.render import DEVICE_ASSET, STYLE_ASSET, STATIC_ASSETS

    html = render(example_panel())
    css, _ = STATIC_ASSETS[STYLE_ASSET]
    script, _ = STATIC_ASSETS[DEVICE_ASSET]
    assert html.count('<style id="dashboard-stylesheet"') == 1
    assert 'rel="stylesheet"' not in html
    assert f'data-source-href="/static/{STYLE_ASSET}"' in html and css.count('--bg:') == 2
    assert html.count(css) == 1 and script not in html
    assert 'casino-stage' not in html and 'casino-accent' not in html
    assert '@keyframes' not in css
    assert 'id="push-enable"' in html and 'id="push-remove"' in html
    assert f'src="/static/{DEVICE_ASSET}"' in html and 'navigator.serviceWorker.register' in script
    assert 'prefers-reduced-motion:reduce' in css


def test_panel_wire_encoding_keeps_evidence_uncached_and_fingerprint_assets_immutable(monkeypatch):
    from hashlib import sha256
    from fastapi.testclient import TestClient
    from sentinel.panel import app as panel_app
    from sentinel.panel.render import STATIC_ASSETS

    page = example_panel()
    clock = int(page.now.timestamp() * 1000)
    monkeypatch.setattr(panel_app, '_read_panel', lambda: page)
    monkeypatch.setattr(panel_app, 'time_ns', lambda: clock * 1_000_000)
    client = TestClient(panel_app.app)
    for route in ('/?document=1', '/panel.json'):
        exact = client.get(route, headers={'Accept-Encoding': 'identity'})
        encoded = client.get(route, headers={'Accept-Encoding': 'gzip'})
        refused = client.get(route, headers={'Accept-Encoding': 'gzip;q=0, *;q=1'})
        assert exact.status_code == encoded.status_code == refused.status_code == 200
        assert 'content-encoding' not in exact.headers and 'content-encoding' not in refused.headers
        assert encoded.headers['content-encoding'] == 'gzip'
        assert int(encoded.headers['content-length']) < len(exact.content)
        assert encoded.content == exact.content == refused.content
        for response in (exact, encoded, refused):
            assert response.headers['cache-control'] == 'no-store'
            assert response.headers['vary'] == 'Accept-Encoding'
            assert response.headers['x-sentinel-panel-status'] == exact.headers['x-sentinel-panel-status']
            if route == '/?document=1':
                assert response.headers['x-sentinel-server-time'] == str(clock)
                assert f'data-server-time="{clock}"' in response.text

    for asset in STATIC_ASSETS:
        resource = client.get(f'/static/{asset}')
        assert resource.status_code == 200
        assert sha256(resource.content).hexdigest() == asset.split('.')[1]
        assert resource.headers['cache-control'] == 'public, max-age=31536000, immutable'
    for asset in ('dashboard.css', 'dashboard-device.js', 'caesars-palace-512.png'):
        assert client.get(f'/static/{asset}').headers['cache-control'] == 'no-store'


def test_production_projection_has_no_retired_in_panel_worker():
    from sentinel.panel import verification_monitor
    assert not hasattr(verification_monitor,'Monitor')
    assert not hasattr(verification_monitor,'observe_shadow')
    assert not hasattr(verification_monitor,'observe_paper')
