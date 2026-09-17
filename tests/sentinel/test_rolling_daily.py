"""Adjacent rolling publications advance one canonical durable book."""
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from sentinel import rolling_daily as daily, rolling_daily_checkpoint as cp
from sentinel import rolling_initialization as init, rolling_checkpoint as origin
from sentinel import shadow_observation as shadow
from sentinel.core import rolling_continuity as continuity
from sentinel.core.history import require_history_compatible, HistoryReconstructionRequired
from sentinel.feed import operational_snapshot as op, calendar, rolling_store
from sentinel.feed.rolling_contract import PriceWindow, digest, canonical_json
from tests.sentinel.test_rolling_initialization import ready, start, OBS  # noqa: F401
from tests.sentinel.test_operational_snapshot import operational_source  # noqa: F401
from tests.sentinel.test_rolling_snapshot_publisher import conn, pg, source  # noqa: F401


def refresh(conn, data, monkeypatch, *, days=1, rebase=False):
    session = max(row["date"] for row in data["SEP"])
    for _ in range(days):
        previous = max(row["date"] for row in data["SEP"])
        session = calendar.next_session(previous)
        for table in ("SEP", "SFP"):
            rows = [deepcopy(row) for row in data[table] if row["date"] == previous]
            for row in rows:
                row["date"] = session
            data[table].extend(rows)
        for row in data["TICKERS"]:
            row["lastpricedate"] = session
    if rebase:
        for row in data["SEP"]:
            # AAA has an ACTIONS dividend on its original adjusted basis. Rebase
            # dividend-free series; changing AAA alone would change raw cash.
            if row["ticker"] == "AAA":
                continue
            for field in ("close", "open"):
                row[field] = str(Decimal(row[field]) * 2)
            row["volume"] = str(Decimal(row["volume"]) / 2)
        for row in data["SFP"]:
            row["closeadj"] = str(Decimal(row["closeadj"]) * 2)
    window_start = str(PriceWindow.through(session).start)
    data["SFP"][:] = [row for row in data["SFP"] if row["date"] >= window_start]
    now = datetime.fromisoformat(session).replace(tzinfo=timezone.utc) + timedelta(days=1, hours=4)
    monkeypatch.setattr(op, "_now", lambda: now)
    monkeypatch.setattr(init, "_now", lambda conn: now)
    monkeypatch.setattr(calendar, "latest_closed_session", lambda now=None: session)
    strategy = init._context(OBS, 100_000)["strategy"]
    job = op.enqueue(conn, strategy_sha256=digest(strategy), dependencies_sha256=digest("daily fixture"))
    conn.commit()
    return op.prepare(conn, job)


def advance(conn):
    return daily.advance(conn, observation_id=OBS, starting_cash=100_000)


def resume(conn):
    return daily.resume(conn, observation_id=OBS, starting_cash=100_000)


@pytest.fixture
def first(conn, ready):
    return start(conn)


@pytest.fixture
def decimal_source(operational_source, monkeypatch):
    """Rebase decimal vendor prices, rather than synthetic float-string noise."""
    original = op.prepare
    def prepare(*args, **kwargs):
        for row in operational_source["SEP"]:
            for field in ("open", "close", "closeunadj"):
                row[field] = format(float(row[field]), ".4f")
        return original(*args, **kwargs)
    monkeypatch.setattr(op, "prepare", prepare)


@pytest.fixture
def rebase_first(decimal_source, ready, conn):
    return start(conn)


def test_daily_advances_pending_book_and_matches_canonical_transition(conn, first, operational_source, monkeypatch):
    refreshed = refresh(conn, operational_source, monkeypatch)
    with op.pinned(conn) as (pub, binding):
        material, anchors, proof = continuity.prepare(conn, prior=first.state,
            previous_binding=origin.read(conn).snapshot, publication=pub, binding=binding)
        published = replace(init._published(material, pub), signal_basis_anchors=anchors, history_proof=proof)
        expected = shadow.advance_state(shadow.SessionState.from_dict(first.state.to_dict()), published,
            controller_config=init._context(OBS, 100_000)["controller"], strategy_identity=first.state.strategy_identity)
    result = advance(conn)
    assert result.state.wealth_core["episodes"]
    assert result.state.wealth_core["cash"] < 100_000
    assert result.state.state_hash == expected.state_hash
    assert result.state.data_version == refreshed["data_version"]
    assert result.verification == shadow.CANDIDATE and result.shadow_verdict == shadow.NOT_DEPLOYABLE
    assert cp.read(conn).input_value["rolling_continuity"] == proof
    conn.commit()
    assert resume(conn).state.state_hash == result.state.state_hash
    assert advance(conn).appended is False
    assert len(shadow.PostgresShadowObservationStore(conn, observation_id=OBS).records()) == 2
    with pytest.raises(origin.RollingColdStartRefused, match="LINEAGE_CHANGED"):
        init.resume(conn, observation_id=OBS, starting_cash=100_000)


def test_repeated_continuation_outlives_origin_prices(conn, first, ready, operational_source, monkeypatch):
    refresh(conn, operational_source, monkeypatch)
    second = advance(conn)
    second_input = deepcopy(cp.read(conn).input_value)
    conn.commit()
    # Only the prior/current snapshot is a live price dependency after handoff.
    conn.execute("SET LOCAL session_replication_role=replica")
    for table in ("sentinel_snapshot_bars", "sentinel_snapshot_benchmarks"):
        conn.execute("DELETE FROM " + table + " WHERE candidate_id=%s", (ready["candidate_id"],))
    conn.commit()
    assert resume(conn).state.state_hash == second.state.state_hash
    refresh(conn, operational_source, monkeypatch)
    third = advance(conn)
    assert third.session == "2026-09-16"
    assert third.state.wealth_core["episodes"]
    assert resume(conn).state.state_hash == third.state.state_hash
    archived = conn.execute("SELECT state FROM sentinel_processed_sessions WHERE cursor_name=%s",
                            (cp.input_name(OBS, second.session),)).fetchone()[0]
    assert archived == second_input
    assert digest(archived) == shadow.PostgresShadowObservationStore(conn, observation_id=OBS).records()[1]["input_sha256"]


@pytest.mark.parametrize("defect", ["raw", "signal", "volume", "sector", "actions", "spy", "bil"])
def test_historical_economic_changes_refuse_without_advancing(conn, first, operational_source, monkeypatch, defect):
    data = operational_source
    day = "2026-09-10"
    if defect in {"raw", "signal", "volume"}:
        row = next(row for row in data["SEP"] if row["ticker"] == "AAA" and row["date"] == day)
        field = {"raw": "closeunadj", "signal": "close", "volume": "volume"}[defect]
        row[field] = str(float(row[field]) * (1.00001 if defect == "signal" else 1.001))
    elif defect == "sector":
        data["TICKERS"][0]["sector"] = "Healthcare"
    elif defect == "actions":
        # Reference-only old event outside the retained price window.
        data["ACTIONS"].append({**data["ACTIONS"][0], "date": "2000-01-03", "value": "2"})
    else:
        row = next(row for row in data["SFP"] if row["ticker"] == defect.upper() and row["date"] == day)
        row["closeadj"] = str(float(row["closeadj"]) + 1)
    refresh(conn, data, monkeypatch)
    with pytest.raises(continuity.RollingContinuityRefused, match="CHANGED|REBASE"):
        advance(conn)
    assert cp.read(conn) is None
    assert resume(conn).state.state_hash == first.state.state_hash


def test_uniform_rebase_is_accepted(conn, rebase_first, operational_source, monkeypatch):
    first = rebase_first
    refresh(conn, operational_source, monkeypatch)
    with op.pinned(conn) as (pub, binding):
        material, anchors, proof = continuity.prepare(conn, prior=first.state,
            previous_binding=origin.read(conn).snapshot, publication=pub, binding=binding)
        baseline = replace(init._published(material, pub), signal_basis_anchors=anchors, history_proof=proof)
        expected = shadow.advance_state(shadow.SessionState.from_dict(first.state.to_dict()), baseline,
            controller_config=init._context(OBS, 100_000)["controller"], strategy_identity=first.state.strategy_identity)
    refresh(conn, operational_source, monkeypatch, days=0, rebase=True)
    with op.pinned(conn) as (_, binding):
        from sentinel.core.rolling_reader import RollingPriceReader
        before = origin.read(conn).snapshot
        old = RollingPriceReader(conn, candidate_id=before["candidate_id"], snapshot_id=before["snapshot_id"])
        new = RollingPriceReader(conn, candidate_id=binding["candidate_id"], snapshot_id=binding["snapshot_id"])
        lo = max(str(old.manifest.window.start), str(new.manifest.window.start))
        for left, right in zip(old.bars(start=lo, end=first.session), new.bars(start=lo, end=first.session)):
            a, b = asdict(left), asdict(right)
            a.pop("signal_close")
            b.pop("signal_close")
            assert a == b
    result = advance(conn)
    assert result.state.wealth_core["episodes"]
    for field in ("wealth_core", "ledger", "pending", "controller"):
        assert getattr(result.state, field) == getattr(expected, field)
    for sid, series in result.state.feed["series"].items():
        for field in ("signal_closes", "raw_closes", "volumes"):
            assert series[field] == expected.feed["series"][sid][field]
    assert resume(conn).state.state_hash == result.state.state_hash


def test_missing_causal_sessions_never_jump_cursor(conn, first, operational_source, monkeypatch):
    refresh(conn, operational_source, monkeypatch, days=2)
    with pytest.raises(continuity.RollingContinuityRefused, match="ADJACENT"):
        advance(conn)
    assert resume(conn).state.state_hash == first.state.state_hash


@pytest.mark.parametrize("boundary", ["append", "archive", "checkpoint"])
def test_failed_write_rolls_back_record_and_checkpoint(conn, first, operational_source, monkeypatch, boundary):
    refresh(conn, operational_source, monkeypatch)
    target, name = ((shadow.PostgresShadowObservationStore, "append") if boundary == "append"
                    else (cp, "archive_input" if boundary == "archive" else "write"))
    original = getattr(target, name)
    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("injected continuation failure")
    monkeypatch.setattr(target, name, fail)
    with pytest.raises((RuntimeError, shadow.ShadowObservationRefused), match="injected|append failed"):
        advance(conn)
    assert cp.read(conn) is None
    assert conn.execute("SELECT 1 FROM sentinel_processed_sessions WHERE cursor_name=%s",
                        (cp.input_name(OBS, "2026-09-15"),)).fetchone() is None
    assert resume(conn).state.state_hash == first.state.state_hash
    monkeypatch.setattr(target, name, original)
    assert advance(conn).state.wealth_core["episodes"]


def test_changed_signed_checkpoint_refuses(conn, first, operational_source, monkeypatch):
    refresh(conn, operational_source, monkeypatch)
    advance(conn)
    conn.execute("UPDATE sentinel_processed_sessions SET state=jsonb_set(state,'{checkpoint,state_sha256}',%s::jsonb) "
                 "WHERE cursor_name=%s", (canonical_json("a" * 64), cp.CURSOR))
    conn.commit()
    with pytest.raises(origin.RollingColdStartRefused, match="AUTHENTICATION"):
        resume(conn)


def test_changed_input_archive_refuses(conn, first, operational_source, monkeypatch):
    refresh(conn, operational_source, monkeypatch)
    result = advance(conn)
    conn.execute("UPDATE sentinel_processed_sessions SET state='{}' WHERE cursor_name=%s",
                 (cp.input_name(OBS, result.session),))
    conn.commit()
    with pytest.raises(origin.RollingColdStartRefused, match="INPUT_ARCHIVE_CHANGED"):
        resume(conn)


def test_input_archive_cannot_be_overwritten(conn, first, operational_source, monkeypatch):
    refresh(conn, operational_source, monkeypatch)
    result = advance(conn)
    checkpoint = cp.read(conn)
    with pytest.raises(origin.RollingColdStartRefused, match="ALREADY_EXISTS"):
        cp.archive_input(conn, checkpoint)
    conn.rollback()
    assert resume(conn).state.state_hash == result.state.state_hash


def test_proof_cannot_admit_a_different_prior_state(conn, first, operational_source, monkeypatch):
    refresh(conn, operational_source, monkeypatch)
    with op.pinned(conn) as (pub, binding):
        _, _, proof = continuity.prepare(conn, prior=first.state,
            previous_binding=origin.read(conn).snapshot, publication=pub, binding=binding)
        with pytest.raises(HistoryReconstructionRequired, match="BINDING"):
            require_history_compatible(prior_version=first.state.data_version,
                last_processed_session=first.session, version=pub.version, proof=proof,
                prior_state_sha256="a" * 64, session=pub.window_end)


def test_checkpoint_reads_only_current_suffix_in_read_only_transaction(conn, first, operational_source, monkeypatch):
    refresh(conn, operational_source, monkeypatch)
    advance(conn)
    refresh(conn, operational_source, monkeypatch)
    latest = advance(conn)
    original = shadow.PostgresShadowObservationStore.records
    def bounded(self):
        assert self.records_from == latest.session
        assert conn.execute("SHOW transaction_read_only").fetchone()[0] == "on"
        assert conn.execute("SHOW transaction_isolation").fetchone()[0] == "repeatable read"
        rows = original(self)
        assert len(rows) == 1
        return rows
    monkeypatch.setattr(shadow.PostgresShadowObservationStore, "records", bounded)
    monkeypatch.setattr(continuity, "prepare", lambda *a, **k: pytest.fail("restart read prices"))
    monkeypatch.setattr(shadow, "advance_state", lambda *a, **k: pytest.fail("restart transitioned"))
    assert resume(conn).state.state_hash == latest.state.state_hash


def test_lost_commit_reply_recovers_once(conn, first, operational_source, monkeypatch):
    refresh(conn, operational_source, monkeypatch)
    original = cp.write
    def lost(*args, **kwargs):
        original(*args, **kwargs)
        conn.commit()
        raise ConnectionError("commit reply lost")
    monkeypatch.setattr(cp, "write", lost)
    with pytest.raises(ConnectionError, match="reply lost"):
        advance(conn)
    expected = cp.read(conn).state_sha256
    conn.commit()
    assert advance(conn).state.state_hash == expected
    assert advance(conn).appended is False


def test_stale_checkpoint_cannot_overwrite_current(conn, first, operational_source, monkeypatch):
    refresh(conn, operational_source, monkeypatch)
    advance(conn)
    stale = cp.read(conn)
    conn.commit()
    refresh(conn, operational_source, monkeypatch)
    latest = advance(conn)
    with pytest.raises(origin.RollingColdStartRefused, match="CAS_CHANGED"):
        cp.write(conn, stale, previous=stale)
    conn.rollback()
    assert resume(conn).state.state_hash == latest.state.state_hash


@pytest.mark.parametrize("defect", ["record", "foreign", "suffix"])
def test_checkpoint_refuses_tampered_or_foreign_lineage(conn, first, operational_source, monkeypatch, defect):
    refresh(conn, operational_source, monkeypatch)
    advance(conn)
    if defect == "record":
        conn.execute("UPDATE sentinel_processed_sessions SET state=jsonb_set(state,'{state,wealth_core,cash}','1') "
                     "WHERE cursor_name=%s", (f"shadow-observation:v1:{OBS}:session:2026-09-15",))
    else:
        name = "catchup" if defect == "foreign" else f"shadow-observation:v1:{OBS}:session:2026-09-16"
        conn.execute("INSERT INTO sentinel_processed_sessions VALUES (%s,'2026-09-16','{}')", (name,))
    conn.commit()
    with pytest.raises((origin.RollingColdStartRefused, shadow.ShadowObservationRefused)):
        resume(conn)


@pytest.mark.parametrize("boundary", ["deadline", "backup"])
def test_final_write_rechecks_authority(conn, first, operational_source, monkeypatch, boundary):
    refresh(conn, operational_source, monkeypatch)
    original = cp.write
    def late(*args, **kwargs):
        original(*args, **kwargs)
        if boundary == "deadline":
            monkeypatch.setattr(init, "_now", lambda conn: datetime(2026, 9, 16, 13, 30, tzinfo=timezone.utc))
        else:
            def refused(*a, **k):
                raise RuntimeError("backup unavailable")
            monkeypatch.setattr(daily.backup_runtime_authority, "require", refused)
    monkeypatch.setattr(cp, "write", late)
    with pytest.raises((origin.RollingColdStartRefused, RuntimeError), match="MISSED_OPEN|backup unavailable"):
        advance(conn)
    assert cp.read(conn) is None
    assert resume(conn).state.state_hash == first.state.state_hash


def test_writer_lock_excludes_continuation(conn, first, operational_source, monkeypatch):
    from sentinel.feed import store
    refresh(conn, operational_source, monkeypatch)
    other = store.connect(conn.info.dsn)
    try:
        with daily.journal.writer_lock(other):
            with pytest.raises(daily.journal.WriterLockUnavailable):
                advance(conn)
        assert resume(conn).state.state_hash == first.state.state_hash
    finally:
        other.close()


@pytest.mark.parametrize("defect,reason", [
    ("keys", "IDENTITY_KEYS"), ("signal", "NONUNIFORM_SIGNAL"),
    ("raw", "RAW_ECONOMICS"), ("spy", "NONUNIFORM_BENCHMARK"),
    ("bil", "BIL_RAW_ECONOMICS"),
])
def test_overlap_guard_distinguishes_economic_changes(monkeypatch, defect, reason):
    from stock_strategy_shared.wealth_core.feed import VendorBar
    from sentinel.feed.rolling_contract import CanonicalBenchmark
    axis = ("2026-09-10", "2026-09-11", "2026-09-14")
    bars = [VendorBar(day, "1", "AAA", raw_close=20. + i, raw_open=19. + i,
                      volume=1000., signal_close=10. + i) for i, day in enumerate(axis)]
    benchmarks = [CanonicalBenchmark(session=day, spy_total_return=600. + i,
        bil_open_signal=90., bil_close_signal=91., bil_close_adjusted=100. + i,
        bil_close_unadjusted=92.) for i, day in enumerate(axis)]
    current_bars, current_benchmarks = deepcopy(bars), deepcopy(benchmarks)
    if defect == "keys":
        current_bars.pop(1)
    elif defect == "signal":
        current_bars[1] = replace(current_bars[1], signal_close=13.)
    elif defect == "raw":
        current_bars[1] = replace(current_bars[1], raw_close=22.)
    else:
        field = "spy_total_return" if defect == "spy" else "bil_close_unadjusted"
        current_benchmarks[1] = current_benchmarks[1].model_copy(update={field: 123.})
    def reader(candidate, rows):
        def stream(**kwargs):
            yield from rows
        return SimpleNamespace(candidate_id=candidate,
            manifest=SimpleNamespace(window=SimpleNamespace(start=axis[0])), bars=stream)
    monkeypatch.setattr(rolling_store, "read_benchmarks",
        lambda conn, candidate: iter(benchmarks if candidate == "old" else current_benchmarks))
    refs = SimpleNamespace(resolver=SimpleNamespace(resolve=lambda ticker, day: "1"))
    with pytest.raises(continuity.RollingContinuityRefused, match=reason):
        continuity._overlap(None, reader("old", bars), reader("new", current_bars), refs, axis[-1])


def test_live_anchor_outside_snapshot_refuses(conn, first, operational_source, monkeypatch):
    refresh(conn, operational_source, monkeypatch)
    prior = shadow.SessionState.from_dict(first.state.to_dict())
    next(iter(prior.feed["series"].values()))["signal_basis_anchor"][0] = "2000-01-03"
    with op.pinned(conn) as (pub, binding):
        from sentinel.core.rolling_reader import RollingReaderRefused
        with pytest.raises(RollingReaderRefused, match="ANCHOR_OUTSIDE"):
            continuity.prepare(conn, prior=prior, previous_binding=origin.read(conn).snapshot,
                               publication=pub, binding=binding)
