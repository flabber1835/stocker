from copy import deepcopy
from contextlib import contextmanager
import json
from types import SimpleNamespace

from stock_strategy_shared.wealth_core.adapter import PendingOrder
from stock_strategy_shared.wealth_core.engine import Operation, Reason
from stock_strategy_shared.wealth_core.ledger import EventType

from stock_strategy_shared.wealth_core.feed import (
    FeedError, SecurityMeta, SecuritySeries, VendorBar)
from stock_strategy_shared.wealth_core.state import HoldingEpisode, PortfolioState

from sentinel.controller.frozen_rule import load
from sentinel.controller.machine import Controller
from sentinel.core.production import (
    FeedAnchor, PublishedSession, SessionState, advance_state,
    load_published_session)
from sentinel.core import production
from sentinel.core.terminal import TerminalLoadResult


def _spy_fields(session: str, closes):
    closes = list(closes)
    tail = [f"0000-SPY-{index:04d}" for index in range(len(closes) - 1)]
    tail.append(session)
    return {"spy_closeadj": closes, "spy_sessions": tail,
            "spy_expected_sessions": tail}


def _published(session="2026-08-10", version=7):
    meta = {"1": SecurityMeta("1", "AAA", category="Domestic Common Stock",
                               permaticker="1", first_session=session)}
    return PublishedSession(
        session=session, data_version=version, meta=meta, sectors={"1": "TECH"},
        bars=[VendorBar(session, "1", "AAA", 10.0, 10.0, 1_000_000)],
        **_spy_fields(session, [100.0 + i for i in range(25)]))


def test_production_breadth_uses_the_certified_float32_lag_return():
    series = SecuritySeries(
        security_id="1", ticker="AAA", issuer_id="P:1",
        sessions=["S0000", "S0021"], session_indices=[0, 21],
        signal_closes=[100.1, 100.1], raw_closes=[100.1, 100.1],
        volumes=[1_000_000, 1_000_000])
    assert 100.1 / 100.1 - 1.0 == 0.0
    assert production._return(series, 21) > 0.0


def _fresh():
    config = load()
    return config, SessionState.fresh(
        starting_cash=100_000, controller=Controller(config),
        strategy_identity={"strategy": config.strategy_id,
                           "controller_rule_sha256": config.digest,
                           "wealth_core_source_sha256": "test-source"})


def _advance(state, published, config):
    return advance_state(state, published, controller_config=config,
                         strategy_identity=state.strategy_identity)


def _synthetic_published(number: int, version: int = 7) -> PublishedSession:
    """One fixed-width session from a production-shaped, split-bearing feed."""
    session = f"S{number:04d}"
    meta = {"1": SecurityMeta(
        "1", "AAA", category="Domestic Common Stock", permaticker="1",
        related_tickers=("AAA",), first_session="S0001")}
    split = 2.0 if number == 50 else 1.0
    raw_close = 10.0 if number < 50 else 5.0
    return PublishedSession(
        session=session, data_version=version, meta=meta,
        sectors={"1": "TECH"},
        bars=[VendorBar(session, "1", "AAA", raw_close, raw_close,
                        1_000_000, split_ratio=split)],
        spy_closeadj=[100.0 + i + (0.2 if i % 3 == 0 else 0.0)
                      for i in range(41)])


def _turnover_published(number: int, version: int = 7) -> PublishedSession:
    """One genuinely new, fixed-width security on every market session."""
    session = f"S{number:04d}"
    security_id = f"P{number:04d}"
    ticker = f"T{number:04d}"
    meta = {security_id: SecurityMeta(
        security_id, ticker, category="Domestic Common Stock",
        permaticker=security_id, related_tickers=(ticker,),
        first_session=session)}
    return PublishedSession(
        session=session, data_version=version, meta=meta,
        sectors={security_id: "TECH"},
        bars=[VendorBar(session, security_id, ticker, 10.0, 10.0,
                        1_000_000)],
        spy_closeadj=[100.0 + i + (0.2 if i % 3 == 0 else 0.0)
                      for i in range(41)])


def _serialized_size(state: SessionState) -> int:
    return len(json.dumps(
        state.to_dict(), sort_keys=True, separators=(",", ":")).encode())


def _run_synthetic(count: int, *, reload_every: int | None = None):
    config, state = _fresh()
    decisions = []
    plan_hashes = []
    measurements = {0: _serialized_size(state)}
    for number in range(1, count + 1):
        if reload_every and number > 1 and (number - 1) % reload_every == 0:
            state = SessionState.from_dict(json.loads(json.dumps(state.to_dict())))
        state = _advance(state, _synthetic_published(number), config)
        decisions.append(deepcopy(state.last_decision))
        plan_hashes.append(deepcopy(state.last_evidence["wealth_core"]["hashes"]))
        if number in (256, 1_000):
            measurements[number] = _serialized_size(state)
    return state, decisions, plan_hashes, measurements


def _run_turnover(count: int, *, reload_every: int | None = None):
    config, state = _fresh()
    decisions = []
    plan_hashes = []
    measurements = {0: _serialized_size(state)}
    for number in range(1, count + 1):
        if reload_every and number > 1 and (number - 1) % reload_every == 0:
            state = SessionState.from_dict(json.loads(json.dumps(state.to_dict())))
        state = _advance(state, _turnover_published(number), config)
        decisions.append(deepcopy(state.last_decision))
        plan_hashes.append(deepcopy(state.last_evidence["wealth_core"]["hashes"]))
        if number in (256, 512, 1_000):
            measurements[number] = _serialized_size(state)
    return state, decisions, plan_hashes, measurements


def test_one_session_advance_persists_complete_authoritative_envelope():
    config, before = _fresh()
    after = _advance(before, _published(), config)

    assert before.last_processed_session is None
    assert after.last_processed_session == "2026-08-10"
    assert after.data_version == 7
    assert isinstance(after.pending, list)
    assert after.wealth_core["slots"]
    assert after.controller["last_session"] == "2026-08-10"
    assert after.last_decision["session"] == "2026-08-10"
    assert after.last_evidence["observation"]["spy_r20"] is not None
    assert "state_after" not in after.last_evidence["wealth_core"]
    assert "pending_after" not in after.last_evidence["wealth_core"]


def test_reload_is_identical_and_does_not_alias_prior_state():
    config, before = _fresh()
    raw = deepcopy(before.to_dict())
    reloaded = SessionState.from_dict(raw)
    a = _advance(before, _published(), config)
    b = _advance(reloaded, _published(), config)

    assert a.to_dict() == b.to_dict()
    assert a.state_hash == b.state_hash
    assert before.to_dict() == raw


def test_publication_version_cannot_move_backwards():
    config, before = _fresh()
    before.data_version = 8
    try:
        _advance(before, _published(version=7), config)
    except ValueError as exc:
        assert "moved backwards" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("backward publication was accepted")


def test_failure_leaves_the_prior_envelope_authoritative():
    config, before = _fresh()
    raw = deepcopy(before.to_dict())
    broken = _published()
    broken = PublishedSession(**{
        **broken.__dict__, "bars": [broken.bars[0], broken.bars[0]]})

    try:
        _advance(before, broken, config)
    except ValueError:
        pass
    else:  # pragma: no cover
        raise AssertionError("invalid duplicate session bars were accepted")
    assert before.to_dict() == raw


def test_lifetime_peak_outside_rolling_history_controls_drawdown():
    config, before = _fresh()
    before.shadow_peak_nav = 200_000
    before.shadow_nav_history = [100_000] * 64
    after = _advance(before, _published(), config)
    assert after.last_evidence["observation"]["shadow_drawdown"] == -0.5
    assert after.shadow_peak_nav == 200_000


def test_version_one_is_explicitly_refused():
    _, before = _fresh()
    raw = before.to_dict()
    raw["version"] = 1
    try:
        SessionState.from_dict(raw)
    except ValueError as exc:
        assert "cannot be migrated safely" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("unsafe version-1 state was accepted")


def test_production_envelope_refuses_nonfinite_json_numbers():
    for value in (float("nan"), float("inf"), float("-inf")):
        _, state = _fresh()
        persisted = state.to_dict()
        persisted["shadow_peak_nav"] = value
        try:
            SessionState.from_dict(persisted)
        except ValueError as exc:
            assert "Out of range float values" in str(exc)
        else:  # pragma: no cover
            raise AssertionError(f"non-finite persisted state {value!r} loaded")

        state.shadow_peak_nav = value
        try:
            state.to_dict()
        except ValueError as exc:
            assert "Out of range float values" in str(exc)
        else:  # pragma: no cover
            raise AssertionError(f"non-finite state {value!r} was serialised")


def test_persisted_identity_must_match_running_source():
    config, before = _fresh()
    wrong = {**before.strategy_identity,
             "wealth_core_source_sha256": "different-source"}
    try:
        advance_state(before, _published(), controller_config=config,
                      strategy_identity=wrong)
    except ValueError as exc:
        assert "differs from running identity" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("source identity drift was accepted")


def test_session_calculation_remains_inside_one_publication_pin(monkeypatch):
    from sentinel.core.production import advance_and_persist
    active = False

    @contextmanager
    def fake_pin(conn):
        nonlocal active
        active = True
        try:
            yield type("Pin", (), {"version": 7})()
        finally:
            active = False

    config, before = _fresh()

    def load_published(conn, session, *, known_feed_security_ids):
        assert active
        assert known_feed_security_ids == ()
        return _published(session=session)

    monkeypatch.setattr("sentinel.feed.publication.pinned", fake_pin)
    result = advance_and_persist(
        object(), "2026-08-10", before.to_dict(),
        load_published=load_published, controller_config=config,
        strategy_identity=before.strategy_identity)
    assert result["last_processed_session"] == "2026-08-10"
    assert not active


def test_advance_and_persist_migrates_before_requesting_reentry_anchor(
        monkeypatch):
    from sentinel.core.production import advance_and_persist

    @contextmanager
    def fake_pin(conn):
        yield type("Pin", (), {"version": 7})()

    config, state = _fresh()
    legacy = state.to_dict()
    legacy["version"] = 2
    legacy["last_processed_session"] = "S0200"
    legacy["data_version"] = 7
    legacy["feed"] = {
        "session_index": 200, "seen_sessions": {"S0001": 0},
        "series": {"RETURN": {
            "security_id": "RETURN", "ticker": "RTRN",
            "issuer_id": "P:RETURN", "split_factor": 2.0,
            "sessions": ["S0001"], "session_indices": [0],
            "signal_closes": [10.0], "raw_closes": [5.0],
            "volumes": [1_000_000]}}}
    legacy["last_known"] = {"RETURN": 5.0}
    meta = {"RETURN": SecurityMeta(
        "RETURN", "RTRN", category="Domestic Common Stock",
        permaticker="RETURN", related_tickers=("RTRN",),
        first_session="S0001")}

    def load_published(conn, session, *, known_feed_security_ids):
        assert session == "S0201"
        # The raw v2 envelope still names RETURN, but migration expires it.
        # Only the canonical feed may suppress corpus anchor reconstruction.
        assert known_feed_security_ids == ()
        return PublishedSession(
            session=session, data_version=7, meta=meta,
            sectors={"RETURN": "TECH"},
            bars=[VendorBar(session, "RETURN", "RTRN", 5.0, 5.0,
                            1_000_000)],
            spy_closeadj=[100.0 + i for i in range(41)],
            feed_anchors={"RETURN": FeedAnchor(
                "RETURN", "RTRN", "P:RETURN", prior_split_factor=2.0)})

    monkeypatch.setattr("sentinel.feed.publication.pinned", fake_pin)
    result = advance_and_persist(
        object(), "S0201", legacy, load_published=load_published,
        controller_config=config, strategy_identity=state.strategy_identity)
    series = result["feed"]["series"]["RETURN"]
    assert series["split_factor"] == 2.0
    assert series["signal_closes"] == [10.0]
    assert result["last_processed_session"] == "S0201"


def test_loaded_version_must_equal_the_pin(monkeypatch):
    from sentinel.core.production import advance_and_persist

    @contextmanager
    def fake_pin(conn):
        yield type("Pin", (), {"version": 8})()

    config, before = _fresh()
    monkeypatch.setattr("sentinel.feed.publication.pinned", fake_pin)
    try:
        advance_and_persist(
            object(), "2026-08-10", before.to_dict(),
            load_published=lambda *_, **__: _published(),
            controller_config=config,
            strategy_identity=before.strategy_identity)
    except RuntimeError as exc:
        assert "differs from session pin" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("a publication change inside a session was accepted")


def test_stop_evidence_waits_for_executed_fill_and_pending_exit_survives(monkeypatch):
    config, state = _fresh()

    def fake_plan(*, session, bars, feed, pending, ledger, **_):
        feed.advance(session, bars)
        if session == "2026-08-10":
            pending.append(PendingOrder(
                operation=Operation.CLOSE_POSITION, security_id="1", ticker="AAA",
                slot_id=0, shares=10, signal_session=session,
                reason=Reason.EXIT_TRAILING_STOP.value))
        elif session == "2026-08-12":
            ledger.post(
                session=session, event_type=EventType.SELL, cash_before=100_000,
                security_id="1", ticker="AAA", shares_delta=-10,
                cash_delta=100, price=10, reason=Reason.EXIT_TRAILING_STOP.value)
            pending.clear()
        return SimpleNamespace(estimated_equity=100_000, intents=[object()],
                               to_dict=lambda: {})

    monkeypatch.setattr("sentinel.core.production.plan_session", fake_plan)
    state = _advance(state, _published("2026-08-10"), config)
    assert state.last_evidence["observation"]["stops20"] == 0
    assert len(state.pending) == 1

    state = _advance(state, _published("2026-08-11"), config)
    assert state.last_evidence["observation"]["stops20"] == 0
    assert len(state.pending) == 1

    reloaded = SessionState.from_dict(state.to_dict())
    state = _advance(reloaded, _published("2026-08-12"), config)
    assert state.last_evidence["observation"]["stops20"] == 1
    assert state.pending == []


def test_completed_stops_keep_multiplicity_for_exactly_twenty_controller_sessions(monkeypatch):
    config, state = _fresh()

    def fake_plan(*, session, ledger, **_):
        if session == "2026-01-01":
            for _ in range(3):
                ledger.post(
                    session=session, event_type=EventType.SELL, cash_before=100_000,
                    security_id="1", ticker="AAA", shares_delta=-10,
                    cash_delta=100, price=10,
                    reason=Reason.EXIT_TRAILING_STOP.value)
        return SimpleNamespace(estimated_equity=100_000, intents=[],
                               to_dict=lambda: {})

    monkeypatch.setattr("sentinel.core.production.plan_session", fake_plan)
    for day in range(1, 21):
        state = _advance(state, _published(f"2026-01-{day:02d}"), config)
    assert state.last_evidence["observation"]["stops20"] == 3

    state = _advance(state, _published("2026-01-21"), config)
    assert state.last_evidence["observation"]["stops20"] == 0


def test_serialized_state_reaches_a_bounded_plateau_through_session_1000():
    state, _, _, sizes = _run_synthetic(1_000)
    series = state.feed["series"]["1"]

    assert len(state.feed["seen_sessions"]) == 127
    assert all(len(series[field]) == 127 for field in (
        "sessions", "session_indices", "signal_closes", "raw_closes", "volumes"))
    assert sizes[0] < sizes[256]
    # Integer index width changes at decimal boundaries, but retained object
    # count and economic evidence are already flat.  This byte band catches
    # even one extra session, while allowing that bounded representation detail.
    assert abs(sizes[1_000] - sizes[256]) <= 512
    assert sizes[1_000] < sizes[256] * 1.05
    print("serialized_sizes "
          f"before_warmup={sizes[0]} "
          f"plateau_session_256={sizes[256]} "
          f"session_1000={sizes[1_000]}")


def test_security_turnover_plateaus_and_restarts_are_identical():
    uninterrupted, decisions_a, hashes_a, sizes = _run_turnover(1_000)
    restarted, decisions_b, hashes_b, _ = _run_turnover(
        1_000, reload_every=7)

    assert len(uninterrupted.feed["series"]) == 127
    assert uninterrupted.last_known == {}
    plateau_sizes = [sizes[256], sizes[512], sizes[1_000]]
    assert max(plateau_sizes) - min(plateau_sizes) <= 512
    assert sizes[1_000] < sizes[256] * 1.02

    assert uninterrupted.wealth_core == restarted.wealth_core
    assert uninterrupted.pending == restarted.pending
    assert uninterrupted.ledger == restarted.ledger
    assert uninterrupted.controller == restarted.controller
    assert uninterrupted.last_decision == restarted.last_decision
    assert uninterrupted.last_evidence == restarted.last_evidence
    assert decisions_a == decisions_b
    assert hashes_a == hashes_b
    assert uninterrupted.state_hash == restarted.state_hash
    print("turnover_serialized_sizes "
          f"before_warmup={sizes[0]} "
          f"plateau_session_256={sizes[256]} "
          f"session_512={sizes[512]} "
          f"session_1000={sizes[1_000]}")


def test_evicted_split_security_reappears_on_its_original_signal_basis():
    config, state = _fresh()
    first_meta = {"SPLIT": SecurityMeta(
        "SPLIT", "SPLT", category="Domestic Common Stock",
        permaticker="SPLIT", related_tickers=("SPLT",),
        first_session="S0001")}
    state = _advance(state, PublishedSession(
        session="S0001", data_version=7, meta=first_meta,
        sectors={"SPLIT": "TECH"},
        bars=[VendorBar("S0001", "SPLIT", "SPLT", 5.0, 5.0,
                        1_000_000, split_ratio=2.0)],
        spy_closeadj=[100.0 + i for i in range(41)]), config)
    assert state.feed["series"]["SPLIT"]["signal_closes"] == [10.0]

    for number in range(2, 131):
        state = _advance(state, _turnover_published(number), config)
    assert "SPLIT" not in state.feed["series"]

    returning = PublishedSession(
        session="S0131", data_version=7, meta=first_meta,
        sectors={"SPLIT": "TECH"},
        bars=[VendorBar("S0131", "SPLIT", "SPLT", 5.0, 5.0,
                        1_000_000)],
        spy_closeadj=[100.0 + i for i in range(41)],
        feed_anchors={"SPLIT": FeedAnchor(
            "SPLIT", "SPLT", "P:SPLIT", prior_split_factor=2.0)})
    state = _advance(state, returning, config)
    series = state.feed["series"]["SPLIT"]
    assert series["split_factor"] == 2.0
    assert series["signal_closes"] == [10.0]
    assert series["issuer_id"] == "P:SPLIT"


def test_returning_security_without_a_corpus_anchor_fails_closed():
    config, state = _fresh()
    published = PublishedSession(
        session="S0200", data_version=7,
        meta={"OLD": SecurityMeta(
            "OLD", "OLD", category="Domestic Common Stock",
            permaticker="OLD", first_session="S0001")},
        sectors={"OLD": "TECH"},
        bars=[VendorBar("S0200", "OLD", "OLD", 10.0, 10.0, 1_000_000)],
        spy_closeadj=[100.0 + i for i in range(41)])
    try:
        _advance(state, published, config)
    except FeedError as exc:
        assert "no pinned-corpus split/identity anchor" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("a returning security silently took a new anchor")


def test_retained_persisted_series_requires_a_complete_valid_anchor():
    config, state = _fresh()
    state = _advance(state, _published(), config)
    valid = state.to_dict()

    for field_name in ("security_id", "ticker", "issuer_id", "split_factor"):
        broken = deepcopy(valid)
        del broken["feed"]["series"]["1"][field_name]
        try:
            SessionState.from_dict(broken)
        except ValueError as exc:
            assert "incomplete anchor" in str(exc)
            assert field_name in str(exc)
        else:  # pragma: no cover
            raise AssertionError(f"missing {field_name} anchor was synthesized")

    invalid = (
        ("security_id", "other"), ("ticker", ""), ("ticker", " "),
        ("issuer_id", ""), ("issuer_id", "\t"),
        ("split_factor", 0.0), ("split_factor", -1.0),
        ("split_factor", float("nan")), ("split_factor", float("inf")),
        ("split_factor", True))
    for field_name, value in invalid:
        broken = deepcopy(valid)
        broken["feed"]["series"]["1"][field_name] = value
        try:
            SessionState.from_dict(broken)
        except ValueError as exc:
            assert "anchor" in str(exc)
        else:  # pragma: no cover
            raise AssertionError(
                f"invalid {field_name} anchor {value!r} was accepted")


def test_path_dependent_securities_pin_anchors_and_marks_after_expiry():
    _, state = _fresh()
    portfolio = PortfolioState.from_dict(state.wealth_core)
    portfolio.episodes[0] = HoldingEpisode(
        security_id="held", ticker="HELD", issuer_id="P:held", slot_id=0,
        signal_date="S0000", entry_date="S0001", entry_raw_open=10.0,
        entry_split_adjusted_price=10.0, initial_shares=10,
        current_shares=10)
    portfolio.slots[0].occupied_by = "held"
    portfolio.slots[1].reserve("pending", "PEND", "P:pending")
    portfolio.security_cooldowns["cooldown"] = 3
    portfolio.unresolved_terminals["terminal"] = "unresolved terms"
    portfolio.sessions_since_valid_mark["terminal"] = 4
    portfolio.terminal_pending_sessions["terminal"] = 2
    portfolio.terminal_pending_terms["terminal"] = {"terms": {}}
    portfolio.terminal_carry_audit["terminal"] = {"session": "S0199"}
    portfolio.last_valid_mark_session["terminal"] = "S0199"
    state.wealth_core = portfolio.to_dict()
    state.pending = [PendingOrder(
        operation=Operation.OPEN_SLOT_POSITION, security_id="pending",
        ticker="PEND", slot_id=1, shares=10, signal_session="S0200",
        reason=Reason.ENTRY_DURABLE_RANK.value).to_dict()]

    def expired_series(security_id: str) -> dict:
        return {
            "security_id": security_id, "ticker": security_id.upper(),
            "issuer_id": f"P:{security_id}", "split_factor": 2.0,
            "sessions": ["S0001"], "session_indices": [0],
            "signal_closes": [10.0], "raw_closes": [5.0],
            "volumes": [1_000_000]}

    protected = {"held", "pending", "cooldown", "terminal"}
    state.feed = {
        "session_index": 200, "seen_sessions": {"S0001": 0},
        "series": {sid: expired_series(sid)
                   for sid in protected | {"expired"}}}
    state.last_known = {sid: 5.0 for sid in protected | {"expired"}}

    persisted = state.to_dict()
    assert set(persisted["feed"]["series"]) == protected
    assert set(persisted["last_known"]) == protected
    for sid in protected:
        assert persisted["feed"]["series"][sid]["sessions"] == []


def test_published_loader_reconstructs_prior_split_factor_from_pinned_rows(
        monkeypatch):
    meta = {"1": SecurityMeta(
        "1", "AAA", category="Domestic Common Stock", permaticker="1",
        related_tickers=("AAA",), first_session="S0001")}

    spy_tail = [f"S{number:04d}" for number in range(160, 201)]

    class Cursor:
        def __init__(self):
            self.sql = ""

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def execute(self, sql, _params=()):
            self.sql = sql
            executed.append(sql)

        def fetchall(self):
            if "SELECT security_id,ticker" in self.sql:
                return [("1", "AAA", 5.0, 5.0, 1_000_000, 1.0, 0.0)]
            if "SELECT session,closeadj" in self.sql:
                return list(reversed([
                    (session, 100.0 + index)
                    for index, session in enumerate(spy_tail)]))
            if "ARRAY_REMOVE(ARRAY_AGG(sector" in self.sql:
                return [("1", "TECH")]
            if "session<%s" in self.sql:
                return [("1", 2.0), ("1", 3.0)]
            raise AssertionError(self.sql)

    class Connection:
        def cursor(self):
            return Cursor()

    executed = []
    monkeypatch.setattr("sentinel.feed.publication.assert_coherent", lambda _: None)
    monkeypatch.setattr(
        "sentinel.feed.publication.current",
        lambda _: SimpleNamespace(version=7))
    monkeypatch.setattr(
        "sentinel.feed.publication.visible_predicate", lambda _: "TRUE")
    monkeypatch.setattr("sentinel.core.loader.load_meta", lambda _: meta)
    monkeypatch.setattr(
        "sentinel.core.loader.load_terminal_events",
        lambda *_, **__: TerminalLoadResult(events=[], rows=[]))
    monkeypatch.setattr(
        "sentinel.feed.universe.load_resolver",
        lambda _: SimpleNamespace(resolve_with_reason=lambda *_: None))
    monkeypatch.setattr(
        "sentinel.feed.calendar.previous_sessions",
        lambda session, count: spy_tail
        if (session, count) == ("S0200", 41) else [])

    published = load_published_session(Connection(), "S0200")
    anchor = published.feed_anchors["1"]
    assert anchor.prior_split_factor == 6.0
    assert anchor.issuer_id == "P:1"
    bar_queries = [sql for sql in executed if "FROM sentinel_bars b" in sql]
    assert len(bar_queries) == 2
    assert all("sentinel_bar_split_repairs" in sql for sql in bar_queries)
    universe_query = next(
        sql for sql in executed if "FROM sentinel_universe u" in sql)
    assert "TRUE" in universe_query


def test_restart_window_keeps_t_minus_126_and_discards_t_minus_127():
    config, state = _fresh()
    for number in range(1, 201):
        state = _advance(state, _synthetic_published(number), config)

    series = state.feed["series"]["1"]
    assert state.feed["session_index"] == 199
    assert series["sessions"][0] == "S0074"       # t - 126
    assert series["session_indices"][0] == 73
    assert "S0073" not in series["sessions"]      # t - 127
    assert "S0073" not in state.feed["seen_sessions"]
    assert len(series["sessions"]) == 127
    # The session carrying the 2:1 split has expired, but its path-dependent
    # factor and current security/issuer identity remain restart anchors.
    assert "S0050" not in series["sessions"]
    assert series["split_factor"] == 2.0
    assert series["security_id"] == "1"
    assert series["ticker"] == "AAA"
    assert series["issuer_id"] == "P:1"


def test_repeated_serialization_cycles_preserve_every_production_output():
    uninterrupted, decisions_a, hashes_a, _ = _run_synthetic(220)
    restarted, decisions_b, hashes_b, _ = _run_synthetic(220, reload_every=7)

    assert uninterrupted.wealth_core == restarted.wealth_core
    assert uninterrupted.pending == restarted.pending
    assert uninterrupted.ledger == restarted.ledger
    assert uninterrupted.controller == restarted.controller
    assert uninterrupted.last_decision == restarted.last_decision
    assert uninterrupted.last_evidence == restarted.last_evidence
    assert decisions_a == decisions_b
    assert hashes_a == hashes_b
    assert uninterrupted.state_hash == restarted.state_hash


def test_version_two_envelope_migrates_by_pruning_only_redundant_history():
    config, current = _fresh()
    for number in range(1, 201):
        current = _advance(current, _synthetic_published(number), config)

    legacy = deepcopy(current.to_dict())
    legacy["version"] = 2
    legacy["feed"]["seen_sessions"]["S0073"] = 72
    old = legacy["feed"]["series"]["1"]
    old["sessions"].insert(0, "S0073")
    old["session_indices"].insert(0, 72)
    old["signal_closes"].insert(0, 10.0)
    old["raw_closes"].insert(0, 5.0)
    old["volumes"].insert(0, 1_000_000)
    legacy["feed"]["series"]["dormant"] = {
        "security_id": "dormant", "ticker": "DORM", "issuer_id": "P:dormant",
        "split_factor": 4.0, "sessions": ["S0001"],
        "session_indices": [0], "signal_closes": [20.0],
        "raw_closes": [5.0], "volumes": [1_000_000]}
    legacy["last_known"]["dormant"] = 5.0
    legacy["last_evidence"]["wealth_core"]["state_after"] = {"recursive": True}
    legacy["last_evidence"]["wealth_core"]["pending_after"] = [{"copy": True}]

    migrated = SessionState.from_dict(legacy)
    plan_evidence = migrated.last_evidence["wealth_core"]
    assert migrated.version == 3
    assert migrated.feed == current.feed
    assert "dormant" not in migrated.feed["series"]
    assert "dormant" not in migrated.last_known
    assert "state_after" not in plan_evidence
    assert "pending_after" not in plan_evidence

    a = _advance(current, _synthetic_published(201), config)
    b = _advance(migrated, _synthetic_published(201), config)
    assert a.to_dict() == b.to_dict()
    assert a.state_hash == b.state_hash
