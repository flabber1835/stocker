"""Canonical deterministic transition for one production session.

This module contains no database, clock, persistence, execution, or broker
seam. Production and certification both call :func:`advance_session` with a
fully published session snapshot and a prior production state envelope.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Mapping

from stock_strategy_shared.wealth_core.adapter import PendingOrder
from stock_strategy_shared.wealth_core.eligibility import EligibilityConfig
from stock_strategy_shared.wealth_core.engine import Reason, WealthCoreConfig
from stock_strategy_shared.wealth_core.ledger import EventType, Ledger
from stock_strategy_shared.wealth_core.live import plan_session
from stock_strategy_shared.wealth_core.state import PortfolioState

from sentinel.breadth.classifier import session_breadth
from sentinel.controller.concordance import (
    advance_recent_leadership,
    is_concordance_identity,
    state_from_dict as leadership_state_from_dict,
    state_to_dict as leadership_state_to_dict,
)
from sentinel.controller.concordance_parent import (
    STRATEGY_ID as CONCORDANCE_PARENT_STRATEGY_ID,
)
from sentinel.controller.frozen_rule import ControllerConfig
from sentinel.controller.ldrc import (
    ldrc_step,
    state_from_dict as ldrc_state_from_dict,
    state_to_dict as ldrc_state_to_dict,
)
from sentinel.controller.machine import Controller, Observation
from sentinel.core.production import (
    ENVELOPE_VERSION,
    REQUIRED_IDENTITY_FIELDS,
    PublishedSession,
    SessionState,
    _bounded_evidence,
    _bounded_last_known,
    _feed_from_dict,
    _feed_to_dict,
    _path_dependent_security_ids,
    _period_return,
    _restore_missing_feed_anchors,
    holdings_from_shadow,
)
from sentinel.regime.spy import dated_spy_regime


def advance_session(
    prior: SessionState | Mapping,
    published: PublishedSession,
    *,
    controller_config: ControllerConfig,
    strategy_identity: Mapping,
    wealth_config: WealthCoreConfig | None = None,
    eligibility_config: EligibilityConfig | None = None,
    concordance_audit=None,
) -> SessionState:
    """Return the next production state for exactly one published session."""
    env = (
        prior
        if isinstance(prior, SessionState)
        else SessionState.from_dict(prior)
    )
    if env.version != ENVELOPE_VERSION:
        raise ValueError(
            f"unsupported production state version {env.version!r}"
        )
    running_identity = dict(strategy_identity)
    missing = REQUIRED_IDENTITY_FIELDS - set(running_identity)
    if missing:
        raise ValueError(
            "running strategy identity is incomplete: "
            + ", ".join(sorted(missing))
        )
    if (
        running_identity["strategy"] != controller_config.strategy_id
        or running_identity["controller_rule_sha256"]
        != controller_config.digest
    ):
        raise ValueError(
            "running strategy/controller identity disagrees with configuration"
        )
    if env.strategy_identity != running_identity:
        raise ValueError(
            "persisted strategy/config/source identity differs from running identity"
        )
    concordance = is_concordance_identity(running_identity)
    if (
        concordance
        and controller_config.strategy_id != CONCORDANCE_PARENT_STRATEGY_ID
    ):
        raise ValueError(
            "Concordance overlay requires the versioned hardened 30pp parent"
        )
    if (
        env.last_processed_session
        and published.session <= env.last_processed_session
    ):
        raise ValueError("production sessions must advance strictly")
    if (
        env.data_version is not None
        and published.data_version < env.data_version
    ):
        raise ValueError("corpus publication version moved backwards")

    elig = eligibility_config or EligibilityConfig()
    state = PortfolioState.from_dict(env.wealth_core)
    pending = [PendingOrder.from_dict(item) for item in env.pending]
    ledger = Ledger.from_dict(env.ledger)
    last_known = dict(env.last_known)
    feed = _feed_from_dict(env.feed, published.meta, elig)
    _restore_missing_feed_anchors(feed, published)
    ledger_event_boundary = len(ledger.events)
    plan = plan_session(
        session=published.session,
        bars=published.bars,
        meta=published.meta,
        state=state,
        pending=pending,
        ledger=ledger,
        last_known=last_known,
        feed=feed,
        cfg=wealth_config,
        eligibility_cfg=elig,
        terminal_events=published.terminal_events,
    )

    completed_stops = [
        event
        for event in ledger.events[ledger_event_boundary:]
        if event.session == published.session
        and event.event_type is EventType.SELL
        and event.reason == Reason.EXIT_TRAILING_STOP.value
    ]

    held = holdings_from_shadow(state, feed, published.sectors)
    breadth = session_breadth(held)
    navs = list(env.shadow_nav_history)
    nav = float(plan.estimated_equity)
    navs.append(nav)
    navs = navs[-41:]
    peak = max(float(env.shadow_peak_nav), nav)
    stops = list(env.trailing_stop_sessions)
    stops.extend([published.session] * len(completed_stops))
    recent_sessions = (
        list(env.controller_session_history) + [published.session]
    )[-20:]
    recent_session_set = set(recent_sessions)
    stops = [
        stop_session
        for stop_session in stops
        if stop_session in recent_session_set
    ]
    damaged = list(env.breadth_history) + [breadth.damaged_breadth]
    regime = dated_spy_regime(
        published.spy_sessions,
        published.spy_closeadj,
        decision_session=published.session,
        expected_sessions=published.spy_expected_sessions,
    )
    observation = Observation(
        session=published.session,
        shadow_nav=nav,
        damaged_breadth=breadth.damaged_breadth,
        green_breadth=breadth.green_breadth,
        shadow_drawdown=(nav / peak - 1.0 if peak else None),
        shadow_r5=_period_return(navs, 5),
        shadow_r10=_period_return(navs, 10),
        shadow_r20=_period_return(navs, 20),
        shadow_r40=_period_return(navs, 40),
        damaged_breadth_delta5=(
            damaged[-1] - damaged[-6] if len(damaged) >= 6 else None
        ),
        spy_r20=regime.spy_r20,
        spy_vol_ratio=regime.spy_vol_ratio,
    )
    observation = Observation(
        **{**asdict(observation), "stops20": len(stops)}
    )
    controller = Controller(controller_config)
    controller_state, native_decision = controller.step(
        observation=observation,
        state=env.controller,
    )
    decision = native_decision.to_dict()
    recent_leadership_state = env.recent_leadership
    ldrc_state = env.ldrc
    concordance_evidence = {}
    if concordance:
        witness_before = leadership_state_from_dict(
            env.recent_leadership or {}
        )
        witness_after, witness_decision = advance_recent_leadership(
            session=published.session,
            candidate_rows=plan.leadership_candidates,
            eligible_universe_count=plan.eligible_universe_count,
            signal_closes=plan.signal_closes,
            state=witness_before,
        )
        overlay_before = ldrc_state_from_dict(env.ldrc or {})
        overlay_after, overlay_decision = ldrc_step(
            session=published.session,
            native_allocation=native_decision.target_core_exposure,
            effective_native_allocation=overlay_before.previous_native_allocation,
            wc_drawdown=observation.shadow_drawdown,
            recent_r20=witness_decision.recent_r20,
            recent_r40=witness_decision.recent_r40,
            spy_r20=regime.spy_r20,
            state=overlay_before,
        )
        if (
            overlay_decision.desired_allocation
            > native_decision.target_core_exposure + 1e-15
        ):
            raise AssertionError("Concordance cannot increase native exposure")
        if concordance_audit is not None:
            concordance_audit(
                session=published.session,
                candidate_rows=tuple(plan.leadership_candidates),
                eligible_universe_count=plan.eligible_universe_count,
                signal_closes=dict(plan.signal_closes),
                native_allocation=native_decision.target_core_exposure,
                effective_native_allocation=(
                    overlay_before.previous_native_allocation
                ),
                wc_drawdown=observation.shadow_drawdown,
                spy_r20=regime.spy_r20,
                production_witness_decision=asdict(witness_decision),
                production_witness_state=leadership_state_to_dict(
                    witness_after
                ),
                production_ldrc_decision=asdict(overlay_decision),
                production_ldrc_state=ldrc_state_to_dict(overlay_after),
                production_final_allocation=overlay_decision.desired_allocation,
            )
        decision = {
            **decision,
            "native_target_core_exposure": (
                native_decision.target_core_exposure
            ),
            "target_core_exposure": overlay_decision.desired_allocation,
            "ldrc": asdict(overlay_decision),
        }
        recent_leadership_state = leadership_state_to_dict(witness_after)
        ldrc_state = ldrc_state_to_dict(overlay_after)
        concordance_evidence = {
            "native_controller": native_decision.to_dict(),
            "recent_leadership": asdict(witness_decision),
            "recent_leadership_readiness": {
                "history_sessions": len(witness_after.session_history),
                "r20_available": witness_decision.recent_r20 is not None,
                "r40_available": witness_decision.recent_r40 is not None,
            },
            "ldrc": asdict(overlay_decision),
        }
    evidence = {
        "observation": asdict(observation),
        "breadth": {
            "denominator": breadth.denominator,
            "greens": breadth.greens,
            "ambers": breadth.ambers,
            "reds": breadth.reds,
            "holdings": [asdict(holding) for holding in held],
        },
        "wealth_core": _bounded_evidence(
            {"wealth_core": plan.to_dict()}
        )["wealth_core"],
        **concordance_evidence,
    }
    wealth_core = state.to_dict()
    pending_state = [item.to_dict() for item in pending]
    protected = _path_dependent_security_ids(wealth_core, pending_state)
    return SessionState(
        wealth_core=wealth_core,
        pending=pending_state,
        ledger=ledger.to_dict(),
        last_known=_bounded_last_known(last_known, protected),
        feed=_feed_to_dict(feed, protected),
        controller=controller_state,
        shadow_nav_history=navs,
        shadow_peak_nav=peak,
        trailing_stop_sessions=stops,
        controller_session_history=recent_sessions,
        breadth_history=damaged[-6:],
        last_processed_session=published.session,
        data_version=published.data_version,
        strategy_identity=dict(env.strategy_identity),
        last_decision=decision,
        last_evidence=evidence,
        recent_leadership=recent_leadership_state,
        ldrc=ldrc_state,
        concordance_witness_origin=env.concordance_witness_origin,
    )


__all__ = ["advance_session"]
