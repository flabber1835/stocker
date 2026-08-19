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


def test_source_maintenance_checks_pass_only_when_sep_current_and_actions_inside_cadence():
    result = readiness._impl.Readiness()
    with (mock.patch.object(
            readiness._maintenance, "load_sep_cursor",
            return_value=_cursor("sharadar-sep-lastupdated/v1", "2026-08-18")),
          mock.patch.object(
            readiness._maintenance, "load_actions_cursor",
            return_value=_cursor("sharadar-actions-reconcile/v1", "2026-08-16"))):
        readiness._add_source_maintenance_checks(
            object(), result, today="2026-08-18T20:00:00-04:00")

    checks = _checks(result)
    assert checks["SEP mutation watermark"].status == readiness.PASS
    assert checks["ACTIONS complete reconciliation"].status == readiness.PASS
    assert result.ready


def test_post_publication_sep_failure_cannot_leave_readiness_green():
    """The ordinary daily publication may exist while today's CDC is unfinished."""
    result = readiness._impl.Readiness()
    with (mock.patch.object(
            readiness._maintenance, "load_sep_cursor",
            return_value=_cursor("sharadar-sep-lastupdated/v1", "2026-08-17")),
          mock.patch.object(
            readiness._maintenance, "load_actions_cursor",
            return_value=_cursor("sharadar-actions-reconcile/v1", "2026-08-16"))):
        readiness._add_source_maintenance_checks(
            object(), result, today="2026-08-18")

    checks = _checks(result)
    assert checks["SEP mutation watermark"].status == readiness.FAIL
    assert "behind" in checks["SEP mutation watermark"].detail
    assert not result.ready


def test_actions_cursor_becomes_blocking_exactly_when_full_reconciliation_is_due():
    result = readiness._impl.Readiness()
    due = (dt.date(2026, 8, 18)
           - dt.timedelta(days=maintenance.ACTIONS_RECONCILE_DAYS)).isoformat()
    with (mock.patch.object(
            readiness._maintenance, "load_sep_cursor",
            return_value=_cursor("sharadar-sep-lastupdated/v1", "2026-08-18")),
          mock.patch.object(
            readiness._maintenance, "load_actions_cursor",
            return_value=_cursor("sharadar-actions-reconcile/v1", due))):
        readiness._add_source_maintenance_checks(
            object(), result, today="2026-08-18")

    checks = _checks(result)
    assert checks["SEP mutation watermark"].status == readiness.PASS
    assert checks["ACTIONS complete reconciliation"].status == readiness.FAIL
    assert "is due every" in checks["ACTIONS complete reconciliation"].detail
    assert not result.ready


def test_missing_or_corrupt_maintenance_authority_fails_closed():
    missing = readiness._impl.Readiness()
    with (mock.patch.object(
            readiness._maintenance, "load_sep_cursor", return_value=None),
          mock.patch.object(
            readiness._maintenance, "load_actions_cursor", return_value=None)):
        readiness._add_source_maintenance_checks(
            object(), missing, today="2026-08-18")
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
            object(), corrupt, today="2026-08-18")
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
            object(), result, today="2026-08-18")

    checks = _checks(result)
    assert checks["SEP mutation watermark"].status == readiness.FAIL
    assert checks["ACTIONS complete reconciliation"].status == readiness.FAIL
    assert "ahead" in checks["SEP mutation watermark"].detail
    assert "ahead" in checks["ACTIONS complete reconciliation"].detail
