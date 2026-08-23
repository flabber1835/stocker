"""Falsifiers for the broker-free forward shadow observation boundary."""
from __future__ import annotations

import ast
import hashlib
import json
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from stock_strategy_shared.wealth_core.feed import (
    DecisionMetadataTimelineBuilder, SecurityMeta, VendorBar)

from sentinel import shadow_observation as SO
from sentinel import shadow_runtime as SR
from sentinel import shadow_service as SS
from sentinel.controller.frozen_rule import load
from sentinel.controller.machine import Controller
from sentinel.core.production import DefensiveBar, PublishedSession, SessionState
from sentinel.core.loader import CorpusWindow
from sentinel.feed import calendar
from sentinel.feed import publication as publication_store
from sentinel.feed import readiness
from sentinel.feed import store as feed_store


FIRST = "2026-08-20"
SECOND = "2026-08-21"
AFTER_WEEKEND = "2026-08-24"
TEST_RUNTIME_IDENTITY = {
    "schema": "sentinel.shadow-runtime-identity/test",
    "validated_source_identity_sha256": "f" * 64,
}


def _activation(session=FIRST):
    execution = calendar.next_session(session)
    opened, _closed = calendar.session_window(execution)
    observed = opened.astimezone(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0)
    return {
        "schema": "sentinel.shadow-activation-timing/1",
        "decision_session": session,
        "execution_session": execution,
        "observed_at": observed.isoformat().replace("+00:00", "Z"),
        "execution_open_at": opened.astimezone(timezone.utc).isoformat().replace(
            "+00:00", "Z"),
        "status": SO.BEFORE_NEXT_OPEN,
    }


def _preopen_clock(session=FIRST):
    return SR.publication_not_before(session) + timedelta(minutes=5)


def _sha(value) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


class MemoryStore:
    def __init__(self):
        self.seed = None
        self.rows = []

    def genesis(self):
        return deepcopy(self.seed)

    def append_genesis(self, genesis):
        if self.seed is None:
            self.seed = deepcopy(genesis)
        elif self.seed != genesis:
            raise SO.ShadowObservationRefused("genesis rewrite")

    def records(self):
        return deepcopy(self.rows)

    def append(self, record):
        self.rows.append(deepcopy(record))


def _identity(config):
    return {
        "strategy": config.strategy_id,
        "controller_rule_sha256": config.digest,
        "wealth_core_source_sha256": "canonical-test-source",
        "data_semantics_source_sha256": "canonical-data-semantics-source",
    }


def _warmup_identity(first_session=FIRST):
    axis = calendar.previous_sessions(
        first_session, SO.SHADOW_WARMUP_SESSIONS + 1)[:-1]
    identity = {
        "schema": SO.WARMUP_INPUT_SCHEMA,
        "first_warmup_session": axis[0],
        "last_warmup_session": axis[-1],
        "session_count": SO.SHADOW_WARMUP_SESSIONS,
        "sessions_sha256": _sha(axis),
        "bars_sha256": "a" * 64,
        "metadata_mode": "PROSPECTIVE_STATIC_FEATURE_METADATA",
        "metadata_sha256": "b" * 64,
    }
    identity["warmup_input_sha256"] = _sha(identity)
    return identity


def _warmup_window(*, causal=False, metadata_change_session=None):
    axis = calendar.previous_sessions(
        FIRST, SO.SHADOW_WARMUP_SESSIONS + 1)[:-1]
    meta = SecurityMeta(
        "1", "AAA", category="Domestic Common Stock", permaticker="1",
        related_tickers=("AAA",), first_session=axis[0])
    bars = {
        session: [VendorBar(
            session, "1", "AAA", 10.0, 10.0, 1_000_000.0,
            split_ratio=1.0, dividend_per_share=0.0, tradeable=True)]
        for session in axis}
    window = CorpusWindow(
        sessions=axis, bars_by_session=bars, meta={"1": meta})
    if causal:
        builder = DecisionMetadataTimelineBuilder(axis)
        for session in axis:
            row = meta
            if session == metadata_change_session:
                row = replace(meta, category="Canadian Common Stock")
            builder.add_snapshot(session, {"1": row})
        window.metadata_timeline = builder.finish()
    return axis, window


@pytest.mark.parametrize(("field", "value"), [
    ("raw_close", 10.01),
    ("raw_open", 10.02),
    ("split_ratio", 2.0),
    ("dividend_per_share", 0.25),
])
def test_warmup_identity_detects_any_historical_price_action_correction(
        field, value):
    axis, baseline_window = _warmup_window()
    baseline = SR._warmup_input_identity(
        baseline_window, axis, prospective_witness=True)
    _axis, corrected_window = _warmup_window()
    corrected_window.bars_by_session[axis[0]][0] = replace(
        corrected_window.bars_by_session[axis[0]][0], **{field: value})
    corrected = SR._warmup_input_identity(
        corrected_window, axis, prospective_witness=True)

    assert corrected["bars_sha256"] != baseline["bars_sha256"]
    assert corrected["warmup_input_sha256"] != baseline[
        "warmup_input_sha256"]


def test_warmup_identity_detects_static_and_causal_metadata_corrections():
    axis, static_window = _warmup_window()
    static = SR._warmup_input_identity(
        static_window, axis, prospective_witness=True)
    static_window.meta["1"] = replace(
        static_window.meta["1"], category="Canadian Common Stock")
    corrected_static = SR._warmup_input_identity(
        static_window, axis, prospective_witness=True)
    assert corrected_static["metadata_sha256"] != static["metadata_sha256"]

    axis, causal = _warmup_window(causal=True)
    causal_identity = SR._warmup_input_identity(
        causal, axis, prospective_witness=False)
    _axis, corrected_causal = _warmup_window(
        causal=True, metadata_change_session=axis[0])
    corrected_causal_identity = SR._warmup_input_identity(
        corrected_causal, axis, prospective_witness=False)
    assert corrected_causal_identity["metadata_sha256"] != causal_identity[
        "metadata_sha256"]
    assert len(json.dumps(
        causal_identity, sort_keys=True, separators=(",", ":"))) < 1024


def _observer(*, store=None, starting_cash="100000", runtime_identity=None):
    config = load()
    identity = _identity(config)
    seed = SessionState.fresh(
        starting_cash=100_000, controller=Controller(config),
        strategy_identity=identity)
    store = store or MemoryStore()
    observer = SO.ShadowObserver(
        store=store, observation_id="year-end-2026",
        starting_cash=starting_cash, first_session=FIRST,
        initial_state=seed, controller_config=config,
        strategy_identity=identity,
        runtime_identity=(runtime_identity or TEST_RUNTIME_IDENTITY),
        activation_timing=_activation(),
        warmup_input_identity=_warmup_identity())
    return observer, store


def _fully_published(session: str, *, version: int = 7,
                     price: float = 10.0, evidence=None):
    spy_sessions = calendar.previous_sessions(session, 25)
    previous_session = spy_sessions[-2]
    meta = {
        "1": SecurityMeta(
            "1", "AAA", category="Domestic Common Stock", permaticker="1",
            related_tickers=("AAA",), first_session=FIRST),
    }
    published = PublishedSession(
        session=session, data_version=version, meta=meta,
        sectors={"1": "TECH"},
        bars=[VendorBar(
            session, "1", "AAA", price, price, 1_000_000)],
        spy_closeadj=[100.0 + index for index in range(25)],
        spy_sessions=spy_sessions, spy_expected_sessions=spy_sessions,
        defensive_bar=DefensiveBar(
            session=session, security_id="SENTINEL:BIL", ticker="BIL",
            open_signal=100.0, close_signal=100.0,
            close_adjusted=100.0, close_unadjusted=100.0),
        defensive_previous_bar=DefensiveBar(
            session=previous_session, security_id="SENTINEL:BIL", ticker="BIL",
            open_signal=100.0, close_signal=100.0,
            close_adjusted=100.0, close_unadjusted=100.0))
    publication = {
        "version": version,
        "previous_version": version - 1,
        "run_id": f"published-run-{version}",
        "window": [FIRST, session],
        "evidence": evidence or {"complete": True, "frontier": session},
    }
    return SO.FullyPublishedSession(published, publication)


def _economics_state(observer, *, session: str, allocation: str,
                     parent_open: str, parent_close: str) -> SessionState:
    state = deepcopy(observer.initial_state)
    state.last_processed_session = session
    state.last_decision = {
        "session": session,
        "target_core_exposure": allocation,
    }
    nav = float(parent_close)
    state.shadow_nav_history = [nav]
    state.last_evidence = {
        "observation": {"session": session, "shadow_nav": nav},
        "wealth_core": {
            "session": session,
            "blocked": False,
            "block_reason": None,
            "resolved_equity": round(nav, 2),
            "estimated_equity": round(nav, 2),
            "resolved_open_equity": float(parent_open),
            "open_unresolved_security_ids": [],
        },
    }
    return state


def _bil_prices(*, session: str, previous_session: str,
                previous_close: str, adjusted_open: str,
                adjusted_close: str) -> dict:
    # Equal signal/adjusted closes make open_signal itself the adjusted open.
    return {
        "bil_previous_session": previous_session,
        "bil_previous_close_adjusted": previous_close,
        "bil_open_signal": adjusted_open,
        "bil_close_signal": adjusted_close,
        "bil_close_adjusted": adjusted_close,
        "bil_close_unadjusted": adjusted_close,
    }


def test_pure_canonical_transition_is_a_non_deployable_candidate():
    observer, store = _observer()

    result = observer.observe(_fully_published(FIRST))

    assert result.shadow_verdict == SO.NOT_DEPLOYABLE
    assert result.verification == SO.CANDIDATE
    assert result.state.last_processed_session == FIRST
    assert result.state.data_version == 7
    assert result.to_dict() == {
        "session": FIRST,
        "shadow_verdict": "NOT_DEPLOYABLE",
        "verification": "CANDIDATE",
        "starting_cash": "100000",
        "strategy_nav": "100000",
        "strategy_cumulative_return": "0",
        "parent_core_nav": "100000",
        "runtime_identity_sha256": result.runtime_identity_sha256,
        "runtime_authority_sha256": None,
        "live_frontier": None,
        "sessions_lag": 0,
        "state_sha256": result.state.state_hash,
        "record_sha256": result.record_sha256,
        "appended": True,
    }
    assert len(store.rows) == 1
    assert store.rows[0]["state"] == result.state.to_dict()
    assert store.rows[0]["starting_cash"] == "100000"
    assert store.rows[0]["strategy_identity"] == result.state.strategy_identity
    assert store.rows[0]["publication"]["status"] == "FULLY_PUBLISHED"
    assert store.rows[0]["shadow_verdict"] == SO.NOT_DEPLOYABLE
    assert store.rows[0]["verification"] == SO.CANDIDATE
    assert store.seed["schema"] == SO.GENESIS_SCHEMA
    assert store.seed["initial_state"] == observer.initial_state.to_dict()
    assert store.seed["initial_state_sha256"] == observer.initial_state.state_hash
    assert store.seed["warmup_input_identity"] == \
        observer.warmup_input_identity
    assert store.seed["warmup_input_identity_sha256"] == \
        observer.warmup_input_identity_sha256
    assert store.seed["genesis_sha256"] == observer.genesis_sha256


def test_bil_adjusted_open_formula_divides_by_signal_close_exactly_once():
    previous = DefensiveBar(
        session="2026-08-19", security_id="SENTINEL:BIL", ticker="BIL",
        open_signal=90, close_signal=90, close_adjusted=90,
        close_unadjusted=90)
    current = DefensiveBar(
        session=FIRST, security_id="SENTINEL:BIL", ticker="BIL",
        open_signal=90, close_signal=90, close_adjusted=91,
        close_unadjusted=90)

    prices = SO._strategy_prices(  # noqa: SLF001 - arithmetic falsifier
        current, session=FIRST, previous_value=previous)

    assert prices["bil_open_adjusted"] == "91"
    assert Decimal(prices["bil_open_adjusted"]) != Decimal(91) / Decimal(90)


def test_first_committed_close_stays_cash_and_earns_no_past_return(
        monkeypatch):
    observer, store = _observer()
    canonical_advance = SO.advance_state

    def parent_moved_before_commit(*args, **kwargs):
        state = canonical_advance(*args, **kwargs)
        state.shadow_nav_history[-1] = 110_000.004
        state.last_evidence["observation"]["shadow_nav"] = 110_000.004
        state.last_evidence["wealth_core"].update({
            "resolved_open_equity": 100_000.001,
            "resolved_equity": 110_000.00,
            "estimated_equity": 110_000.00,
        })
        return state

    monkeypatch.setattr(SO, "advance_state", parent_moved_before_commit)
    result = observer.observe(_fully_published(FIRST))
    economics = store.rows[0]["strategy_economics"]

    assert result.strategy_nav == "100000"
    assert result.strategy_cumulative_return == "0"
    assert result.parent_core_nav == "110000.004"
    assert economics["held_allocation"] is None
    assert economics["pending_allocation"] == "1"
    assert economics["net_factor"] == "1"


@pytest.mark.parametrize(("allocation", "expected_factor"), [
    ("1", "1"),
    ("0", "0.999"),
])
def test_initial_open_charges_only_the_new_bil_sleeve(
        allocation, expected_factor):
    observer, _store = _observer()
    previous_first = calendar.previous_sessions(FIRST, 2)[0]
    first = observer._advance_strategy_economics(  # noqa: SLF001
        previous=observer.initial_strategy_economics,
        state=_economics_state(
            observer, session=FIRST, allocation=allocation,
            parent_open="100000", parent_close="100000"),
        strategy_prices=_bil_prices(
            session=FIRST, previous_session=previous_first,
            previous_close="100", adjusted_open="100",
            adjusted_close="100"))
    second = observer._advance_strategy_economics(  # noqa: SLF001
        previous=first,
        state=_economics_state(
            observer, session=SECOND, allocation=allocation,
            parent_open="100000", parent_close="100000"),
        strategy_prices=_bil_prices(
            session=SECOND, previous_session=FIRST,
            previous_close="100", adjusted_open="100",
            adjusted_close="100"))

    assert first["strategy_nav"] == "100000"
    assert first["net_factor"] == "1"
    assert second["net_factor"] == expected_factor
    assert second["turnover"] == ("0" if allocation == "1" else "1")


def test_full_precision_parent_open_prevents_fractional_cent_phantom_return():
    observer, _store = _observer()
    previous_first = calendar.previous_sessions(FIRST, 2)[0]
    first = observer._advance_strategy_economics(  # noqa: SLF001
        previous=observer.initial_strategy_economics,
        state=_economics_state(
            observer, session=FIRST, allocation="1",
            parent_open="1.234", parent_close="1.234"),
        strategy_prices=_bil_prices(
            session=FIRST, previous_session=previous_first,
            previous_close="100", adjusted_open="100",
            adjusted_close="100"))
    second = observer._advance_strategy_economics(  # noqa: SLF001
        previous=first,
        state=_economics_state(
            observer, session=SECOND, allocation="1",
            parent_open="1.234", parent_close="1.234"),
        strategy_prices=_bil_prices(
            session=SECOND, previous_session=FIRST,
            previous_close="100", adjusted_open="100",
            adjusted_close="100"))

    assert second["parent_core_open_equity"] == "1.234"
    assert second["parent_core_close_equity"] == "1.234"
    assert second["core_intraday_return"] == "0"
    assert second["net_factor"] == "1"


def test_bil_return_is_invariant_to_current_publication_scale_restatement():
    observer, _store = _observer()
    previous_first = calendar.previous_sessions(FIRST, 2)[0]
    first = observer._advance_strategy_economics(  # noqa: SLF001
        previous=observer.initial_strategy_economics,
        state=_economics_state(
            observer, session=FIRST, allocation="0",
            parent_open="100000", parent_close="100000"),
        strategy_prices=_bil_prices(
            session=FIRST, previous_session=previous_first,
            previous_close="100", adjusted_open="100",
            adjusted_close="100"))
    second = observer._advance_strategy_economics(  # noqa: SLF001
        previous=first,
        state=_economics_state(
            observer, session=SECOND, allocation="0",
            parent_open="100000", parent_close="100000"),
        strategy_prices=_bil_prices(
            session=SECOND, previous_session=FIRST,
            previous_close="100", adjusted_open="100",
            adjusted_close="100"))
    state = _economics_state(
        observer, session=AFTER_WEEKEND, allocation="0",
        parent_open="100000", parent_close="100000")
    baseline = observer._advance_strategy_economics(  # noqa: SLF001
        previous=second, state=state,
        strategy_prices=_bil_prices(
            session=AFTER_WEEKEND, previous_session=SECOND,
            previous_close="100", adjusted_open="101",
            adjusted_close="102"))
    rescaled = observer._advance_strategy_economics(  # noqa: SLF001
        previous=second, state=state,
        strategy_prices=_bil_prices(
            session=AFTER_WEEKEND, previous_session=SECOND,
            previous_close="200", adjusted_open="202",
            adjusted_close="204"))

    assert baseline["strategy_nav"] == rescaled["strategy_nav"]
    assert baseline["net_factor"] == rescaled["net_factor"] == "1.02"
    assert (rescaled["bil_previous_close_adjusted_current_publication"]
            != second["bil_close_adjusted"])


def test_changed_allocation_uses_old_overnight_new_intraday_and_10bp_shift():
    observer, _store = _observer()
    previous_first = calendar.previous_sessions(FIRST, 2)[0]
    first = observer._advance_strategy_economics(  # noqa: SLF001
        previous=observer.initial_strategy_economics,
        state=_economics_state(
            observer, session=FIRST, allocation="0.6",
            parent_open="100", parent_close="100"),
        strategy_prices=_bil_prices(
            session=FIRST, previous_session=previous_first,
            previous_close="100", adjusted_open="100",
            adjusted_close="100"))
    second = observer._advance_strategy_economics(  # noqa: SLF001
        previous=first,
        state=_economics_state(
            observer, session=SECOND, allocation="0.2",
            parent_open="100", parent_close="110"),
        strategy_prices=_bil_prices(
            session=SECOND, previous_session=FIRST,
            previous_close="100", adjusted_open="100",
            adjusted_close="102"))
    third = observer._advance_strategy_economics(  # noqa: SLF001
        previous=second,
        state=_economics_state(
            observer, session=AFTER_WEEKEND, allocation="0.2",
            parent_open="111.1", parent_close="113.322"),
        strategy_prices=_bil_prices(
            session=AFTER_WEEKEND, previous_session=SECOND,
            previous_close="204", adjusted_open="206.04",
            adjusted_close="208.1004"))

    expected = Decimal("1.01") * Decimal("0.9996") * Decimal("1.012")
    assert third["held_allocation"] == "0.2"
    assert third["turnover"] == "0.4"
    assert Decimal(third["net_factor"]) == expected
    assert Decimal(third["strategy_nav"]) == \
        Decimal(second["strategy_nav"]) * expected


@pytest.mark.parametrize(("old_allocation", "new_allocation", "expected"), [
    ("1", "0", Decimal("1.00899")),
    ("0", "1", Decimal("0.999")),
    ("1", "1", Decimal("1.01")),
    ("0", "0", Decimal("1")),
])
def test_ex_date_dividend_belongs_to_the_prior_close_allocation(
        old_allocation, new_allocation, expected):
    observer, _store = _observer()
    previous_first = calendar.previous_sessions(FIRST, 2)[0]
    first = observer._advance_strategy_economics(  # noqa: SLF001
        previous=observer.initial_strategy_economics,
        state=_economics_state(
            observer, session=FIRST, allocation=old_allocation,
            parent_open="100", parent_close="100"),
        strategy_prices=_bil_prices(
            session=FIRST, previous_session=previous_first,
            previous_close="100", adjusted_open="100",
            adjusted_close="100"))
    second = observer._advance_strategy_economics(  # noqa: SLF001
        previous=first,
        state=_economics_state(
            observer, session=SECOND, allocation=new_allocation,
            parent_open="100", parent_close="100"),
        strategy_prices=_bil_prices(
            session=SECOND, previous_session=FIRST,
            previous_close="100", adjusted_open="100",
            adjusted_close="100"))
    # Flat ex-price security plus a $1 unsettled ex-date dividend claim. The
    # canonical parent open and close are both $101: the claim is an asset of
    # the prior-close owner before the allocation changes at this open, while
    # remaining absent from spendable cash.
    third = observer._advance_strategy_economics(  # noqa: SLF001
        previous=second,
        state=_economics_state(
            observer, session=AFTER_WEEKEND, allocation=new_allocation,
            parent_open="101", parent_close="101"),
        strategy_prices=_bil_prices(
            session=AFTER_WEEKEND, previous_session=SECOND,
            previous_close="100", adjusted_open="100",
            adjusted_close="100"))

    causal = (
        Decimal(old_allocation) * Decimal("1.01")
        + (Decimal(1) - Decimal(old_allocation))
        if old_allocation == new_allocation else
        (Decimal(1) + Decimal(old_allocation) * Decimal("0.01"))
        * (Decimal(1) - Decimal("0.001")
           * abs(Decimal(new_allocation) - Decimal(old_allocation))))
    assert causal == expected
    assert Decimal(third["core_overnight_return"]) == Decimal("0.01")
    assert Decimal(third["core_intraday_return"]) == Decimal("0")
    assert Decimal(third["net_factor"]) == causal


@pytest.mark.parametrize(
    ("event_kind", "parent_open", "old_allocation", "new_allocation",
     "expected"), [
        ("cash_merger", "110", "1", "0", Decimal("1.0989")),
        ("cash_merger", "110", "0", "1", Decimal("0.999")),
        ("cash_merger", "110", "1", "1", Decimal("1.1")),
        ("cash_merger", "110", "0", "0", Decimal("1")),
        ("conversion", "120", "1", "0", Decimal("1.1988")),
        ("conversion", "120", "0", "1", Decimal("0.999")),
        ("conversion", "120", "1", "1", Decimal("1.2")),
        ("conversion", "120", "0", "0", Decimal("1")),
    ])
def test_terminal_entitlement_belongs_to_the_prior_close_allocation(
        event_kind, parent_open, old_allocation, new_allocation, expected):
    observer, _store = _observer()
    previous_first = calendar.previous_sessions(FIRST, 2)[0]
    first = observer._advance_strategy_economics(  # noqa: SLF001
        previous=observer.initial_strategy_economics,
        state=_economics_state(
            observer, session=FIRST, allocation=old_allocation,
            parent_open="100", parent_close="100"),
        strategy_prices=_bil_prices(
            session=FIRST, previous_session=previous_first,
            previous_close="100", adjusted_open="100",
            adjusted_close="100"))
    second = observer._advance_strategy_economics(  # noqa: SLF001
        previous=first,
        state=_economics_state(
            observer, session=SECOND, allocation=new_allocation,
            parent_open="100", parent_close="100"),
        strategy_prices=_bil_prices(
            session=SECOND, previous_session=FIRST,
            previous_close="100", adjusted_open="100",
            adjusted_close="100"))
    third = observer._advance_strategy_economics(  # noqa: SLF001
        previous=second,
        state=_economics_state(
            observer, session=AFTER_WEEKEND, allocation=new_allocation,
            parent_open=parent_open, parent_close=parent_open),
        strategy_prices=_bil_prices(
            session=AFTER_WEEKEND, previous_session=SECOND,
            previous_close="100", adjusted_open="100",
            adjusted_close="100"))

    overnight = Decimal(parent_open) / Decimal("100") - Decimal(1)
    if old_allocation == new_allocation:
        causal = (Decimal(old_allocation) * (Decimal(1) + overnight)
                  + Decimal(1) - Decimal(old_allocation))
    else:
        causal = ((Decimal(1) + Decimal(old_allocation) * overnight)
                  * Decimal("0.999"))
    assert event_kind in {"cash_merger", "conversion"}
    assert Decimal(third["core_overnight_return"]) == overnight
    assert Decimal(third["core_intraday_return"]) == Decimal(0)
    assert causal == expected
    assert Decimal(third["net_factor"]) == expected


def test_terminal_causality_rotates_the_committed_model_identity():
    assert SO.SHADOW_EXECUTION_MODEL == \
        "PROSPECTIVE_CONCORDANCE_SCALAR_CORE_BIL_V3"


def test_only_adjacent_xnys_sessions_advance_and_restart_verifies_chain():
    observer, store = _observer()
    first = observer.observe(_fully_published(FIRST))
    committed_first = first.state.to_dict()
    second = observer.observe(_fully_published(SECOND, version=8, price=10.5))

    assert calendar.next_session(FIRST) == SECOND
    assert second.state.last_processed_session == SECOND
    assert store.rows[1]["previous_record_sha256"] == first.record_sha256
    assert store.rows[1]["prior_state_sha256"] == first.state.state_hash
    assert first.state.to_dict() == committed_first, (
        "advancing the next session must not alias/mutate its predecessor")

    config = load()
    restarted = SO.ShadowObserver.resume(
        store=store, observation_id="year-end-2026",
        starting_cash="100000", first_session=FIRST,
        controller_config=config, strategy_identity=_identity(config),
        runtime_identity=TEST_RUNTIME_IDENTITY)
    verified = restarted.verify_history()
    assert verified.session == SECOND
    assert verified.verification == SO.CANDIDATE
    assert verified.shadow_verdict == SO.NOT_DEPLOYABLE
    assert verified.appended is False


def test_unpublished_next_session_refuses_before_canonical_advance(monkeypatch):
    observer, store = _observer()
    requested = []

    class MissingSource:
        def load_fully_published(self, session, *, known_feed_security_ids):
            requested.append((session, tuple(known_feed_security_ids)))
            return None

    monkeypatch.setattr(
        SO, "advance_state",
        lambda *args, **kwargs: pytest.fail("unpublished input advanced state"))

    with pytest.raises(
            SO.ShadowObservationRefused,
            match=f"next session {FIRST} is not fully published"):
        observer.advance_next(MissingSource())

    assert requested == [(FIRST, ())]
    assert store.rows == []


def test_gap_refuses_before_canonical_advance(monkeypatch):
    observer, store = _observer()
    observer.observe(_fully_published(FIRST))
    called = []
    monkeypatch.setattr(
        SO, "advance_state",
        lambda *args, **kwargs: called.append(True))

    with pytest.raises(
            SO.ShadowObservationRefused,
            match=f"expected {SECOND}, got {AFTER_WEEKEND}"):
        observer.observe(
            _fully_published(AFTER_WEEKEND, version=8, price=11.0))

    assert called == []
    assert len(store.rows) == 1


def test_exact_retry_is_idempotent_but_changed_input_is_a_rewrite():
    observer, store = _observer()
    published = _fully_published(FIRST)
    first = observer.observe(published)

    retry = observer.observe(published)
    assert retry.record_sha256 == first.record_sha256
    assert retry.appended is False
    assert len(store.rows) == 1

    with pytest.raises(
            SO.ShadowObservationRefused,
            match="published input.*rewritten"):
        observer.observe(_fully_published(FIRST, price=99.0))
    assert len(store.rows) == 1


def test_publication_that_does_not_cover_session_is_not_fully_published():
    candidate = _fully_published(FIRST)
    candidate = SO.FullyPublishedSession(
        candidate.published,
        candidate.publication, published_through="2026-08-19")

    with pytest.raises(
            SO.ShadowObservationRefused,
            match="not fully published"):
        candidate.commitment()


def test_changed_durable_row_fails_closed_on_restart():
    observer, store = _observer()
    observer.observe(_fully_published(FIRST))
    store.rows[0]["state"]["wealth_core"]["cash"] = 90_000.0

    config = load()
    restarted = SO.ShadowObserver.resume(
        store=store, observation_id="year-end-2026",
        starting_cash="100000", first_session=FIRST,
        controller_config=config, strategy_identity=_identity(config),
        runtime_identity=TEST_RUNTIME_IDENTITY)
    with pytest.raises(
            SO.ShadowObservationRefused,
            match="record changed"):
        restarted.verify_history()


def test_rehashed_strategy_economics_rewrite_fails_closed_on_restart():
    observer, store = _observer()
    observer.observe(_fully_published(FIRST))
    row = store.rows[0]
    row["strategy_economics"]["strategy_nav"] = "200000"
    row["strategy_economics"]["strategy_cumulative_return"] = "1"
    row["record_sha256"] = _sha({
        key: value for key, value in row.items() if key != "record_sha256"})

    config = load()
    restarted = SO.ShadowObserver.resume(
        store=store, observation_id="year-end-2026",
        starting_cash="100000", first_session=FIRST,
        controller_config=config, strategy_identity=_identity(config),
        runtime_identity=TEST_RUNTIME_IDENTITY)
    with pytest.raises(
            SO.ShadowObservationRefused,
            match="combined Core.BIL economics changed"):
        restarted.verify_history()


def test_rehashed_but_incoherent_session_state_still_fails_closed():
    observer, store = _observer()
    observer.observe(_fully_published(FIRST))
    row = store.rows[0]
    row["state"]["last_processed_session"] = SECOND
    row["state_sha256"] = SessionState.from_dict(row["state"]).state_hash
    row["record_sha256"] = _sha({
        key: value for key, value in row.items() if key != "record_sha256"})

    config = load()
    restarted = SO.ShadowObserver.resume(
        store=store, observation_id="year-end-2026",
        starting_cash="100000", first_session=FIRST,
        controller_config=config, strategy_identity=_identity(config),
        runtime_identity=TEST_RUNTIME_IDENTITY)
    with pytest.raises(
            SO.ShadowObservationRefused,
            match="state/session identity is incoherent"):
        restarted.verify_history()


def test_rehashed_but_weakened_publication_semantics_still_fail_closed():
    observer, store = _observer()
    observer.observe(_fully_published(FIRST))
    row = store.rows[0]
    row["publication"]["schema"] = "weaker-local-claim"
    row["record_sha256"] = _sha({
        key: value for key, value in row.items() if key != "record_sha256"})

    config = load()
    restarted = SO.ShadowObserver.resume(
        store=store, observation_id="year-end-2026",
        starting_cash="100000", first_session=FIRST,
        controller_config=config, strategy_identity=_identity(config),
        runtime_identity=TEST_RUNTIME_IDENTITY)
    with pytest.raises(
            SO.ShadowObservationRefused,
            match="publication commitment is incoherent"):
        restarted.verify_history()


def test_starting_cash_is_explicit_and_cannot_adopt_account_equity():
    with pytest.raises(
            SO.ShadowObservationRefused,
            match="cash/peak differs from explicit starting cash"):
        _observer(starting_cash="125000")


def test_seed_requires_exact_canonical_slot_cardinality_and_defaults():
    config = load()
    identity = _identity(config)
    seed = SessionState.fresh(
        starting_cash=100_000, controller=Controller(config),
        strategy_identity=identity)
    seed.wealth_core["slots"].pop("24")

    with pytest.raises(
            SO.ShadowObservationRefused,
            match="not a canonical SessionState"):
        SO.ShadowObserver(
            store=MemoryStore(), observation_id="year-end-2026",
            starting_cash="100000", first_session=FIRST,
            initial_state=seed, controller_config=config,
            strategy_identity=identity,
            runtime_identity=TEST_RUNTIME_IDENTITY,
            activation_timing=_activation(),
            warmup_input_identity=_warmup_identity())


def test_nonpositive_shadow_nav_cannot_be_labelled_verified(monkeypatch):
    observer, store = _observer()
    canonical_advance = SO.advance_state

    def broken_economics(*args, **kwargs):
        state = canonical_advance(*args, **kwargs)
        state.shadow_nav_history[-1] = -1.0
        state.last_evidence["observation"]["shadow_nav"] = -1.0
        return state

    monkeypatch.setattr(SO, "advance_state", broken_economics)
    with pytest.raises(
            SO.ShadowObservationRefused,
            match="NAV must be finite and positive"):
        observer.observe(_fully_published(FIRST))
    assert store.rows == []


def test_blocked_unresolved_equity_emits_no_verified_nav_or_return(monkeypatch):
    observer, store = _observer()
    canonical_advance = SO.advance_state

    def unresolved_economics(*args, **kwargs):
        state = canonical_advance(*args, **kwargs)
        state.last_evidence["wealth_core"].update({
            "blocked": True,
            "block_reason": "UNRESOLVED_EQUITY",
            "resolved_equity": None,
        })
        # The positive estimate is exactly the dangerous value: it must not be
        # promoted merely because it looks like an ordinary NAV.
        assert state.shadow_nav_history[-1] == 100_000.0
        return state

    monkeypatch.setattr(SO, "advance_state", unresolved_economics)
    with pytest.raises(
            SO.ShadowObservationRefused,
            match="unresolved or blocked Wealth Core equity"):
        observer.observe(_fully_published(FIRST))

    assert store.rows == []


def test_restart_refuses_rehashed_unresolved_performance_record():
    observer, store = _observer()
    observer.observe(_fully_published(FIRST))
    row = store.rows[0]
    row["state"]["last_evidence"]["wealth_core"].update({
        "blocked": True,
        "block_reason": "UNRESOLVED_EQUITY",
        "resolved_equity": None,
    })
    retained_state = SessionState.from_dict(row["state"])
    row["state"] = retained_state.to_dict()
    row["state_sha256"] = retained_state.state_hash
    row["record_sha256"] = _sha({
        key: value for key, value in row.items() if key != "record_sha256"})

    config = load()
    restarted = SO.ShadowObserver.resume(
        store=store, observation_id="year-end-2026",
        starting_cash="100000", first_session=FIRST,
        controller_config=config, strategy_identity=_identity(config),
        runtime_identity=TEST_RUNTIME_IDENTITY)
    with pytest.raises(
            SO.ShadowObservationRefused,
            match="unresolved or blocked Wealth Core equity"):
        restarted.verify_history()


def test_corrupt_immutable_genesis_cannot_seed_a_restart():
    observer, store = _observer()
    observer.observe(_fully_published(FIRST))
    store.seed["initial_state"]["feed"]["session_index"] = 99

    config = load()
    with pytest.raises(SO.ShadowObservationRefused):
        SO.ShadowObserver.resume(
            store=store, observation_id="year-end-2026",
            starting_cash="100000", first_session=FIRST,
            controller_config=config, strategy_identity=_identity(config),
            runtime_identity=TEST_RUNTIME_IDENTITY)


def test_runtime_identity_drift_requires_a_new_observation_lineage():
    observer, store = _observer()
    observer.observe(_fully_published(FIRST))
    config = load()

    with pytest.raises(
            SO.ShadowObservationRefused,
            match="genesis changed after commitment"):
        SO.ShadowObserver.resume(
            store=store, observation_id="year-end-2026",
            starting_cash="100000", first_session=FIRST,
            controller_config=config, strategy_identity=_identity(config),
            runtime_identity={
                **TEST_RUNTIME_IDENTITY,
                "validated_source_identity_sha256": "e" * 64,
            })


def test_activation_after_following_open_cannot_commit_genesis():
    config = load()
    identity = _identity(config)
    seed = SessionState.fresh(
        starting_cash=100_000, controller=Controller(config),
        strategy_identity=identity)
    late = _activation()
    late["observed_at"] = late["execution_open_at"]
    store = MemoryStore()

    with pytest.raises(
            SO.ShadowObservationRefused,
            match="before the following XNYS open"):
        SO.ShadowObserver(
            store=store, observation_id="late-lineage",
            starting_cash="100000", first_session=FIRST,
            initial_state=seed, controller_config=config,
            strategy_identity=identity,
            runtime_identity=TEST_RUNTIME_IDENTITY,
            activation_timing=late,
            warmup_input_identity=_warmup_identity())
    assert store.seed is None


class FakePostgres:
    def __init__(self):
        self.rows = {}
        self.pending = {}
        self.statements = []
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.rows.update(deepcopy(self.pending))
        self.pending.clear()
        self.commits += 1

    def rollback(self):
        self.pending.clear()
        self.rollbacks += 1

    def close(self):
        return None


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self.result = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, statement, params=None):
        sql = " ".join(statement.lower().split())
        self.conn.statements.append(sql)
        if sql == "begin transaction read only":
            self.result = []
        elif sql.startswith("select cursor_name,session,state"):
            prefix = params[0][:-1]
            visible = {**self.conn.rows, **self.conn.pending}
            self.result = [
                (name, session, deepcopy(state))
                for name, (session, state) in sorted(
                    visible.items(), key=lambda item: item[1][0])
                if name.startswith(prefix)
            ]
        elif sql.startswith("insert into sentinel_processed_sessions"):
            name, session, encoded = params
            if name not in self.conn.rows and name not in self.conn.pending:
                self.conn.pending[name] = (session, json.loads(encoded))
            self.result = []
        elif sql.startswith("select session,state"):
            row = self.conn.pending.get(
                params[0], self.conn.rows.get(params[0]))
            self.result = [] if row is None else [(row[0], deepcopy(row[1]))]
        else:  # pragma: no cover - a new SQL operation needs its own falsifier
            raise AssertionError(sql)

    def fetchall(self):
        return list(self.result)

    def fetchone(self):
        return self.result[0] if self.result else None


def _install_runtime_gates(monkeypatch, conn, *, session=FIRST, version=7):
    publication = publication_store.Publication(
        version=version, previous_version=version - 1,
        run_id=f"published-run-{version}",
        window_start=FIRST, window_end=session,
        evidence={"complete": True, "frontier": session})
    canonical = _fully_published(session, version=version).published

    @contextmanager
    def pinned(actual, *, commit):
        assert actual is conn and commit is False
        yield publication

    monkeypatch.setattr(publication_store, "pinned", pinned)
    monkeypatch.setattr(
        publication_store, "assert_coherent", lambda actual: None)
    monkeypatch.setattr(publication_store, "chain_gaps", lambda actual: [])
    monkeypatch.setattr(
        feed_store, "latest_visible_session", lambda actual: session)
    monkeypatch.setattr(
        readiness, "check_readiness",
        lambda actual: SimpleNamespace(
            ready=True, failures=[],
            checks=[SimpleNamespace(name="canonical", status="PASS")]))
    monkeypatch.setattr(
        SO, "load_published_session",
        lambda actual, requested, *, known_feed_security_ids: (
            canonical if requested == session else pytest.fail(requested)))
    monkeypatch.setattr(
        SR, "_warmup_loader",
        lambda _conn, observer: (
            lambda: deepcopy(observer.warmup_input_identity)))
    return publication, canonical


def _postgres_runtime(conn, *, observer, clock=None, warmup_input_loader=None):
    return SO.PostgresShadowRuntime(
        conn, observer=observer, clock=clock,
        warmup_input_loader=(
            warmup_input_loader
            or (lambda: deepcopy(observer.warmup_input_identity))))


def test_postgres_adapter_uses_distinct_immutable_namespaced_rows():
    conn = FakePostgres()
    store = SO.PostgresShadowObservationStore(
        conn, observation_id="year-end-2026")
    record = {"observation_id": "year-end-2026", "session": FIRST,
              "commitment": "one"}
    genesis = {
        "observation_id": "year-end-2026", "first_session": FIRST,
        "commitment": "seed"}

    store.append_genesis(genesis)
    store.append(record)
    store.append(record)
    conn.commit()

    assert set(conn.rows) == {
        f"{SO.POSTGRES_CURSOR_PREFIX}year-end-2026:genesis",
        f"{SO.POSTGRES_CURSOR_PREFIX}year-end-2026:session:{FIRST}",
    }
    assert all("catchup" not in name for name in conn.rows)
    assert store.genesis() == genesis
    assert store.records() == [record]
    assert all(" update " not in f" {sql} " and " delete " not in f" {sql} "
               for sql in conn.statements)
    assert any("on conflict (cursor_name) do nothing" in sql
               for sql in conn.statements)

    with pytest.raises(
            SO.ShadowObservationRefused,
            match="already committed with different evidence"):
        store.append({**record, "commitment": "rewritten"})


def test_postgres_publication_source_holds_pin_and_passes_restart_anchors(
        monkeypatch):
    events = []
    publication = publication_store.Publication(
        version=7, previous_version=6, run_id="published-run-7",
        window_start=FIRST, window_end=FIRST,
        evidence={"complete": True})
    canonical = _fully_published(FIRST).published

    @contextmanager
    def pinned(conn, *, commit):
        assert conn == "read-only-connection"
        assert commit is False
        events.append("pin-enter")
        yield publication
        events.append("pin-exit")

    monkeypatch.setattr(publication_store, "pinned", pinned)
    monkeypatch.setattr(
        publication_store, "assert_coherent",
        lambda conn: events.append("coherent"))

    def load_published(conn, session, *, known_feed_security_ids):
        events.append((conn, session, tuple(known_feed_security_ids)))
        return canonical

    source = SO.PostgresFullyPublishedSessionSource(
        "read-only-connection", load_published=load_published)
    result = source.load_fully_published(
        FIRST, known_feed_security_ids=("1", "2"))

    assert result.commitment()["status"] == SO.FULLY_PUBLISHED
    assert events == [
        "pin-enter", "coherent",
        ("read-only-connection", FIRST, ("1", "2")), "pin-exit"]


def test_only_real_postgres_runtime_promotes_candidate_to_shadow_go(
        monkeypatch):
    conn = FakePostgres()
    store = SO.PostgresShadowObservationStore(
        conn, observation_id="year-end-2026")
    observer, _ = _observer(store=store)
    publication = publication_store.Publication(
        version=7, previous_version=6, run_id="published-run-7",
        window_start=FIRST, window_end=FIRST,
        evidence={"complete": True})
    canonical = _fully_published(FIRST).published

    @contextmanager
    def pinned(actual, *, commit):
        assert actual is conn and commit is False
        yield publication

    monkeypatch.setattr(publication_store, "pinned", pinned)
    monkeypatch.setattr(publication_store, "assert_coherent", lambda actual: None)
    monkeypatch.setattr(publication_store, "chain_gaps", lambda actual: [])
    monkeypatch.setattr(
        feed_store, "latest_visible_session", lambda actual: FIRST)
    monkeypatch.setattr(
        readiness, "check_readiness",
        lambda actual: SimpleNamespace(
            ready=True, failures=[],
            checks=[SimpleNamespace(name="canonical", status="PASS")]))
    monkeypatch.setattr(
        SO, "load_published_session",
        lambda actual, session, *, known_feed_security_ids: canonical)

    result = _postgres_runtime(
        conn, observer=observer,
        clock=lambda: _preopen_clock()).advance_next()

    assert result.shadow_verdict == SO.SHADOW_GO
    assert result.verification == SO.VERIFIED
    assert len(result.runtime_authority_sha256) == 64
    assert conn.commits == 3 and conn.rollbacks == 0
    retained = store.records()[0]
    assert retained["shadow_verdict"] == SO.NOT_DEPLOYABLE
    assert retained["verification"] == SO.CANDIDATE
    authority = store.authorities()[0]
    assert authority["record_sha256"] == retained["record_sha256"]
    assert authority["runtime_identity_sha256"] == \
        result.runtime_identity_sha256
    assert authority["strategy_economics_sha256"] == _sha(
        retained["strategy_economics"])
    assert authority["warmup_input_identity_sha256"] == \
        observer.warmup_input_identity_sha256
    assert authority["candidate_committed_at"] < \
        authority["execution_open_at"]


def test_postgres_runtime_refuses_go_when_full_readiness_fails(monkeypatch):
    conn = FakePostgres()
    store = SO.PostgresShadowObservationStore(
        conn, observation_id="year-end-2026")
    observer, _ = _observer(store=store)
    publication = publication_store.Publication(
        version=7, previous_version=6, run_id="published-run-7",
        window_start=FIRST, window_end=FIRST, evidence={})

    @contextmanager
    def pinned(actual, *, commit):
        yield publication

    monkeypatch.setattr(publication_store, "pinned", pinned)
    monkeypatch.setattr(publication_store, "assert_coherent", lambda actual: None)
    monkeypatch.setattr(publication_store, "chain_gaps", lambda actual: [])
    monkeypatch.setattr(
        feed_store, "latest_visible_session", lambda actual: FIRST)
    monkeypatch.setattr(
        readiness, "check_readiness",
        lambda actual: SimpleNamespace(
            ready=False,
            failures=[SimpleNamespace(name="Sharadar readiness")], checks=[]))
    monkeypatch.setattr(
        SO, "load_published_session",
        lambda *args, **kwargs: pytest.fail("failed readiness loaded a session"))

    with pytest.raises(
            SO.ShadowObservationRefused,
            match="canonical data readiness failed"):
        _postgres_runtime(
            conn, observer=observer,
            clock=lambda: _preopen_clock()).advance_next()

    assert store.records() == []
    assert conn.commits == 1 and conn.rollbacks == 1


def test_candidate_without_runtime_attestation_never_verifies(monkeypatch):
    conn = FakePostgres()
    store = SO.PostgresShadowObservationStore(
        conn, observation_id="year-end-2026")
    observer, _ = _observer(store=store)
    observer.observe(_fully_published(FIRST))
    conn.commit()

    with pytest.raises(
            SO.ShadowObservationRefused,
            match="lacks exact runtime authority"):
        _postgres_runtime(
            conn, observer=observer,
            clock=lambda: _preopen_clock()).durable_status()
    assert store.authorities() == []


def test_crash_after_candidate_commit_recovers_only_before_open(monkeypatch):
    conn = FakePostgres()
    store = SO.PostgresShadowObservationStore(
        conn, observation_id="year-end-2026")
    observer, _ = _observer(store=store)
    _install_runtime_gates(monkeypatch, conn)
    append_authority = store.append_authority
    monkeypatch.setattr(
        store, "append_authority",
        lambda _value: (_ for _ in ()).throw(RuntimeError("injected crash")))

    with pytest.raises(
            SO.ShadowObservationRefused, match="injected crash"):
        _postgres_runtime(
            conn, observer=observer,
            clock=lambda: _preopen_clock()).advance_next()

    assert len(store.records()) == 1
    assert store.authorities() == []
    monkeypatch.setattr(store, "append_authority", append_authority)
    recovered = _postgres_runtime(
        conn, observer=observer,
        clock=lambda: _preopen_clock()).advance_through(FIRST)

    assert recovered.shadow_verdict == SO.SHADOW_GO
    assert recovered.verification == SO.VERIFIED
    assert recovered.appended is False
    assert len(store.records()) == len(store.authorities()) == 1


@pytest.mark.parametrize("partial", ["GENESIS_ONLY", "TRAILING_CANDIDATE"])
def test_shadow_service_restart_recovers_exact_partial_lineage_end_to_end(
        monkeypatch, partial):
    conn = FakePostgres()
    publication, _canonical = _install_runtime_gates(monkeypatch, conn)
    runtime_identity = {
        **TEST_RUNTIME_IDENTITY,
        "validated_data_publication_sha256":
            SR._data_publication_subject_sha256(publication, FIRST),
    }
    store = SO.PostgresShadowObservationStore(
        conn, observation_id="year-end-2026")
    observer, _ = _observer(
        store=store, runtime_identity=runtime_identity)
    if partial == "TRAILING_CANDIDATE":
        observer.observe(_fully_published(FIRST))
        conn.commit()
    assert len(store.records()) == (1 if partial == "TRAILING_CANDIDATE" else 0)
    assert store.authorities() == []
    monkeypatch.setattr(
        SR, "_strategy",
        lambda: (observer.controller_config, observer.strategy_identity))
    monkeypatch.setattr(
        SR, "_validated_runtime_identity",
        lambda **_kwargs: runtime_identity)
    monkeypatch.setattr(SR, "_utcnow", lambda: _preopen_clock())
    monkeypatch.setattr(feed_store, "connect", lambda _url: conn)
    monkeypatch.setattr(feed_store, "require_feed_schema", lambda _conn: None)
    monkeypatch.setattr(SS.schema, "require_runtime_schema", lambda _conn: None)
    config = SS.ShadowServiceConfig(
        database_url="postgresql://test", observation_id="year-end-2026",
        starting_cash=Decimal("100000"),
        publication_timing_policy=SR.SHADOW_PUBLICATION_TIMING_POLICY,
        poll_seconds=300)

    classified = SS.preflight(config, now=_preopen_clock())
    assert classified["status"] == "RECOVERY_REQUIRED"
    assert classified["recovery_kind"] == partial
    result = SS.advance_once(config, now=_preopen_clock())

    assert result["shadow_verdict"] == SO.SHADOW_GO
    assert result["verification"] == SO.VERIFIED
    assert result["session"] == FIRST
    assert len(store.records()) == len(store.authorities()) == 1


def test_shadow_service_partial_lineage_is_permanently_refused_at_cutoff(
        monkeypatch):
    conn = FakePostgres()
    store = SO.PostgresShadowObservationStore(
        conn, observation_id="year-end-2026")
    observer, _ = _observer(store=store)
    observer.observe(_fully_published(FIRST))
    conn.commit()
    monkeypatch.setattr(
        SR, "_strategy",
        lambda: (observer.controller_config, observer.strategy_identity))
    monkeypatch.setattr(
        SR, "_validated_runtime_identity",
        lambda **_kwargs: TEST_RUNTIME_IDENTITY)
    monkeypatch.setattr(SS.schema, "require_runtime_schema", lambda _conn: None)
    opened, _closed = calendar.session_window(calendar.next_session(FIRST))
    config = SS.ShadowServiceConfig(
        database_url="postgresql://test", observation_id="year-end-2026",
        starting_cash=Decimal("100000"),
        publication_timing_policy=SR.SHADOW_PUBLICATION_TIMING_POLICY,
        poll_seconds=300)

    with pytest.raises(SR.ShadowRuntimeRefused,
                       match="retrospective fill refused"):
        SS._preflight(conn, config, now=opened)

    assert len(store.records()) == 1
    assert store.authorities() == []


def test_direct_shadow_runtime_cannot_bypass_source_not_before(monkeypatch):
    not_before = SR.publication_not_before(FIRST)
    monkeypatch.setattr(
        SR, "_utcnow", lambda: not_before - timedelta(seconds=1))
    monkeypatch.setattr(
        SR, "_strategy",
        lambda: pytest.fail("pre-final data must not construct the strategy"))

    with pytest.raises(SR.ShadowRuntimeRefused, match="not source-final"):
        SR.advance_ready_shadow(
            object(), through=FIRST, observation_id="year-end-2026",
            starting_cash="100000")


def test_fresh_genesis_requires_exact_reviewed_publication_subject(monkeypatch):
    conn = FakePostgres()
    publication, _canonical = _install_runtime_gates(monkeypatch, conn)
    expected = SR._data_publication_subject_sha256(publication, FIRST)

    SR._require_reviewed_genesis_publication(
        conn, current=publication, first_session=FIRST,
        runtime_identity={"validated_data_publication_sha256": expected})
    with pytest.raises(SR.ShadowRuntimeRefused,
                       match="differs from the reviewed"):
        SR._require_reviewed_genesis_publication(
            conn, current=publication, first_session=FIRST,
            runtime_identity={
                "validated_data_publication_sha256": "0" * 64})


def test_trailing_candidate_is_permanently_refused_at_following_open(
        monkeypatch):
    conn = FakePostgres()
    store = SO.PostgresShadowObservationStore(
        conn, observation_id="year-end-2026")
    observer, _ = _observer(store=store)
    observer.observe(_fully_published(FIRST))
    conn.commit()
    _install_runtime_gates(monkeypatch, conn)
    opened, _closed = calendar.session_window(calendar.next_session(FIRST))

    with pytest.raises(
            SO.ShadowObservationRefused,
            match="retrospective fill refused"):
        _postgres_runtime(
            conn, observer=observer,
            clock=lambda: opened).advance_through(FIRST)

    assert len(store.records()) == 1
    assert store.authorities() == []


def test_tampered_rehashed_runtime_authority_is_not_verified(monkeypatch):
    conn = FakePostgres()
    store = SO.PostgresShadowObservationStore(
        conn, observation_id="year-end-2026")
    observer, _ = _observer(store=store)
    _install_runtime_gates(monkeypatch, conn)
    _postgres_runtime(
        conn, observer=observer,
        clock=lambda: _preopen_clock()).advance_next()
    authority_name = (
        f"{SO.POSTGRES_CURSOR_PREFIX}year-end-2026:authority:{FIRST}")
    session, authority = conn.rows[authority_name]
    authority["runtime_identity_sha256"] = "e" * 64
    authority["authority_sha256"] = _sha({
        key: value for key, value in authority.items()
        if key != "authority_sha256"})
    conn.rows[authority_name] = (session, authority)

    with pytest.raises(
            SO.ShadowObservationRefused,
            match="runtime authority is incoherent"):
        _postgres_runtime(
            conn, observer=observer,
            clock=lambda: _preopen_clock()).durable_status()


def test_same_session_retry_revalidates_exact_postgres_authority(monkeypatch):
    conn = FakePostgres()
    store = SO.PostgresShadowObservationStore(
        conn, observation_id="year-end-2026")
    observer, _ = _observer(store=store)
    _install_runtime_gates(monkeypatch, conn)
    runtime = _postgres_runtime(
        conn, observer=observer, clock=lambda: _preopen_clock())
    first = runtime.advance_through(FIRST)
    retry = runtime.advance_through(FIRST)

    assert retry.shadow_verdict == SO.SHADOW_GO
    assert retry.verification == SO.VERIFIED
    assert retry.appended is False
    assert retry.runtime_authority_sha256 == first.runtime_authority_sha256
    assert len(store.records()) == len(store.authorities()) == 1


def test_exact_publication_authority_avoids_repeated_252_session_scan(
        monkeypatch):
    conn = FakePostgres()
    store = SO.PostgresShadowObservationStore(
        conn, observation_id="year-end-2026")
    observer, _ = _observer(store=store)
    _install_runtime_gates(monkeypatch, conn)
    _postgres_runtime(
        conn, observer=observer,
        clock=lambda: _preopen_clock()).advance_next()

    status = _postgres_runtime(
        conn, observer=observer, clock=lambda: _preopen_clock(),
        warmup_input_loader=lambda: pytest.fail(
            "same publication already has durable warm-up authority"),
    ).durable_status()

    assert status.verification == SO.VERIFIED


def test_status_accepts_only_scale_equivalent_same_frontier_republication(
        monkeypatch):
    conn = FakePostgres()
    store = SO.PostgresShadowObservationStore(
        conn, observation_id="year-end-2026")
    observer, _ = _observer(store=store)
    _install_runtime_gates(monkeypatch, conn)
    first = _postgres_runtime(
        conn, observer=observer,
        clock=lambda: _preopen_clock()).advance_next()
    restated = publication_store.Publication(
        version=8, previous_version=7, run_id="restated-run-8",
        window_start=FIRST, window_end=FIRST,
        evidence={"complete": True, "frontier": FIRST, "restated": True})
    canonical = _fully_published(FIRST, version=8).published
    canonical = replace(
        canonical,
        spy_closeadj=[value * 2 for value in canonical.spy_closeadj],
        defensive_bar=replace(
            canonical.defensive_bar, close_adjusted=200.0),
        defensive_previous_bar=replace(
            canonical.defensive_previous_bar, close_adjusted=200.0))

    @contextmanager
    def repinned(actual, *, commit):
        assert actual is conn and commit is False
        yield restated

    monkeypatch.setattr(publication_store, "pinned", repinned)
    monkeypatch.setattr(
        SO, "load_published_session",
        lambda _conn, requested, **_kwargs: (
            canonical if requested == FIRST else pytest.fail(requested)))

    status = _postgres_runtime(
        conn, observer=observer,
        clock=lambda: _preopen_clock()).durable_status()

    assert status.shadow_verdict == SO.SHADOW_GO
    assert status.verification == SO.VERIFIED
    assert status.session == status.live_frontier == FIRST
    assert status.sessions_lag == 0
    assert status.record_sha256 == first.record_sha256
    assert status.runtime_authority_sha256 == first.runtime_authority_sha256


def test_same_frontier_raw_price_correction_withdraws_verified_status(
        monkeypatch):
    conn = FakePostgres()
    store = SO.PostgresShadowObservationStore(
        conn, observation_id="year-end-2026")
    observer, _ = _observer(store=store)
    _install_runtime_gates(monkeypatch, conn)
    _postgres_runtime(
        conn, observer=observer,
        clock=lambda: _preopen_clock()).advance_next()
    restated = publication_store.Publication(
        version=8, previous_version=7, run_id="corrected-run-8",
        window_start=FIRST, window_end=FIRST,
        evidence={"complete": True, "frontier": FIRST, "corrected": True})
    corrected = _fully_published(FIRST, version=8, price=11.0).published

    @contextmanager
    def repinned(_actual, *, commit):
        assert commit is False
        yield restated

    monkeypatch.setattr(publication_store, "pinned", repinned)
    monkeypatch.setattr(
        SO, "load_published_session",
        lambda _conn, requested, **_kwargs: (
            corrected if requested == FIRST else pytest.fail(requested)))

    with pytest.raises(
            SO.ShadowObservationRefused,
            match="economically revised committed shadow session"):
        _postgres_runtime(
            conn, observer=observer,
            clock=lambda: _preopen_clock()).durable_status()

    assert len(store.records()) == len(store.authorities()) == 1


def test_historical_warmup_correction_withdraws_verified_status(monkeypatch):
    conn = FakePostgres()
    store = SO.PostgresShadowObservationStore(
        conn, observation_id="year-end-2026")
    observer, _ = _observer(store=store)
    _install_runtime_gates(monkeypatch, conn)
    _postgres_runtime(
        conn, observer=observer,
        clock=lambda: _preopen_clock()).advance_next()
    corrected = deepcopy(observer.warmup_input_identity)
    corrected["bars_sha256"] = "c" * 64
    corrected["warmup_input_sha256"] = _sha({
        key: value for key, value in corrected.items()
        if key != "warmup_input_sha256"})
    restated = publication_store.Publication(
        version=8, previous_version=7, run_id="warmup-correction-run-8",
        window_start=FIRST, window_end=FIRST,
        evidence={"complete": True, "frontier": FIRST})
    current_session = _fully_published(FIRST, version=8).published

    @contextmanager
    def repinned(_actual, *, commit):
        assert commit is False
        yield restated

    monkeypatch.setattr(publication_store, "pinned", repinned)
    monkeypatch.setattr(
        SO, "load_published_session",
        lambda _conn, requested, **_kwargs: (
            current_session if requested == FIRST else pytest.fail(requested)))

    with pytest.raises(
            SO.ShadowObservationRefused,
            match="revised the 252-session shadow warm-up"):
        _postgres_runtime(
            conn, observer=observer, clock=lambda: _preopen_clock(),
            warmup_input_loader=lambda: corrected).durable_status()

    assert len(store.records()) == len(store.authorities()) == 1


def test_d_plus_one_overlap_correction_withdraws_status_and_blocks_advance(
        monkeypatch):
    conn = FakePostgres()
    store = SO.PostgresShadowObservationStore(
        conn, observation_id="year-end-2026")
    observer, _ = _observer(store=store)
    _install_runtime_gates(monkeypatch, conn)
    _postgres_runtime(
        conn, observer=observer,
        clock=lambda: _preopen_clock()).advance_next()
    next_publication = publication_store.Publication(
        version=8, previous_version=7, run_id="d-plus-one-run-8",
        window_start=FIRST, window_end=SECOND,
        evidence={"complete": True, "frontier": SECOND})
    corrected_prior = _fully_published(
        FIRST, version=8, price=11.0).published

    @contextmanager
    def repinned(_actual, *, commit):
        assert commit is False
        yield next_publication

    monkeypatch.setattr(publication_store, "pinned", repinned)
    monkeypatch.setattr(
        feed_store, "latest_visible_session", lambda _conn: SECOND)
    monkeypatch.setattr(
        SO, "load_published_session",
        lambda _conn, requested, **_kwargs: (
            corrected_prior if requested == FIRST else pytest.fail(
                "economic overlap scan must refuse before next append")))
    runtime = _postgres_runtime(
        conn, observer=observer,
        clock=lambda: _preopen_clock(SECOND))

    with pytest.raises(
            SO.ShadowObservationRefused,
            match="economically revised committed shadow session"):
        runtime.durable_status()
    with pytest.raises(
            SO.ShadowObservationRefused,
            match="economically revised committed shadow session"):
        runtime.advance_next()

    assert len(store.records()) == len(store.authorities()) == 1


def test_memory_store_cannot_be_promoted_to_shadow_go():
    observer, _ = _observer()

    with pytest.raises(
            SO.ShadowObservationRefused,
            match="bound PostgreSQL store"):
        _postgres_runtime(FakePostgres(), observer=observer)


def test_postgres_promotion_requires_canonical_warmup_reloader():
    conn = FakePostgres()
    store = SO.PostgresShadowObservationStore(
        conn, observation_id="year-end-2026")
    observer, _ = _observer(store=store)

    with pytest.raises(
            SO.ShadowObservationRefused,
            match="canonical warm-up input loader"):
        SO.PostgresShadowRuntime(conn, observer=observer)


def test_module_has_no_broker_or_execution_import_or_mutation_api():
    path = Path(SO.__file__)
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports = set()
    function_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.add(node.module or "")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            function_names.add(node.name)

    assert not any(
        name == "sentinel.broker"
        or name.startswith("sentinel.execution")
        or "alpaca" in name.lower()
        for name in imports)
    assert function_names.isdisjoint({
        "submit", "submit_order", "cancel", "cancel_order", "replace_order"})


def test_shadow_runtime_import_graph_is_broker_free():
    tree = ast.parse(Path(SR.__file__).read_text(encoding="utf-8"))
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.add(node.module or "")

    assert not any(
        name == "sentinel.paper"
        or name.startswith("sentinel.execution")
        or "alpaca" in name.lower()
        for name in imports)
