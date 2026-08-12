from copy import deepcopy

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


def test_one_session_advance_persists_complete_authoritative_envelope():
    config, before = _fresh()
    after = advance_state(before, _published(), controller_config=config)

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
    a = advance_state(before, _published(), controller_config=config)
    b = advance_state(reloaded, _published(), controller_config=config)

    assert a.to_dict() == b.to_dict()
    assert a.state_hash == b.state_hash
    assert before.to_dict() == raw


def test_publication_version_cannot_move_backwards():
    config, before = _fresh()
    before.data_version = 8
    try:
        advance_state(before, _published(version=7), controller_config=config)
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
        advance_state(before, broken, controller_config=config)
    except ValueError:
        pass
    else:  # pragma: no cover
        raise AssertionError("invalid duplicate session bars were accepted")
    assert before.to_dict() == raw
