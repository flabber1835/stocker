"""Regression for ACTIONS semantic replay epochs after #237 and #364/A1."""
from __future__ import annotations

from sentinel import archive_identifiers as archive_ids

from sentinel.feed import maintenance


def test_actions_cursor_epoch_advances_for_cash_adjudication_semantics():
    assert maintenance.ACTIONS_CURSOR_NAME == \
        archive_ids.FEED['ACTIONS_RECONCILE_V10']
    assert maintenance.ACTIONS_CURSOR_KIND == \
        archive_ids.FEED['ACTIONS_RECONCILE_KIND_V10']


def test_load_actions_cursor_never_queries_legacy_v6_authority(monkeypatch):
    seen = {}

    def read_cursor(_conn, name, kind):
        seen["name"] = name
        seen["kind"] = kind
        return None

    monkeypatch.setattr(maintenance._core, "_read_cursor", read_cursor)
    assert maintenance.load_actions_cursor(object()) is None
    assert seen == {
        "name": archive_ids.FEED['ACTIONS_RECONCILE_V10'],
        "kind": archive_ids.FEED['ACTIONS_RECONCILE_KIND_V10'],
    }
