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
from typing import TYPE_CHECKING, Any, Mapping

if TYPE_CHECKING:  # pragma: no cover
    from stock_strategy_shared.wealth_core.marks import EquityView, Mark

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
    # UNSET until the first OWNED close (locked convention, 2026-08-03). The
    # signal-day close happened before ownership, and the entry OPEN is not a
    # closing observation — seeding the peak from either would arm the trailing
    # stop against a price the position never owned. None means "no owned close
    # yet", and the stop cannot fire.
    episode_peak_split_adjusted_close: float | None = None
    market_sessions_held: int = 0
    # SOURCE-LOT PROVENANCE. Every predecessor this holding came from, oldest
    # first: the original admission, then one entry per conversion.
    #
    # Execution and marking use an AGGREGATED security-level quantity — that is
    # what the broker holds and what equity must count — but aggregation destroys
    # the answer to "where did these shares come from?", and after two positions
    # are taken over by the same acquirer that question has no other source. It
    # is what distinguishes one 8% holding from two 4% holdings that happen to
    # have collided, which changes what a human should do about it.
    source_lots: list[dict] = field(default_factory=list)
    review_completed: bool = False
    exit_pending: bool = False
    exit_reason: str | None = None

    def observe_entry_close(self, split_adjusted_close: float | None) -> None:
        """Initialise the peak from the ENTRY SESSION's close.

        Separate from `observe_close` because the entry session does NOT age the
        holding — the entry close is age 0 by the locked convention — but it is
        the first owned close and therefore the first legitimate peak.
        """
        if split_adjusted_close is not None:
            self.episode_peak_split_adjusted_close = float(split_adjusted_close)

    def observe_close(self, split_adjusted_close: float | None) -> None:
        """Advance one session: age the holding and ratchet the episode peak.

        The peak only ever rises within an episode, and it initialises on the
        first owned close if the entry session was missed. Both happen together
        because a caller that ages without ratcheting (or vice versa) produces a
        stop that measures the wrong drawdown, silently.
        """
        self.market_sessions_held += 1
        if split_adjusted_close is None:
            return
        px = float(split_adjusted_close)
        if self.episode_peak_split_adjusted_close is None or \
                px > self.episode_peak_split_adjusted_close:
            self.episode_peak_split_adjusted_close = px

    @property
    def review_due(self) -> bool:
        """Exactly once, at the review age. `==` not `>=`: the spec says each
        holding is reviewed ONCE, and `review_completed` records that it was.
        Using `>=` with a broken flag would re-review daily forever — which is
        the Structural Core behaviour this strategy explicitly is not."""
        # `>=`, not `==`. The flag already guarantees once-only; `==` meant a
        # review DEFERRED for a missing close (see engine.decide) could never
        # fire again, because the age moves past the threshold the next session.
        return (not self.review_completed
                and self.market_sessions_held >= REVIEW_AGE_SESSIONS)

    def stop_triggered(self, split_adjusted_close: float | None) -> bool:
        """Spec §9. Inclusive at exactly 30% off the episode peak.

        Returns False while the peak is UNSET: the close-based stop is not
        evaluated until at least one owned close exists (locked convention).
        """
        peak = self.episode_peak_split_adjusted_close
        if split_adjusted_close is None or peak is None or peak <= 0:
            return False
        return float(split_adjusted_close) <= peak * STOP_RETENTION

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
    occupied_by: str | None = None          # security_id, once FILLED
    cooldown_sessions_elapsed: int | None = None   # None = not cooling
    # Claimed by a queued-but-unfilled entry. A separate field from
    # `occupied_by` because the two are genuinely different states: the slot
    # holds no shares, contributes nothing to equity and can still be released,
    # but it is NOT available to another candidate.
    reserved_for: str | None = None         # security_id
    reserved_ticker: str | None = None
    reserved_issuer: str | None = None

    @property
    def in_cooldown(self) -> bool:
        return (self.cooldown_sessions_elapsed is not None
                and self.cooldown_sessions_elapsed < COOLDOWN_SESSIONS)

    @property
    def ready(self) -> bool:
        """A genuine vacancy: empty, UNRESERVED, and out of cooldown.

        The reservation term is load-bearing. Without it a slot whose entry
        order has not filled yet still reads as free, so the next session hands
        the same vacancy to the next candidate — and a security that stays
        untradeable for N sessions accumulates N entry orders against N slots,
        every one of which fills the moment it trades again. Observed: 13 queued
        buys for one security, ~52% of the book in a strategy whose risk model
        is 4% per name.
        """
        return (self.occupied_by is None and self.reserved_for is None
                and not self.in_cooldown)

    def reserve(self, security_id: str, ticker: str, issuer_id: str) -> None:
        self.reserved_for = security_id
        self.reserved_ticker = ticker
        self.reserved_issuer = issuer_id

    def release_reservation(self) -> None:
        self.reserved_for = self.reserved_ticker = self.reserved_issuer = None

    def start_cooldown(self) -> None:
        self.occupied_by = None
        self.release_reservation()
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
    # security_id -> why its terminal action cannot be applied. Lives on the
    # STATE rather than beside the event stream so it survives a restart: a
    # blocked book that silently unblocks itself on redeploy is the failure the
    # block exists to prevent.
    unresolved_terminals: dict[str, str] = field(default_factory=dict)

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

    def lots_by_security(self) -> dict[str, list[dict]]:
        """Per-security PROVENANCE beside the aggregated quantity.

        The companion to `shares_by_security`: that answers "how much do we
        own?", this answers "out of what?". Two predecessor positions converted
        into one acquirer appear here as two lots under one security, which is
        the only place that fact survives.
        """
        out: dict[str, list[dict]] = {}
        for slot_id in sorted(self.episodes):
            ep = self.episodes[slot_id]
            out.setdefault(ep.security_id, []).append({
                "slot_id": slot_id,
                "shares": ep.current_shares,
                "entry_date": ep.entry_date,
                "sessions_held": ep.market_sessions_held,
                "origin": list(ep.source_lots)})
        return out

    def reserved_security_ids(self) -> set[str]:
        """Securities with a queued-but-unfilled entry. They are NOT held — they
        contribute nothing to equity — but they are already spoken for, so a
        later session must not select them again."""
        return {s.reserved_for for s in self.slots.values() if s.reserved_for}

    def reserved_issuer_ids(self) -> set[str]:
        return {s.reserved_issuer for s in self.slots.values() if s.reserved_issuer}

    def reserved_tickers(self) -> set[str]:
        return {s.reserved_ticker for s in self.slots.values() if s.reserved_ticker}

    def reserve_slot(self, slot_id: int, security_id: str, ticker: str,
                     issuer_id: str) -> None:
        self.slots[slot_id].reserve(security_id, ticker, issuer_id)

    def shares_by_security(self) -> dict[str, int]:
        """AGGREGATED across episodes, not one entry per episode.

        Normally one security occupies one slot and the distinction is invisible.
        A CONVERSION breaks that: two separate holdings acquired by the same
        company both become shares of the acquirer, in two slots. A dict
        comprehension keyed on security_id silently dropped one of them, so
        equity undercounted a position the book still owned — and every later 4%
        admission was sized off the short number. Found by the golden fixture the
        moment two conversions delivered the same acquirer.

        The issuer-uniqueness rule governs ADMISSION, not corporate actions:
        nothing prevents a takeover from consolidating two holdings, and the
        engine has to be able to represent that rather than assume it away.
        """
        out: dict[str, int] = {}
        for e in self.episodes.values():
            out[e.security_id] = out.get(e.security_id, 0) + e.current_shares
        return out

    def equity_view(self, marks: Mapping[str, "Mark"]) -> "EquityView":
        """Portfolio value split into the trustworthy part and the estimate.

        Replaces a plain `equity()` deliberately. A single float cannot express
        "we do not know what one of these is worth", and a caller handed one
        will size 4% of it — which is the failure this whole type exists to
        prevent.
        """
        from stock_strategy_shared.wealth_core.marks import build_equity_view
        return build_equity_view(self.cash, self.shares_by_security(), marks)

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
            "unresolved_terminals": dict(sorted(self.unresolved_terminals.items())),
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
            unresolved_terminals=dict(d.get("unresolved_terminals") or {}),
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
    "episode_peak_origin":
        "LOCKED 2026-08-03: the peak is UNSET at the opening fill, initialised "
        "from the ENTRY SESSION'S CLOSE, and thereafter the max owned close. "
        "The stop is not evaluated until an owned close exists.",
    "underwater_strictness":
        "spec §8 says 'current close < entry price'. Implemented STRICTLY less, "
        "so exactly flat is not underwater and the holding survives review.",
}
