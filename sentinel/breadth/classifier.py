"""The recovered Sentinel 1.1 per-security breadth classifier.

## Provenance — this is a TRANSCRIPTION, and of exactly one thing

The authority is the recovered classifier as it stands in the repository:

```text
docs/sentinel-reference-implementation/sentinel_1p1_standalone.py:526-546
    labelled in its own source "Exact recovered breadth classifier, computed
    directly from current shadow holdings"
docs/sentinel-breadth-reconstruction/recovered_breadth_classifier.py
    the same rules as a pandas module, byte-identical to the copy under
    docs/sentinel-reproduction-kit/04_EXACT_BREADTH_RECOVERY/
```

Both were reached by different routes and agree. Neither is read at runtime —
this module is pure and imports nothing outside the stdlib — but
`tests/sentinel/test_breadth_classifier.py` runs a randomised DIFFERENTIAL test
against the pandas artefact, so a divergence introduced here fails the suite
rather than waiting for the NAS.

**The predicates below were transcribed from that source and never from prose.**
`docs/sentinel-controller-certification.md` §7b records why that distinction is
load-bearing: the architecture document's own summary of GREEN states inclusive
comparisons and omits the age escape entirely, and an implementation built from
it would misclassify every holding younger than 63 sessions — precisely the band
a book rebuilding after a recovery consists of.

## Status: RECOVERED, IMPLEMENTED, NOT YET CORPUS-CERTIFIED

```text
classifier logic          RECOVERED    exact, in the repo, two agreeing sources
this production module    IMPLEMENTED  falsified offline by the tests below
raw-corpus parity         REQUIRES NAS 7,061-session reproduction against the
                                       corrected lineage is a separate step
```

Offline falsification is not corpus certification. Nothing here may be cited as
reproducing the frozen tape until the authoritative Sharadar run does it session
by session — see `docs/sentinel-deployment.md` §12 item F.

## Three properties that are silent if got wrong

```text
RED FEEDS ONLY SECTOR STRESS. It never enters green_b or damaged_b directly.
    Its entire job is the numerator of its sector's stress fraction

AMBER IS NOT THE COMPLEMENT OF GREEN. They are disjoint but do not partition
    the book: green_b + damaged_b need not sum to 1, and a classifier that
    forces them to has changed the strategy

THE DENOMINATOR IS len(held) — the CURRENT shadow holdings on the session, not
    a `holdings` column and not the slot count. The forensic pass found that
    only this denominator makes every frozen fraction resolve to an integer
```

## What is NOT here, deliberately

The historical `position_features()` returned more than Sentinel consumes. Its
`priority` cohort ranking is not reproduced and must not be invented: Sentinel's
entire breadth dependency is `mean(amber)` and `mean(green)`, it never asks
which damaged holding is worst, and a per-name ranking has nowhere to be
consumed even in principle. This module exposes what Sentinel needs and stops
there. That is a narrower API than the old helper, not a missing piece of one.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Sequence, Tuple

from .returns import is_available

#: GREEN. Strict on both, and the strictness is material: a book marked exactly
#: at its peak (own_dd == 0.0) is common rather than exotic, and `>=` would
#: admit a name whose 21-session return is precisely flat.
GREEN_OWN_DD_STRICTLY_ABOVE = -0.075
GREEN_R21_STRICTLY_ABOVE = 0.0
GREEN_R63_STRICTLY_ABOVE = 0.0

#: The age-63 GREEN exemption. A holding younger than this many completed
#: sessions has no valid 63-session ownership comparison, so GREEN's r63
#: condition is WAIVED for it entirely — not defaulted, not treated as failing.
#: Admissions are one per session at 4% of equity, so a book rebuilding after a
#: recovery is mostly positions inside this band; dropping the clause shifts
#: green_b on exactly the sessions the recovery ramp is reading.
GREEN_R63_REQUIRED_FROM_AGE = 63

#: RED. Inclusive on drawdown, STRICT on r21 — `r21 == 0.0` is not red.
RED_OWN_DD_AT_OR_BELOW = -0.10
RED_R21_STRICTLY_BELOW = 0.0

#: AMBER's two individual-damage clauses, both inclusive.
AMBER_OWN_DD_AT_OR_BELOW = -0.10
AMBER_R21_AT_OR_BELOW = -0.03

#: AMBER's sector escalation. Inclusive: a sector exactly half RED escalates.
SECTOR_STRESS_AT_OR_ABOVE = 0.50


@dataclass(frozen=True)
class Holding:
    """One shadow holding on one decision date.

    Every metric may be None or NaN, both meaning UNAVAILABLE. They are not
    zero: an unavailable `own_dd` must fail GREEN's drawdown test and AMBER's
    damage test alike, which is what the reference's `np.isfinite` guards do.
    """

    ticker: str
    sector: Optional[str]
    own_dd: Optional[float]
    r21: Optional[float]
    r63: Optional[float]
    age_sessions: int


@dataclass(frozen=True)
class HoldingLabel:
    """A holding's three flags plus the sector stress that was applied to it."""

    ticker: str
    sector: Optional[str]
    green: bool
    red: bool
    amber: bool
    sector_stress: float


@dataclass(frozen=True)
class SessionBreadth:
    """One session's breadth. `damaged_breadth`/`green_breadth` are the only
    two values Sentinel's controller reads; the counts are kept beside them so
    a parity failure can be localised to a holding rather than a fraction."""

    damaged_breadth: float
    green_breadth: float
    denominator: int
    greens: int
    ambers: int
    reds: int
    labels: Tuple[HoldingLabel, ...]


def is_green(h: Holding) -> bool:
    """`standalone:536`.

    Note the shape of the age clause: `age < 63 OR r63 > 0`. A young holding is
    green on the drawdown and r21 conditions ALONE. It is not "green with r63
    assumed positive" — r63 is not consulted at all.
    """
    return (
        is_available(h.own_dd)
        and h.own_dd > GREEN_OWN_DD_STRICTLY_ABOVE
        and is_available(h.r21)
        and h.r21 > GREEN_R21_STRICTLY_ABOVE
        and (
            h.age_sessions < GREEN_R63_REQUIRED_FROM_AGE
            or (is_available(h.r63) and h.r63 > GREEN_R63_STRICTLY_ABOVE)
        )
    )


def is_red(h: Holding) -> bool:
    """`standalone:537`. Severe individual damage, and the input to sector
    stress. RED is never counted into either breadth fraction directly."""
    return (
        is_available(h.own_dd)
        and h.own_dd <= RED_OWN_DD_AT_OR_BELOW
        and is_available(h.r21)
        and h.r21 < RED_R21_STRICTLY_BELOW
    )


def sector_stress(holdings: Sequence[Holding]) -> Dict[Optional[str], float]:
    """RED fraction within each sector on this decision date.

    `standalone:539-540`, `standalone:543`. The denominator is every holding in
    the sector, red or not. Sectors are whatever the shadow says, `None`
    included — an unknown sector is its own bucket rather than being dropped,
    because dropping it would silently shrink a stressed sector's denominator.
    """
    counts: Dict[Optional[str], list] = {}
    for h in holdings:
        bucket = counts.setdefault(h.sector, [0, 0])
        bucket[0] += int(is_red(h))
        bucket[1] += 1
    return {sec: (red / held if held else 0.0) for sec, (red, held) in counts.items()}


def is_amber(h: Holding, stress: float, green: bool) -> bool:
    """`standalone:544`. The label Sentinel consumes as `damaged`.

    Three clauses, OR-ed. The third is the escalation the forensic pass proved
    must exist: its reconstruction of the first two was short by 0.403 holdings
    per session and NEVER over-predicted, and a one-sided shortfall means the
    original was `damaged_core OR <something>` rather than a different base
    rule. `AND NOT green` is what keeps a healthy name in a burning sector out
    of the damaged count.
    """
    return (
        (is_available(h.own_dd) and h.own_dd <= AMBER_OWN_DD_AT_OR_BELOW)
        or (is_available(h.r21) and h.r21 <= AMBER_R21_AT_OR_BELOW)
        or (stress >= SECTOR_STRESS_AT_OR_ABOVE and not green)
    )


def session_breadth(holdings: Sequence[Holding]) -> SessionBreadth:
    """Classify one session's holdings and reduce them to the two scalars.

    `standalone:526-546`. An EMPTY BOOK is 0.0 / 0.0, not NaN and not an error
    (`standalone:546`). That branch is reachable in production — a cold start
    before the first fill, and any session where the shadow holds nothing — and
    0.0 damaged with 0.0 green is correctly read by the controller as "no
    damage evidence", not as a healthy book, because its healthy triple also
    requires `green_breadth >= min_green_breadth`.
    """
    stress = sector_stress(holdings)
    labels = []
    greens = ambers = reds = 0
    for h in holdings:
        green = is_green(h)
        red = is_red(h)
        s = stress.get(h.sector, 0.0)
        amber = is_amber(h, s, green)
        greens += int(green)
        ambers += int(amber)
        reds += int(red)
        labels.append(HoldingLabel(h.ticker, h.sector, green, red, amber, s))

    n = len(holdings)
    return SessionBreadth(
        damaged_breadth=(ambers / n if n else 0.0),
        green_breadth=(greens / n if n else 0.0),
        denominator=n,
        greens=greens,
        ambers=ambers,
        reds=reds,
        labels=tuple(labels),
    )


def breadth_observation_fields(holdings: Sequence[Holding]) -> Dict[str, float]:
    """The seam into `controller.Observation`, and nothing more.

    Returns `{"damaged_breadth": ..., "green_breadth": ...}` — the two fields
    the controller reads. It is a mapping rather than a constructed Observation
    on purpose: this module must not acquire a dependency on the controller, and
    the caller that assembles a full Observation also owns the shadow returns,
    the drawdown and the SPY regime.

    This makes the forward chain POSSIBLE. It does not activate it:

    ```text
    Sharadar -> Wealth Core shadow -> THIS MODULE -> damaged/green
             -> SPY regime -> Observation -> controller.step
                                                   ^
                            the `decide` seam stays empty until the NAS run
                            certifies the chain end to end (certification §7c)
    ```
    """
    b = session_breadth(holdings)
    return {"damaged_breadth": b.damaged_breadth, "green_breadth": b.green_breadth}
