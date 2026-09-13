"""Operational parity exercises the real current-strategy warm-up and kernel."""
from contextlib import contextmanager
from dataclasses import replace
from types import SimpleNamespace

import pytest

from sentinel import shadow_runtime
from sentinel.core.loader import CorpusWindow
from sentinel.core.session import DefensiveBar, PublishedSession
from sentinel.feed import calendar, publication
from sentinel.feed.readiness import REQUIRED_SPY_SESSIONS
from stock_strategy_shared.wealth_core.feed import SecurityMeta, VendorBar
from tools import sentinel_operational_parity as parity

COMMIT = "a" * 40
FRONTIER = "2026-09-04"


class Connection:
    def __init__(self, *, read_only="on"):
        self.read_only = read_only
        self.rolled_back = False
        self.statements = []

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        pass

    def execute(self, sql):
        self.statements.append(sql)

    def fetchone(self):
        return (self.read_only if self.statements[-1].endswith("read_only")
                else "repeatable read",)

    def rollback(self):
        self.rolled_back = True


@pytest.fixture
def operational_inputs(monkeypatch):
    sessions = calendar.previous_sessions(FRONTIER, 253)[:-1]
    meta = {str(i): SecurityMeta(str(i), f"T{i}", "Common Stock", str(i),
                                first_session=sessions[0]) for i in range(30)}
    def bars(day, session):
        return [VendorBar(session, sid, m.ticker, 100.+day, 100.+day, 1e6,
                          signal_close=100.+day) for sid, m in meta.items()]
    window = CorpusWindow(sessions, {s: bars(i, s) for i, s in enumerate(sessions)}, meta)
    window.median5_spy_closes = {s: 100.+i*.05 for i, s in enumerate(sessions)}
    window.median5_terminals = {}
    warmup = shadow_runtime._warmup_input_identity(
        window, sessions, prospective_witness=True)
    monkeypatch.setattr(shadow_runtime, "_load_warmup_material",
                        lambda *_a, **_k: (window, True, warmup))
    spy_sessions = calendar.previous_sessions(FRONTIER, REQUIRED_SPY_SESSIONS)
    published = PublishedSession(
        FRONTIER, 1, bars(252, FRONTIER), meta, {},
        [100.+i*.05 for i in range(len(spy_sessions))],
        spy_sessions=spy_sessions, spy_expected_sessions=spy_sessions,
        defensive_bar=DefensiveBar(FRONTIER, "SENTINEL:BIL", "BIL", 100., 100., 100., 100.),
        defensive_previous_bar=DefensiveBar(
            sessions[-1], "SENTINEL:BIL", "BIL", 100., 100., 100., 100.),
        signal_basis_anchors={bar.security_id: bar for bar in bars(251, sessions[-1])})
    held = publication.Publication(1, None, "seed", sessions[0], FRONTIER, {})
    @contextmanager
    def pinned(conn, *, commit):
        assert commit is False
        yield held
    monkeypatch.setattr(parity.publication, "pinned", pinned)
    monkeypatch.setattr(parity.publication, "current", lambda _conn: held)
    monkeypatch.setattr(parity.publication, "assert_operationally_coherent",
                        lambda *_a, **_k: SimpleNamespace(to_dict=lambda: {
                            "coherent": True, "scope": "PRODUCTION_OPERATIONAL",
                            "version": 1, "blocking_runs": []}))
    monkeypatch.setattr(parity.store, "latest_visible_session", lambda _conn: FRONTIER)
    monkeypatch.setattr(parity, "load_published_session", lambda *_a, **_k: published)
    monkeypatch.setenv("SENTINEL_IMAGE_SOURCE_REVISION", COMMIT)
    monkeypatch.setattr(parity.identity, "rehearsal_identity", lambda: {
        "identity_hash": "b" * 64, "environment": {
            "compatible": True, "lock_present": True,
            "sentinel_source": {"hash": "c" * 64},
            "wealth_core_source": {"hash": "d" * 64}}})
    return published


def test_current_champion_real_startup_and_restart_from_operational_window(operational_inputs):
    conn = Connection()
    report = parity.run_proof(conn, starting_cash="100000.00", expected_commit=COMMIT)
    assert report["verdict"] == "PASS"
    proof = report["proof"]
    assert proof["strategy_identity"]["strategy"] == "sentinel-compact-champion-v1"
    assert proof["warmup_input"]["session_count"] == 252
    assert proof["starting_cash"] == "100000"
    assert proof["decision_session"] == FRONTIER
    assert proof["prior_state_sha256"] != proof["result_state_sha256"]
    assert all(proof["checks"].values())
    assert conn.rolled_back
    assert conn.statements[0].endswith("REPEATABLE READ, READ ONLY")


@pytest.mark.parametrize("fault", ["mutate_prior", "mutate_input", "restart_diverges", "wrong_version", "no_advance"])
def test_real_transition_faults_refuse_and_rollback(monkeypatch, operational_inputs, fault):
    real = parity.advance_session
    calls = 0
    def broken(prior, published, **kwargs):
        nonlocal calls
        calls += 1
        result = real(prior, published, **kwargs)
        if fault == "mutate_prior":
            prior.shadow_peak_nav += 1
        elif fault == "mutate_input":
            published.bars[0] = replace(
                published.bars[0], volume=published.bars[0].volume + 1)
        elif fault == "no_advance":
            result = prior
        elif fault == "restart_diverges" and calls == 2:
            result.shadow_peak_nav += 1
        elif fault == "wrong_version":
            result = replace(result, data_version=2)
        return result
    monkeypatch.setattr(parity, "advance_session", broken)
    conn = Connection()
    with pytest.raises(parity.OperationalParityRefused, match="transition checks failed"):
        parity.run_proof(conn, starting_cash="100000", expected_commit=COMMIT)
    assert conn.rolled_back


def test_writable_snapshot_is_refused_before_loading_inputs(operational_inputs):
    conn = Connection(read_only="off")
    with pytest.raises(parity.OperationalParityRefused, match="read-only"):
        parity.run_proof(conn, starting_cash="100000", expected_commit=COMMIT)
    assert conn.rolled_back


def test_wrong_image_revision_is_refused_before_database_reads(operational_inputs):
    conn = Connection()
    with pytest.raises(parity.OperationalParityRefused, match="source revision"):
        parity.run_proof(conn, starting_cash="100000", expected_commit="f" * 40)
    assert conn.statements == []
    assert conn.rolled_back
