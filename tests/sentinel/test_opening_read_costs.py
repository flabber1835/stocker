"""Execution proof replay and normalized reference access on private PostgreSQL."""
from datetime import date
from types import SimpleNamespace

import pytest

from sentinel import structural_verification
from sentinel.automation import control_integrity, store
from sentinel.automation.model import AutomationRefused
from sentinel.execution.journal import WRITER_LOCK_KEY
from sentinel.feed import normalized_layout, publication, readiness_scope
from tests.sentinel.test_automation_service import config, conn, enable, pg  # noqa: F401


def test_control_replay_reused_until_the_exact_history_changes(conn, monkeypatch):
    enable(conn, config())
    active = store.load_control(conn)
    calls = []
    original = control_integrity._replay

    def counted(connection):
        calls.append(1)
        return original(connection)

    monkeypatch.setattr(control_integrity, "_replay", counted)
    conn.execute("SELECT pg_advisory_lock_shared(%s),pg_advisory_lock(%s)",
                 (publication.CORPUS_LOCK_KEY, WRITER_LOCK_KEY))
    pub = SimpleNamespace(evidence={"rolling_snapshot": {}}, to_dict=lambda: {"test": "control-replay"})
    with readiness_scope.pinned(conn, pub), structural_verification.callback(conn):
        assert store.load_control(conn) == active
        assert store.load_control(conn) == active
        assert len(calls) == 1
        with pytest.raises(AutomationRefused, match="kill state"):
            control_integrity.validate_control_lineage(conn, active.model_copy(update={"kill_switch_engaged": True}))
        assert len(calls) == 1
        store.engage_kill(conn, actor="qualification", reason="exercise physical invalidation")
        assert store.load_control(conn).kill_switch_engaged
        assert len(calls) == 2
        with pytest.raises(AutomationRefused, match="generation"):
            control_integrity.validate_control_lineage(conn, active)


def test_target_basis_inventory_tracks_only_the_selected_plan(conn):
    from sentinel import dual_plan_authority
    from sentinel.execution.held_targets import _basis_for_plan
    conn.execute("INSERT INTO sentinel_processed_sessions(cursor_name,session,state) VALUES "
                 "(%s,current_date,'{}'),('unrelated',current_date,'{}')",
                 (dual_plan_authority.CURSOR_PREFIX + "one",))
    before = structural_verification._inventory(conn, "held-share-basis", "one")
    conn.execute("UPDATE sentinel_processed_sessions SET state='{}' WHERE cursor_name='unrelated'")
    assert structural_verification._inventory(conn, "held-share-basis", "one") == before
    conn.execute("UPDATE sentinel_processed_sessions SET state=%s::jsonb WHERE cursor_name=%s",
                 ('{"held_share_targets":{"value":2}}', dual_plan_authority.CURSOR_PREFIX + "one"))
    assert structural_verification._inventory(conn, "held-share-basis", "one") != before
    assert _basis_for_plan(conn, "one") == {"value": 2}


def test_candidate_header_lookup_stays_indexed_and_detects_missing_or_wrong_headers(conn):
    conn.execute("""CREATE TEMP TABLE sentinel_normalized_blocks(
        block_sha256 text PRIMARY KEY,kind text,session date, normalization_version text,calendar_version text);
        CREATE TEMP TABLE sentinel_candidate_blocks(candidate_id text,kind text,session date,block_sha256 text,
            PRIMARY KEY(candidate_id,kind,session));
        INSERT INTO sentinel_normalized_blocks
            SELECT i::text,'BARS',date '2026-01-01','n','c' FROM generate_series(1,12000) i;
        INSERT INTO sentinel_candidate_blocks VALUES ('one','BARS','2026-01-01','1'),
            ('one','BENCHMARKS','2026-01-01','2');
        UPDATE sentinel_normalized_blocks SET kind='BENCHMARKS' WHERE block_sha256='2';
        ANALYZE sentinel_normalized_blocks; ANALYZE sentinel_candidate_blocks""")

    class Explain:
        def execute(self, statement, args):
            return conn.execute("EXPLAIN (ANALYZE, FORMAT JSON) " + statement, args)

    plan = normalized_layout._candidate_headers(Explain(), "one")[0][0][0]["Plan"]

    def blocks(node):
        if node.get("Relation Name") == "sentinel_normalized_blocks":
            yield node
        for child in node.get("Plans", []):
            yield from blocks(child)

    header, = blocks(plan)
    assert header["Node Type"] == "Index Scan" and header["Actual Rows"] == 1
    day = date(2026, 1, 1)
    manifest = SimpleNamespace(window=SimpleNamespace(sessions=[day]), normalization_version="n", calendar_version="c")

    def verify():
        return normalized_layout._require_references(normalized_layout._candidate_headers(conn, "one"), manifest)

    assert len(verify()) == 2
    conn.execute("UPDATE sentinel_normalized_blocks SET calendar_version='bad' WHERE block_sha256='2'")
    with pytest.raises(normalized_layout.LayoutRefused, match="BLOCK_HEADER_CHANGED"):
        verify()
    conn.execute("DELETE FROM sentinel_normalized_blocks WHERE block_sha256='2'")
    with pytest.raises(normalized_layout.LayoutRefused, match="BLOCK_HEADER_CHANGED"):
        verify()
