from copy import deepcopy
from contextlib import contextmanager
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
