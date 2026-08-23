"""Regression for the post-#238 ACTIONS semantic replay migration."""
from __future__ import annotations

from sentinel.feed import maintenance


def test_actions_cursor_epoch_advances_after_tri_split_semantic_change():
    assert maintenance.ACTIONS_CURSOR_NAME == \
        "sharadar-actions-export-reconcile:v6"
    assert maintenance.ACTIONS_CURSOR_KIND == \
        "sharadar-actions-export-reconcile/v6"


def test_load_actions_cursor_never_queries_legacy_v5_authority(monkeypatch):
    seen = {}

    def read_cursor(_conn, name, kind):
        seen["name"] = name
        seen["kind"] = kind
        return None

    monkeypatch.setattr(maintenance, "_read_cursor", read_cursor)
    assert maintenance.load_actions_cursor(object()) is None
    assert seen == {
        "name": "sharadar-actions-export-reconcile:v6",
        "kind": "sharadar-actions-export-reconcile/v6",
    }
