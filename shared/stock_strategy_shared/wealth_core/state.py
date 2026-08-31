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

from copy import deepcopy
import hashlib
import json
import math
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, AbstractSet, Any, Mapping

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
    # FLOAT, not int: a split is a transformation and its fractional
    # entitlement is real. Integer-share constraints are a BROKER fact and
    # belong in the execution projection — see wealth_core/shares.py.
    initial_shares: float
    current_shares: float
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


def _episode_json(ep) -> dict[str, Any]:
    """One episode, with share counts CANONICALLY serialised.

    An integral quantity emits as `int`, which is load-bearing rather than
    cosmetic: every share count in the certified golden fixture is a whole
    number, and widening the field to float so a split can keep its fraction
    would otherwise emit `20.0` where `20` stood — moving `daily_state`,
    `order`, `ledger` and `final_state` for a book in which nothing economic
    changed. A REPRESENTATION change must never masquerade as a SEMANTIC one,
    especially while a certification hash is open.
    """
    from stock_strategy_shared.wealth_core.shares import as_json
    d = asdict(ep)
    d["initial_shares"] = as_json(d["initial_shares"])
    d["current_shares"] = as_json(d["current_shares"])
    return d


#: `to_dict()` keys that are PERSISTED but never HASHED.
#:
#: The rule they encode: audit provenance is an OBSERVATION of what the engine
#: did, so it must survive a restart and must not be able to move a parity hash.
#: Anything added here has to be DERIVED — recomputable from state or inputs
#: that are themselves hashed — or it becomes a way for a real divergence to
#: hide. That is enforced by test, not by this comment.
#:
#: Deliberately a frozenset of literal key names rather than a prefix or naming
#: convention: a convention silently captures the next field somebody names with
#: the wrong word, and the cost of accidentally excluding a REAL state field
#: from the hash is a parity check that passes when it should fail.
_AUDIT_ONLY_STATE_KEYS = frozenset({
    "terminal_carry_audit", "last_valid_mark_session"})


@dataclass
class PortfolioState:
    """Everything the strategy must remember between sessions.

    Serialisable and hashable by construction: a replay that cannot reproduce
    the hash has not reproduced the state, and the spec makes replay a hard
    requirement rather than a nicety.
    """
    slots: dict[int, SlotState] = field(default_factory=dict)
    episodes: dict[int, HoldingEpisode] = field(default_factory=dict)   # by slot_id
    # security_id -> sessions elapsed. Keyed on the PERMANENT identity, not the
    # ticker. A ticker is an observation label: a security that exited and then
    # renamed used to become immediately re-buyable, because the cooldown was
    # looked up under a symbol that no longer existed. "Unbuyable for 21
    # sessions" is a statement about the company, not about the string it trades
    # under.
    security_cooldowns: dict[str, int] = field(default_factory=dict)
    cash: float = 0.0
    initialized: bool = False
    session_index: int = 0
    # security_id -> why its terminal action cannot be applied. Lives on the
    # STATE rather than beside the event stream so it survives a restart: a
    # blocked book that silently unblocks itself on redeploy is the failure the
    # block exists to prevent.
    unresolved_terminals: dict[str, str] = field(default_factory=dict)

    # ── settlement-waterfall counters (settlement.py) ────────────────────────
    # All three PERSIST for the same reason `unresolved_terminals` does: a grace
    # period that reset on every redeploy would never expire on a book that
    # restarts weekly, and the failure would look like patience rather than a
    # counter losing its place. Every one of them treats ABSENT as zero, so a
    # healthy book carries three empty dicts and its state hash is unchanged.

    # security_id -> consecutive sessions with NO usable mark. Feeds the
    # waterfall's recency bound (C1) and its orphan timeout (C2).
    sessions_since_valid_mark: dict[str, int] = field(default_factory=dict)

    # security_id -> sessions carried under a DOCUMENTED terms-less event.
    # Counted separately from staleness above because the two routinely
    # diverge: a security can keep printing every session while its announced
    # deal has no terms, so staleness stays 0 and a grace driven off it would
    # never expire.
    terminal_pending_sessions: dict[str, int] = field(default_factory=dict)

    # security_id -> {"terms": <serialised TerminalTerms>, "stale_at_event": int}
    # for the event the grace is being served for.
    #
    # The terms themselves rather than just a reference string, and that is
    # forced by the data: a terminal event appears in ACTIONS on ONE session and
    # never again, so from the session after the announcement there is nothing
    # left to re-resolve against. Without the terms here, `sweep_pending_terms`
    # would have to invent a settlement rule of its own for expiry — a second
    # implementation of the waterfall, which is how the two engines drift.
    #
    # Carrying them also makes the two things the grace exists for CHECKABLE:
    # exact terms arriving later are compared against what was pending, and a
    # SECOND, different event mid-grace is detected by its `reference` instead
    # of silently inheriting the first one's age (which would re-admit the
    # foreclosure defect through the counter rather than through the rule).
    terminal_pending_terms: dict[str, dict] = field(default_factory=dict)

    # ── AUDIT-ONLY provenance (terminal_audit.py) ────────────────────────────
    # PERSISTED so a restart mid-grace does not lose it, and EXCLUDED FROM THE
    # STATE HASH so adding it moves no parity hash. Both halves are required and
    # for different reasons.
    #
    # Persisted: a carry can run ten sessions and the deploy restarts weekly, so
    # provenance held only in memory would be missing from exactly the long
    # graces most worth auditing, and a resumed run's `terminal_results` would
    # differ from an uninterrupted one's — a parity failure caused by the audit
    # rather than by the strategy.
    #
    # Unhashed: `state_hash()` covers `to_dict()`, and `daily_state_hash` chains
    # one such hash per session, so a new key here would move the daily_state and
    # final_state hashes as well as final_result. The re-pin is authorised for
    # ONE movement. This follows `RunResult.settlement_counters`, which is kept
    # out of `to_dict()` for the same reason: it is a REPORT.
    #
    # Safe to leave unhashed ONLY because every value is DERIVED from things that
    # are already hashed — share counts from the episode, prices from the
    # normalised bar stream, sessions from the session list. A divergence in any
    # of them shows up in an earlier hash, which is the one that names the layer
    # at fault. See `_AUDIT_ONLY_STATE_KEYS`.

    # security_id -> the carry provenance record built by
    # `terminal_audit.new_carry_record`, for the C1 grace currently being served.
    terminal_carry_audit: dict[str, dict] = field(default_factory=dict)

    # security_id -> the SESSION of its most recent trustworthy print. The price
    # already lives in the caller-owned `last_known`; only the date is missing,
    # and "last trustworthy print" is not answerable without it.
    last_valid_mark_session: dict[str, str] = field(default_factory=dict)

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

    def security_in_cooldown(self, security_id: str) -> bool:
        n = self.security_cooldowns.get(security_id)
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

    def equity_view(
            self, marks: Mapping[str, "Mark"], *,
            noncash_assets: float = 0.0) -> "EquityView":
        """Portfolio value split into the trustworthy part and the estimate.

        Replaces a plain `equity()` deliberately. A single float cannot express
        "we do not know what one of these is worth", and a caller handed one
        will size 4% of it — which is the failure this whole type exists to
        prevent.
        """
        from stock_strategy_shared.wealth_core.marks import build_equity_view
        return build_equity_view(
            self.cash, self.shares_by_security(), marks,
            noncash_assets=noncash_assets)

    # ── session advance ──────────────────────────────────────────────────────

    def age_one_session(
            self,
            split_adjusted_closes: dict[str, float],
            *,
            skip_slot_cooldowns: AbstractSet[int] = frozenset(),
            skip_security_cooldowns: AbstractSet[str] = frozenset(),
            ) -> None:
        """Advance every clock by one completed session.

        Order matters and is fixed: holdings age and ratchet first, then
        cooldowns. Both use the same "strictly after the event" convention
        documented in the module docstring.

        Cooldowns created during this same session are named by the caller and
        remain at age 0. Their first completed session strictly after the exit
        is the next market close. The default ages every cooldown, preserving
        the direct state-machine API for callers that are already operating at
        a strictly-after-event close.
        """
        for e in self.episodes.values():
            e.observe_close(split_adjusted_closes.get(e.security_id))
        for slot_id, s in self.slots.items():
            if slot_id not in skip_slot_cooldowns:
                s.age_cooldown()
        for sid in list(self.security_cooldowns):
            if sid in skip_security_cooldowns:
                continue
            self.security_cooldowns[sid] += 1
            if self.security_cooldowns[sid] >= COOLDOWN_SESSIONS:
                del self.security_cooldowns[sid]
        self.session_index += 1

    # ── serialisation (spec §12: replay) ─────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        return {
            "slots": {str(k): asdict(v) for k, v in sorted(self.slots.items())},
            "episodes": {str(k): _episode_json(v)
                         for k, v in sorted(self.episodes.items())},
            "security_cooldowns": dict(sorted(self.security_cooldowns.items())),
            "cash": self.cash,
            "initialized": self.initialized,
            "session_index": self.session_index,
            "unresolved_terminals": dict(sorted(self.unresolved_terminals.items())),
            "sessions_since_valid_mark": dict(
                sorted(self.sessions_since_valid_mark.items())),
            "terminal_pending_sessions": dict(
                sorted(self.terminal_pending_sessions.items())),
            "terminal_pending_terms": {
                k: deepcopy(self.terminal_pending_terms[k])
                for k in sorted(self.terminal_pending_terms)},
            # AUDIT-ONLY, and excluded from `state_hash` by
            # `_AUDIT_ONLY_STATE_KEYS`. Present HERE because to_dict is also the
            # persistence format, and a carry that outlives a restart must keep
            # its provenance.
            "terminal_carry_audit": {
                k: deepcopy(self.terminal_carry_audit[k])
                for k in sorted(self.terminal_carry_audit)},
            "last_valid_mark_session": dict(
                sorted(self.last_valid_mark_session.items())),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "PortfolioState":
        if not isinstance(d, Mapping):
            raise ValueError("persisted Wealth Core state is not an object")
        raw_slots = d.get("slots")
        if not isinstance(raw_slots, Mapping) or not raw_slots:
            raise ValueError("persisted Wealth Core state has no slot domain")
        try:
            slot_ids = sorted(int(key) for key in raw_slots)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "persisted Wealth Core slot keys are not integer identities") from exc
        if slot_ids != list(range(len(slot_ids))):
            raise ValueError(
                "persisted Wealth Core slots are not a contiguous zero-based domain")
        for key, value in raw_slots.items():
            try:
                slot_id = value.get("slot_id") if isinstance(value, Mapping) else None
                valid_slot = (
                    not isinstance(slot_id, bool) and int(slot_id) == int(key))
            except (TypeError, ValueError):
                valid_slot = False
            if not valid_slot:
                raise ValueError(
                    "persisted Wealth Core slot key and slot_id disagree")
        raw_cash = d.get("cash", 0.0)
        if isinstance(raw_cash, bool):
            raise ValueError("persisted Wealth Core cash is not a finite number")
        try:
            cash = float(raw_cash)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "persisted Wealth Core cash is not a finite number") from exc
        if not math.isfinite(cash) or cash < 0:
            raise ValueError(
                "persisted Wealth Core cash must be finite and non-negative")

        raw_session_index = d.get("session_index", 0)
        if isinstance(raw_session_index, bool):
            raise ValueError(
                "persisted Wealth Core session_index is not an integer")
        try:
            session_index = int(raw_session_index)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "persisted Wealth Core session_index is not an integer") from exc
        if str(raw_session_index).strip() != str(session_index):
            raise ValueError(
                "persisted Wealth Core session_index is not an exact integer")
        if session_index < 0:
            raise ValueError(
                "persisted Wealth Core session_index must be non-negative")

        initialized = d.get("initialized", False)
        if type(initialized) is not bool:
            raise ValueError(
                "persisted Wealth Core initialized flag is not boolean")
        return cls(
            slots={int(k): SlotState(**v) for k, v in raw_slots.items()},
            episodes={int(k): HoldingEpisode(**v)
                      for k, v in (d.get("episodes") or {}).items()},
            # No fallback to the old `ticker_cooldowns` key, deliberately. Its
            # values were TICKERS, and reading them as security ids would
            # silently apply a cooldown to nothing while the real security stayed
            # buyable — a wrong answer dressed as compatibility. Wealth Core has
            # never run in production (it is inert until a config selects it and
            # live activation is blocked), so no such blob exists; if one ever
            # does, it must be migrated deliberately rather than reinterpreted.
            security_cooldowns=dict(d.get("security_cooldowns") or {}),
            cash=cash,
            initialized=initialized,
            session_index=session_index,
            unresolved_terminals=dict(d.get("unresolved_terminals") or {}),
            # Absent means zero — a blob written before the settlement waterfall
            # existed carries no pending grace, which is the correct reading:
            # nothing was being carried.
            sessions_since_valid_mark=dict(
                d.get("sessions_since_valid_mark") or {}),
            terminal_pending_sessions=dict(
                d.get("terminal_pending_sessions") or {}),
            terminal_pending_terms=deepcopy(dict(
                d.get("terminal_pending_terms") or {})),
            # Absent for the same reason as above, and additionally for every
            # blob written before the audit existed. An empty audit is the
            # correct reading of a run that never recorded one.
            terminal_carry_audit=deepcopy(dict(
                d.get("terminal_carry_audit") or {})),
            last_valid_mark_session=dict(d.get("last_valid_mark_session") or {}),
        )

    def hash_payload(self) -> dict[str, Any]:
        """`to_dict()` minus the audit-only keys: what a REPORT or a HASH sees.

        Separate from `to_dict` because the two have genuinely different jobs.
        `to_dict` is the PERSISTENCE format and must carry everything a restart
        needs, including a grace period's carry provenance. This is the
        OBSERVABLE state, and it must stay stable when observability is added —
        otherwise every consumer of a state blob inherits the audit's churn.

        Used by `state_hash` and by `RunResult.to_dict()`'s `final_state`. That
        second caller matters more than it looks: `final_state` is inside the
        `final_result` hash, so without this the audit's own bookkeeping —
        `last_valid_mark_session` carries one entry per HELD security, terminal
        or not — would be pinned into the certified artefact, widening what the
        re-pin covers from "the terminal audit" to "mark bookkeeping for the
        whole book".
        """
        return {k: v for k, v in self.to_dict().items()
                if k not in _AUDIT_ONLY_STATE_KEYS}

    def state_hash(self) -> str:
        """Stable across processes and dict orderings.

        sort_keys is what makes it stable; without it the hash would depend on
        insertion order and a replay in a fresh process could differ from the
        original while representing identical state.

        AUDIT-ONLY KEYS ARE EXCLUDED. `to_dict` serves two masters — persistence
        and hashing — and they want different things from it: a restart must
        recover the terminal audit, while a parity hash must not move when
        observability is added. Excluding them here is what keeps the terminal
        re-pin to ONE hash movement (`final_result`) instead of also dragging
        `daily_state` and `final_state` along with it.

        This is only sound because those keys are DERIVED. Everything in them is
        recomputable from state and inputs that ARE hashed, so no divergence can
        hide here that does not also show up in an earlier hash — and the hash
        order exists precisely so the earliest mismatch names the layer at fault.
        """
        from stock_strategy_shared.wealth_core.hashes import quantize
        blob = json.dumps(quantize(self.hash_payload()), sort_keys=True,
                          separators=(",", ":"), default=str)
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
