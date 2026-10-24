"""Canonical pure feature warmup shared by formation and runtime adapters."""
from __future__ import annotations
import math
from typing import Mapping
from stock_strategy_shared.wealth_core.eligibility import EligibilityConfig
from stock_strategy_shared.wealth_core.engine import WealthCoreConfig, score_universe
from stock_strategy_shared.wealth_core.feed import Feed
from stock_strategy_shared.wealth_core.ledger import Ledger
from stock_strategy_shared.wealth_core.state import PortfolioState
from sentinel.controller.concordance import (advance_recent_leadership, is_concordance_identity,
    state_from_dict as leadership_state_from_dict, state_to_dict as leadership_state_to_dict)
from sentinel.controller import median5 as median5_controller
from sentinel.core.session import (CONCORDANCE_WITNESS_HISTORICAL,
    CONCORDANCE_WITNESS_PROSPECTIVE, SessionState, _feed_to_dict)


def warm_session_state(state: SessionState | Mapping, window, *,
                       publication_version: int,
                       eligibility_config: EligibilityConfig | None = None,
                       prospective_concordance_witness: bool = False,
                       ) -> SessionState:
    """Prime canonical rolling feed features without inventing book history.

    A fresh account has no episodes, peaks, ages, cooldowns, pending actions or
    controller memory to reconstruct. Running those historical sessions through
    ``plan_session`` would manufacture all of them. ``Feed.warmup`` is the
    canonical feature-only path; its bounded restart form is installed into the
    otherwise-fresh version-3 envelope and the decision session is advanced
    later, exactly once.
    """
    env = (state if isinstance(state, SessionState)
           else SessionState.from_dict(state))
    portfolio = PortfolioState.from_dict(env.wealth_core)
    ledger = Ledger.from_dict(env.ledger)
    if (env.last_processed_session is not None or portfolio.episodes
            or env.pending or ledger.events or env.controller_session_history):
        raise ValueError("feature-only warm-up requires a fresh canonical state")
    sessions = list(window.sessions)
    if (not sessions
            or any(left >= right for left, right in zip(sessions, sessions[1:]))):
        raise ValueError(
            "warm-up window sessions must be strictly increasing and unique")
    if type(prospective_concordance_witness) is not bool:
        raise ValueError(
            "prospective_concordance_witness must be an explicit boolean")
    elig = eligibility_config or EligibilityConfig()
    if median5_controller.enabled(env.strategy_identity):
        return _warm_median5(env, window, sessions, publication_version,
                             prospective_concordance_witness, elig)
    witness_state = None
    concordance = is_concordance_identity(env.strategy_identity)
    if prospective_concordance_witness and not concordance:
        raise ValueError(
            "prospective Concordance witness mode requires Concordance identity")
    if concordance and not prospective_concordance_witness:
        timeline = getattr(window, "metadata_timeline", None)
        if (timeline is None or list(timeline.sessions) != sessions):
            raise ValueError(
                "Concordance warm-up requires exact session-effective metadata")
        feed = Feed({}, elig, metadata_timeline=timeline)
        witness_state = leadership_state_from_dict(env.recent_leadership or {})
        wealth_cfg = WealthCoreConfig()
        for session in sessions:
            bars = window.bars_by_session.get(session, ())
            normalized = feed.advance(session, bars)
            scored = score_universe(normalized.security_bars, wealth_cfg)
            candidates = tuple(
                row for row in scored
                if row.momentum is not None and row.recent is not None)
            eligible_count = sum(
                1 for row in normalized.security_bars if row.eligible)
            # Before the canonical 127-close formation window exists there is
            # no leadership population and therefore no witness observation.
            # Appending flat NAVs here would manufacture r20/r40 readiness from
            # sessions on which the sensor could not yet exist.
            if eligible_count == 0:
                continue
            signal_closes = {}
            for bar in bars:
                series = feed.series.get(bar.security_id)
                if (series is None or not series.sessions
                        or series.sessions[-1] != session
                        or not series.signal_closes):
                    continue
                close = series.signal_closes[-1]
                if close is not None:
                    signal_closes[bar.security_id] = float(close)
            witness_state, _ = advance_recent_leadership(
                session=session, candidate_rows=candidates,
                eligible_universe_count=eligible_count,
                signal_closes=signal_closes, state=witness_state)
    else:
        # In the authenticated current-only paper cold start this primes only
        # price/volume/split features.  It makes no historical strategy or
        # witness decision; the zero-capital witness begins on the first live
        # close.  Non-Concordance warmup has always used this same feature-only
        # path.
        feed = Feed(window.meta, elig)
        feed.warmup(sessions, window.bars_by_session)
    warmed = SessionState.from_dict(env.to_dict())
    warmed.feed = _feed_to_dict(feed, set())
    if witness_state is not None:
        warmed.recent_leadership = leadership_state_to_dict(witness_state)
    if concordance:
        warmed.concordance_witness_origin = (
            CONCORDANCE_WITNESS_PROSPECTIVE
            if prospective_concordance_witness
            else CONCORDANCE_WITNESS_HISTORICAL)
    warmed.data_version = int(publication_version)
    return warmed



def _warm_median5(env, window, sessions, publication_version, prospective, elig):
    """Form features and optionally the historical zero-capital witness."""
    from stock_strategy_shared.wealth_core.median5 import rank
    config = median5_controller.wealth_config(env.strategy_identity)
    if elig != EligibilityConfig():
        raise ValueError("Median-5 warmup cannot override eligibility")
    if len(sessions) < 252:
        raise ValueError("Median-5 requires 252 warmup sessions")
    timeline = getattr(window, "metadata_timeline", None)
    if not prospective and (timeline is None or list(timeline.sessions) != sessions):
        raise ValueError("Median-5 historical witness requires causal metadata")
    spy = getattr(window, "median5_spy_closes", None)
    if spy is None or any(s not in spy for s in sessions):
        raise ValueError("Median-5 warmup requires the exact dated SPY history")
    warmed = SessionState.from_dict(env.to_dict())
    portfolio = PortfolioState.from_dict(warmed.wealth_core)
    feed = Feed(window.meta if prospective else {}, elig,
                metadata_timeline=None if prospective else timeline)
    feed.median5_state = portfolio.median5
    feed.restart_sessions = 260
    controller_state = warmed.median5
    previous = None
    terminal_by_session = getattr(window, "median5_terminals", {})
    if not prospective and not hasattr(window, "median5_terminals"):
        raise ValueError("Median-5 historical witness requires causal terminal evidence")
    for index, session in enumerate(sessions):
        norm = feed.advance(session, window.bars_by_session.get(session, ()))
        median5_controller.remember_peer_keys(controller_state,
            window.meta if prospective else timeline.session_map(session))
        close = float(spy[session])
        if not math.isfinite(close) or close <= 0:
            raise ValueError("invalid Median-5 warmup SPY close")
        controller_state["spy_history"].append([index, close, close/previous-1 if previous else None])
        previous = close
        if not prospective:
            scored = score_universe(norm.security_bars, config)
            rank(scored, portfolio.median5)
            candidates = [s for s in scored if s.momentum is not None and s.recent is not None]
            controller_state, _ = median5_controller.witness(
                controller_state, session=session, candidates=candidates,
                closes={b.security_id: b.closes[-1] for b in norm.security_bars if b.closes and b.closes[-1] is not None},
                terminals=terminal_by_session.get(session, ()))
    controller_state["spy_history"] = controller_state["spy_history"][-254:]
    warmed.median5 = controller_state
    warmed.wealth_core = portfolio.to_dict()
    warmed.feed = _feed_to_dict(feed, set())
    warmed.concordance_witness_origin = (CONCORDANCE_WITNESS_PROSPECTIVE if prospective
                                         else CONCORDANCE_WITNESS_HISTORICAL)
    warmed.data_version = int(publication_version)
    return SessionState.from_dict(warmed.to_dict())
