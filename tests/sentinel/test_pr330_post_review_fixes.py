from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest

from sentinel.feed import sep_negative_space_guarded as guarded
from sentinel.feed import sep_reconciliation as recon


BOUNDARY = "2026-09-07T20:00:00+00:00"


def _source_authority(*, ceiling="2026-09-07", boundary=BOUNDARY,
                      refresh="2026-09-07T19:59:00+00:00",
                      window=None, source_rows=None):
    evidence = {
        "authority": "nasdaq-data-link-table-export-composite/v1",
        "table": "SEP",
        "observation_ceiling": ceiling,
        "source_observation_boundary": boundary,
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
        "source_rows": 2,
        "data_snapshot_time": "2026-09-07T19:58:30+00:00",
        "last_refreshed_time": "2026-09-07T19:58:00+00:00",
        "verified_through": "2026-09-04",
        "verified_publication_version": 7,
        "verified_distinct_rows": 2,
    }


def test_mutation_boundary_requires_complete_authority():
    with pytest.raises(
            guarded.SepNegativeSpaceRefused,
            match="lacks complete SEP Exporter authority"):
        guarded._require_production_retirement_authority(
            source_authority_evidence=None,
            actions_authority_evidence=_actions_authority(),
            observation_ceiling=dt.date(2026, 9, 7),
            source_observation_boundary=BOUNDARY)


def test_mutation_boundary_rejects_same_day_future_sep_refresh():
    with pytest.raises(
            guarded.SepNegativeSpaceRefused,
            match="vendor refresh after the frozen source observation boundary"):
        guarded._require_production_retirement_authority(
            source_authority_evidence=_source_authority(
                refresh="2026-09-07T20:01:00+00:00"),
            actions_authority_evidence=_actions_authority(),
            observation_ceiling=dt.date(2026, 9, 7),
            source_observation_boundary=BOUNDARY)


def test_mutation_boundary_requires_exact_frozen_ceiling_binding():
    with pytest.raises(
            guarded.SepNegativeSpaceRefused,
            match="not bound to the frozen observation ceiling"):
        guarded._require_production_retirement_authority(
            source_authority_evidence=_source_authority(ceiling="2026-09-06"),
            actions_authority_evidence=_actions_authority(),
            observation_ceiling=dt.date(2026, 9, 7),
            source_observation_boundary=BOUNDARY)


def test_mutation_boundary_requires_exact_frozen_instant_binding():
    with pytest.raises(
            guarded.SepNegativeSpaceRefused,
            match="not bound to the frozen source observation boundary"):
        guarded._require_production_retirement_authority(
            source_authority_evidence=_source_authority(
                boundary="2026-09-07T19:59:59+00:00"),
            actions_authority_evidence=_actions_authority(),
            observation_ceiling=dt.date(2026, 9, 7),
            source_observation_boundary=BOUNDARY)


def test_mutation_boundary_rejects_forged_evidence_on_injected_fetch():
    def injected(*_args, **_kwargs):
        return iter(())

    with pytest.raises(
            guarded.SepNegativeSpaceRefused,
            match="not backed by the canonical Exporter replay capability"):
        guarded._require_production_retirement_authority(
            source_authority_evidence=_source_authority(
                window=["2026-01-01", "2026-01-31"], source_rows=0),
            actions_authority_evidence=_actions_authority(),
            observation_ceiling=dt.date(2026, 9, 7),
            source_observation_boundary=BOUNDARY,
            fetch=injected, start="2026-01-01", end="2026-01-31",
            source_rows=0)


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
            observation_ceiling="2026-09-07",
            source_observation_boundary=BOUNDARY)


def test_complete_export_persists_frozen_boundary_in_authority(monkeypatch):
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
        observation_ceiling="2026-09-07",
        source_observation_boundary=BOUNDARY)
    try:
        assert evidence["observation_ceiling"] == "2026-09-07"
        assert evidence["source_observation_boundary"] == BOUNDARY
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

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, sql, params=()):
        normalized = " ".join(str(sql).split())
        self.conn.calls.append((normalized, tuple(params)))
        self.rowcount = 0
        self._one = None
        if normalized.startswith("SELECT COUNT(*) FROM sentinel_bars"):
            self._one = (1,)
        elif normalized.startswith("UPDATE feed_ingest_runs SET status='success'"):
            self.rowcount = 1
        else:  # pragma: no cover
            raise AssertionError(f"unexpected SQL: {normalized}")

    def fetchone(self):
        return self._one


class _Conn:
    def __init__(self):
        self.calls = []

    def cursor(self):
        return _Cursor(self)


def test_published_retirement_is_append_only_tombstone(monkeypatch):
    conn = _Conn()
    run = SimpleNamespace(
        progress=SimpleNamespace(
            run_id="22222222-2222-2222-2222-222222222222"))
    keys = [{
        "security_id": "P:1",
        "session": "2026-04-02",
        "ticker": "AAA",
    }]
    plan = {
        "interval": ["2026-04-02", "2026-04-02"],
        "keys": keys,
        "keys_sha256": guarded.core._keys_digest(keys),
    }
    published = {}

    monkeypatch.setattr(guarded.core, "_load_retire_table", lambda *a, **k: None)
    monkeypatch.setattr(
        guarded.publication, "visible_predicate", lambda alias: "TRUE")

    def publish(*_args, **kwargs):
        published.update(kwargs["evidence"])
        return "published"

    monkeypatch.setattr(guarded.publication, "publish", publish)

    from tests.support.sep_retirement import authorized_plan
    plan, token = authorized_plan(keys, publication_version=1)
    monkeypatch.setattr(
        guarded.publication, "require_current", lambda conn: SimpleNamespace(version=1))
    result = guarded._retire_and_publish_authorized(
        conn, run=run, plan=plan, validated_authority=token)

    assert result == "published"
    assert published == {"kind": guarded.KIND, "source_retirement": plan}
    sql = [statement for statement, _params in conn.calls]
    assert not any("UPDATE sentinel_bars" in row for row in sql)
    assert not any("DELETE FROM sentinel_bars" in row for row in sql)
    assert not any("UPDATE sentinel_bar_split_repairs" in row for row in sql)
    assert not any("DELETE FROM sentinel_bar_split_repairs" in row for row in sql)


@pytest.mark.parametrize("entry", [
    guarded._retire_and_publish_authorized, guarded.core._retire_and_publish,
])
@pytest.mark.parametrize("evidence", [{}, {"source_authority": {}}, {"actions_authority": {}}])
def test_retirement_entry_points_refuse_absent_authority_before_database_access(entry, evidence):
    with pytest.raises(guarded.SepNegativeSpaceRefused, match="lacks validated dual-source authority"):
        entry(object(), run=object(), plan=evidence)
