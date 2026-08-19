"""#185: a current market frontier is not sufficient source authority."""
from __future__ import annotations

import datetime as dt
from unittest import mock

from sentinel.feed import maintenance, readiness


def _cursor(kind: str, day: str, version: int = 7):
    return maintenance.SourceCursor(
        kind=kind, processed_through=dt.date.fromisoformat(day),
        publication_version=version)


def _checks(result):
    return {check.name: check for check in result.checks}


def test_source_maintenance_checks_pass_when_frontier_is_covered():
    result = readiness._impl.Readiness()
    with (mock.patch.object(
            readiness._maintenance, "load_sep_cursor",
            return_value=_cursor("sharadar-sep-lastupdated/v1", "2026-08-18")),
          mock.patch.object(
            readiness._maintenance, "load_actions_cursor",
            return_value=_cursor("sharadar-actions-reconcile/v1", "2026-08-16"))):
        readiness._add_source_maintenance_checks(
            object(), result, today="2026-08-18T20:00:00-04:00",
            required_through="2026-08-18")

    checks = _checks(result)
    assert checks["SEP mutation watermark"].status == readiness.PASS
    assert checks["ACTIONS complete reconciliation"].status == readiness.PASS
    assert result.ready


def test_next_open_does_not_require_that_days_post_close_maintenance():
    """Friday's immutable decision remains executable at Monday's open."""
    result = readiness._impl.Readiness()
    with (mock.patch.object(
            readiness._maintenance, "load_sep_cursor",
            return_value=_cursor("sharadar-sep-lastupdated/v1", "2026-08-14")),
          mock.patch.object(
            readiness._maintenance, "load_actions_cursor",
            return_value=_cursor("sharadar-actions-reconcile/v1", "2026-08-10"))):
        readiness._add_source_maintenance_checks(
            object(), result, today="2026-08-17T09:30:00-04:00",
            required_through="2026-08-14")

    checks = _checks(result)
    assert checks["SEP mutation watermark"].status == readiness.PASS
    assert checks["ACTIONS complete reconciliation"].status == readiness.PASS
    assert result.ready


def test_newer_weekend_maintenance_also_covers_older_decision_frontier():
    result = readiness._impl.Readiness()
    with (mock.patch.object(
            readiness._maintenance, "load_sep_cursor",
            return_value=_cursor("sharadar-sep-lastupdated/v1", "2026-08-16")),
          mock.patch.object(
            readiness._maintenance, "load_actions_cursor",
            return_value=_cursor("sharadar-actions-reconcile/v1", "2026-08-16"))):
        readiness._add_source_maintenance_checks(
            object(), result, today="2026-08-17T09:30:00-04:00",
            required_through="2026-08-14")
    assert result.ready


def test_post_publication_sep_failure_cannot_leave_readiness_green():
    """Monday's published close cannot pass while its CDC remains at Friday."""
    result = readiness._impl.Readiness()
    with (mock.patch.object(
            readiness._maintenance, "load_sep_cursor",
            return_value=_cursor("sharadar-sep-lastupdated/v1", "2026-08-14")),
          mock.patch.object(
            readiness._maintenance, "load_actions_cursor",
            return_value=_cursor("sharadar-actions-reconcile/v1", "2026-08-14"))):
        readiness._add_source_maintenance_checks(
            object(), result, today="2026-08-17T18:00:00-04:00",
            required_through="2026-08-17")

    checks = _checks(result)
    assert checks["SEP mutation watermark"].status == readiness.FAIL
    assert "behind published decision frontier" in checks[
        "SEP mutation watermark"].detail
    assert not result.ready


def test_actions_cursor_becomes_blocking_when_due_at_decision_frontier():
    result = readiness._impl.Readiness()
    frontier = dt.date(2026, 8, 18)
    due = (frontier
           - dt.timedelta(days=maintenance.ACTIONS_RECONCILE_DAYS)).isoformat()
    with (mock.patch.object(
            readiness._maintenance, "load_sep_cursor",
            return_value=_cursor("sharadar-sep-lastupdated/v1", "2026-08-18")),
          mock.patch.object(
            readiness._maintenance, "load_actions_cursor",
            return_value=_cursor("sharadar-actions-reconcile/v1", due))):
        readiness._add_source_maintenance_checks(
            object(), result, today="2026-08-18",
            required_through=frontier.isoformat())

    checks = _checks(result)
    assert checks["SEP mutation watermark"].status == readiness.PASS
    assert checks["ACTIONS complete reconciliation"].status == readiness.FAIL
    assert "is due every" in checks["ACTIONS complete reconciliation"].detail
    assert not result.ready


def test_actions_cadence_does_not_expire_between_decision_and_next_open():
    """Cadence authority is frozen at the decision, not aged by execution wait."""
    result = readiness._impl.Readiness()
    # Six days old at Friday's decision: valid. Nine calendar days old by the
    # following Monday execution: still valid for Friday's already-frozen plan.
    with (mock.patch.object(
            readiness._maintenance, "load_sep_cursor",
            return_value=_cursor("sharadar-sep-lastupdated/v1", "2026-08-14")),
          mock.patch.object(
            readiness._maintenance, "load_actions_cursor",
            return_value=_cursor("sharadar-actions-reconcile/v1", "2026-08-08"))):
        readiness._add_source_maintenance_checks(
            object(), result, today="2026-08-17T09:30:00-04:00",
            required_through="2026-08-14")
    assert result.ready


def test_missing_or_corrupt_maintenance_authority_fails_closed():
    missing = readiness._impl.Readiness()
    with (mock.patch.object(
            readiness._maintenance, "load_sep_cursor", return_value=None),
          mock.patch.object(
            readiness._maintenance, "load_actions_cursor", return_value=None)):
        readiness._add_source_maintenance_checks(
            object(), missing, today="2026-08-18",
            required_through="2026-08-18")
    assert not missing.ready
    assert all(c.status == readiness.FAIL for c in missing.checks)

    corrupt = readiness._impl.Readiness()
    with (mock.patch.object(
            readiness._maintenance, "load_sep_cursor",
            side_effect=maintenance.SharadarMutationRefused("bad SEP cursor")),
          mock.patch.object(
            readiness._maintenance, "load_actions_cursor",
            side_effect=maintenance.SharadarMutationRefused("bad ACTIONS cursor"))):
        readiness._add_source_maintenance_checks(
            object(), corrupt, today="2026-08-18",
            required_through="2026-08-18")
    assert not corrupt.ready
    assert all(c.status == readiness.FAIL for c in corrupt.checks)


def test_future_source_cursors_are_not_normalized_into_pass():
    result = readiness._impl.Readiness()
    with (mock.patch.object(
            readiness._maintenance, "load_sep_cursor",
            return_value=_cursor("sharadar-sep-lastupdated/v1", "2026-08-19")),
          mock.patch.object(
            readiness._maintenance, "load_actions_cursor",
            return_value=_cursor("sharadar-actions-reconcile/v1", "2026-08-19"))):
        readiness._add_source_maintenance_checks(
            object(), result, today="2026-08-18",
            required_through="2026-08-18")

    checks = _checks(result)
    assert checks["SEP mutation watermark"].status == readiness.FAIL
    assert checks["ACTIONS complete reconciliation"].status == readiness.FAIL
    assert "ahead" in checks["SEP mutation watermark"].detail
    assert "ahead" in checks["ACTIONS complete reconciliation"].detail


def test_future_decision_frontier_refuses_both_maintenance_domains():
    result = readiness._impl.Readiness()
    readiness._add_source_maintenance_checks(
        object(), result, today="2026-08-18",
        required_through="2026-08-19")
    checks = _checks(result)
    assert checks["SEP mutation watermark"].status == readiness.FAIL
    assert checks["ACTIONS complete reconciliation"].status == readiness.FAIL
