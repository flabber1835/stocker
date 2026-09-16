"""Real-Postgres bounded readers and canonical checkpoint rehearsal falsifiers."""
from copy import deepcopy
from dataclasses import replace
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from sentinel import rolling_rehearsal as rehearsal
from sentinel.core.rolling_reader import RollingPriceReader, RollingReaderRefused
from sentinel.feed import rolling_store as store
from sentinel.feed.rolling_builder import NORMALIZATION_VERSION
from sentinel.feed.rolling_contract import CanonicalBar, CanonicalBenchmark, PriceWindow, RestartRequirement
from tests.sentinel.test_rolling_snapshot_storage import pg, conn, begin  # noqa: F401
from tests.sentinel import test_shadow_observation as shadow


@pytest.fixture(scope="module")
def window():
    return PriceWindow.through(shadow.SECOND)


def candidate(conn, window, *, close=10., normalization=NORMALIZATION_VERSION,
              signal=None, bil_open=100., bil_adjusted=100.):
    value = begin(conn, window)
    store.write_bars(conn, value, (CanonicalBar(
        session=day, security_id="1", ticker="AAA", close_signal=signal,
        close_unadjusted=close, open_unadjusted=10., volume=1e6,
        split_ratio=1., dividend_per_share=0.) for day in window.sessions))
    store.write_benchmarks(conn, value, (CanonicalBenchmark(
        session=day, spy_total_return=600., bil_open_signal=bil_open,
        bil_close_signal=100., bil_close_adjusted=bil_adjusted,
        bil_close_unadjusted=100.) for day in window.sessions))
    manifest = store.seal(conn, value,
        expected_keys=((str(day), "1") for day in window.sessions),
        normalization_version=normalization, requirements=RestartRequirement())
    return value, manifest


def reader(conn, window, **kwargs):
    value, manifest = candidate(conn, window, **kwargs)
    return RollingPriceReader(conn, candidate_id=value, snapshot_id=manifest.snapshot_id)


def prior_and_baseline():
    observer, _ = shadow._observer()
    result = observer.observe(shadow._fully_published(shadow.FIRST))
    baseline = replace(shadow._fully_published(shadow.SECOND).published,
                       spy_closeadj=[600.] * 25)
    # Match PostgreSQL DOUBLE PRECISION, rather than the older in-memory
    # fixture's integer volume spelling (Python equality hides that difference).
    baseline = replace(baseline, bars=[replace(bar, volume=float(bar.volume))
                                       for bar in baseline.bars])
    return result.state, baseline, observer.controller_config


def test_explicit_generation_and_bounded_sql(conn, window, monkeypatch):
    old = reader(conn, window)
    newer = reader(conn, window, close=20.)
    from sentinel.core import rolling_reader as module
    original = module.streaming_cursor
    calls = []
    def capture(actual, sql, params):
        calls.append((sql, params))
        return original(actual, sql, params)
    monkeypatch.setattr(module, "streaming_cursor", capture)
    assert [b.raw_close for b in old.bars(start=shadow.SECOND, end=shadow.SECOND)] == [10.]
    assert [b.raw_close for b in newer.bars(start=shadow.SECOND, end=shadow.SECOND)] == [20.]
    assert all("candidate_id=%s AND session BETWEEN %s AND %s" in sql for sql, _ in calls)
    assert calls[0][1] == (old.candidate_id, shadow.SECOND, shadow.SECOND)


def test_snapshot_identity_cannot_be_substituted(conn, window):
    value, _manifest = candidate(conn, window)
    with pytest.raises(RollingReaderRefused, match="SNAPSHOT_ID_MISMATCH"):
        RollingPriceReader(conn, candidate_id=value, snapshot_id="a" * 64)


def test_unknown_semantics_refuse(conn, window):
    with pytest.raises(RollingReaderRefused, match="UNSUPPORTED_SNAPSHOT_SEMANTICS"):
        reader(conn, window, normalization="unreviewed/2")


def test_unsealed_candidate_refuses(conn, window):
    with pytest.raises(store.SnapshotStorageRefused, match="sealed manifest"):
        RollingPriceReader(conn, candidate_id=begin(conn, window), snapshot_id="a" * 64)


def test_price_range_cannot_escape_snapshot(conn, window):
    selected = reader(conn, window)
    with pytest.raises(RollingReaderRefused, match="PRICE_RANGE_OUTSIDE_SNAPSHOT"):
        list(selected.bars(start="2000-01-03", end=shadow.SECOND))


@pytest.mark.parametrize("count", [1, True, 2.5, 301])
def test_invalid_or_unavailable_spy_tail_refuses(conn, window, count):
    selected = reader(conn, window)
    with pytest.raises(RollingReaderRefused):
        selected.prices(session=shadow.SECOND, spy_sessions=count, anchor_sessions={})


def test_restart_budget_is_measured_through_cursor_not_window_end(conn, window):
    selected = reader(conn, window)
    prior, _, _ = prior_and_baseline()
    selected.require_checkpoint_window(prior)
    prior.last_processed_session = str(window.sessions[250])
    with pytest.raises(RollingReaderRefused, match="CHECKPOINT_RESTART_WINDOW_UNAVAILABLE"):
        selected.require_checkpoint_window(prior)


@pytest.mark.parametrize("day", ["2000-01-03", shadow.SECOND])
def test_old_or_future_live_anchor_is_not_guessed(conn, window, day):
    selected = reader(conn, window)
    with pytest.raises(RollingReaderRefused, match="LIVE_SIGNAL_ANCHOR_OUTSIDE_SNAPSHOT"):
        selected.prices(session=shadow.SECOND, spy_sessions=25, anchor_sessions={"1": day})


def test_missing_live_anchor_is_not_guessed(conn, window):
    selected = reader(conn, window)
    with pytest.raises(RollingReaderRefused, match="LIVE_SIGNAL_ANCHOR_MISSING"):
        selected.prices(session=shadow.SECOND, spy_sessions=25, anchor_sessions={"1": shadow.FIRST})


def test_anchor_identity_date_and_price_domains(conn, window):
    selected = reader(conn, window, signal=5.)
    prices = selected.prices(session=shadow.SECOND, spy_sessions=254,
                             anchor_sessions={"1": shadow.FIRST})
    anchor = prices.signal_basis_anchors["1"]
    assert (anchor.security_id, anchor.session, anchor.raw_close, anchor.signal_close) == (
        "1", shadow.FIRST, 10., 5.)
    assert prices.bars[0].signal_close == 5.
    assert prices.bars[0].raw_close == 10.
    assert len(prices.benchmarks) == 254
    assert prices.benchmarks[-1].spy_total_return == 600.


def test_corrupt_benchmark_tail_refuses(conn, window):
    selected = reader(conn, window)
    with conn.cursor() as cur:
        cur.execute("ALTER TABLE sentinel_snapshot_benchmarks DISABLE TRIGGER snapshot_immutable")
        cur.execute("DELETE FROM sentinel_snapshot_benchmarks WHERE candidate_id=%s AND session=%s",
                    (selected.candidate_id, shadow.FIRST))
        cur.execute("ALTER TABLE sentinel_snapshot_benchmarks ENABLE TRIGGER snapshot_immutable")
    with pytest.raises(RollingReaderRefused, match="INCOMPLETE_SPY_BIL_TAIL"):
        selected.prices(session=shadow.SECOND, spy_sessions=254, anchor_sessions={})


def test_empty_session_refuses(conn, window):
    selected = reader(conn, window)
    with conn.cursor() as cur:
        cur.execute("ALTER TABLE sentinel_snapshot_bars DISABLE TRIGGER snapshot_immutable")
        cur.execute("DELETE FROM sentinel_snapshot_bars WHERE candidate_id=%s AND session=%s",
                    (selected.candidate_id, shadow.SECOND))
        cur.execute("ALTER TABLE sentinel_snapshot_bars ENABLE TRIGGER snapshot_immutable")
    with pytest.raises(RollingReaderRefused, match="EMPTY_SNAPSHOT_SESSION"):
        selected.prices(session=shadow.SECOND, spy_sessions=254, anchor_sessions={})


def test_comparison_preserves_explicit_legacy_references(conn, window):
    selected = reader(conn, window)
    _, baseline, _ = prior_and_baseline()
    prices = selected.prices(session=shadow.SECOND, spy_sessions=25, anchor_sessions={})
    comparison = prices.comparison_input(baseline)
    for field in ("meta", "sectors", "terminal_events", "spinoff_distributions",
                  "feed_anchors", "history_proof"):
        assert getattr(comparison, field) is getattr(baseline, field)
    assert comparison.data_version == baseline.data_version
    assert not hasattr(prices, "data_version")
    with pytest.raises(RollingReaderRefused, match="BASELINE_SESSION_MISMATCH"):
        prices.comparison_input(replace(baseline, session=shadow.FIRST))
    with pytest.raises(RollingReaderRefused, match="BASELINE_SPY_AXIS_MISMATCH"):
        prices.comparison_input(replace(baseline, spy_expected_sessions=()))


@pytest.mark.parametrize("field", ["bil_open", "bil_adjusted"])
def test_storage_optional_bil_fields_are_required_for_economic_read(conn, window, field):
    selected = reader(conn, window, **{field: None})
    _, baseline, _ = prior_and_baseline()
    prices = selected.prices(session=shadow.SECOND, spy_sessions=25, anchor_sessions={})
    with pytest.raises(ValueError, match="positive finite"):
        prices.comparison_input(baseline)


def test_kernel_rehearsal_preserves_checkpoint_and_has_no_authority(conn, window):
    selected = reader(conn, window)
    prior, baseline, config = prior_and_baseline()
    before = deepcopy(prior.to_dict())
    result = rehearsal.compare_transition(selected, prior=prior, baseline=baseline,
                                          controller_config=config)
    assert prior.to_dict() == before
    assert result["session"] == shadow.SECOND
    assert set(result) == {"session", "input_sha256", "successor_state_sha256", "decision_sha256"}
    expected = rehearsal.advance_session(prior, baseline, controller_config=config,
                                         strategy_identity=prior.strategy_identity)
    assert result["successor_state_sha256"] == expected.state_hash


def test_input_drift_refuses_even_when_book_holds_only_cash(conn, window):
    selected = reader(conn, window, close=10.01)
    prior, baseline, config = prior_and_baseline()
    assert not prior.wealth_core["episodes"]
    with pytest.raises(RollingReaderRefused, match="PRICE_INPUT_DIFFERENCE"):
        rehearsal.compare_transition(selected, prior=prior, baseline=baseline,
                                      controller_config=config)


def test_exact_input_comparison_does_not_use_python_numeric_equality(conn, window):
    selected = reader(conn, window)
    prior, baseline, config = prior_and_baseline()
    baseline = replace(baseline, bars=[replace(bar, volume=int(bar.volume))
                                       for bar in baseline.bars])
    with pytest.raises(RollingReaderRefused, match="PRICE_INPUT_DIFFERENCE"):
        rehearsal.compare_transition(selected, prior=prior, baseline=baseline,
                                      controller_config=config)


def test_nonconsecutive_successor_refuses(conn, window):
    selected = reader(conn, window)
    prior, baseline, config = prior_and_baseline()
    prior.last_processed_session = str(window.sessions[-3])
    with pytest.raises(RollingReaderRefused, match="CHECKPOINT_SUCCESSOR_REQUIRED"):
        rehearsal.compare_transition(selected, prior=prior, baseline=baseline,
                                      controller_config=config)


def test_kernel_output_difference_refuses(conn, window, monkeypatch):
    selected = reader(conn, window)
    prior, baseline, config = prior_and_baseline()
    original = rehearsal.advance_session
    calls = []
    def broken(*args, **kwargs):
        result = original(*args, **kwargs)
        if calls:
            result.shadow_peak_nav += 1
        calls.append(1)
        return result
    monkeypatch.setattr(rehearsal, "advance_session", broken)
    with pytest.raises(RollingReaderRefused, match="SUCCESSOR_STATE_DIFFERENCE"):
        rehearsal.compare_transition(selected, prior=prior, baseline=baseline,
                                      controller_config=config)


def attested_runtime(monkeypatch):
    actual = shadow.FakePostgres()
    observer, _ = shadow._observer(store=shadow.SO.PostgresShadowObservationStore(
        actual, observation_id="year-end-2026"))
    shadow._install_runtime_gates(monkeypatch, actual)
    runtime = shadow._postgres_runtime(actual, observer=observer,
                                       clock=lambda: shadow._preopen_clock())
    runtime.advance_next()
    runtime.warmup_input_loader = rehearsal._no_warmup
    return runtime


def test_checkpoint_uses_existing_attestations_not_vendor_genesis(monkeypatch):
    runtime = attested_runtime(monkeypatch)
    before = deepcopy(runtime.observer.store.records())
    state, origin = rehearsal.checkpoint(runtime)
    assert origin["state_sha256"] == state.state_hash
    assert origin["authority_sha256"] == runtime.observer.store.authorities()[-1]["authority_sha256"]
    assert runtime.observer.store.records() == before


def test_checkpoint_rejects_unattested_candidate(monkeypatch):
    runtime = attested_runtime(monkeypatch)
    monkeypatch.setattr(runtime.observer.store, "authorities", lambda: [])
    with pytest.raises(shadow.SO.ShadowObservationRefused, match="lacks exact runtime authority"):
        rehearsal.checkpoint(runtime)


def test_checkpoint_rejects_rehashed_corrupt_authority(monkeypatch):
    runtime = attested_runtime(monkeypatch)
    authorities = runtime.observer.store.authorities()
    authorities[-1]["state_sha256"] = "a" * 64
    authorities[-1]["authority_sha256"] = shadow.SO._sha256(
        {k: v for k, v in authorities[-1].items() if k != "authority_sha256"})
    monkeypatch.setattr(runtime.observer.store, "authorities", lambda: authorities)
    with pytest.raises(shadow.SO.ShadowObservationRefused, match="authority is incoherent"):
        rehearsal.checkpoint(runtime)


def test_write_capable_transaction_refuses_before_any_work(conn):
    with pytest.raises(RollingReaderRefused, match="READ_ONLY_REPEATABLE_READ_REQUIRED"):
        rehearsal.rehearse(conn, job_id="unused", observation_id="unused", controller_config=None)


def test_cli_rolls_back_and_redacts_driver_errors(monkeypatch, capsys):
    from tools import sentinel_rolling_reader_compare as cli
    calls = []
    class Connection:
        def cursor(self):
            raise RuntimeError("postgresql://secret:password@example")
        def rollback(self):
            calls.append("rollback")
        def close(self):
            calls.append("close")
    monkeypatch.setenv("SENTINEL_DATABASE_URL", "not-reported")
    monkeypatch.setattr(cli, "connect", lambda *a, **k: Connection())
    assert cli.main(["--job-id", "x", "--observation-id", "x"]) == 1
    assert calls == ["rollback", "close"]
    output = capsys.readouterr().out
    assert "RuntimeError" in output and "password" not in output


@pytest.fixture
def rehearsal_setup(conn, window, monkeypatch):
    runtime = attested_runtime(monkeypatch)
    value, manifest = candidate(conn, window)
    with conn.cursor() as cur:
        cur.execute("CREATE TABLE IF NOT EXISTS sentinel_processed_sessions "
                    "(cursor_name TEXT PRIMARY KEY,session DATE NOT NULL,state JSONB NOT NULL)")
        for name, (day, payload) in runtime.conn.rows.items():
            cur.execute("INSERT INTO sentinel_processed_sessions VALUES (%s,%s,%s::jsonb) "
                        "ON CONFLICT DO NOTHING", (name, day, rehearsal.canonical_json(payload)))
    conn.commit()
    prior, baseline, config = prior_and_baseline()
    baseline = replace(baseline, spy_closeadj=[600.] * 254,
        spy_sessions=shadow.calendar.previous_sessions(shadow.SECOND, 254),
        spy_expected_sessions=shadow.calendar.previous_sessions(shadow.SECOND, 254))
    request = rehearsal.rolling_jobs.PreparationRequest(
        window=window, expected_publication_version=7, cursor=shadow.FIRST,
        strategy_sha256=rehearsal.digest(prior.strategy_identity), dependencies_sha256="a" * 64)
    comparison = {"candidate_id": value, "snapshot_id": manifest.snapshot_id,
                  "comparison_version": 1, "scope": "COMPARISON_ONLY", "job_id": "test-job"}
    @contextmanager
    def pinned(actual, *, commit):
        assert actual is conn and commit is False
        yield SimpleNamespace(version=7)
    monkeypatch.setattr(rehearsal.publication, "pinned", pinned)
    monkeypatch.setattr(rehearsal.rolling_publisher, "published", lambda *args: comparison)
    monkeypatch.setattr(rehearsal.rolling_jobs, "status", lambda *args: {
        "request": request.model_dump(mode="json")})
    monkeypatch.setattr(rehearsal, "load_published_session", lambda *args, **kwargs: baseline)
    with conn.cursor() as cur:
        cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
    return config, request, comparison


def test_read_only_rehearsal_uses_retained_origin_and_never_promotes(conn, rehearsal_setup):
    config, _, comparison = rehearsal_setup
    with conn.cursor() as cur:
        cur.execute("SELECT cursor_name,state FROM sentinel_processed_sessions ORDER BY cursor_name")
        before = cur.fetchall()
    report = rehearsal.rehearse(conn, job_id="test-job", observation_id="year-end-2026",
                                controller_config=config)
    assert report["operational_go"] is False
    assert report["status"] == "PRICE_READER_PARITY_PASS"
    assert report["comparison"] == comparison
    assert report["checkpoint"]["cursor"] == shadow.FIRST
    assert report["shared_legacy_inputs"] == list(rehearsal.SHARED_LEGACY_INPUTS)
    with conn.cursor() as cur:
        cur.execute("SELECT cursor_name,state FROM sentinel_processed_sessions ORDER BY cursor_name")
        assert cur.fetchall() == before


@pytest.mark.parametrize("field,value,reason", [
    ("expected_publication_version", 6, "LEGACY_PUBLICATION_CHANGED"),
    ("strategy_sha256", "b" * 64, "CHECKPOINT_STRATEGY_MISMATCH"),
    ("cursor", "2026-08-19", "CHECKPOINT_CURSOR_MISMATCH"),
])
def test_rehearsal_refuses_changed_bindings(conn, rehearsal_setup, monkeypatch, field, value, reason):
    config, request, _ = rehearsal_setup
    changed = {**request.model_dump(mode="json"), field: value}
    monkeypatch.setattr(rehearsal.rolling_jobs, "status", lambda *args: {"request": changed})
    with pytest.raises(RollingReaderRefused, match=reason):
        rehearsal.rehearse(conn, job_id="test-job", observation_id="year-end-2026",
                            controller_config=config)


def test_unpublished_comparison_refuses(conn, rehearsal_setup, monkeypatch):
    config, _, _ = rehearsal_setup
    monkeypatch.setattr(rehearsal.rolling_publisher, "published", lambda *args: None)
    with pytest.raises(RollingReaderRefused, match="PUBLISHED_COMPARISON_REQUIRED"):
        rehearsal.rehearse(conn, job_id="test-job", observation_id="year-end-2026",
                            controller_config=config)


def test_selected_champion_resumes_pending_book_through_same_kernel(conn, window):
    from stock_strategy_shared.wealth_core.feed import SecurityMeta, VendorBar
    from sentinel.controller.machine import Controller
    from sentinel.core.loader import CorpusWindow
    from sentinel.core.production import warm_session_state
    from sentinel.core.session import DefensiveBar, PublishedSession, SessionState
    from sentinel.strategy import production_strategy
    sessions = [str(day) for day in window.sessions]
    meta = {str(i): SecurityMeta(str(i), f"T{i}", "Common Stock", str(i),
                                first_session=sessions[0]) for i in range(30)}
    bars = {s: [VendorBar(s, sid, m.ticker, 100.+index, 100.+index, 1e6,
                          signal_close=100.+index) for sid, m in meta.items()]
            for index, s in enumerate(sessions)}
    cfg, identity = production_strategy()
    warm = CorpusWindow(sessions[-254:-2], bars, meta)
    warm.median5_spy_closes = {s: 600. for s in warm.sessions}
    seed = SessionState.fresh(starting_cash=1e6, controller=Controller(cfg), strategy_identity=identity)
    warmed = warm_session_state(seed, warm, publication_version=1,
                                prospective_concordance_witness=True)
    def baseline(day):
        axis = shadow.calendar.previous_sessions(day, 254)
        return PublishedSession(day, 1, bars[day], meta, {sid: "Technology" for sid in meta},
            [600.] * 254, spy_sessions=axis, spy_expected_sessions=axis,
            defensive_bar=DefensiveBar(day, "SENTINEL:BIL", "BIL", 100., 100., 100., 100.),
            defensive_previous_bar=DefensiveBar(axis[-2], "SENTINEL:BIL", "BIL", 100., 100., 100., 100.))
    prior = rehearsal.advance_session(warmed, baseline(shadow.FIRST), controller_config=cfg,
                                       strategy_identity=identity)
    assert prior.pending  # The checkpoint carries real pending initial admissions.
    value = begin(conn, window)
    store.write_bars(conn, value, (CanonicalBar(session=bar.session, security_id=bar.security_id,
        ticker=bar.ticker, close_signal=bar.signal_close, close_unadjusted=bar.raw_close,
        open_unadjusted=bar.raw_open, volume=bar.volume, split_ratio=bar.split_ratio,
        dividend_per_share=bar.dividend_per_share) for rows in bars.values() for bar in rows))
    store.write_benchmarks(conn, value, (CanonicalBenchmark(session=day, spy_total_return=600.,
        bil_open_signal=100., bil_close_signal=100., bil_close_adjusted=100., bil_close_unadjusted=100.)
        for day in window.sessions))
    manifest = store.seal(conn, value,
        expected_keys=((s, sid) for s in sessions for sid in sorted(meta)),
        normalization_version=NORMALIZATION_VERSION, requirements=RestartRequirement())
    selected = RollingPriceReader(conn, candidate_id=value, snapshot_id=manifest.snapshot_id)
    before = prior.state_hash
    result = rehearsal.compare_transition(selected, prior=prior, baseline=baseline(shadow.SECOND),
                                          controller_config=cfg)
    expected = rehearsal.advance_session(prior, baseline(shadow.SECOND), controller_config=cfg,
                                         strategy_identity=identity)
    assert expected.wealth_core["episodes"]  # Same pending admissions actually filled.
    assert result["successor_state_sha256"] == expected.state_hash
    assert prior.state_hash == before
