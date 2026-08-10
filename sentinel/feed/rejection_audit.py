"""Could a REFUSED price row have changed the answer? Fail closed when unknown.

Operational readiness and certification ask different questions about the same
rows, and conflating them is how one of the two ends up wrong.

```text
READINESS      "is the feed healthy enough to plan a book tomorrow?"
               A handful of unresolvable tickers is normal — the vendor prices
               instruments Sentinel has no identity for and never wants. WARN.

CERTIFICATION  "is THIS replay, over THIS interval, complete?"
               A rejected row is a security the vendor priced and the corpus
               does not contain. Whether that mattered is a question with an
               answer, and the rehearsal is not evidence until it is answered.
```

So a rejection is never automatically a certification failure — the ticker may
be economically irrelevant — but "we did not check" is. This module classifies
every rejected ticker in the interval into exactly one of three verdicts and
refuses when any lands in the third.

## The three verdicts

```text
IMMATERIAL   it could NOT have entered the universe even at its best observed
             values. Decided against the SAME EligibilityConfig the engine
             applies, using UPPER BOUNDS over what was actually seen — max
             price, max dollar volume, total priced sessions. "Even at its
             best it fails" is a real proof; "on average it looks small" is not
MATERIAL     it intersects something the run depended on — a holding, a pending
             terminal episode, or a corporate action in the interval
UNDETERMINED anything else. It cleared the floors it could be tested against,
             or it could not be tested at all
```

`certifiable` is true only when nothing is MATERIAL and nothing is
UNDETERMINED. That is the fail-closed rule: an unanswerable question blocks the
claim rather than being rounded down to "probably fine".

## Why upper bounds, and why they are honest

The audit knows a rejected ticker's price and volume on the sessions it was
refused, because `note_rejection` records them. It does NOT know what the
security would have done inside the engine — the momentum series, the
volatility, the issuer group. So it never claims a rejection WOULD have been
admitted. It only ever proves the negative: a security whose best observed
as-traded price never reached the minimum, or whose best observed dollar volume
never reached the signal floor, or which was priced on fewer sessions than the
history requirement, could not have been admitted on any session in this
interval regardless of what else is unknown about it.

Everything else is UNDETERMINED, and that is the intended outcome. The set of
things this can prove is deliberately small.

## What it does NOT do

It does not decide whether the rehearsal is valid. It reports, and it exits
non-zero on anything short of CLEAR, so the decision is a human's — made in
front of a named list of tickers rather than a count.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional

from stock_strategy_shared.wealth_core.eligibility import EligibilityConfig

CLEAR = "CLEAR"
MATERIAL = "MATERIAL"
UNDETERMINED = "UNDETERMINED"

#: Reasons a row can be refused. Both are DROPS of a row the vendor supplied,
#: and both have to be counted — the second one used to leave no evidence at
#: all, so "how many priced rows did the ingest refuse" could only be half
#: answered, and the missing half was the one where the vendor DID price the
#: security.
NO_IDENTITY = "NO_IDENTITY"
NO_RAW_CLOSE = "NO_RAW_CLOSE"


@dataclass
class TickerVerdict:
    ticker: str
    rows: int
    sessions: int
    first_session: Optional[str]
    last_session: Optional[str]
    reasons: list[str]
    max_close: Optional[float]
    max_dollar_volume: Optional[float]
    verdict: str
    why: str
    intersects: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"ticker": self.ticker, "rows": self.rows,
                "sessions": self.sessions, "first_session": self.first_session,
                "last_session": self.last_session, "reasons": self.reasons,
                "max_close": self.max_close,
                "max_dollar_volume": self.max_dollar_volume,
                "verdict": self.verdict, "why": self.why,
                "intersects": self.intersects}


@dataclass
class RejectionAudit:
    window: tuple[str, str]
    rejected_rows: int
    distinct_tickers: int
    per_ticker: list[TickerVerdict]

    @property
    def material(self) -> list[TickerVerdict]:
        return [t for t in self.per_ticker if t.verdict == MATERIAL]

    @property
    def undetermined(self) -> list[TickerVerdict]:
        return [t for t in self.per_ticker if t.verdict == UNDETERMINED]

    @property
    def verdict(self) -> str:
        if self.material:
            return MATERIAL
        if self.undetermined:
            return UNDETERMINED
        return CLEAR

    @property
    def certifiable(self) -> bool:
        """CLEAR only. An unanswerable question blocks the claim — that is the
        whole point of separating this from the operational WARN."""
        return self.verdict == CLEAR

    def to_dict(self) -> dict:
        return {"window": {"start": self.window[0], "end": self.window[1]},
                "rejected_rows": self.rejected_rows,
                "distinct_tickers": self.distinct_tickers,
                "immaterial": sum(1 for t in self.per_ticker
                                  if t.verdict == "IMMATERIAL"),
                "material": [t.to_dict() for t in self.material],
                "undetermined": [t.to_dict() for t in self.undetermined],
                "verdict": self.verdict,
                "certifiable": self.certifiable}


def _rows(conn, start: str, end: str) -> list[tuple]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT ticker, COUNT(*), COUNT(DISTINCT session),"
            " MIN(session), MAX(session),"
            " ARRAY_AGG(DISTINCT reason), MAX(close_unadjusted),"
            " MAX(close_unadjusted * COALESCE(volume, 0))"
            " FROM sentinel_ingest_rejections"
            " WHERE session BETWEEN %s AND %s GROUP BY ticker ORDER BY ticker",
            (start, end))
        return list(cur.fetchall())


def _actioned_tickers(conn, start: str, end: str) -> set[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT ticker FROM sentinel_actions"
                    " WHERE session BETWEEN %s AND %s", (start, end))
        return {str(r[0]).upper() for r in cur.fetchall() if r[0]}


def audit(conn, *, start: str, end: str,
          held_tickers: Iterable[str] = (),
          pending_terminal_tickers: Iterable[str] = (),
          eligibility: EligibilityConfig | None = None) -> RejectionAudit:
    """Classify every refused ticker in [start, end]."""
    cfg = eligibility or EligibilityConfig()
    held = {str(t).upper() for t in held_tickers}
    pending = {str(t).upper() for t in pending_terminal_tickers}
    actioned = _actioned_tickers(conn, start, end)

    per: list[TickerVerdict] = []
    total_rows = 0
    for (ticker, rows, sessions, lo, hi, reasons, max_close,
         max_dv) in _rows(conn, start, end):
        total_rows += int(rows)
        t = str(ticker).upper()
        intersects = []
        if t in held:
            intersects.append("held_position")
        if t in pending:
            intersects.append("pending_terminal_episode")
        if t in actioned:
            intersects.append("corporate_action_in_window")

        if intersects:
            # MATERIAL outranks every immateriality proof. A security the run
            # HELD, or whose termination the run was waiting on, mattered by
            # definition — whatever its price says about admission, and the
            # admission floors do not govern a position already open.
            verdict, why = MATERIAL, "intersects " + ", ".join(intersects)
        else:
            verdict, why = _immateriality(cfg, sessions, max_close, max_dv)

        per.append(TickerVerdict(
            ticker=t, rows=int(rows), sessions=int(sessions),
            first_session=str(lo) if lo else None,
            last_session=str(hi) if hi else None,
            reasons=sorted(str(r) for r in (reasons or []) if r),
            max_close=None if max_close is None else float(max_close),
            max_dollar_volume=None if max_dv is None else float(max_dv),
            verdict=verdict, why=why, intersects=intersects))

    return RejectionAudit(window=(start, end), rejected_rows=total_rows,
                          distinct_tickers=len(per), per_ticker=per)


def _immateriality(cfg: EligibilityConfig, sessions: int,
                   max_close, max_dv) -> tuple[str, str]:
    """Prove the NEGATIVE or say UNDETERMINED. Never prove the positive.

    Each test is an UPPER BOUND over what was actually observed, so a pass here
    means the security could not have been admitted on any session in the
    interval no matter what else is unknown about it. Nothing in this function
    can conclude that a rejection WOULD have been admitted — that would need
    the momentum series, the volatility and the issuer group, none of which
    survive a dropped row.
    """
    if sessions < cfg.min_history_sessions:
        return ("IMMATERIAL",
                f"priced on {sessions} session(s) in the window, below the "
                f"{cfg.min_history_sessions} of history admission requires, so "
                f"it could not have been ranked on any of them")
    if max_close is not None and float(max_close) < cfg.min_unadjusted_price:
        return ("IMMATERIAL",
                f"best observed as-traded close {float(max_close):.4g} never "
                f"reached the {cfg.min_unadjusted_price} floor")
    if max_dv is not None and float(max_dv) < cfg.min_signal_dollar_volume:
        return ("IMMATERIAL",
                f"best observed dollar volume {float(max_dv):,.0f} never "
                f"reached the {cfg.min_signal_dollar_volume:,.0f} signal floor")
    if max_close is None:
        return (UNDETERMINED,
                "no as-traded price was recorded with the rejection, so the "
                "eligibility floors cannot be evaluated against it")
    return (UNDETERMINED,
            "it cleared every floor that can be tested from a dropped row; "
            "whether it would have been admitted needs the price history the "
            "drop destroyed")


__all__ = ["CLEAR", "MATERIAL", "NO_IDENTITY", "NO_RAW_CLOSE", "RejectionAudit",
           "TickerVerdict", "UNDETERMINED", "audit"]
