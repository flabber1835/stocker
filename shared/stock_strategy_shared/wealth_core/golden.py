"""Wealth Core v1 — the SHARED golden scenario. PURE, deterministic, no I/O.

This is the cross-engine parity artefact. The backtester, the wind tunnel and
the live book each obtain `VendorBar`s from a different place; this module
constructs one such stream in code, so all three can run the SAME input through
their own wiring and compare `RunResult.result_hash()`. A fixture stored as data
could only prove that one engine is self-consistent — the scenario has to be
executable by every engine to prove they agree.

It is generated rather than stored for a second reason: the required coverage is
eleven distinct conditions over a universe large enough for the leadership
cutoff to bind, which is ~24,000 bars. As data that is an unreviewable blob; as
code the interesting sessions are named and legible, and only the expected HASH
is pinned.

DETERMINISM. No `random`, no `Date`, no floating-point accumulation across
securities. Prices come from an explicit integer LCG rendered to a fixed number
of decimal places, so the stream is identical on every platform and every Python
version — a fixture whose values drift with the interpreter would fail parity
for reasons that have nothing to do with the strategy.

THE ELEVEN CONDITIONS, and the session each one lands on:

    insufficient history         SHORT lists at S150, never has 127 closes
    duplicate issuer             DUALA / DUALB share relatedtickers throughout
    split                        SPLITTER 2:1 at S150
    dividend ex-date + settle    PAYER $0.50 at S155
    non-tradeable session        HALTED prints but cannot fill, S167-S178
    missing mark                 GHOST has no bar at all on S170
    unresolved terminal          MERGED goes unresolved at S175
    terminal resolution          MERGED settles for $54 cash at S180
    write-off                    BUST confirmed worthless at S185
    trailing stop                STOPOUT crashes at S145, HALTED at S166
    one-time review, passed      the early entries reach age 119 around S245
    one-time review, exit        FADER is underwater and unqualified at review
    pending EXIT across restart  HALTED stops out at S166 and cannot fill until
                                 S179, so its exit order straddles the boundary
    pending ENTRY across restart STOPOUT's slot leaves cooldown at S167 and the
                                 replacement (a filler) is untradeable to S175

THE RESTART BOUNDARY IS S170 BECAUSE THAT IS THE HARD CASE, not a round number:
one entry and one exit are both queued there, GHOST's mark is missing so
admissions are blocked, and a slot sits RESERVED by an unfilled order. A restart
that loses any one of those three facts produces a different run, and an earlier
version of this engine lost the third — the reserved slot read as free after a
restart and the vacancy was handed to a second candidate.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from stock_strategy_shared.wealth_core.feed import SecurityMeta, VendorBar
from stock_strategy_shared.wealth_core.terminal import TerminalKind, TerminalTerms

N_SESSIONS = 260                      # long enough for age-119 reviews to fire
N_FILLER = 110
STARTING_CASH = 1_000_000.0
RESTART_AT = 170                      # index into SESSIONS, mid-queue on purpose

COMMON = "Domestic Common Stock"

SESSIONS: list[str] = [f"S{i:03d}" for i in range(N_SESSIONS)]


# ── deterministic prices ────────────────────────────────────────────────────

def _lcg(seed: int) -> int:
    """Numerical Recipes' constants. An explicit integer generator rather than
    `random`, so the stream cannot shift with a Python release."""
    return (1664525 * seed + 1013904223) % (2 ** 32)


def _wiggle(security_index: int, t: int) -> float:
    """A reproducible +/-2% jitter. Two arguments in, one number out, no state —
    so a scenario can be built session-by-session or all at once and get the
    same prices either way."""
    s = _lcg(_lcg(security_index * 7919 + 104_729) + t * 6151)
    return ((s % 4001) - 2000) / 100_000.0


def _price(security_index: int, t: int, base: float, drift: float) -> float:
    """Rounded to the cent at the point of construction, never later.

    Rounding here rather than at comparison time is what keeps the split
    reconstruction exact: a raw close of 61.115 halved by a 2:1 split is a
    price no exchange ever printed, and carrying it would put the fixture's
    signal series a fraction away from any engine that rounds on read.
    """
    return round(base * (1.0 + drift * t / N_SESSIONS) * (1.0 + _wiggle(security_index, t)), 2)


def _volume(security_index: int, t: int) -> float:
    """Comfortably above both liquidity floors for every security, so the
    fixture tests the conditions it is about and not incidental ADV churn."""
    return 400_000.0 + (_lcg(security_index * 31 + t) % 100_000)


@dataclass(frozen=True)
class _Spec:
    security_id: str
    ticker: str
    index: int
    base: float
    drift: float
    first_t: int = 0
    category: str = COMMON
    permaticker: str | None = None
    related: tuple[str, ...] = ()


def _specs() -> list[_Spec]:
    """The named securities first, then filler.

    Filler drift rises with index so the momentum ranking is a total order with
    no ties — the leadership cutoff at exactly 25 of 119 then bites on a
    well-defined boundary rather than on a tie-break, which is a separate
    property with its own test.
    """
    named = [
        # Strong drift: these are meant to reach the leadership set, and they
        # are admitted first, so every scripted event below lands on a HOLDING.
        _Spec("SEC_DUAL_A", "DUALA", 900, 40.0, 1.40, permaticker="P900",
              related=("DUALB",)),
        _Spec("SEC_DUAL_B", "DUALB", 901, 55.0, 1.38, permaticker="P900",
              related=("DUALA",)),
        _Spec("SEC_SPLITTER", "SPLIT", 902, 60.0, 1.45, permaticker="P902"),
        _Spec("SEC_PAYER", "PAYER", 903, 70.0, 1.42, permaticker="P903"),
        _Spec("SEC_HALTED", "HALT", 904, 30.0, 1.44, permaticker="P904"),
        _Spec("SEC_MERGED", "MERG", 905, 45.0, 1.43, permaticker="P905"),
        _Spec("SEC_BUST", "BUST", 906, 25.0, 1.41, permaticker="P906"),
        _Spec("SEC_GHOST", "GHOST", 907, 35.0, 1.39, permaticker="P907"),
        _Spec("SEC_STOPOUT", "STOP", 909, 50.0, 1.46, permaticker="P909"),
        _Spec("SEC_FADER", "FADE", 910, 65.0, 1.37, permaticker="P910"),
        # Terminal paths beyond cash and worthlessness. CONVERTED is taken over
        # for stock at a ratio that leaves a FRACTION (so cash-in-lieu is
        # exercised, not merely available); MIXED is cash-plus-stock; STRANDED
        # has a deal announced with terms nobody supplied, and must BLOCK.
        _Spec("SEC_CONVERTED", "CONV", 911, 48.0, 1.435, permaticker="P911"),
        _Spec("SEC_MIXED", "MIX", 912, 52.0, 1.425, permaticker="P912"),
        _Spec("SEC_STRANDED", "STRD", 913, 44.0, 1.415, permaticker="P913"),
        # The security DELIVERED by the conversion. It must exist in the corpus
        # from the start or the converted episode would have no closes and the
        # trailing stop would go blind on a position the book still owns.
        _Spec("SEC_ACQUIRER", "ACQR", 914, 90.0, 0.60, permaticker="P914"),
        # Listed late: fewer than 127 closes for the whole run.
        _Spec("SEC_SHORT", "SHORT", 908, 80.0, 2.00, first_t=150, permaticker="P908"),
    ]
    filler = [_Spec(f"SEC_F{i:03d}", f"F{i:03d}", i, 20.0 + (i % 40),
                    0.05 + i * 0.008, permaticker=f"P{i:03d}")
              for i in range(N_FILLER)]
    return named + filler


SPECS: list[_Spec] = _specs()


# ── the scripted events ─────────────────────────────────────────────────────
# Session INDICES, named once. Every one is referenced by the assertions in
# tests/wealth_core/test_golden_fixture.py, so a schedule change that stops
# exercising a condition fails a test rather than quietly reducing coverage.

STOPOUT_CRASH_FROM = 145      # -40%: trailing stop fires at this close
SPLIT_SESSION = 150
DIVIDEND_SESSION = 155
HALTED_CRASH_FROM = 166       # stop fires here, but the security then halts
HALTED_UNTRADEABLE = range(167, 179)
# The entry that straddles S170. It ends at S175 so the fill lands on S176,
# which is where the close-to-open gap bites and where the restart matrix's
# `entry_opening_gap_reduced_quantity` cut at 177 expects a short fill.
REPLACEMENT_UNTRADEABLE = range(167, 176)
GHOST_MISSING_SESSION = 170
UNRESOLVED_FROM = 175
MERGER_SESSION = 180
BUST_UNRESOLVED_FROM = 182
WRITE_OFF_SESSION = 185
FADER_DECLINE_FROM = 135      # slow enough to stay ABOVE the stop, see below
CONVERSION_SESSION = 190      # security-for-security, with a fractional stub
MIXED_SESSION = 195           # cash-plus-stock
STRANDED_ANNOUNCED = 200      # terms UNKNOWN: must block, not approximate
STRANDED_RESOLVED = 210       # ...and the block must LIFT once supplied
# The ratios are ECONOMICALLY COHERENT with the two price paths at the
# conversion sessions, not round numbers. A real stock-for-stock ratio is set so
# that ratio x acquirer_price ~ target_price, and the peak rescale in
# terminal.py depends on exactly that relationship.
#
# The first cut used 0.37, which handed target holders about half their market
# value. The rescaled peak then sat far above anything the acquirer traded at
# and BOTH converted positions stopped out on the next session — which is the
# correct response to a deal that destroys half the position's value, and
# useless as a test of conversion. Both are also deliberately non-round so the
# entitlement leaves a FRACTION and the cash-in-lieu leg is genuinely exercised
# rather than merely available.
CONVERSION_RATIO = 0.757
MIXED_RATIO = 0.687

# The security whose entry straddles the restart boundary.
#
# WHICH security this is is an OUTPUT of the strategy, not a free choice: it is
# whichever one the ranking actually admits into the slot STOPOUT vacates when
# that slot leaves cooldown. Naming the wrong one costs nothing visible — the
# untradeable window lands on a security nobody was buying, the entry fills on
# time, and the fixture quietly stops covering the case. It is asserted in
# test_the_boundary_really_is_mid_flight.
#
# It WAS a filler (SEC_F094), on the reasoning that "by S166 every named
# security is held". The initial-construction fix invalidated that: the opening
# now fills all 25 slots at S126/S127 instead of drip-feeding, so F094 is bought
# in the opening and the S166 vacancy goes to the best candidate that is NOT yet
# held. That is SEC_BUST, and for a mechanical reason worth recording, because
# it is not "BUST got luckier":
#
#   * BUST's drift (1.41) puts it among the strong named securities on momentum,
#     but its base price (25.0) x ~450k shares is ~$11M of daily dollar volume —
#     BELOW the $20M ADV20 floor. It is therefore INELIGIBLE at S126 and absent
#     from the 25-name leadership population entirely, which is why the opening
#     never considers it.
#   * By S166 its drift has carried the price past ~$45, ADV20 clears, and it
#     enters the leadership set — into the room STOPOUT left when its -40% crash
#     at S145 collapsed its momentum.
#   * At S166 it scores 1.3810, behind only MERGED (1.4238), STRANDED (1.4139)
#     and SPLITTER (1.4053), all three of which are already held. So it is the
#     highest-ranked unheld candidate, and the slot is its.
#
# BUST therefore carries two conditions — the straddling entry and the write-off
# at S185 — and that is forced rather than untidy. A dedicated security for the
# straddle would have to outrank BUST at S166 to take the slot, which would push
# BUST to the next vacancy (slot 5, ~S188) and leave it UNHELD when its write-off
# is due, silently retiring that condition instead.
REPLACEMENT_SECURITY = "SEC_BUST"


def _named_path(security_id: str, t: int, raw: float) -> float:
    """Piecewise price paths, applied ON TOP of the drift.

    FADER is the delicate one and the multiplier is chosen against the two
    thresholds it has to sit between: the review exit needs it UNDERWATER versus
    its entry, while the trailing stop must NOT fire, which means never closing
    at or below 70% of its peak. The decline has to beat FADER's OWN upward
    drift to get there — at 0.24 it did not, and the security finished the run
    up 6% having exercised nothing. At 0.40 it lands ~15% below entry and ~15%
    off its peak, clearing the stop with room. The fixture ASSERTS both facts
    rather than trusting this arithmetic.
    """
    if security_id == "SEC_STOPOUT" and t >= STOPOUT_CRASH_FROM:
        return round(raw * 0.60, 2)
    if security_id == "SEC_HALTED" and t >= HALTED_CRASH_FROM:
        return round(raw * 0.62, 2)
    if security_id == "SEC_FADER" and t >= FADER_DECLINE_FROM:
        span = max(1, N_SESSIONS - FADER_DECLINE_FROM)
        frac = min(1.0, (t - FADER_DECLINE_FROM) / span)
        return round(raw * (1.0 - 0.40 * frac), 2)
    return raw


def build_meta() -> dict[str, SecurityMeta]:
    return {s.security_id: SecurityMeta(
        security_id=s.security_id, ticker=s.ticker, category=s.category,
        permaticker=s.permaticker, related_tickers=s.related,
        first_session=SESSIONS[s.first_t]) for s in SPECS}


def build_bars() -> dict[str, list[VendorBar]]:
    """The whole stream, session -> bars.

    Note what the corporate-action sessions do NOT do: the split session leaves
    the raw close on its post-split level and states `split_ratio` separately,
    and the dividend session leaves the close untouched and states
    `dividend_per_share`. Folding either into the price is the adjustment error
    the price-domain contract exists to prevent, and a fixture that folded them
    would certify the bug instead of catching it.
    """
    out: dict[str, list[VendorBar]] = {s: [] for s in SESSIONS}
    for spec in SPECS:
        for t, session in enumerate(SESSIONS):
            if t < spec.first_t:
                continue
            if spec.security_id == "SEC_GHOST" and t == GHOST_MISSING_SESSION:
                continue                       # no bar at all -> STALE mark
            # After their terminal events these stop printing entirely.
            if spec.security_id == "SEC_MERGED" and t > MERGER_SESSION:
                continue
            if spec.security_id == "SEC_BUST" and t > WRITE_OFF_SESSION:
                continue
            if spec.security_id == "SEC_CONVERTED" and t > CONVERSION_SESSION:
                continue
            if spec.security_id == "SEC_MIXED" and t > MIXED_SESSION:
                continue
            if spec.security_id == "SEC_STRANDED" and t > STRANDED_RESOLVED:
                continue

            split, div = 1.0, 0.0
            tradeable, unresolved = True, False

            raw = _price(spec.index, t, spec.base, spec.drift)
            raw = _named_path(spec.security_id, t, raw)

            if spec.security_id == "SEC_SPLITTER":
                if t == SPLIT_SESSION:
                    split = 2.0
                if t >= SPLIT_SESSION:
                    raw = round(raw / 2.0, 2)  # the post-split price LEVEL
            if spec.security_id == "SEC_PAYER" and t == DIVIDEND_SESSION:
                div = 0.50
            if spec.security_id == "SEC_HALTED" and t in HALTED_UNTRADEABLE:
                tradeable = False              # prints a close, cannot fill
            if spec.security_id == REPLACEMENT_SECURITY and t in REPLACEMENT_UNTRADEABLE:
                tradeable = False
            if spec.security_id == "SEC_MERGED" and UNRESOLVED_FROM <= t <= MERGER_SESSION:
                unresolved, tradeable = True, False
            if spec.security_id == "SEC_BUST" and BUST_UNRESOLVED_FROM <= t <= WRITE_OFF_SESSION:
                unresolved, tradeable = True, False
            # STRANDED keeps PRINTING and stays tradeable throughout. That is
            # the point: a contested bid trades right up to closing, so the
            # block has to come from the missing TERMS, not from an absent
            # price. If it stopped printing, the mark would fail for the
            # ordinary stale reason and the terms rule would go untested.

            out[session].append(VendorBar(
                session=session, security_id=spec.security_id, ticker=spec.ticker,
                raw_close=raw, raw_open=round(raw * 0.998, 2),
                volume=_volume(spec.index, t), split_ratio=split,
                dividend_per_share=div, tradeable=tradeable,
                unresolved_corporate_action=unresolved))
    return out


def build_terminal_events() -> list[TerminalTerms]:
    """One of every supported kind, plus one deliberately incomplete deal.

    The incomplete one is not an edge case bolted on: "terms arrive late" is the
    ordinary situation for a real acquisition, and a fixture without it would
    only ever prove the happy path.
    """
    return [
        TerminalTerms(session=SESSIONS[MERGER_SESSION], security_id="SEC_MERGED",
                      kind=TerminalKind.CASH_MERGER, cash_per_share=54.0,
                      reference="golden/cash-merger"),
        TerminalTerms(session=SESSIONS[WRITE_OFF_SESSION], security_id="SEC_BUST",
                      kind=TerminalKind.WRITE_OFF,
                      reference="golden/write-off"),
        TerminalTerms(session=SESSIONS[CONVERSION_SESSION],
                      security_id="SEC_CONVERTED", kind=TerminalKind.CONVERSION,
                      delivered_security_id="SEC_ACQUIRER",
                      delivered_ticker="ACQR", delivered_issuer_id="P:P914",
                      exchange_ratio=CONVERSION_RATIO,
                      cash_in_lieu_price_per_delivered_share=140.0,
                      reference="golden/stock-for-stock"),
        TerminalTerms(session=SESSIONS[MIXED_SESSION], security_id="SEC_MIXED",
                      kind=TerminalKind.CASH_PLUS_STOCK, cash_per_share=18.0,
                      delivered_security_id="SEC_ACQUIRER",
                      delivered_ticker="ACQR", delivered_issuer_id="P:P914",
                      exchange_ratio=MIXED_RATIO,
                      cash_in_lieu_price_per_delivered_share=140.0,
                      reference="golden/cash-plus-stock"),
        # ANNOUNCED WITH NO TERMS. Every economic field is absent, so this must
        # block admissions rather than be applied at any assumed value.
        TerminalTerms(session=SESSIONS[STRANDED_ANNOUNCED],
                      security_id="SEC_STRANDED", kind=TerminalKind.CASH_MERGER,
                      reference="golden/terms-pending"),
        TerminalTerms(session=SESSIONS[STRANDED_RESOLVED],
                      security_id="SEC_STRANDED", kind=TerminalKind.CASH_MERGER,
                      cash_per_share=61.5, reference="golden/terms-supplied"),
    ]


@dataclass(frozen=True)
class GoldenScenario:
    sessions: Sequence[str]
    bars_by_session: Mapping[str, Sequence[VendorBar]]
    meta: Mapping[str, SecurityMeta]
    terminal_events: Sequence[TerminalTerms]
    starting_cash: float = STARTING_CASH
    restart_at: int = RESTART_AT


def golden_scenario() -> GoldenScenario:
    """The single entry point every engine's parity test calls."""
    return GoldenScenario(sessions=list(SESSIONS), bars_by_session=build_bars(),
                          meta=build_meta(), terminal_events=build_terminal_events())


__all__ = ["GoldenScenario", "golden_scenario", "SESSIONS", "STARTING_CASH",
           "RESTART_AT"]
