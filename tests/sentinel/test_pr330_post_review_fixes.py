from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest

from sentinel.feed import sep_negative_space_guarded as guarded
from sentinel.feed import sep_reconciliation as recon


def _source_authority(*, ceiling="2026-09-07", refresh="2026-09-07T23:59:00+00:00",
                      window=None, source_rows=None):
    evidence = {
        "authority": "nasdaq-data-link-table-export-composite/v1",
        "table": "SEP",
        "observation_ceiling": ceiling,
        "last_refreshed_time": refresh,
    }
    if window is not None:
        evidence["window"] = list(window)
    if source_rows is not None:
        evidence["source_rows"] = int(source_rows)
    return evidence


def _actions_authority():
    return {
        "authority": "nasdaq-data-link-table-export/v1",
        "table": "ACTIONS",
    }


def test_destructive_boundary_requires_complete_authority():
    with pytest.raises(
            guarded.SepNegativeSpaceRefused,
            match="lacks complete SEP Exporter authority"):
        guarded._require_production_retirement_authority(
            source_authority_evidence=None,
            actions_authority_evidence=_actions_authority(),
            observation_ceiling=dt.date(2026, 9, 7))


def test_destructive_boundary_rejects_future_sep_refresh():
    with pytest.raises(
            guarded.SepNegativeSpaceRefused,
            match="vendor refresh after the frozen observation ceiling"):
        guarded._require_production_retirement_authority(
            source_authority_evidence=_source_authority(
                refresh="2026-09-08T00:01:00+00:00"),
            actions_authority_evidence=_actions_authority(),
            observation_ceiling=dt.date(2026, 9, 7))


def test_destructive_boundary_requires_exact_frozen_ceiling_binding():
    with pytest.raises(
            guarded.SepNegativeSpaceRefused,
            match="not bound to the frozen observation ceiling"):
        guarded._require_production_retirement_authority(
            source_authority_evidence=_source_authority(ceiling="2026-09-06"),
            actions_authority_evidence=_actions_authority(),
            observation_ceiling=dt.date(2026, 9, 7))


def test_destructive_boundary_rejects_forged_evidence_on_injected_fetch():
    def injected(*_args, **_kwargs):
        return iter(())

    with pytest.raises(
            guarded.SepNegativeSpaceRefused,
            match="not backed by the canonical Exporter replay capability"):
        guarded._require_production_retirement_authority(
            source_authority_evidence=_source_authority(
                window=["2026-01-01", "2026-01-31"], source_rows=0),
            actions_authority_evidence=_actions_authority(),
            observation_ceiling=dt.date(2026, 9, 7), fetch=injected,
            start="2026-01-01", end="2026-01-31", source_rows=0)


def test_complete_export_refuses_generation_after_frozen_ceiling(monkeypatch):
    from sentinel.feed import snapshot_export

    monkeypatch.setattr(
        snapshot_export, "fetch_complete_sep",
        lambda **kwargs: ([], {
            "authority": "nasdaq-data-link-table-export/v1",
            "table": "SEP",
            "source_rows": 0,
            "data_snapshot_time": "2026-09-08T00:02:00+00:00",
            "last_refreshed_time": "2026-09-08T00:01:00+00:00",
        }))

    with pytest.raises(
            recon.SepReconciliationStateInvalid,
            match="newer than the frozen observation ceiling"):
        recon._complete_export_source(
            start="2026-01-01", end="2026-01-31",
            observation_ceiling="2026-09-07")


def test_complete_export_persists_frozen_ceiling_in_authority(monkeypatch):
    from sentinel.feed import snapshot_export

    monkeypatch.setattr(
        snapshot_export, "fetch_complete_sep",
        lambda **kwargs: ([], {
            "authority": "nasdaq-data-link-table-export/v1",
            "table": "SEP",
            "source_rows": 0,
            "data_snapshot_time": "2026-09-07T20:00:00+00:00",
            "last_refreshed_time": "2026-09-07T19:59:00+00:00",
        }))

    fetch, evidence = recon._complete_export_source(
        start="2026-01-01", end="2026-01-31",
        observation_ceiling="2026-09-07")
    try:
        assert evidence["observation_ceiling"] == "2026-09-07"
        assert evidence["last_refreshed_time"] == "2026-09-07T19:59:00+00:00"
        assert fetch._sentinel_sep_retirement_capability is \
            guarded._SEP_RETIREMENT_CAPABILITY
    finally:
        fetch.cleanup()


class _Cursor:
    def __init__(self, conn):
        self.conn = conn
        self.rowcount = 0
        self._one = None
        self._all = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, sql, params=()):
        normalized = " ".join(str(sql).split())
        self.conn.calls.append((normalized, tuple(params)))
        self.rowcount = 0
        self._one = None
        self._all = []
        if normalized.startswith("SELECT COUNT(*) FROM sentinel_bars"):
            self._one = (1,)
        elif normalized.startswith("SELECT s.security_id,s.session,s.last_written_run_id"):
            self._all = [(
                "P:1", dt.date(2026, 4, 2),
                "11111111-1111-1111-1111-111111111111")]
        elif normalized.startswith("UPDATE sentinel_bar_split_repairs"):
            self.rowcount = 1
        elif normalized.startswith("DELETE FROM sentinel_bar_split_repairs"):
            self.rowcount = 1
        elif normalized.startswith("UPDATE sentinel_bars b SET last_written_run_id"):
            self.rowcount = 1
        elif normalized.startswith("DELETE FROM sentinel_bars"):
            self.rowcount = 1
        elif normalized.startswith("UPDATE feed_ingest_runs SET status='success'"):
            self.rowcount = 1
        else:  # pragma: no cover - makes an unexpected SQL shape obvious
            raise AssertionError(f"unexpected SQL: {normalized}")

    def fetchone(self):
        return self._one

    def fetchall(self):
        return list(self._all)


class _Conn:
    def __init__(self):
        self.calls = []

    def cursor(self):
        return _Cursor(self)


def test_published_rows_transition_to_running_retirement_owner_before_delete(monkeypatch):
    conn = _Conn()
    run_id = "22222222-2222-2222-2222-222222222222"
    run = SimpleNamespace(progress=SimpleNamespace(run_id=run_id))
    plan = {
        "interval": ["2026-04-02", "2026-04-02"],
        "keys": [{
            "security_id": "P:1",
            "session": "2026-04-02",
            "ticker": "AAA",
        }],
    }

    monkeypatch.setattr(guarded.core, "_load_retire_table", lambda *a, **k: None)
    monkeypatch.setattr(
        guarded.publication, "visible_predicate", lambda alias: "TRUE")
    monkeypatch.setattr(
        guarded.publication, "publish", lambda *a, **k: "published")

    result = guarded._retire_and_publish_authorized(conn, run=run, plan=plan)

    assert result == "published"
    sql = [statement for statement, _params in conn.calls]
    repair_update = next(i for i, row in enumerate(sql)
                         if row.startswith("UPDATE sentinel_bar_split_repairs"))
    repair_delete = next(i for i, row in enumerate(sql)
                         if row.startswith("DELETE FROM sentinel_bar_split_repairs"))
    bar_update = next(i for i, row in enumerate(sql)
                      if row.startswith("UPDATE sentinel_bars b SET last_written_run_id"))
    bar_delete = next(i for i, row in enumerate(sql)
                      if row.startswith("DELETE FROM sentinel_bars"))
    assert repair_update < repair_delete < bar_update < bar_delete
    assert conn.calls[bar_update][1] == (run_id,)
