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
             price, max dollar volume. "Even at its best it fails" is a real
             proof; "on average it looks small" is not
MATERIAL     it intersects something the run depended on — a holding, a pending
             terminal episode, or a corporate action in the interval
UNDETERMINED anything else. It cleared the floors it could be tested against,
             or it could not be tested at all
```

`certifiable` is true only when nothing is MATERIAL, nothing is UNDETERMINED,
and no rejection evidence was truncated. That is the fail-closed rule: an
unanswerable question blocks the claim rather than being rounded down to
"probably fine".

## Why upper bounds, and why they are honest

The audit knows a rejected ticker's price and volume on the sessions it was
refused, because `note_rejection` records them. It does NOT know what the
security would have done inside the engine — the momentum series, the
volatility, the issuer group. So it never claims a rejection WOULD have been
admitted. It only ever proves the negative: a security whose best observed
as-traded price never reached the minimum, or whose best observed dollar volume
never reached the signal floor, could not have been admitted on any session it
was refused on, regardless of what else is unknown about it.

Everything else is UNDETERMINED, and that is the intended outcome. The set of
things this can prove is deliberately small.

## The history proof that was WRONG, and is gone

An earlier version also cleared a ticker whose REJECTED session count fell below
`min_history_sessions`, reasoning that 126 sessions of history are required
before a security can be ranked. Those are not the same 126.

```text
AAA has 300 valid prior sessions in the corpus
AAA has ONE refused row on 2022-06-15
   rejected sessions = 1
   1 < 126  ->  "could not have been ranked"        <- INVALID
```

The security already had its history; the rejection table counts only what was
DROPPED. Worse for a held name, where admission eligibility is beside the point
entirely — one missing bar can move a mark, a stop peak, a terminal grace or a
fill, none of which the 126-session floor governs.

A history argument is only available to something that knows the security's
COMPLETE history through that date. The rejection table knows the opposite of
that by construction, so the proof is not repaired here — it is removed.

## The intersection checks are only as good as their inputs

`held_tickers` and `pending_terminal_tickers` default to `None`, meaning
UNAVAILABLE, and every ticker then comes back UNDETERMINED. They do NOT default
to empty. An empty set is the claim "nothing was held", and a caller that
simply did not supply the information would otherwise have made that claim
silently — which is how the strongest materiality check in this module became
a no-op on the one path that matters. Pass `()` to assert a genuinely empty
book; that assertion is then recorded in the report.

## What it does NOT do

It does not decide whether the rehearsal is valid. It reports, and it exits
non-zero on anything short of CLEAR, so the decision is a human's — made in
front of a named list of tickers rather than a count.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional

from sentinel.feed import anomalies as anomaly_store
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
    #: Rejection evidence the ingest counted but never wrote. Any of it
    #: overlapping this interval makes the audit's central claim — that it
    #: examined every refused row — demonstrably false.
    truncated_evidence: list[dict] = field(default_factory=list)
    #: Corpus anomalies the ingest resolved but did not resolve AWAY.
    gating_anomalies: list[dict] = field(default_factory=list)
    #: Every split disposition in the interval, rendered as mutually explicit
    #: certification categories rather than inferred from warning prose.
    split_dispositions: list[dict] = field(default_factory=list)
    #: Whether the caller could tell us what the run held. False means the two
    #: strongest materiality checks were unavailable, not that they passed.
    holdings_known: bool = False

    @property
    def material(self) -> list[TickerVerdict]:
        return [t for t in self.per_ticker if t.verdict == MATERIAL]

    @property
    def undetermined(self) -> list[TickerVerdict]:
        return [t for t in self.per_ticker if t.verdict == UNDETERMINED]

    @property
    def unsafe_split_dispositions(self) -> list[dict]:
        return [item for item in self.split_dispositions
                if item.get("blocks_certification")]

    @property
    def verdict(self) -> str:
        if self.material:
            return MATERIAL
        if (self.undetermined or self.truncated_evidence
                or self.gating_anomalies or self.unsafe_split_dispositions):
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
                "holdings_known": self.holdings_known,
                "immaterial": sum(1 for t in self.per_ticker
                                  if t.verdict == "IMMATERIAL"),
                "material": [t.to_dict() for t in self.material],
                "undetermined": [t.to_dict() for t in self.undetermined],
                "truncated_evidence": self.truncated_evidence,
                "gating_anomalies": self.gating_anomalies,
                "split_dispositions": self.split_dispositions,
                "unsafe_split_dispositions": self.unsafe_split_dispositions,
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
        cur.execute("SELECT DISTINCT ticker FROM sentinel_active_actions"
                    " WHERE session BETWEEN %s AND %s", (start, end))
        return {str(r[0]).upper() for r in cur.fetchall() if r[0]}


def _truncations(conn, start: str, end: str) -> list[dict]:
    """Windows where rejection evidence was counted and not written.

    Overlap, not containment: a truncated 2021 chunk makes a certified interval
    inside 2021 unanswerable just as surely as one that spans it.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT run_id, chunk, window_start, window_end, retained,"
            " truncated FROM sentinel_rejection_truncation"
            " WHERE window_start <= %s AND window_end >= %s"
            " ORDER BY window_start", (end, start))
        return [{"run_id": str(r[0]), "chunk": str(r[1]),
                 "window_start": str(r[2]), "window_end": str(r[3]),
                 "retained": int(r[4]), "truncated": int(r[5])}
                for r in cur.fetchall()]


#: Anomalies that BLOCK certification of an interval they fall in. A split the
#: two sources disagree about is one of them being wrong about a share count; a
#: distribution whose amount the vendor never stated is stored as 0.0 and is
#: indistinguishable, in the corpus, from no distribution at all. Neither is
#: repaired by the ingest, so neither can be certified past in silence.
#: Derived-only and seam dispositions are handled by `_split_dispositions` and
#: always block absent genuine full-interval counterfactual equivalence proof.
GATING_ANOMALY_KINDS = ("SPLIT_DISAGREEMENT", "UNUSABLE_DIVIDEND")

_SPLIT_DISPOSITION = {
    "SPLIT_AUTHORITATIVE_APPLIED": "authoritative applied split",
    "SPLIT_CORROBORATED_DERIVED": "corroborated derived split",
    "SPLIT_ONLY_DERIVED": "derived-only non-seam split",
    "SEAM_SPLIT_UNCORROBORATED": "seam artifact suppressed",
    "SPLIT_DISAGREEMENT": "unresolved material disagreement",
    "SPLIT_RESOLVED_NO_EVENT": "current sources prove no split event",
}


def _anomalies(conn, start: str, end: str) -> list[dict]:
    return [{key: row[key] for key in
             ("kind", "ticker", "session", "detail",
              "last_written_run_id", "publication_version")}
            for row in anomaly_store.active_rows(
                conn, start=start, end=end, kinds=GATING_ANOMALY_KINDS)]


def _split_dispositions(conn, start: str, end: str, *, held: set[str],
                        pending: set[str], holdings_known: bool,
                        eligibility: EligibilityConfig) -> list[dict]:
    dispositions = []
    rows = anomaly_store.active_rows(
        conn, start=start, end=end, kinds=_SPLIT_DISPOSITION)
    for row in rows:
        kind, ticker = row["kind"], row["ticker"].upper()
        intersects = []
        if ticker in held:
            intersects.append("held_position")
        if ticker in pending:
            intersects.append("pending_terminal_episode")

        if kind in {"SPLIT_AUTHORITATIVE_APPLIED",
                    "SPLIT_CORROBORATED_DERIVED",
                    "SPLIT_RESOLVED_NO_EVENT"}:
            relevance, policy, blocks = (
                "resolved", "accepted canonical split evidence", False)
        elif kind == "SPLIT_DISAGREEMENT":
            relevance, policy, blocks = (
                "unresolved", "refuse: neither source may rewrite shares", True)
        elif intersects:
            relevance, policy, blocks = (
                "material",
                "hold: uncertain split intersects path-dependent state", True)
        else:
            relevance, policy, blocks = (
                "counterfactual_unproven",
                "hold: event-day floors and observed-book absence cannot prove "
                "full-interval split-treatment equivalence", True)

        dispositions.append({
            "category": _SPLIT_DISPOSITION[kind], "kind": kind,
            "ticker": ticker, "session": row["session"],
            "detail": row["detail"],
            "last_written_run_id": row["last_written_run_id"],
            "publication_version": row["publication_version"],
            "economic_relevance": relevance, "intersects": intersects,
            "policy": policy, "blocks_certification": blocks,
        })
    return dispositions


def audit(conn, *, start: str, end: str,
          held_tickers: Optional[Iterable[str]] = None,
          pending_terminal_tickers: Optional[Iterable[str]] = None,
          eligibility: EligibilityConfig | None = None) -> RejectionAudit:
    """Classify every refused ticker in [start, end].

    `held_tickers` / `pending_terminal_tickers` are `None` by DEFAULT, meaning
    the caller could not tell us — not that the book was empty. Pass `()` to
    assert an empty book explicitly.
    """
    cfg = eligibility or EligibilityConfig()
    holdings_known = (held_tickers is not None
                      and pending_terminal_tickers is not None)
    held = {str(t).upper() for t in (held_tickers or ())}
    pending = {str(t).upper() for t in (pending_terminal_tickers or ())}
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
        elif not holdings_known:
            # THE FAIL-CLOSED BRANCH. Without the book, the two checks that
            # could have made this ticker MATERIAL never ran, so no
            # immateriality proof about ADMISSION is worth anything: a held
            # name is not governed by the admission floors at all.
            verdict, why = (UNDETERMINED,
                            "holding intersection unavailable — the caller did "
                            "not supply the securities held or pending "
                            "terminal settlement over this interval, so the "
                            "two strongest materiality checks did not run")
        else:
            verdict, why = _immateriality(cfg, max_close, max_dv)

        per.append(TickerVerdict(
            ticker=t, rows=int(rows), sessions=int(sessions),
            first_session=str(lo) if lo else None,
            last_session=str(hi) if hi else None,
            reasons=sorted(str(r) for r in (reasons or []) if r),
            max_close=None if max_close is None else float(max_close),
            max_dollar_volume=None if max_dv is None else float(max_dv),
            verdict=verdict, why=why, intersects=intersects))

    return RejectionAudit(window=(start, end), rejected_rows=total_rows,
                          distinct_tickers=len(per), per_ticker=per,
                          truncated_evidence=_truncations(conn, start, end),
                          gating_anomalies=_anomalies(conn, start, end),
                          split_dispositions=_split_dispositions(
                              conn, start, end, held=held, pending=pending,
                              holdings_known=holdings_known, eligibility=cfg),
                          holdings_known=holdings_known)


def _immateriality(cfg: EligibilityConfig, max_close, max_dv) -> tuple[str, str]:
    """Prove the NEGATIVE or say UNDETERMINED. Never prove the positive.

    Each test is an UPPER BOUND over the values actually observed on the
    REFUSED sessions, so a pass means the security could not have been admitted
    on any session it was refused on, no matter what else is unknown about it.
    Nothing here can conclude that a rejection WOULD have been admitted — that
    would need the momentum series, the volatility and the issuer group, none
    of which survive a dropped row.

    There is deliberately NO history-length test. See the module docstring: the
    rejection table counts DROPPED sessions, and comparing that to a 126-session
    history requirement cleared securities that had a full history and one
    missing bar.
    """
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


__all__ = ["CLEAR", "GATING_ANOMALY_KINDS", "MATERIAL", "NO_IDENTITY",
           "NO_RAW_CLOSE", "RejectionAudit", "TickerVerdict", "UNDETERMINED",
           "audit"]
