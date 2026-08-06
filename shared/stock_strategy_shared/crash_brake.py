"""Market-wide crash brake — pure state detection.

WHAT IT IS FOR. The trailing stop retires a holding whose own trend has broken.
It is useless against the drawdown that actually hurts a concentrated momentum
book: twenty-five correlated positions all falling together, none of them yet
30% off its own peak. By the time individual stops fire, the damage is done. So
the brake acts on the BOOK, not on names — it cuts gross exposure and leaves
composition alone.

WHAT IT IS NOT. Not a forecast, and not a market-timing overlay. It is a rare,
coarse, two-condition switch that is off almost all of the time. Both conditions
must hold, which is the point: a sharp index drop alone is routinely a handful of
mega-caps, and weak breadth alone is a normal feature of a narrow bull market.
Requiring both is what keeps it rare.

    market_return <= threshold      (broad index, trailing window)
    AND breadth   <  threshold      (share of eligible names above their SMA)

THE HONEST CAVEAT, recorded here because it governs how the output should be
read: the evidence that motivated this rule came from a 2014-2018 panel whose
only stress events were August 2015 and February 2018. That period contains no
GFC, no COVID, no 2022. A crash brake calibrated on a sample with no crash is the
weakest kind of fitted parameter, and it is also the change with the largest
claimed effect. Validate against the named stress regimes before believing it.

Pure: no DB, no env, no clock. Both live and the wind tunnel import THIS.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence


@dataclass(frozen=True)
class CrashState:
    """Why the brake is (or is not) engaged. Every input is reported, because a
    risk control that says only 'engaged' cannot be argued with afterwards."""
    engaged: bool
    market_return: float | None
    breadth: float | None
    n_breadth_names: int
    reason: str
    # Was there enough data to reach a verdict AT ALL? `engaged=False` answers
    # two different questions and used to conflate them: "the evidence says no
    # crash" and "there is no evidence". The first is a reason to carry normal
    # exposure; the second is a reason to carry WHATEVER YOU ALREADY HAD.
    #
    # Conflating them made this control fail OPEN. The module reasoned correctly
    # about the engage direction — "a brake that trips on missing data would
    # de-risk the book every time the benchmark hiccups" — and never re-examined
    # the same state for the RESTORE direction, where the identical value means
    # "re-risk the book on missing data". With the brake engaged at 50% and one
    # session of thin breadth, the delta step emitted risk_restore buys across
    # every position while the reason string still read "holding exposure".
    evaluable: bool = True

    @property
    def equity_exposure_key(self) -> str:
        if not self.evaluable:
            return "unknown"
        return "stressed" if self.engaged else "normal"


def market_window_return(closes: Sequence[float], window: int) -> float | None:
    """Trailing return of the benchmark over `window` sessions.

    None when the history is too short — and the caller must treat that as "do
    not engage". An unknown market move is not evidence of a crash, and a brake
    that trips on missing data would de-risk the book every time the benchmark
    feed hiccups.
    """
    if window <= 0 or closes is None or len(closes) < window + 1:
        return None
    a, b = closes[-(window + 1)], closes[-1]
    try:
        a, b = float(a), float(b)
    except (TypeError, ValueError):
        return None
    if not (a > 0) or not (b > 0):        # NaN-safe
        return None
    return b / a - 1.0


def breadth_above_sma(closes_by_ticker: Mapping[str, Sequence[float]],
                      sma_sessions: int,
                      min_names: int = 50) -> tuple[float | None, int]:
    """Share of names trading above their own `sma_sessions` moving average.

    Returns (share, n_evaluated). A name without enough history is EXCLUDED from
    both numerator and denominator rather than counted as below — counting it as
    below would make breadth collapse whenever the universe refreshes, which is
    an ingestion event, not a market event.

    `min_names` guards the other direction: a breadth reading over a handful of
    survivors is noise, and acting on it would be worse than not acting. Below
    the floor the share is returned as None, which the caller treats as "cannot
    evaluate" — the same fail-safe as an unknown market return.
    """
    above = 0
    n = 0
    for _t, closes in (closes_by_ticker or {}).items():
        if closes is None or len(closes) < sma_sessions:
            continue
        window = closes[-sma_sessions:]
        try:
            vals = [float(c) for c in window]
            last = float(closes[-1])
        except (TypeError, ValueError):
            continue
        if any(v != v for v in vals) or last != last:   # NaN
            continue
        sma = sum(vals) / len(vals)
        if not (sma > 0):
            continue
        n += 1
        if last > sma:
            above += 1
    if n < max(1, min_names):
        return None, n
    return above / n, n


def evaluate_crash_state(
    *,
    benchmark_closes: Sequence[float],
    closes_by_ticker: Mapping[str, Sequence[float]],
    market_return_window_sessions: int,
    market_return_threshold: float,
    breadth_sma_sessions: int,
    breadth_threshold: float,
    min_breadth_names: int = 50,
    enabled: bool = True,
) -> CrashState:
    """Both conditions, or nothing.

    FAIL-SAFE ON MISSING DATA. If either input cannot be computed the brake stays
    DISENGAGED and says so. That is the opposite of the falling-knife veto's
    fail-closed stance, and the asymmetry is deliberate: refusing to buy on
    missing data costs an opportunity, whereas selling half the book on missing
    data is an unforced, self-inflicted loss.
    """
    if not enabled:
        return CrashState(False, None, None, 0, "crash_brake disabled")

    mret = market_window_return(benchmark_closes, market_return_window_sessions)
    breadth, n = breadth_above_sma(closes_by_ticker, breadth_sma_sessions,
                                   min_names=min_breadth_names)

    if mret is None:
        return CrashState(False, None, breadth, n,
                          "benchmark history too short — cannot evaluate, "
                          "holding exposure", evaluable=False)
    if breadth is None:
        return CrashState(False, mret, None, n,
                          f"breadth unavailable ({n} names with enough history, "
                          f"need {min_breadth_names}) — holding exposure",
                          evaluable=False)

    market_bad = mret <= market_return_threshold
    breadth_bad = breadth < breadth_threshold
    if market_bad and breadth_bad:
        return CrashState(
            True, mret, breadth, n,
            f"market {mret:+.1%} <= {market_return_threshold:+.1%} AND breadth "
            f"{breadth:.0%} < {breadth_threshold:.0%} ({n} names)")
    why = []
    if not market_bad:
        why.append(f"market {mret:+.1%} above {market_return_threshold:+.1%}")
    if not breadth_bad:
        why.append(f"breadth {breadth:.0%} above {breadth_threshold:.0%}")
    return CrashState(False, mret, breadth, n, "; ".join(why))


def target_exposure(state: CrashState, normal: float, stressed: float,
                    *, prior: float) -> float:
    """Gross equity exposure the book should carry. Composition is untouched —
    this scales every position by the same factor, which is what makes it a risk
    overlay rather than a second, hidden selection rule.

    `prior` is the exposure the book is ALREADY carrying, and it is mandatory —
    keyword-only, no default — on purpose. An unevaluable state returns it
    unchanged, so an unknown signal can never move the book in either direction.
    Giving it a default would let a call site keep the old fail-open behaviour by
    saying nothing, and saying nothing is exactly how the defect survived: the
    caller acted on the returned number while the state's own reason string said
    "holding exposure".
    """
    if not state.evaluable:
        return prior
    return stressed if state.engaged else normal


def scale_weights(weights: Mapping[str, float], exposure: float) -> dict[str, float]:
    """Apply the exposure scalar, preserving RELATIVE weights exactly.

    Relative weights are preserved on the way down and on the way back up, so
    restoring exposure cannot quietly re-rank the book: a position that was 6% of
    a 100%-invested book is 3% at 50% exposure and 6% again on restore, never
    'whatever the current target says'. Re-deriving weights on restore would make
    the brake a rebalancing trigger, which is the rotation the stop-only policy
    exists to avoid.
    """
    if exposure is None or exposure < 0:
        return dict(weights)
    return {t: w * exposure for t, w in (weights or {}).items()}


# ── turning an exposure change into intents ──────────────────────────────────

def plan_exposure_moves(actual_weights: Mapping[str, float],
                        exposure: float,
                        *, prev_exposure: float = 1.0,
                        min_move_weight: float = 0.002) -> list[dict]:
    """Per-position moves that take the book from `prev_exposure` to `exposure`.

    Returns [{ticker, action, current_weight, target_weight, delta}] where action
    is 'risk_reduce' (sell) or 'risk_restore' (buy). Empty when the exposure is
    unchanged — the brake must be silent on the ~99% of days it is disengaged.

    RELATIVE WEIGHTS ARE PRESERVED. Every position moves by the same FACTOR, so
    restoring cannot re-rank the book: a name that was 6% of a fully-invested book
    is 3% at half exposure and 6% again on restore, never "whatever today's target
    says". Re-deriving from the target would make the brake a rebalancing trigger,
    which is the rotation a stop-only policy exists to avoid.

    `min_move_weight` drops moves too small to be worth a commission — a 0.1%
    nudge across 25 names is 25 orders of pure cost.
    """
    if not actual_weights or exposure is None or prev_exposure is None:
        return []
    if prev_exposure <= 0 or abs(exposure - prev_exposure) < 1e-9:
        return []
    scale = exposure / prev_exposure
    action = "risk_reduce" if scale < 1.0 else "risk_restore"
    out = []
    for t, w in sorted(actual_weights.items()):
        try:
            cur = float(w)
        except (TypeError, ValueError):
            continue
        if not (cur > 0):
            continue
        tgt = cur * scale
        if abs(tgt - cur) < min_move_weight:
            continue
        out.append({"ticker": t, "action": action,
                    "current_weight": round(cur, 6),
                    "target_weight": round(tgt, 6),
                    "delta": round(tgt - cur, 6)})
    return out


# ── the transition record ───────────────────────────────────────────────────
# WHY THIS EXISTS. The only parity check on this control asserted that the live
# pipeline SOURCE CONTAINS a call to `evaluate_crash_state`. Presence is not
# equivalence, and presence is exactly what let the fail-open restore defect stay
# green: both engines called the shared evaluator, both got `engaged=False`, and
# they disagreed about nothing the test could see — while the live caller turned
# that state into a full re-risk of the book.
#
# So parity compares a SERIALISED RECORD of the transition rather than its
# outcome. The decisive property is that semantic divergence becomes visible even
# when the resulting exposure happens to MATCH: two engines that arrive at the
# same number by different reasoning are not in parity, they are one input away
# from disagreeing, and an exposure-only comparison cannot tell.
#
# Each predicate is recorded SEPARATELY rather than only their conjunction. Two
# engines can agree on "engaged" while disagreeing about which condition carried
# it, and that disagreement is a real defect a single boolean hides.

TRANSITION_RECORD_VERSION = 1


def transition_record(state: CrashState, *, prior: float, target: float,
                      market_return_threshold: float,
                      breadth_threshold: float,
                      min_breadth_names: int,
                      inputs_available_at: str | None = None) -> dict:
    """Canonical, ordered, hashable record of one crash-brake evaluation.

    Emitted by EVERY engine that evaluates the brake — the live pipeline, the
    wind tunnel, the backtester — so the three can be compared field by field
    rather than by their final exposure.

    `inputs_available_at` carries the as-of stamp of the data the decision read.
    It is optional only because the legacy brake does not yet track it; the
    defensive controller does, and recording the field now means adding it later
    is not a schema change to a hash everyone has already pinned.
    """
    # Rounded before serialisation, deliberately. An unrounded float makes the
    # record depend on the interpreter's repr rather than on the decision — the
    # exact defect that made several Wealth Core hashes interpreter-dependent.
    def _q(x):
        return None if x is None else round(float(x), 10)

    return {
        "version": TRANSITION_RECORD_VERSION,
        "evaluable": bool(state.evaluable),
        "engaged": bool(state.engaged),
        "exposure_key": state.equity_exposure_key,
        # Each predicate on its own. None when the input was unavailable, which
        # is DIFFERENT from False and must not serialise the same way.
        "predicate_market_bad": (
            None if state.market_return is None
            else bool(state.market_return <= market_return_threshold)),
        "predicate_breadth_bad": (
            None if state.breadth is None
            else bool(state.breadth < breadth_threshold)),
        "market_return": _q(state.market_return),
        "breadth": _q(state.breadth),
        "n_breadth_names": int(state.n_breadth_names),
        "market_return_threshold": _q(market_return_threshold),
        "breadth_threshold": _q(breadth_threshold),
        "min_breadth_names": int(min_breadth_names),
        "prior_exposure": _q(prior),
        "target_exposure": _q(target),
        # The action the record implies, so a reader does not re-derive it — and
        # so a disagreement about the DIRECTION shows up as a field rather than
        # as an argument about two exposure numbers.
        "implied_action": (
            "none" if target is None or prior is None or abs(target - prior) < 1e-9
            else "risk_reduce" if target < prior else "risk_restore"),
        "inputs_available_at": inputs_available_at,
        "reason": state.reason,
    }


def transition_hash(record: Mapping) -> str:
    """Stable hash of a transition record, for cross-engine comparison.

    `reason` is EXCLUDED. It is prose meant for humans and it names thresholds
    inside formatted strings, so hashing it would make a wording change look like
    a behavioural divergence — which trains people to re-pin the hash, which is
    how a real divergence gets waved through.
    """
    import hashlib
    import json
    payload = {k: v for k, v in dict(record).items() if k != "reason"}
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      default=str)
    return hashlib.sha256(blob.encode()).hexdigest()
