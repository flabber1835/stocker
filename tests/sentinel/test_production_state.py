from copy import deepcopy
from contextlib import contextmanager
import json
from types import SimpleNamespace

from stock_strategy_shared.wealth_core.adapter import PendingOrder
from stock_strategy_shared.wealth_core.engine import Operation, Reason
from stock_strategy_shared.wealth_core.ledger import EventType

from stock_strategy_shared.wealth_core.feed import SecurityMeta, VendorBar

from sentinel.controller.frozen_rule import load
from sentinel.controller.machine import Controller
from sentinel.core.production import PublishedSession, SessionState, advance_state


def _published(session="2026-08-10", version=7):
    meta = {"1": SecurityMeta("1", "AAA", category="Domestic Common Stock",
                               permaticker="1", first_session=session)}
    return PublishedSession(
        session=session, data_version=version, meta=meta, sectors={"1": "TECH"},
        bars=[VendorBar(session, "1", "AAA", 10.0, 10.0, 1_000_000)],
        spy_closeadj=[100.0 + i for i in range(25)])


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

    def load_published(conn, session):
        assert active
        return _published(session=session)

    monkeypatch.setattr("sentinel.feed.publication.pinned", fake_pin)
    result = advance_and_persist(
        object(), "2026-08-10", before.to_dict(),
        load_published=load_published, controller_config=config,
        strategy_identity=before.strategy_identity)
    assert result["last_processed_session"] == "2026-08-10"
    assert not active


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
            load_published=lambda *_: _published(),
            controller_config=config,
            strategy_identity=before.strategy_identity)
    except RuntimeError as exc:
        assert "differs from session pin" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("a publication change inside a session was accepted")


def test_stop_evidence_waits_for_executed_fill_and_pending_exit_survives(monkeypatch):
    config, state = _fresh()

    def fake_plan(*, session, pending, ledger, **_):
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
    legacy["last_evidence"]["wealth_core"]["state_after"] = {"recursive": True}
    legacy["last_evidence"]["wealth_core"]["pending_after"] = [{"copy": True}]

    migrated = SessionState.from_dict(legacy)
    plan_evidence = migrated.last_evidence["wealth_core"]
    assert migrated.version == 3
    assert migrated.feed == current.feed
    assert "state_after" not in plan_evidence
    assert "pending_after" not in plan_evidence

    a = _advance(current, _synthetic_published(201), config)
    b = _advance(migrated, _synthetic_published(201), config)
    assert a.to_dict() == b.to_dict()
    assert a.state_hash == b.state_hash
