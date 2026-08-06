"""One net intent per (account, ticker) — reconciled, not merely constrained.

THE DEFECT THIS CLOSES. Controls that propose trades are layered: the delta
engine decides per-name membership, and the crash brake then appends book-level
exposure moves WITHOUT removing the base decision. `delta_intents` has no unique
`(run_id, ticker)`, so one ticker can carry `exit` AND `risk_reduce` in a single
run. Whichever row a downstream reader happened to pick up was the instruction
that executed.

WHY A UNIQUE INDEX IS THE WRONG FIX, and this module exists instead. Constraining
`delta_intents` would convert conflicting logic into an INSERTION FAILURE — the
conflict would surface as a crash at the moment the brake first engages, which is
precisely the moment nothing may fail, and the operator would learn that two
controls disagreed without learning what either of them wanted. Uniqueness is not
reconciliation. So:

    proposals    APPEND-ONLY. Every contributing proposal survives, including the
                 ones reconciliation discarded. Diagnostics are not the thing to
                 sacrifice for the invariant.
    net intent   ONE final economic instruction per (run_id, account_id, ticker).
                 The unique index lives on THAT table.
    provenance   every contributing proposal, and the rule that resolved them,
                 stored with the net intent — so "why did this ticker get this
                 instruction?" has an answer rather than an absence.

THE COMPOSITION RULE: risk reduction dominates, and among same-direction
proposals the most conservative one wins. This is the same `min()` composition
settled for the defensive controller (defense plan §6 decision 2), for the same
reason: conservative composition is the only rule immune to a disagreement
between two independent controls. A control that wanted to sell and a control
that wanted to buy do not average into a defensible instruction; the selling one
is the one whose failure mode is survivable.

    1  any SELL-side proposal wins over any buy-side or neutral one
       within sell-side: `exit` dominates (a full liquidation is the maximal
       reduction and subsumes every partial), otherwise the LOWEST resulting
       target weight
    2  no sell-side, buys present: the LOWEST target weight — the smallest buy
       both controls can be said to permit
    3  neutral only: at_risk > hold > watch. at_risk outranks hold because it
       carries state (a countdown), and losing that would erase the reason the
       position is still held.

Ties break on `seq` — the order the proposal was made within the run — so the
result is deterministic and does not depend on dict or row ordering.

NEUTRAL PROPOSALS NEVER SUPPRESS AN EXECUTABLE ONE. `hold` is the delta engine
saying "nothing to do from where I sit", not a veto over a control that has
something to do. Reading it as a veto would let the engine's silence disarm the
brake.

ACCOUNT SCOPE — read this before adding a second broker account. The schema and
this module are ACCOUNT-AWARE: the unique invariant is on
`(run_id, account_id, ticker)` and every function keys on the pair. The
IMPLEMENTATION is SINGLE-ACCOUNT: the deploy runs one broker account, nothing
supplies an account id, and every proposal therefore carries
`DEFAULT_ACCOUNT_ID`. That is a correct description of today, not a stub —
but it means the account dimension is UNEXERCISED, and unexercised dimensions
are where the first multi-account run finds its bugs. Before multi-account
support, or before any executor cutover that introduces account-specific reads,
proposal construction in the delta step must pass a real account id and every
caller of `compare_to_rows` must pass the account it is comparing.

Pure: no DB, no env, no clock. Live, the wind tunnel and the backtester import
THIS, so a divergence between them is a code difference rather than two rules
that drifted.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional, Sequence

#: The one broker account this deploy runs. See "ACCOUNT SCOPE" above: the
#: schema and this module are account-aware, the implementation is not yet.
DEFAULT_ACCOUNT_ID = "default"

# ── the action vocabulary, partitioned by economic direction ─────────────────
SELL_SIDE: frozenset[str] = frozenset({"exit", "risk_reduce", "sell_trim"})
BUY_SIDE: frozenset[str] = frozenset({"entry", "buy_add", "risk_restore"})
NEUTRAL: frozenset[str] = frozenset({"hold", "watch", "at_risk"})

#: Most-informative first. `at_risk` beats `hold` because it carries a countdown.
NEUTRAL_PRECEDENCE: tuple[str, ...] = ("at_risk", "hold", "watch")

#: Every action this module knows how to place. An action outside this set is a
#: programming error rather than a data condition — see `reconcile`.
KNOWN_ACTIONS: frozenset[str] = SELL_SIDE | BUY_SIDE | NEUTRAL

# ── rule names, recorded on every net intent as provenance ───────────────────
RULE_SOLE = "sole_proposal"
RULE_EXIT_DOMINATES = "sell_dominates:exit"
RULE_SELL_MIN_WEIGHT = "sell_dominates:min_weight"
RULE_BUY_MIN_WEIGHT = "buy_min_weight"
RULE_NEUTRAL_PRECEDENCE = "neutral_precedence"


@dataclass(frozen=True)
class Proposal:
    """One control's instruction for one ticker, before reconciliation.

    `source` names the control that proposed it ('delta_engine', 'crash_brake',
    …) and is what makes the provenance readable after the fact. `seq` is the
    order the proposal was made within the run and exists solely to break ties
    deterministically.
    """
    ticker: str
    action: str
    source: str
    seq: int
    target_weight: Optional[float] = None
    rank: Optional[int] = None
    composite_score: Optional[float] = None
    confirmation_days_met: Optional[int] = None
    actual_weight: Optional[float] = None
    weight_drift: Optional[float] = None
    reason: str = ""
    account_id: str = DEFAULT_ACCOUNT_ID


@dataclass(frozen=True)
class NetIntent:
    """The single executable instruction for one (account_id, ticker).

    `winner` is the proposal that carried it; `contributing` is EVERY proposal
    for that key including the discarded ones, in `seq` order. `resolved_by`
    names the rule. Together those three answer the reviewer's question without
    requiring them to re-derive the rule from the code.
    """
    account_id: str
    ticker: str
    action: str
    winner: Proposal
    resolved_by: str
    contributing: tuple[Proposal, ...] = field(default=())

    @property
    def conflicted(self) -> bool:
        """True when more than one control proposed something for this key.

        Not the same as "more than one row": a single control proposing twice is
        also a conflict worth seeing.
        """
        return len(self.contributing) > 1

    @property
    def discarded(self) -> tuple[Proposal, ...]:
        return tuple(p for p in self.contributing if p is not self.winner)


def _weight_key(p: Proposal) -> tuple[int, float, int]:
    """Sort key selecting the most conservative proposal: lowest target weight.

    An UNKNOWN weight never wins over a known one. A proposal that cannot say how
    much exposure it wants has not demonstrated it is the conservative choice,
    and treating None as 0.0 would let a missing field silently outrank a real
    instruction to buy.
    """
    w = p.target_weight
    return (1 if w is None else 0, float(w) if w is not None else 0.0, p.seq)


def _resolve(key_proposals: Sequence[Proposal]) -> tuple[Proposal, str]:
    """Pick the winner for ONE (account_id, ticker), and name the rule."""
    if len(key_proposals) == 1:
        return key_proposals[0], RULE_SOLE

    sells = [p for p in key_proposals if p.action in SELL_SIDE]
    if sells:
        exits = [p for p in sells if p.action == "exit"]
        if exits:
            # A full liquidation subsumes every partial reduction. No weight
            # comparison is meaningful here — an exit has no residual weight.
            return min(exits, key=lambda p: p.seq), RULE_EXIT_DOMINATES
        return min(sells, key=_weight_key), RULE_SELL_MIN_WEIGHT

    buys = [p for p in key_proposals if p.action in BUY_SIDE]
    if buys:
        return min(buys, key=_weight_key), RULE_BUY_MIN_WEIGHT

    ranked = sorted(
        key_proposals,
        key=lambda p: (NEUTRAL_PRECEDENCE.index(p.action), p.seq),
    )
    return ranked[0], RULE_NEUTRAL_PRECEDENCE


def reconcile(proposals: Iterable[Proposal]) -> list[NetIntent]:
    """Collapse proposals into ONE net intent per (account_id, ticker).

    Raises ValueError on an unknown action. That is deliberate: a new action
    token reaching this function means someone added a control without deciding
    where it sits in the composition order, and guessing on their behalf is how a
    risk-reducing instruction gets silently outranked by a buy. Loud here beats
    wrong at the broker.

    Ordering of the result is (account_id, ticker) so two engines given the same
    proposals emit byte-identical output.
    """
    by_key: dict[tuple[str, str], list[Proposal]] = {}
    for p in proposals:
        if p.action not in KNOWN_ACTIONS:
            raise ValueError(
                f"intent reconciliation: unknown action {p.action!r} for "
                f"{p.ticker} from {p.source!r}; classify it in SELL_SIDE / "
                f"BUY_SIDE / NEUTRAL before proposing it"
            )
        by_key.setdefault((p.account_id, p.ticker), []).append(p)

    out: list[NetIntent] = []
    for (account_id, ticker) in sorted(by_key):
        group = sorted(by_key[(account_id, ticker)], key=lambda p: p.seq)
        winner, rule = _resolve(group)
        out.append(
            NetIntent(
                account_id=account_id,
                ticker=ticker,
                action=winner.action,
                winner=winner,
                resolved_by=rule,
                contributing=tuple(group),
            )
        )
    return out


def provenance_json(net: NetIntent) -> dict:
    """The provenance blob persisted alongside a net intent.

    Every contributing proposal, flagged with whether it won. Kept small and
    flat: this is read by a human asking why, not joined on.
    """
    return {
        "resolved_by": net.resolved_by,
        "conflicted": net.conflicted,
        "contributing": [
            {
                "source": p.source,
                "action": p.action,
                "seq": p.seq,
                "target_weight": p.target_weight,
                "reason": p.reason[:200] if p.reason else "",
                "won": p is net.winner,
            }
            for p in net.contributing
        ],
    }


def compare_to_rows(
    rows: Iterable[tuple[str, str]],
    nets: Sequence[NetIntent],
    *,
    account_id: str = DEFAULT_ACCOUNT_ID,
) -> dict:
    """Shadow-comparison report: legacy `delta_intents` rows vs reconciled nets.

    `rows` is (ticker, action) as persisted today. Returns the divergence summary
    the delta step logs while the executor still reads the legacy table — so the
    reconciliation is observed under real traffic before anything depends on it.

    `conflicts` is the population this defect is about: tickers the legacy table
    carries more than once, with no rule deciding which one executes.

    KEYED ON (account_id, ticker), NOT ticker. `delta_intents` has no account
    column, so every legacy row belongs to ONE account and the caller names it —
    but the nets do not, and indexing them by ticker alone would let one
    account's intent overwrite another's the first time a second account exists.
    The comparator would then silently report agreement between rows and a net
    intent belonging to a different book. Nets for other accounts are counted
    rather than dropped, so the mismatch is visible instead of invisible.
    """
    legacy: dict[str, list[str]] = {}
    for ticker, action in rows:
        legacy.setdefault(ticker, []).append(action)

    net_by_key = {(n.account_id, n.ticker): n for n in nets}
    other_accounts = sorted({n.account_id for n in nets if n.account_id != account_id})
    conflicts, changed, missing = [], [], []

    for ticker, actions in sorted(legacy.items()):
        net = net_by_key.get((account_id, ticker))
        if net is None:
            missing.append(ticker)
            continue
        if len(actions) > 1:
            conflicts.append({
                "ticker": ticker,
                "legacy_actions": sorted(actions),
                "net_action": net.action,
                "resolved_by": net.resolved_by,
            })
        elif actions[0] != net.action:
            changed.append({
                "ticker": ticker,
                "legacy_action": actions[0],
                "net_action": net.action,
                "resolved_by": net.resolved_by,
            })

    return {
        "account_id": account_id,
        "legacy_rows": sum(len(a) for a in legacy.values()),
        "legacy_tickers": len(legacy),
        "net_intents": len(nets),
        # Nets belonging to a book the legacy rows cannot describe. Zero today
        # (single-account deploy); non-zero means the comparison is only partial
        # and must not be read as agreement.
        "net_intents_other_accounts": sum(
            1 for n in nets if n.account_id != account_id),
        "other_accounts": other_accounts,
        "conflicts": conflicts,
        "changed": changed,
        "missing_from_net": missing,
        "agrees": (not conflicts and not changed and not missing
                   and not other_accounts),
    }
