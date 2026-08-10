"""Sharadar SEP -> Wealth Core's price domains. PURE, and the file that must not
be wrong.

Retiring Alpha Vantage in favour of Sharadar is not a vendor swap — it is what
removes the single largest unmodelled risk in the deployment. Wealth Core was
CERTIFIED on Sharadar. While live read AV's `adjusted_close` (AV-vintage,
re-based only when AV restates) and certification read Sharadar's (uniformly
restated), the 30% trailing stop would have armed on peaks from a price history
the engine had never been tested against — a strategy change arriving as a data
change. Reading the certified corpus in production makes that class of divergence
structurally impossible rather than merely monitored.

THE MAPPING. Sharadar's column names do not mean what they appear to mean, and
getting them wrong is silent:

```text
SEP.close        SPLIT-adjusted, DIVIDEND-unadjusted   -> the SIGNAL domain
SEP.closeunadj   the actual as-traded price            -> MARKING + EXECUTION
SEP.open         SPLIT-adjusted, like close            -> scaled to as-traded
SEP.closeadj     split AND dividend adjusted           -> READ BY NOTHING
```

`closeadj` is a total-return series. In the signal domain it changes momentum on
every dividend payer; in the mark it sizes every 4% admission off the wrong
equity. It is not referenced anywhere in this package, and
`test_closeadj_is_never_read` enforces that — "not reading it at all is the only
reliable way not to read it by accident" is the rule the backtester's loader
arrived at, and it is repeated here rather than assumed.

**SEP.open is split-adjusted too.** Passing it through unscaled fills orders in
one domain and marks the resulting position in another. The as-traded open is
reconstructed by applying the same ratio the close carries.

This module is a deliberate re-implementation, not an import: the canonical
loader lives in `services/backtester/app/wealth_core_replay.py`, and Sentinel may
not import a retired Stocker service. `tests/sentinel/test_feed_domains.py`
pins the two against each other on the behaviour that matters, so the
duplication is guarded rather than trusted.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Iterator, Mapping, Optional

from stock_strategy_shared.wealth_core.feed import VendorBar

#: The SEP columns this package reads, and the domain each one serves. Declared
#: as data so a test can assert the set, rather than as prose a reader has to
#: trust.
SEP_DOMAIN_MAP = {
    "close": "signal (split-adjusted, dividend-unadjusted)",
    "closeunadj": "raw / as-traded (marking and execution)",
    "open": "split-adjusted open, scaled to as-traded",
    "volume": "eligibility",
}

#: Never read. Present so the prohibition is greppable and testable.
SEP_FORBIDDEN_COLUMNS = ("closeadj",)

#: Rounding in the vendor's own adjustment factor. Anything inside this is
#: reported as "no split" rather than as a fractional one — a spurious 1.003
#: would corrupt a share count silently and permanently.
SPLIT_TOLERANCE = 0.02


class RawPriceDomainUnavailable(RuntimeError):
    """No as-traded price, so the book cannot be marked or executed.

    An ERROR with a named remedy, never a substitution. The tempting fallback —
    mark with `close`, since it is "basically the price" — produces a complete,
    plausible book in split-adjusted currency, where a security that has split
    4:1 marks at a quarter of its real value and its weight stays wrong forever.
    """


def split_ratio_from_domains(
    prev_close: Optional[float], prev_raw: Optional[float],
    close: Optional[float], raw: Optional[float],
    tolerance: float = SPLIT_TOLERANCE,
) -> float:
    """Recover the split ratio from the two domains diverging.

    SEP carries no split column, but it carries a split-ADJUSTED and an
    as-TRADED close, and the ratio between them IS the vendor's cumulative
    adjustment factor. The corpus is a snapshot under the vendor's CURRENT
    adjustment, so for a 2:1 on date D every row before D has
    closeunadj/close = 2 and every row from D on has 1. The factor therefore
    FALLS through a forward split, and the share ratio is before/after — not
    after/before, which points the share count the wrong way and halves a
    position on a 2:1.
    """
    vals = (prev_close, prev_raw, close, raw)
    if any(v is None or v <= 0 for v in vals):
        return 1.0
    before = prev_raw / prev_close
    after = raw / close
    if after <= 0:
        return 1.0
    ratio = before / after
    if abs(ratio - 1.0) <= tolerance:
        return 1.0
    # Splits are near-integral ratios or their reciprocals. Snapping keeps a
    # 1.9997 from becoming a share count nobody can reconcile.
    snapped = round(ratio) if ratio >= 1.0 else 1.0 / round(1.0 / ratio)
    return float(snapped) if snapped > 0 else 1.0


def _f(v) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None          # NaN -> None


@dataclass(frozen=True)
class NormalisedBar:
    """A `VendorBar` plus the SIGNAL close, which VendorBar does not carry.

    The engine DERIVES its signal series from raw closes and split ratios
    (`feed.to_daily_bar` reads `series.signal_closes[-1]`), so it does not need
    SEP.close passed in. Storage does:

      * `split_ratio_from_domains` recovers a split from the two domains
        DIVERGING, and it needs the previous session's pair. A daily ingest
        starts with no previous observation, so without a stored signal close a
        split landing on the first bar of the window is invisible;
      * it is one of the four documented domains, and a corpus that silently
        holds three of them cannot be checked for holding four.

    Kept beside the VendorBar rather than added to it: VendorBar is certified,
    shared with the wind tunnel and the live book, and widening it to suit a
    loader would change a type three engines agree on.
    """

    vendor: VendorBar
    close_signal: Optional[float] = None


@dataclass
class NormalisationReport:
    """What the mapping did, so a thin day is visible rather than inferred."""

    rows: int = 0
    bars: int = 0
    dropped_no_identity: int = 0
    dropped_no_raw_close: int = 0
    splits_detected: int = 0
    # THE DROPPED ROWS THEMSELVES, not just how many.
    #
    # A count cannot answer the question the terminal-identity accounting has to
    # ask: "did the vendor price this ticker in the window?" A SEP row whose
    # identity fails is discarded BEFORE `sentinel_bars`, so the only surviving
    # trace was `dropped_no_identity += 1` — and S4 then read its relevance
    # population from `sentinel_bars`, saw nothing for that ticker, and filed
    # its terminal action as SECURITY_ABSENT_FROM_CORPUS. The exclusion built to
    # be un-hideable was hidden by the ingest that ran before it.
    #
    # (ticker, session, reason). Bounded by `max_rejections` so a catastrophic
    # identity outage cannot make the report itself the memory problem; the
    # COUNT above stays exact regardless, and truncation is reported.
    rejections: list = field(default_factory=list)
    rejections_truncated: int = 0
    # (ticker, session) -> the ratio INFERRED from the price domains, kept even
    # when an authoritative ACTIONS value overrides it. Two independent sources
    # agreeing is worth more than one asserting, and a disagreement is a fact
    # about the corpus that has to be reportable rather than resolved in silence.
    derived_splits: dict = field(default_factory=dict)

    #: Cap on RETAINED rejection rows. The count is unbounded and exact; only
    #: the per-row detail is capped.
    max_rejections: int = 50_000

    @property
    def raw_close_coverage(self) -> float:
        return 0.0 if not self.rows else (self.rows - self.dropped_no_raw_close) / self.rows

    def note_rejection(self, ticker: str, session: str, reason: str, *,
                       close: float | None = None,
                       volume: float | None = None) -> None:
        """Record a refused row, WITH the price and volume it carried.

        The price is not decoration. Certification has to answer "could this
        dropped security have changed the universe, the ranking or the
        selection?", and that question is decided by the eligibility floors —
        an as-traded price, a dollar volume, a session count. Recording only
        the ticker and the date leaves every rejection permanently
        UNDETERMINED, which under a fail-closed rule blocks the rehearsal
        rather than informing it.
        """
        if len(self.rejections) >= self.max_rejections:
            self.rejections_truncated += 1
            return
        self.rejections.append({"ticker": str(ticker), "session": str(session),
                                "reason": reason, "close": close,
                                "volume": volume})


def normalise_sep_rows(
    rows: Iterable[Mapping],
    *,
    resolve_identity=None,
    dividends: Mapping[tuple[str, str], float] | None = None,
    authoritative_splits: Mapping[tuple[str, str], float] | None = None,
    report: NormalisationReport | None = None,
) -> Iterator[NormalisedBar]:
    """SEP rows -> `NormalisedBar`s, in (session, ticker) order.

    `rows` must already be ordered by (date, ticker): the split ratio is
    recovered from the PREVIOUS observation of the same security, so an
    out-of-order stream silently produces ratios against the wrong bar. The
    caller orders in SQL, where it is free.

    `resolve_identity(ticker, session) -> security_id | None` keys the security
    by permanent identity. Unresolvable bars are DROPPED and counted, never
    fallen back to the ticker — a fallback re-introduces the ticker-reuse splice
    on precisely the securities whose identity is doubtful.
    """
    rep = report if report is not None else NormalisationReport()
    prev: dict[str, tuple[Optional[float], Optional[float]]] = {}

    for r in rows:
        rep.rows += 1
        session = str(r["date"])
        ticker = str(r["ticker"])
        sid = resolve_identity(ticker, session) if resolve_identity else ticker
        close = _f(r.get("close"))
        raw = _f(r.get("closeunadj") if "closeunadj" in r else r.get("close_unadjusted"))
        volume = _f(r.get("volume"))
        if sid is None:
            rep.dropped_no_identity += 1
            rep.note_rejection(ticker, session, "NO_IDENTITY",
                               close=raw, volume=volume)
            continue

        if raw is None or raw <= 0:
            # Not silently substituted. A bar with no as-traded price cannot be
            # marked or executed; the engine already handles "no print, no fill"
            # correctly, and that is the honest representation.
            #
            # RECORDED as evidence for the same reason the identity failure is.
            # This drop left nothing behind at all, so a certification asking
            # "how many priced rows did the ingest refuse" could only ever see
            # half the answer — and the half it could not see is the one where
            # the vendor DID present the security.
            rep.dropped_no_raw_close += 1
            rep.note_rejection(ticker, session, "NO_RAW_CLOSE",
                               close=None, volume=volume)
            continue

        p_close, p_raw = prev.get(sid, (None, None))
        ratio = split_ratio_from_domains(p_close, p_raw, close, raw)
        if ratio != 1.0:
            rep.derived_splits[(ticker, session)] = ratio
        if authoritative_splits is not None:
            # ACTIONS decides when present; the derived ratio stays as the
            # cross-check. Two independent sources agreeing is worth more than
            # one asserting.
            ratio = float(authoritative_splits.get((ticker, session), ratio))
        if ratio != 1.0:
            rep.splits_detected += 1
        prev[sid] = (close, raw)

        # SEP.open is SPLIT-ADJUSTED like close. The as-traded open is it scaled
        # by the same factor the close carries on this bar — raw/close — NOT by
        # the split ratio, which describes a change BETWEEN bars.
        op_adj = _f(r.get("open"))
        raw_open = None
        if op_adj is not None and close is not None and close > 0:
            raw_open = op_adj * (raw / close)

        rep.bars += 1
        yield NormalisedBar(close_signal=close, vendor=VendorBar(
            session=session,
            security_id=sid,
            ticker=ticker,
            raw_close=raw,
            raw_open=raw_open,
            volume=_f(r.get("volume")),
            split_ratio=ratio,
            dividend_per_share=float(
                (dividends or {}).get((ticker, session), 0.0) or 0.0),
        ))


def assert_raw_price_domain(report: NormalisationReport,
                            minimum_coverage: float = 0.90) -> float:
    """Refuse a feed that is mostly missing the as-traded price.

    A handful of gaps is ordinary vendor noise the engine handles. A feed that is
    mostly NULL is a DEPLOYMENT STATE, and reporting it as thousands of
    individual data gaps buries the one fact that matters.
    """
    coverage = report.raw_close_coverage
    if report.rows and coverage < minimum_coverage:
        raise RawPriceDomainUnavailable(
            f"as-traded close present on only {coverage:.1%} of {report.rows} "
            f"SEP rows (need {minimum_coverage:.0%}). The book cannot be marked "
            f"or executed. This is a fetch problem, not a data-quality one: "
            f"SEP.closeunadj is the required column. Substituting SEP.close "
            f"would produce a complete, plausible book in split-adjusted "
            f"currency and value every post-split security wrong forever."
        )
    return coverage
