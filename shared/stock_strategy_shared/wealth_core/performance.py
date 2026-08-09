"""Wealth Core performance measurement — PURE, and derived output only.

WHY THIS EXISTS. Wealth Core produces a fully valued session stream and never
converted it into a performance number. `RunResult` carries every session's
`resolved_equity` and every fill; `TunnelRun` exposed only final cash, position
count and marked equity; and the chain rehearsal's API elided the per-session
detail above 400 sessions BEFORE persisting the summary — so a three-year
rehearsal (~753 sessions) threw away the equity curve and left nothing to measure
afterwards. Nothing in the repo computed a CAGR, a drawdown or a turnover for
this strategy. That, not the SF1 re-backfill, was what stood between the corpus
and a first trusted baseline.

DERIVED OUTPUT, NEVER AN INPUT. Nothing here may reach a certified economic or
parity hash. The seven parity layers cover terminal state, cash, the ledger and
every session decision; a measurement is a READING of those, and folding a
reading into the thing it measures would re-pin the certification anchor for a
change with no economic content. This module is import-only from serialisation
paths, and a test asserts the hashes are unmoved.

ONE IMPLEMENTATION, TWO CALLERS. The chain rehearsal establishes the baseline and
the tunnel measures experiments against it; if each computed its own CAGR the
comparison would be between two definitions rather than two runs. bt-engine
imports THIS — it does not re-derive the formulas.

THE FROZEN CONVENTIONS, each of which is a decision rather than a detail:

    point zero          the curve starts at `starting_cash`, BEFORE the first
                        session. Without it a book that fell on day one shows a
                        drawdown measured from the post-loss equity — the worst
                        day of a run is exactly the one most likely to be first.
    calendar time       CAGR and annualised turnover use ACTUAL calendar days
                        between the first and last valuation, not session counts
                        divided by 252. A run spanning a holiday-heavy stretch
                        has fewer sessions and the same elapsed money.
    resolved only       drawdown reads `resolved_equity`. `estimated_equity` is
                        a pre-resolution figure and mixing the two would produce
                        peaks and troughs from different valuation bases.
    never skip          a MISSING `resolved_equity` makes the whole measurement
                        unevaluable. Dropping the session would silently measure
                        a different, shorter run; interpolating would invent a
                        valuation the strategy never had.
    blocked sessions    a BLOCKED session has no `resolved_equity` BY DESIGN —
                        the book could not be valued and made no decisions. The
                        golden scenario blocks 19 of its 260 sessions, so the
                        strict rule above makes it (and any real run containing a
                        blocked stretch) unevaluable. That is the correct DEFAULT
                        and it is kept: a blocked stretch could hide the deepest
                        trough of the run, and carrying the last valuation
                        forward across it would report a drawdown that never
                        acknowledged the days nobody could see. `allow_blocked_gaps`
                        measures the OBSERVED valuations instead, and everything
                        it returns is then labelled: `maximum_drawdown_is_lower_bound`
                        is set, and the excluded sessions are named. It is OFF
                        unless a caller asks, and the unevaluable reason always
                        separates blocked sessions from unexplained ones so an
                        operator can tell design from corruption at a glance.
    executed fills      `trade_count` counts fills. Intents and signals are what
                        the strategy WANTED; a rejected or unaffordable order
                        moved no money and must not inflate turnover.
    gross notional      sum(|shares x raw_open|), the two fields a fill already
                        carries, so no execution-model change is needed.
    agreement           ending equity must equal the last resolved equity AND,
                        when the final book is fully resolved, the final marked
                        equity. Disagreement is a FAILURE, not a rounding note:
                        two valuations of one book differing means one of them is
                        wrong and the metrics inherit it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Mapping, Optional, Sequence

#: Below this elapsed span, annualising is arithmetic on noise: a 3-day 2% gain
#: compounds to a headline number that describes nothing. CAGR is reported as
#: None with a reason rather than as a large confident lie.
MIN_ANNUALIZATION_DAYS = 30

#: Below a year, CAGR is an EXTRAPOLATION of a partial year. Still reported —
#: refusing it would make every short diagnostic run unreadable — but flagged, so
#: nobody quotes an 8-month run's annualised figure as a track record.
FULL_YEAR_DAYS = 365

#: Two valuations of one book should agree to the cent. A cent of slack absorbs
#: float representation, nothing more.
EQUITY_AGREEMENT_TOLERANCE = 0.01


@dataclass(frozen=True)
class SessionFacts:
    """The minimum a session must supply to be measurable.

    Deliberately not `SessionResult` itself: the chain rehearsal and the bulk
    run carry different session types, and both must be measurable by the same
    function or the "chain and bulk agree" check compares two definitions.
    """
    session: str
    resolved_equity: Optional[float]
    fills: Sequence[Mapping[str, Any]] = ()
    #: A blocked session has no valuation BY DESIGN. Recorded so a missing
    #: `resolved_equity` that the strategy explains is distinguishable from one
    #: nothing explains — the difference between a designed state and a defect.
    blocked: bool = False


@dataclass(frozen=True)
class Performance:
    evaluable: bool
    unevaluable_reason: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    session_count: int = 0
    calendar_days: Optional[int] = None
    starting_equity: float = 0.0
    ending_equity: Optional[float] = None
    ending_wealth_multiple: Optional[float] = None
    total_return: Optional[float] = None
    cagr: Optional[float] = None
    cagr_unavailable_reason: Optional[str] = None
    cagr_extrapolated: bool = False
    maximum_drawdown: Optional[float] = None
    max_drawdown_peak_date: Optional[str] = None
    max_drawdown_trough_date: Optional[str] = None
    trade_count: int = 0
    gross_traded_notional: float = 0.0
    gross_turnover: Optional[float] = None
    annualized_turnover: Optional[float] = None
    average_resolved_equity: Optional[float] = None
    #: Buy-and-hold benchmark over the SAME observed span. None throughout when
    #: no series was supplied or the span's endpoints are not both present — a
    #: comparison against a partly-guessed benchmark is worse than none.
    benchmark_ticker: Optional[str] = None
    benchmark_total_return: Optional[float] = None
    benchmark_cagr: Optional[float] = None
    benchmark_maximum_drawdown: Optional[float] = None
    benchmark_unavailable_reason: Optional[str] = None
    excess_total_return: Optional[float] = None
    excess_cagr: Optional[float] = None
    blocked_session_count: int = 0
    excluded_blocked_sessions: tuple = ()
    #: True when blocked sessions were excluded. The unobserved days could
    #: contain a deeper trough, so the reported drawdown is a FLOOR, not the
    #: figure. Any consumer quoting the drawdown must carry this with it.
    maximum_drawdown_is_lower_bound: bool = False

    def to_dict(self) -> dict:
        return {
            "evaluable": self.evaluable,
            "unevaluable_reason": self.unevaluable_reason,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "session_count": self.session_count,
            "calendar_days": self.calendar_days,
            "starting_equity": _r2(self.starting_equity),
            "ending_equity": _r2(self.ending_equity),
            "ending_wealth_multiple": _r6(self.ending_wealth_multiple),
            "total_return": _r6(self.total_return),
            "cagr": _r6(self.cagr),
            "cagr_unavailable_reason": self.cagr_unavailable_reason,
            "cagr_extrapolated": self.cagr_extrapolated,
            "maximum_drawdown": _r6(self.maximum_drawdown),
            "max_drawdown_peak_date": self.max_drawdown_peak_date,
            "max_drawdown_trough_date": self.max_drawdown_trough_date,
            "trade_count": self.trade_count,
            "gross_traded_notional": _r2(self.gross_traded_notional),
            "gross_turnover": _r6(self.gross_turnover),
            "annualized_turnover": _r6(self.annualized_turnover),
            "average_resolved_equity": _r2(self.average_resolved_equity),
            "benchmark_ticker": self.benchmark_ticker,
            "benchmark_total_return": _r6(self.benchmark_total_return),
            "benchmark_cagr": _r6(self.benchmark_cagr),
            "benchmark_maximum_drawdown": _r6(self.benchmark_maximum_drawdown),
            "benchmark_unavailable_reason": self.benchmark_unavailable_reason,
            "excess_total_return": _r6(self.excess_total_return),
            "excess_cagr": _r6(self.excess_cagr),
            "blocked_session_count": self.blocked_session_count,
            "excluded_blocked_sessions": list(self.excluded_blocked_sessions),
            "maximum_drawdown_is_lower_bound": self.maximum_drawdown_is_lower_bound,
        }


def _r2(v):
    return None if v is None else round(float(v), 2)


def _r6(v):
    return None if v is None else round(float(v), 6)


def _unevaluable(reason: str, *, starting_cash: float,
                 sessions: Sequence[SessionFacts]) -> Performance:
    """An unevaluable measurement still reports what it COULD see.

    Returning a bare `evaluable: False` would make a partial run and an empty one
    look identical, and the session count is usually the first thing that
    explains which happened. The blocked tally rides along for the same reason:
    a caller deciding whether to retry with `allow_blocked_gaps` should not have
    to parse the prose to find out how many sessions are at stake.
    """
    blocked = tuple(s.session for s in sessions
                    if s.resolved_equity is None and s.blocked)
    return Performance(
        evaluable=False, unevaluable_reason=reason,
        starting_equity=float(starting_cash),
        session_count=len(sessions),
        start_date=sessions[0].session if sessions else None,
        end_date=sessions[-1].session if sessions else None,
        blocked_session_count=len(blocked),
        excluded_blocked_sessions=blocked,
    )


def _fill_notional(fill: Mapping[str, Any]) -> float:
    """|shares x raw_open| for one fill.

    A fill missing either field is a defect in the execution record, not a
    zero-notional trade — silently treating it as zero would understate turnover
    by exactly the trades whose records are broken.
    """
    shares = fill.get("shares")
    price = fill.get("raw_open")
    if shares is None or price is None:
        raise ValueError(
            f"fill lacks shares/raw_open and cannot be valued: "
            f"{ {k: fill.get(k) for k in ('security_id', 'operation', 'shares', 'raw_open')} }"
        )
    return abs(float(shares) * float(price))


def measure(*,
            starting_cash: float,
            sessions: Sequence[SessionFacts],
            final_marked_equity: Optional[float] = None,
            final_book_resolved: bool = False,
            allow_blocked_gaps: bool = False,
            benchmark_closes: Optional[Mapping[str, float]] = None,
            benchmark_ticker: Optional[str] = None) -> Performance:
    """Measure one Wealth Core run. Pure; raises only on a malformed fill record.

    `final_marked_equity` / `final_book_resolved` come from the run's
    `FinalReport`. The cross-check runs only when the book is fully resolved,
    because an unmarkable position or an unsettled receivable makes the two
    numbers legitimately different and failing on that would reject good runs.
    """
    starting_cash = float(starting_cash)
    if not sessions:
        return _unevaluable("no sessions", starting_cash=starting_cash,
                            sessions=sessions)

    # A missing valuation is either EXPLAINED (the session was blocked, a
    # designed state) or unexplained (a defect). Separated in the reason so an
    # operator can tell those apart without reading the session rows.
    blocked_missing = [s.session for s in sessions
                       if s.resolved_equity is None and s.blocked]
    unexplained = [s.session for s in sessions
                   if s.resolved_equity is None and not s.blocked]

    if unexplained:
        # NEVER tolerated, and `allow_blocked_gaps` does not reach these. A
        # session with no valuation and no explanation is the corruption case.
        shown = ", ".join(unexplained[:5]) + ("…" if len(unexplained) > 5 else "")
        return _unevaluable(
            f"{len(unexplained)} session(s) have no resolved_equity and were "
            f"not blocked ({shown}); a run cannot be measured across valuations "
            f"it does not have",
            starting_cash=starting_cash, sessions=sessions)

    if blocked_missing and not allow_blocked_gaps:
        shown = ", ".join(blocked_missing[:5]) + ("…" if len(blocked_missing) > 5 else "")
        return _unevaluable(
            f"{len(blocked_missing)} BLOCKED session(s) have no resolved_equity "
            f"({shown}). Blocked sessions are a designed state, not corruption — "
            f"but a blocked stretch can hide the deepest trough of the run, so "
            f"measuring across it is opt-in. Pass allow_blocked_gaps=True to "
            f"measure the observed valuations, which reports the drawdown as a "
            f"LOWER BOUND",
            starting_cash=starting_cash, sessions=sessions)

    observed = [s for s in sessions if s.resolved_equity is not None]
    if not observed:
        return _unevaluable("no session carries a resolved_equity",
                            starting_cash=starting_cash, sessions=sessions)

    equities = [float(s.resolved_equity) for s in observed]
    ending_equity = equities[-1]

    if final_book_resolved and final_marked_equity is not None:
        if abs(ending_equity - float(final_marked_equity)) > EQUITY_AGREEMENT_TOLERANCE:
            return _unevaluable(
                f"last resolved equity {ending_equity:.2f} disagrees with final "
                f"marked equity {float(final_marked_equity):.2f} on a fully "
                f"resolved book; one of the two valuations is wrong and the "
                f"metrics would inherit it",
                starting_cash=starting_cash, sessions=sessions)

    start_date, end_date = observed[0].session, observed[-1].session
    calendar_days = _calendar_days(start_date, end_date)

    # ── the curve, with point zero ───────────────────────────────────────────
    # `starting_cash` is prepended so a first-session loss is a drawdown rather
    # than the baseline everything else is measured from.
    curve: list[tuple[Optional[str], float]] = [(None, starting_cash)]
    curve += [(s.session, e) for s, e in zip(observed, equities)]

    max_dd, dd_peak, dd_trough = _drawdown(curve)

    # ── returns ──────────────────────────────────────────────────────────────
    total_return = multiple = None
    if starting_cash > 0:
        multiple = ending_equity / starting_cash
        total_return = multiple - 1.0

    cagr, cagr_reason, extrapolated = _cagr(starting_cash, ending_equity,
                                            calendar_days)

    # ── traded volume ────────────────────────────────────────────────────────
    # Fills are counted from EVERY session, including blocked ones: a blocked
    # session values nothing but the run may still have filled orders placed
    # before it, and dropping those would understate turnover.
    trade_count = 0
    gross_notional = 0.0
    for s in sessions:
        for fill in s.fills or ():
            trade_count += 1
            gross_notional += _fill_notional(fill)

    avg_equity = sum(equities) / len(equities) if equities else None
    gross_turnover = (gross_notional / avg_equity) if avg_equity else None
    annualized_turnover = None
    if gross_turnover is not None and calendar_days and calendar_days > 0:
        annualized_turnover = gross_turnover * (FULL_YEAR_DAYS / calendar_days)

    bench = _benchmark(benchmark_closes, benchmark_ticker,
                       [s.session for s in observed], calendar_days)

    return Performance(
        evaluable=True,
        start_date=start_date,
        end_date=end_date,
        session_count=len(sessions),
        calendar_days=calendar_days,
        blocked_session_count=len(blocked_missing),
        excluded_blocked_sessions=tuple(blocked_missing),
        maximum_drawdown_is_lower_bound=bool(blocked_missing),
        starting_equity=starting_cash,
        ending_equity=ending_equity,
        ending_wealth_multiple=multiple,
        total_return=total_return,
        cagr=cagr,
        cagr_unavailable_reason=cagr_reason,
        cagr_extrapolated=extrapolated,
        maximum_drawdown=max_dd,
        max_drawdown_peak_date=dd_peak,
        max_drawdown_trough_date=dd_trough,
        trade_count=trade_count,
        gross_traded_notional=gross_notional,
        gross_turnover=gross_turnover,
        annualized_turnover=annualized_turnover,
        average_resolved_equity=avg_equity,
        benchmark_ticker=benchmark_ticker,
        benchmark_total_return=bench["total_return"],
        benchmark_cagr=bench["cagr"],
        benchmark_maximum_drawdown=bench["maximum_drawdown"],
        benchmark_unavailable_reason=bench["reason"],
        excess_total_return=(None if bench["total_return"] is None
                             or total_return is None
                             else total_return - bench["total_return"]),
        excess_cagr=(None if bench["cagr"] is None or cagr is None
                     else cagr - bench["cagr"]),
    )


def _benchmark(closes: Optional[Mapping[str, float]], ticker: Optional[str],
               observed_sessions: Sequence[str],
               calendar_days: Optional[int]) -> dict:
    """Buy-and-hold the benchmark over the SAME observed span.

    Measured on the sessions the STRATEGY was measured on, not on the benchmark's
    own full history — otherwise the two numbers describe different periods and
    the excess is meaningless. Sessions the benchmark does not price are dropped
    from ITS curve only (an ETF can be missing a print the book still traded
    through), but the two ENDPOINTS must both exist or there is no comparison.
    """
    empty = {"total_return": None, "cagr": None, "maximum_drawdown": None,
             "reason": None}
    if not closes:
        return {**empty, "reason": "no benchmark series supplied"}

    pairs = [(d, float(closes[d])) for d in observed_sessions
             if closes.get(d) is not None and float(closes[d]) > 0]
    # ENDPOINTS FIRST, and checked before the count. A missing endpoint silently
    # shortens the benchmark's span, which shows up as an excess return the
    # strategy never earned — the specific failure worth naming, and the count
    # check would otherwise swallow it behind a vaguer message.
    priced = {d for d, _ in pairs}
    missing_ends = [d for d in (observed_sessions[0], observed_sessions[-1])
                    if d not in priced]
    if missing_ends:
        return {**empty,
                "reason": (f"{ticker or 'benchmark'} is missing an endpoint "
                           f"({', '.join(missing_ends)}); priced "
                           f"{len(pairs)} of {len(observed_sessions)} session(s)")}
    if len(pairs) < 2:
        return {**empty,
                "reason": f"{ticker or 'benchmark'} prices only {len(pairs)} of "
                          f"{len(observed_sessions)} measured session(s)"}

    first, last = pairs[0][1], pairs[-1][1]
    total_return = (last / first) - 1.0
    cagr, _reason, _extra = _cagr(first, last, calendar_days)
    max_dd, _p, _t = _drawdown(pairs)
    return {"total_return": total_return, "cagr": cagr,
            "maximum_drawdown": max_dd, "reason": None}


def _drawdown(curve: Sequence[tuple]) -> tuple[float, Optional[str], Optional[str]]:
    """Max peak-to-trough fraction over an ordered (label, value) curve.

    Shared by the strategy and the benchmark on purpose: a comparison in which
    the two drawdowns were computed by different code is not a comparison.
    """
    peak_value, peak_date = curve[0][1], curve[0][0]
    max_dd, dd_peak, dd_trough = 0.0, None, None
    for when, value in curve[1:]:
        if value > peak_value:
            peak_value, peak_date = value, when
            continue
        if peak_value > 0:
            dd = (peak_value - value) / peak_value
            if dd > max_dd:
                max_dd, dd_peak, dd_trough = dd, peak_date, when
    return max_dd, dd_peak, dd_trough


def _calendar_days(start: str, end: str) -> Optional[int]:
    try:
        return (date.fromisoformat(end) - date.fromisoformat(start)).days
    except (TypeError, ValueError):
        # Session labels that are not ISO dates are legitimate in the synthetic
        # golden fixture ("S001"). Everything except the two calendar-scaled
        # figures stays measurable, which is better than refusing the run.
        return None


def _cagr(starting: float, ending: float,
          calendar_days: Optional[int]) -> tuple[Optional[float], Optional[str], bool]:
    if starting <= 0:
        return None, "starting equity is not positive", False
    if ending <= 0:
        # The book was wiped out. A fractional power of a non-positive number is
        # not a small CAGR, it is undefined — and -100% is already visible in
        # total_return, which is the honest place for it.
        return None, "ending equity is not positive; see total_return", False
    if calendar_days is None:
        return None, "session labels are not calendar dates", False
    if calendar_days <= 0:
        return None, "start and end fall on the same day", False
    if calendar_days < MIN_ANNUALIZATION_DAYS:
        return None, (f"span of {calendar_days} day(s) is below the "
                      f"{MIN_ANNUALIZATION_DAYS}-day annualisation floor"), False
    years = calendar_days / FULL_YEAR_DAYS
    return ((ending / starting) ** (1.0 / years)) - 1.0, None, calendar_days < FULL_YEAR_DAYS


# ── adapters: one per session-carrying type, so `measure` stays generic ──────

def facts_from_run_result(result) -> list[SessionFacts]:
    """SessionFacts from a `RunResult` — the bulk path, which carries fills.

    Prefers `session_facts`, which the run retains under EVERY hash mode. Under
    `hash_mode="streaming"` the SessionResult objects are folded into the parity
    hashes and dropped, so reading `result.sessions` there would silently
    measure an empty run — a CAGR of zero over no sessions, reported without
    complaint. The facts are the certification input; the objects are not.
    """
    facts = getattr(result, "session_facts", None)
    if facts:
        return list(facts)
    return [SessionFacts(session=s.session,
                         resolved_equity=s.resolved_equity,
                         fills=tuple(s.fills or ()),
                         blocked=bool(getattr(s, "blocked", False)))
            for s in result.sessions]


def measure_run_result(result, starting_cash: float,
                       *, allow_blocked_gaps: bool = False,
                       benchmark_closes: Optional[Mapping[str, float]] = None,
                       benchmark_ticker: Optional[str] = None) -> Performance:
    """Measure a `RunResult`, cross-checking against its own FinalReport."""
    final = getattr(result, "final", None)
    resolved = bool(final) and not final.unmarkable_positions \
        and not final.unresolved_terminals \
        and not _receivables(result)
    return measure(
        starting_cash=starting_cash,
        sessions=facts_from_run_result(result),
        final_marked_equity=(final.marked_equity if final else None),
        final_book_resolved=resolved,
        allow_blocked_gaps=allow_blocked_gaps,
        benchmark_closes=benchmark_closes,
        benchmark_ticker=benchmark_ticker,
    )


def _receivables(result) -> float:
    ledger = getattr(result, "ledger", None)
    return float(ledger.receivable_total()) if ledger else 0.0


__all__ = ["EQUITY_AGREEMENT_TOLERANCE", "FULL_YEAR_DAYS",
           "MIN_ANNUALIZATION_DAYS", "Performance", "SessionFacts",
           "facts_from_run_result", "measure", "measure_run_result"]
