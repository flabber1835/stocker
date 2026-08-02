"""Vendor shadow — how different are Alpha Vantage and Sharadar, really?

A cutover from AV to Sharadar is not a data swap. Live's `adjusted_close` is
AV-VINTAGE (written once, re-based only when AV restates it), while Sharadar's
`closeadj` is uniformly restated across all history. Swapping them silently
re-bases every price, which moves momentum, low_volatility, near_high, every
drawdown, and every peak the trailing stop reads — on a book whose exit policy
IS the peak. The migration would arrive as an unannounced strategy change and
the first evidence of it would be sales.

So this module measures the difference instead of estimating it. Everything here
is PURE: frames in, numbers out, no DB and no clock. The caller (the pipeline's
`/jobs/vendor-shadow`) computes BOTH sides with the same `compute_all_factors`
and `rank_universe` objects in one process, which is what makes the output
interpretable — whatever it reports is a DATA difference, because no code
difference is left for it to be.

Read the results in this order, not in the order they are computed:

  1. `target`  — did it reach the BOOK?
  2. `overlap` — did it reach the DECISION?
  3. `ranking` / `factors` — where did it land?
  4. `price_adjustment` — the corporate-action probe, and usually the cause.

Rank correlation is deliberately NOT the headline. A diff that leaves the rank
IC at 0.99 while moving three names through the top 25 changes the portfolio; one
that shuffles ranks 400-2000 does not.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable, Mapping, Sequence

import pandas as pd


# ── set comparisons ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SetDiff:
    """Both directions, always. 'How many names differ' hides which vendor is
    the one adding them, and that is the whole diagnosis: names only AV has are
    usually listing-metadata differences, names only Sharadar has are usually
    coverage."""
    n_live: int
    n_shadow: int
    n_both: int
    only_live: list[str]
    only_shadow: list[str]

    @property
    def jaccard(self) -> float | None:
        union = self.n_live + self.n_shadow - self.n_both
        return None if union <= 0 else self.n_both / union


def diff_sets(live: Iterable[str], shadow: Iterable[str],
              *, sample: int = 25) -> SetDiff:
    """Membership diff. `sample` bounds the NAMED tickers so a 2000-name
    universe mismatch produces a readable row rather than a wall — the counts
    stay exact, only the listing is truncated."""
    a, b = set(live or ()), set(shadow or ())
    return SetDiff(n_live=len(a), n_shadow=len(b), n_both=len(a & b),
                   only_live=sorted(a - b)[:sample],
                   only_shadow=sorted(b - a)[:sample])


def overlap_at_k(live_ranked: Sequence[str], shadow_ranked: Sequence[str],
                 k: int) -> float | None:
    """Share of the live top-k that also appears in the shadow top-k.

    The measure that matters for a 25-name book: two rankings can correlate at
    0.99 across 2000 tickers and still disagree about three of the names that
    get bought. None when either side is shorter than k — a partial top-k would
    read as disagreement when it is really missing data.
    """
    if k <= 0 or len(live_ranked or ()) < k or len(shadow_ranked or ()) < k:
        return None
    return len(set(live_ranked[:k]) & set(shadow_ranked[:k])) / k


# ── rank agreement ───────────────────────────────────────────────────────────

def spearman(a: pd.Series, b: pd.Series) -> float | None:
    """Spearman rank correlation over the tickers BOTH sides scored.

    Aligned on the index, never on position. The two frames are built from
    different vendors' universes, so positional alignment would silently
    correlate one company's rank against another's — a wrong number that looks
    entirely plausible.
    """
    if a is None or b is None:
        return None
    joined = pd.concat([pd.Series(a).astype(float),
                        pd.Series(b).astype(float)], axis=1, join="inner").dropna()
    if len(joined) < 3 or joined.iloc[:, 0].nunique() < 2 or joined.iloc[:, 1].nunique() < 2:
        return None
    # Rank then Pearson, rather than `method="spearman"`. Pandas routes the named
    # method through scipy, which is NOT a dependency of this image — the same
    # reason main.py's own `_spearman` is written this way. Identical result.
    c = joined.iloc[:, 0].rank().corr(joined.iloc[:, 1].rank())
    return None if c is None or (isinstance(c, float) and math.isnan(c)) else float(c)


def rank_movers(live_rank: Mapping[str, float], shadow_rank: Mapping[str, float],
                *, top: int = 20) -> list[dict]:
    """The names whose rank moves most between vendors, worst first.

    Reported because an aggregate correlation cannot be acted on. A cutover
    decision needs to look at the specific tickers and attribute each to a
    corporate action, a fundamentals vintage, or a genuine coverage gap.
    """
    out = []
    for t, lr in (live_rank or {}).items():
        sr = (shadow_rank or {}).get(t)
        if sr is None or lr is None:
            continue
        try:
            lr_f, sr_f = float(lr), float(sr)
        except (TypeError, ValueError):
            continue
        if lr_f != lr_f or sr_f != sr_f:      # NaN
            continue
        out.append({"ticker": t, "live_rank": int(lr_f), "shadow_rank": int(sr_f),
                    "delta": int(sr_f - lr_f)})
    out.sort(key=lambda r: (-abs(r["delta"]), r["ticker"]))
    return out[:top]


# ── the corporate-action probe ───────────────────────────────────────────────

@dataclass(frozen=True)
class PriceDiff:
    """One ticker's price-series agreement between the two vendors.

    `return_corr` is the headline: adjusted-close LEVELS legitimately differ by a
    constant factor (different adjustment epochs), so comparing levels would flag
    every ticker. Returns are invariant to that factor — unless an actual
    corporate action is handled differently, which is exactly what we want to
    catch.

    `ratio_drift` is the second half. A split or spinoff that one vendor applies
    and the other does not shows up as a STEP in the live/shadow price ratio;
    max-over-min captures the step, while a smooth dividend re-basing produces a
    small, gradual value.
    """
    ticker: str
    n_sessions: int
    return_corr: float | None
    ratio_drift: float | None
    max_abs_return_gap: float | None

    @property
    def suspicious(self) -> bool:
        """Deliberately generous. This flags candidates for a human to attribute,
        and a missed corporate action is far more costly than an extra name on a
        list someone reads once."""
        if self.n_sessions < MIN_PRICE_SESSIONS:
            return False
        if self.return_corr is not None and self.return_corr < RETURN_CORR_FLOOR:
            return True
        if self.ratio_drift is not None and self.ratio_drift > RATIO_DRIFT_CEILING:
            return True
        return False


# A ticker with fewer sessions than this is a coverage difference, not an
# adjustment difference, and reporting it as the latter would bury the real ones.
MIN_PRICE_SESSIONS = 30
# Two vendors' daily returns on the same security should agree almost exactly.
# 0.99 leaves room for rounding and an odd halted session without excusing a
# genuinely different adjustment.
RETURN_CORR_FLOOR = 0.99
# max(ratio)/min(ratio) over the window. A pure dividend re-basing drifts by
# ~0.5-2%/yr; anything past 5% over a one-year window is a step, i.e. an action
# one side applied and the other did not.
RATIO_DRIFT_CEILING = 1.05


def compare_price_series(ticker: str,
                         live: Mapping, shadow: Mapping) -> PriceDiff:
    """Compare one ticker's adjusted-close history across vendors.

    Both inputs are {date: adjusted_close}. Only dates present in BOTH are used:
    a session one vendor lacks is a coverage gap, and treating it as a price
    disagreement would conflate two very different problems.
    """
    a = pd.Series({k: v for k, v in (live or {}).items() if v is not None}, dtype=float)
    b = pd.Series({k: v for k, v in (shadow or {}).items() if v is not None}, dtype=float)
    joined = pd.concat([a, b], axis=1, join="inner").sort_index()
    joined = joined[(joined.iloc[:, 0] > 0) & (joined.iloc[:, 1] > 0)]
    n = len(joined)
    if n < 3:
        return PriceDiff(ticker, n, None, None, None)

    ra = joined.iloc[:, 0].pct_change().dropna()
    rb = joined.iloc[:, 1].pct_change().dropna()
    corr = None
    if len(ra) >= 3 and ra.nunique() > 1 and rb.nunique() > 1:
        c = ra.corr(rb)
        corr = None if c is None or math.isnan(c) else float(c)

    ratio = joined.iloc[:, 0] / joined.iloc[:, 1]
    lo, hi = float(ratio.min()), float(ratio.max())
    drift = None if not (lo > 0) else hi / lo

    gap = (ra - rb).abs()
    return PriceDiff(ticker, n, corr, drift,
                     None if gap.empty else float(gap.max()))


# ── the whole report ─────────────────────────────────────────────────────────

@dataclass
class ShadowReport:
    """Everything one session's comparison produced. Persisted verbatim as JSON;
    no field is derived at read time, so a stored row cannot disagree with the
    run that made it."""
    score_date: str
    config_hash: str | None = None
    universe: dict = field(default_factory=dict)
    factors: dict = field(default_factory=dict)
    ranking: dict = field(default_factory=dict)
    target: dict = field(default_factory=dict)
    price_adjustment: dict = field(default_factory=dict)
    caveats: list[str] = field(default_factory=list)

    def verdict(self) -> str:
        """A one-line human summary. Ordered by what a cutover would BREAK, not
        by what is easiest to measure: the book first, the decision second, the
        rank last."""
        t = self.target.get("jaccard")
        o = self.ranking.get("overlap_at_25")
        if t is not None and t < 0.9:
            return f"TARGET DIFFERS — selected-set jaccard {t:.2f}"
        if o is not None and o < 0.9:
            return f"TOP-25 DIFFERS — overlap {o:.0%}"
        n = len(self.price_adjustment.get("suspicious", []))
        if n:
            return f"prices agree at the rank level, but {n} ticker(s) need attribution"
        return "no material difference detected this session"

    def to_dict(self) -> dict:
        return {"score_date": self.score_date, "config_hash": self.config_hash,
                "universe": self.universe, "factors": self.factors,
                "ranking": self.ranking, "target": self.target,
                "price_adjustment": self.price_adjustment,
                "caveats": self.caveats, "verdict": self.verdict()}


def summarize_price_diffs(diffs: Sequence[PriceDiff], *, sample: int = 25) -> dict:
    """Aggregate the per-ticker probes into one reportable block.

    The suspicious LIST is capped, the suspicious COUNT is not — a cap that
    silently truncates the count would read as "we checked and it is fine",
    which is the failure mode this whole exercise exists to avoid.
    """
    usable = [d for d in diffs if d.n_sessions >= MIN_PRICE_SESSIONS]
    sus = [d for d in usable if d.suspicious]
    corrs = [d.return_corr for d in usable if d.return_corr is not None]
    return {
        "n_compared": len(diffs),
        "n_usable": len(usable),
        "n_too_short": len(diffs) - len(usable),
        "median_return_corr": (None if not corrs
                               else float(pd.Series(corrs).median())),
        "min_return_corr": None if not corrs else float(min(corrs)),
        "n_suspicious": len(sus),
        "suspicious": [
            {"ticker": d.ticker, "n_sessions": d.n_sessions,
             "return_corr": None if d.return_corr is None else round(d.return_corr, 5),
             "ratio_drift": None if d.ratio_drift is None else round(d.ratio_drift, 5),
             "max_abs_return_gap": (None if d.max_abs_return_gap is None
                                    else round(d.max_abs_return_gap, 5))}
            for d in sorted(sus, key=lambda d: (d.return_corr if d.return_corr
                                                is not None else -1))[:sample]
        ],
    }
