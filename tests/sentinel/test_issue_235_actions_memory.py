"""Issue #235/#250 complete ACTIONS bounded-memory regressions."""
from __future__ import annotations

import gc
import inspect
import io
import json
import weakref
import zipfile

import pytest

from sentinel.feed import action_snapshot, action_source, maintenance, store


def _row(**overrides):
    row = {
        "ticker": "AAA", "date": "2026-08-24", "action": "split",
        "name": "2 for 1", "value": "2", "contraticker": None,
        "contraname": None,
    }
    row.update(overrides)
    return row


def _zip_csv(text: str) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("SHARADAR_ACTIONS.csv", text)
    return out.getvalue()


def _prior(row):
    payload = action_source.canonical_payload(row)
    return {
        **row,
        "source_row_id": action_source.source_row_id(payload),
        "source_payload": json.loads(
            action_source.payload_bytes(payload).decode("utf-8")),
    }


def test_external_snapshot_collapses_only_exact_source_repeat():
    sibling = _row(name="ADR ratio", value="0.5")
    with action_snapshot.ActionSnapshot.from_rows(
            [_row(), _row(), sibling]) as snapshot:
        assert snapshot.source_rows == 3
        assert len(snapshot) == 2
        assert snapshot.exact_repeat_rows == 1
        assert sorted(item["value"] for item in snapshot) == ["0.5", "2"]
        assert snapshot[0]["ticker"] == "AAA"


@pytest.mark.parametrize("csv_text,match", [
    ("ticker,date,action,name,value,contraticker,contraname,action\n"
     "AAA,2026-08-24,split,x,2,,,split\n", "duplicate"),
    ("ticker,date,action,name,value,contraticker,contraname\n"
     "AAA,2026-08-24,split,x,2,,,,EXTRA\n", "wider"),
])
def test_external_snapshot_refuses_invalid_csv_shape(csv_text, match):
    with pytest.raises(action_snapshot.ActionSnapshotError, match=match):
        action_snapshot.ActionSnapshot.from_zip_bytes(_zip_csv(csv_text))


def test_external_snapshot_does_not_retain_whole_input_graph():
    refs = []

    class Tracked(dict):
        pass

    def rows():
        for index in range(20_000):
            row = Tracked(_row(
                ticker=f"T{index:05d}",
                date=f"2026-08-{18 + (index % 5):02d}"))
            refs.append(weakref.ref(row))
            yield row

    with action_snapshot.ActionSnapshot.from_rows(rows()) as snapshot:
        gc.collect()
        assert len(snapshot) == 20_000
        assert sum(ref() is not None for ref in refs) <= 1


def test_external_snapshot_derives_delta_and_bar_dates_in_sqlite():
    unchanged = _row(ticker="BBB", action="dividend", value="1")
    old_split = _row(value="2")
    new_split = _row(value="3")
    with action_snapshot.ActionSnapshot.from_rows(
            [unchanged, new_split]) as snapshot:
        assert snapshot.load_prior_rows(
            [_prior(unchanged), _prior(old_split)]) == 2
        assert snapshot.identity_delta_count() == 2
        assert snapshot.changed_dates({"split", "dividend"}) == ["2026-08-24"]


def test_production_paths_contain_no_whole_export_object_graphs():
    writer = inspect.getsource(store.write_actions)
    reconcile = inspect.getsource(maintenance.reconcile_actions_if_due)
    assert "distinct_rows(rows)" not in writer
    assert "list(cur.fetchall())" not in writer
    assert "observations = list" not in writer
    assert "_active_action_rows(conn)" not in reconcile
    assert "current_ids = {" not in reconcile
    assert "ActionSnapshot" in reconcile
