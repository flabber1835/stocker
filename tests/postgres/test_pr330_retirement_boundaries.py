from __future__ import annotations

import datetime as dt
import json
import os
from types import SimpleNamespace
import uuid

import pytest

from sentinel.feed import publication
from sentinel.feed import sep_negative_space_guarded as guarded
from sentinel.feed import sep_reconciliation as reconciliation
from sentinel.feed import store
from sentinel.feed.schema import DDL


BOUNDARY = "2026-09-07T20:00:00+00:00"


@pytest.fixture
def pg_conn():
    dsn = os.environ["SENTINEL_DATABASE_URL"]
    conn = store.connect(dsn, connect_timeout=5, statement_timeout_ms=30000)
    with conn.cursor() as cur:
        for statement in DDL:
            cur.execute(statement)
    conn.commit()
    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()


def _insert_run(conn, run_id, *, kind, status):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO feed_ingest_runs"
            " (run_id,kind,status,source_git_commit,runtime_image_digest)"
            " VALUES (%s,%s,%s,%s,%s)",
            (str(run_id), kind, status, "a" * 40, "sha256:" + "b" * 64))


def _insert_publication(conn, *, version, previous, run_id, evidence):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sentinel_corpus_publications"
            " (version,previous_version,run_id,window_start,window_end,evidence)"
            " VALUES (%s,%s,%s,%s,%s,%s::jsonb)",
            (int(version), previous, str(run_id) if run_id else None,
             "2026-04-02", "2026-04-02", json.dumps(evidence)))


def test_append_only_retirement_hides_bar_and_preserves_physical_evidence(
        pg_conn, monkeypatch):
    base_run = uuid.uuid4()
    retirement_run = uuid.uuid4()
    _insert_run(pg_conn, base_run, kind="daily", status="success")
    _insert_run(pg_conn, retirement_run, kind=guarded.KIND, status="running")
    _insert_publication(
        pg_conn, version=1, previous=None, run_id=base_run, evidence={})
    with pg_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sentinel_bars"
            " (security_id,session,ticker,close_signal,close_unadjusted,"
            "  open_unadjusted,volume,split_ratio,dividend_per_share,"
            "  last_written_run_id)"
            " VALUES ('P:1','2026-04-02','AAA',50,50,49,1000,1,0,%s)",
            (str(base_run),))
        cur.execute(
            "INSERT INTO sentinel_bar_split_repairs"
            " (security_id,session,split_ratio,prior_split_ratio,last_written_run_id)"
            " VALUES ('P:1','2026-04-02',1,1,%s)",
            (str(base_run),))

    keys = [{
        "security_id": "P:1", "session": "2026-04-02", "ticker": "AAA",
    }]
    plan = {
        "schema": guarded.SCHEMA,
        "interval": ["2026-04-02", "2026-04-02"],
        "count": 1,
        "keys": keys,
        "keys_sha256": guarded.core._keys_digest(keys),
        "source_rows": 0,
    }
    run = SimpleNamespace(progress=SimpleNamespace(run_id=str(retirement_run)))

    def publish_tombstone(conn, *, run_id, window_start, window_end, evidence):
        assert str(run_id) == str(retirement_run)
        _insert_publication(
            conn, version=2, previous=1, run_id=retirement_run,
            evidence=evidence)
        return SimpleNamespace(version=2)

    monkeypatch.setattr(guarded.publication, "publish", publish_tombstone)
    result = guarded._retire_and_publish_authorized(
        pg_conn, run=run, plan=plan)
    assert result.version == 2

    with pg_conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*),MIN(last_written_run_id::text) FROM sentinel_bars"
            " WHERE security_id='P:1' AND session='2026-04-02'")
        physical_count, bar_owner = cur.fetchone()
        cur.execute(
            "SELECT COUNT(*),MIN(last_written_run_id::text)"
            " FROM sentinel_bar_split_repairs"
            " WHERE security_id='P:1' AND session='2026-04-02'")
        repair_count, repair_owner = cur.fetchone()
        cur.execute(
            "SELECT COUNT(*) FROM sentinel_bars b"
            " WHERE b.security_id='P:1' AND b.session='2026-04-02' AND "
            + publication.visible_predicate("b"))
        visible_count = int(cur.fetchone()[0])

    assert int(physical_count) == 1
    assert bar_owner == str(base_run)
    assert int(repair_count) == 1
    assert repair_owner == str(base_run)
    assert visible_count == 0


def _source_authority(*, refresh="2026-09-07T19:59:00+00:00"):
    return {
        "authority": "nasdaq-data-link-table-export-composite/v1",
        "table": "SEP",
        "window": ["2026-01-01", "2026-01-31"],
        "source_rows": 0,
        "observation_ceiling": "2026-09-07",
        "source_observation_boundary": BOUNDARY,
        "last_refreshed_time": refresh,
    }


def _actions_authority(*, publication_version=1):
    return {
        "authority": "nasdaq-data-link-table-export/v1",
        "table": "ACTIONS",
        "source_rows": 2,
        "data_snapshot_time": "2026-09-07T19:58:30+00:00",
        "last_refreshed_time": "2026-09-07T19:58:00+00:00",
        "verified_through": "2026-09-04",
        "verified_publication_version": publication_version,
        "verified_distinct_rows": 2,
    }


def _canonical_export_fetch(*_args, **_kwargs):
    return iter(())


_canonical_export_fetch._sentinel_sep_retirement_capability = \
    guarded._SEP_RETIREMENT_CAPABILITY


def test_dual_authority_token_is_revalidated_against_current_publication(pg_conn):
    base_run = uuid.uuid4()
    _insert_run(pg_conn, base_run, kind="daily", status="success")
    _insert_publication(
        pg_conn, version=1, previous=None, run_id=base_run, evidence={})

    source = _source_authority()
    actions = _actions_authority(publication_version=1)
    token = guarded._require_production_retirement_authority(
        source_authority_evidence=source,
        actions_authority_evidence=actions,
        observation_ceiling=dt.date(2026, 9, 7),
        source_observation_boundary=BOUNDARY,
        fetch=_canonical_export_fetch,
        start="2026-01-01", end="2026-01-31", source_rows=0)
    keys = [{
        "security_id": "P:1", "session": "2026-01-15", "ticker": "AAA",
    }]
    plan = {
        "interval": ["2026-01-01", "2026-01-31"],
        "source_rows": 0,
        "keys": keys,
        "keys_sha256": guarded.core._keys_digest(keys),
        "source_authority": source,
        "actions_authority": actions,
    }
    guarded._validate_retirement_authority_at_boundary(
        pg_conn, plan=plan, validated_authority=token)

    forged = dict(plan)
    forged["actions_authority"] = dict(actions, verified_distinct_rows=3)
    with pytest.raises(
            guarded.SepNegativeSpaceRefused,
            match="ACTIONS authority changed after validation"):
        guarded._validate_retirement_authority_at_boundary(
            pg_conn, plan=forged, validated_authority=token)

    _insert_publication(
        pg_conn, version=2, previous=1, run_id=None, evidence={})
    with pytest.raises(
            guarded.SepNegativeSpaceRefused,
            match="published corpus advanced after fresh ACTIONS"):
        guarded._validate_retirement_authority_at_boundary(
            pg_conn, plan=plan, validated_authority=token)


def test_same_day_exporter_refresh_after_frozen_observation_is_refused(
        pg_conn, monkeypatch):
    from sentinel.feed import snapshot_export

    with pg_conn.cursor() as cur:
        cur.execute("SELECT current_setting('server_version_num')::int")
        assert int(cur.fetchone()[0]) >= 160000

    monkeypatch.setattr(
        snapshot_export, "fetch_complete_sep",
        lambda **_kwargs: ([], {
            "authority": "nasdaq-data-link-table-export/v1",
            "table": "SEP",
            "source_rows": 0,
            "data_snapshot_time": "2026-09-07T20:02:00+00:00",
            "last_refreshed_time": "2026-09-07T20:01:00+00:00",
        }))
    with pytest.raises(
            reconciliation.SepReconciliationStateInvalid,
            match="newer than the frozen source observation boundary"):
        reconciliation._complete_export_source(
            start="2026-01-01", end="2026-01-31",
            observation_ceiling="2026-09-07",
            source_observation_boundary=BOUNDARY)
