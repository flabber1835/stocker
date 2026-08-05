"""Wealth Core v1 — persistent strategy state. PURE: no DB, no clock, no I/O.

Wealth Core is NOT a daily normalised-target strategy, so its state cannot be
re-derived each morning from a target portfolio. Position age, the one-time
review flag, the episode peak and the two cooldowns are all path-dependent: lose
them and the strategy is a different strategy. This module is that state, plus
its serialisation and its hash.

SESSION-COUNTING CONVENTIONS — adopted here, and the single most consequential
choice in the whole engine:

  market_sessions_held   counts session closes STRICTLY AFTER the entry session.
                         The entry session's own close is age 0. The spec says
                         review fires when age "reaches 119 completed market
                         sessions AFTER entry", so `age == 119` is the 120th
                         close from entry inclusive.

  cooldown age           counts session closes STRICTLY AFTER the exit session,
                         same convention. "Unavailable for 21 market sessions"
                         means blocked at ages 0-20 and available at 21.

Both are ambiguous in the written specification and both are flagged in
signals.UNRESOLVED-style form at the bottom of this module. They are pinned by
boundary tests at 118/119/120 and 20/21/22 precisely because an off-by-one here
is invisible in aggregate performance and changes every holding period.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any

# Spec §6: 25 persistent slots, 4% of current portfolio equity per admission.
DEFAULT_SLOTS = 25
DEFAULT_ENTRY_WEIGHT = 0.04
# Spec §8 / §10, in the convention documented above.
REVIEW_AGE_SESSIONS = 119
COOLDOWN_SESSIONS = 21
# Spec §9: sell when close <= peak * 0.70. A 30.00% decline triggers; 29.99%
# does not. The comparison is <=, which is what makes the boundary test exact.
STOP_RETENTION = 0.70


@dataclass
class HoldingEpisode:
    """One unbroken holding period in one slot.

    An episode ENDS at exit; a later re-entry into the same security is a NEW
    episode with a fresh peak. The spec is explicit that the 30% stop "does not
    reset except when a new holding episode begins", which is only meaningful
    if the episode is the unit of state rather than the ticker.
    """
    security_id: str
    ticker: str
    issuer_id: str
    slot_id: int
    signal_date: str
    entry_date: str
    entry_raw_open: float
    entry_split_adjusted_price: float
    initial_shares: int
    current_shares: int
    episode_peak_split_adjusted_close: float
    market_sessions_held: int = 0
    review_completed: bool = False
    exit_pending: bool = False
    exit_reason: str | None = None

    def observe_close(self, split_adjusted_close: float) -> None:
        """Advance one session: age the holding and ratchet the episode peak.

        The peak only ever rises within an episode. Both happen together
        because a caller that ages without ratcheting (or vice versa) produces a
        stop that measures the wrong drawdown, silently.
        """
        self.market_sessions_held += 1
        if split_adjusted_close is not None and \
                split_adjusted_close > self.episode_peak_split_adjusted_close:
            self.episode_peak_split_adjusted_close = float(split_adjusted_close)

    @property
    def review_due(self) -> bool:
        """Exactly once, at the review age. `==` not `>=`: the spec says each
        holding is reviewed ONCE, and `review_completed` records that it was.
        Using `>=` with a broken flag would re-review daily forever — which is
        the Structural Core behaviour this strategy explicitly is not."""
        return (not self.review_completed
                and self.market_sessions_held == REVIEW_AGE_SESSIONS)

    def stop_triggered(self, split_adjusted_close: float | None) -> bool:
        """Spec §9. Inclusive at exactly 30% off the episode peak."""
        if split_adjusted_close is None or self.episode_peak_split_adjusted_close <= 0:
            return False
        return float(split_adjusted_close) <= \
            self.episode_peak_split_adjusted_close * STOP_RETENTION

    def is_underwater(self, split_adjusted_close: float | None) -> bool:
        """Spec §8, first limb: current split-adjusted close < split-adjusted
        entry price. STRICTLY less — exactly flat is not underwater."""
        if split_adjusted_close is None:
            return False
        return float(split_adjusted_close) < self.entry_split_adjusted_price


@dataclass
class SlotState:
    """A persistent slot. Cooldown lives on the SLOT as well as the ticker
    (spec §10) — the slot stays cash even if a different security would be
    happy to fill it, which is why the two cannot be collapsed into one."""
    slot_id: int
    occupied_by: str | None = None          # security_id
    cooldown_sessions_elapsed: int | None = None   # None = not cooling

    @property
    def in_cooldown(self) -> bool:
        return (self.cooldown_sessions_elapsed is not None
                and self.cooldown_sessions_elapsed < COOLDOWN_SESSIONS)

    @property
    def ready(self) -> bool:
        """A genuine vacancy: empty AND out of cooldown."""
        return self.occupied_by is None and not self.in_cooldown

    def start_cooldown(self) -> None:
        self.occupied_by = None
        self.cooldown_sessions_elapsed = 0

    def age_cooldown(self) -> None:
        if self.cooldown_sessions_elapsed is not None:
            self.cooldown_sessions_elapsed += 1
            if self.cooldown_sessions_elapsed >= COOLDOWN_SESSIONS:
                self.cooldown_sessions_elapsed = None    # expired, slot is free


@dataclass
class PortfolioState:
    """Everything the strategy must remember between sessions.

    Serialisable and hashable by construction: a replay that cannot reproduce
    the hash has not reproduced the state, and the spec makes replay a hard
    requirement rather than a nicety.
    """
    slots: dict[int, SlotState] = field(default_factory=dict)
    episodes: dict[int, HoldingEpisode] = field(default_factory=dict)   # by slot_id
    ticker_cooldowns: dict[str, int] = field(default_factory=dict)      # ticker -> elapsed
    cash: float = 0.0
    initialized: bool = False
    session_index: int = 0

    @classmethod
    def fresh(cls, starting_cash: float, n_slots: int = DEFAULT_SLOTS) -> "PortfolioState":
        return cls(slots={i: SlotState(slot_id=i) for i in range(n_slots)},
                   cash=float(starting_cash))

    # ── queries ──────────────────────────────────────────────────────────────

    def held_security_ids(self) -> set[str]:
        return {e.security_id for e in self.episodes.values()}

    def held_issuer_ids(self) -> set[str]:
        """Spec §1: at most one position per economic ISSUER. Share classes of
        the same company are one position, not two."""
        return {e.issuer_id for e in self.episodes.values()}

    def ticker_in_cooldown(self, ticker: str) -> bool:
        n = self.ticker_cooldowns.get(ticker)
        return n is not None and n < COOLDOWN_SESSIONS

    def ready_slots(self) -> list[int]:
        """Deterministic: ascending slot_id. Any other order would make the
        chosen slot depend on dict iteration, and the slot id ends up in the
        decision hash."""
        return sorted(s.slot_id for s in self.slots.values() if s.ready)

    def equity(self, marks: dict[str, float]) -> float:
        """Spec §2: portfolio marking uses actual RAW unadjusted closes, which
        the caller supplies as `marks` keyed by security_id. A holding with no
        mark contributes nothing rather than a stale value — silently carrying
        yesterday's price into today's equity would resize every subsequent
        admission."""
        total = self.cash
        for e in self.episodes.values():
            px = marks.get(e.security_id)
            if px is not None:
                total += e.current_shares * float(px)
        return total

    # ── session advance ──────────────────────────────────────────────────────

    def age_one_session(self, split_adjusted_closes: dict[str, float]) -> None:
        """Advance every clock by one completed session.

        Order matters and is fixed: holdings age and ratchet first, then
        cooldowns. Both use the same "strictly after the event" convention
        documented in the module docstring.
        """
        for e in self.episodes.values():
            e.observe_close(split_adjusted_closes.get(e.security_id))
        for s in self.slots.values():
            s.age_cooldown()
        for tic in list(self.ticker_cooldowns):
            self.ticker_cooldowns[tic] += 1
            if self.ticker_cooldowns[tic] >= COOLDOWN_SESSIONS:
                del self.ticker_cooldowns[tic]
        self.session_index += 1

    # ── serialisation (spec §12: replay) ─────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        return {
            "slots": {str(k): asdict(v) for k, v in sorted(self.slots.items())},
            "episodes": {str(k): asdict(v) for k, v in sorted(self.episodes.items())},
            "ticker_cooldowns": dict(sorted(self.ticker_cooldowns.items())),
            "cash": self.cash,
            "initialized": self.initialized,
            "session_index": self.session_index,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "PortfolioState":
        return cls(
            slots={int(k): SlotState(**v) for k, v in (d.get("slots") or {}).items()},
            episodes={int(k): HoldingEpisode(**v)
                      for k, v in (d.get("episodes") or {}).items()},
            ticker_cooldowns=dict(d.get("ticker_cooldowns") or {}),
            cash=float(d.get("cash", 0.0)),
            initialized=bool(d.get("initialized", False)),
            session_index=int(d.get("session_index", 0)),
        )

    def state_hash(self) -> str:
        """Stable across processes and dict orderings.

        sort_keys is what makes it stable; without it the hash would depend on
        insertion order and a replay in a fresh process could differ from the
        original while representing identical state.
        """
        blob = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"),
                          default=str)
        return hashlib.sha256(blob.encode()).hexdigest()[:16]


# Conventions the written specification leaves open. Named as data so the docs
# and the acceptance tests enumerate the same list.
UNRESOLVED: dict[str, str] = {
    "age_origin":
        "spec §8 says review at '119 completed market sessions after entry'. "
        "Adopted: age counts closes STRICTLY AFTER the entry session, so the "
        "entry close is age 0 and age==119 is the 120th close inclusive.",
    "cooldown_origin":
        "spec §10 says 'unavailable for 21 market sessions' and 'expires after "
        "21 completed market sessions'. Adopted: same strictly-after "
        "convention — blocked at ages 0-20, available at 21.",
    "underwater_strictness":
        "spec §8 says 'current close < entry price'. Implemented STRICTLY less, "
        "so exactly flat is not underwater and the holding survives review.",
}
