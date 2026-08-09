"""Is the corpus fit for Wealth Core to plan on? Answered per CHECK, not per row.

`docs/sentinel-deployment.md` §8 says it plainly: **"126 rows" is not the test.**
A row count is satisfied by 126 rows of anything — a corpus with no as-traded
price, or with a three-week hole in the middle, or covering 400 securities
because identity resolution silently dropped the rest. Each of those produces a
plan, and the plan is wrong in a way nothing downstream reports.

So each clause of the contract is its own named check with its own verdict, and
the command fails on the FIRST unmet one while still reporting every result. An
operator needs to know which clause failed, not that "readiness = false".

## The checks, and what each one is actually protecting

```text
sessions            a canonical trading calendar exists at all
continuity          126 CONSECUTIVE sessions to the frontier — a gap in the
                    middle satisfies a count and breaks momentum
freshness           the frontier is recent. A stale corpus plans yesterday's
                    book with today's confidence
signal domain       SEP.close present: momentum and the trailing-stop peak
raw close           as-traded present: marking and the 4% admission size
raw open            as-traded open present: every fill happens at one
volume              ADV20 and signal dollar volume, both eligibility gates
identity            securities resolve to permatickers; unresolved bars are
                    dropped, and a mass drop looks exactly like a thin market
issuer keys         an issuer group per security, or the GOOG/GOOGL defect
                    cannot be detected at all
actions             corporate actions present near the frontier
```

`WARN` exists for the one case that is genuinely a judgement call — coverage
below the preferred 252-session window but above the required 126. Everything
else is PASS or FAIL, because a data contract that can be partially satisfied is
one nobody enforces.
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import Optional

from stock_strategy_shared.wealth_core.eligibility import EligibilityConfig
from stock_strategy_shared.wealth_core.signals import (
    LONG_LOOKBACK_SESSIONS,
    REQUIRED_CLOSES,
)

#: The engine's own requirement, not a number chosen here: `momentum` reads
#: closes[-(LONG_LOOKBACK_SESSIONS + 1)], so 127 closes are needed before a
#: security can be scored at all.
REQUIRED_SESSIONS = REQUIRED_CLOSES

#: §8's preferred startup window. Above REQUIRED and below this is a WARN: the
#: engine will run, with no margin for a vendor gap.
PREFERRED_SESSIONS = 252

#: Calendar days the frontier may lag before the corpus is stale. Four days
#: covers a normal weekend plus a holiday; beyond that, a daily fetch has been
#: failing and nobody noticed.
MAX_FRONTIER_AGE_DAYS = 4

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"


@dataclass
class Check:
    name: str
    status: str
    detail: str
    value: object = None

    @property
    def ok(self) -> bool:
        return self.status != FAIL


@dataclass
class Readiness:
    checks: list[Check] = field(default_factory=list)

    def add(self, name, status, detail, value=None) -> Check:
        c = Check(name, status, detail, value)
        self.checks.append(c)
        return c

    @property
    def ready(self) -> bool:
        return all(c.ok for c in self.checks) and bool(self.checks)

    @property
    def failures(self) -> list[Check]:
        return [c for c in self.checks if c.status == FAIL]


def _q1(conn, sql, params=()):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
    return row[0] if row else None


def check_readiness(conn, *, today: Optional[str] = None,
                    cfg: EligibilityConfig | None = None) -> Readiness:
    """Every clause of the §8 contract, against Sentinel's own corpus."""
    cfg = cfg or EligibilityConfig()
    r = Readiness()
    today = today or _dt.date.today().isoformat()

    frontier = _q1(conn, "SELECT MAX(session) FROM sentinel_bars")
    if frontier is None:
        r.add("sessions", FAIL,
              "the corpus is EMPTY. Run `feed-seed`; Wealth Core cannot plan "
              "from nothing, and an empty corpus reads downstream as a market "
              "with no eligible securities rather than as a missing load.")
        return r
    frontier = str(frontier)

    total = _q1(conn, "SELECT COUNT(DISTINCT session) FROM sentinel_bars")
    r.add("sessions", PASS, f"{total:,} distinct sessions to {frontier}", total)

    # ── continuity, which a row count cannot express ─────────────────────────
    # The last REQUIRED_SESSIONS sessions must be CONSECUTIVE in the corpus. A
    # three-week hole leaves the count intact and silently changes what a
    # 126-session lookback spans.
    with conn.cursor() as cur:
        cur.execute(
            "SELECT session FROM (SELECT DISTINCT session FROM sentinel_bars"
            " ORDER BY session DESC LIMIT %s) s ORDER BY session",
            (max(REQUIRED_SESSIONS, PREFERRED_SESSIONS),))
        recent = [str(x[0]) for x in cur.fetchall()]

    if len(recent) < REQUIRED_SESSIONS:
        r.add("continuity", FAIL,
              f"only {len(recent)} sessions available; the engine needs "
              f"{REQUIRED_SESSIONS} closes before any security can be scored "
              f"(momentum reads closes[-{LONG_LOOKBACK_SESSIONS + 1}])",
              len(recent))
    elif len(recent) < PREFERRED_SESSIONS:
        r.add("continuity", WARN,
              f"{len(recent)} sessions — above the required {REQUIRED_SESSIONS} "
              f"but below the preferred {PREFERRED_SESSIONS}. The engine will "
              f"run with no margin for a vendor gap.", len(recent))
    else:
        r.add("continuity", PASS, f"{len(recent)} consecutive sessions available",
              len(recent))

    # ── freshness ────────────────────────────────────────────────────────────
    age = (_dt.date.fromisoformat(today) - _dt.date.fromisoformat(frontier)).days
    if age > MAX_FRONTIER_AGE_DAYS:
        r.add("freshness", FAIL,
              f"the newest session is {frontier}, {age} days old. A daily fetch "
              f"has been failing: planning on this corpus produces yesterday's "
              f"book with today's confidence.", age)
    else:
        r.add("freshness", PASS, f"frontier {frontier} ({age}d old)", age)

    # ── the four price domains, over the WINDOW THAT WILL BE READ ────────────
    # Measured on the recent window rather than the whole corpus: a decade of
    # sparse early history would drown a hole in the sessions the engine is about
    # to use, which is the only stretch that can break today's plan.
    # Clamped: a corpus SHORTER than the required window has already failed
    # continuity, and the remaining checks should still report against whatever
    # it does hold rather than crash. A readiness report that raises tells the
    # operator less than the one failing check it was about to print.
    window_start = recent[-min(REQUIRED_SESSIONS, len(recent))]
    for column, label, protects in (
        ("close_signal", "signal domain", "momentum and the trailing-stop peak"),
        ("close_unadjusted", "raw close", "marking and the 4% admission size"),
        ("open_unadjusted", "raw open", "every fill"),
        ("volume", "volume", "ADV20 and signal dollar volume"),
    ):
        n, present = _domain_coverage(conn, column, window_start, frontier)
        share = 0.0 if not n else present / n
        if share < 0.90:
            r.add(label, FAIL,
                  f"{label} present on {share:.1%} of bars since {window_start}. "
                  f"It backs {protects}; below this the plan is not wrong in a "
                  f"way anything downstream reports.", round(share, 4))
        else:
            r.add(label, PASS, f"{share:.1%} coverage since {window_start}",
                  round(share, 4))

    # ── identity ─────────────────────────────────────────────────────────────
    securities = _q1(conn, "SELECT COUNT(DISTINCT security_id) FROM sentinel_bars"
                           " WHERE session >= %s", (window_start,))
    listed = _q1(conn, "SELECT COUNT(DISTINCT permaticker) FROM sentinel_universe")
    if not listed:
        r.add("identity", FAIL,
              "sentinel_universe is EMPTY, so every bar was keyed on its ticker "
              "or dropped. Ticker reuse splices two unrelated companies into one "
              "security and computes momentum across the seam.", 0)
    else:
        r.add("identity", PASS,
              f"{securities:,} securities priced, {listed:,} identities stored",
              securities)

    # ── issuer keys ──────────────────────────────────────────────────────────
    # Without these the GOOG/GOOGL class of defect is not merely present, it is
    # UNDETECTABLE: the duplicate-issuer invariant has nothing to compare.
    with_related = _q1(conn, "SELECT COUNT(*) FROM sentinel_universe"
                             " WHERE related_tickers IS NOT NULL") or 0
    if listed and with_related == 0:
        r.add("issuer keys", FAIL,
              "no security carries related_tickers, so every issuer key falls "
              "back to the permaticker and two share classes of one company "
              "cannot be detected as the same issuer.", 0)
    elif listed:
        r.add("issuer keys", PASS,
              f"{with_related:,} securities carry related tickers", with_related)

    # ── corporate actions ────────────────────────────────────────────────────
    recent_actions = _q1(conn, "SELECT COUNT(*) FROM sentinel_actions"
                               " WHERE session >= %s", (window_start,)) or 0
    if recent_actions == 0:
        r.add("actions", FAIL,
              f"no corporate actions since {window_start}. Over a window this "
              f"long that is a missing ingest, not a quiet market — splits and "
              f"terminal events would both go unseen.", 0)
    else:
        r.add("actions", PASS, f"{recent_actions:,} actions since {window_start}",
              recent_actions)

    return r


def _domain_coverage(conn, column: str, start: str, end: str) -> tuple[int, int]:
    # `column` is from a fixed literal tuple above, never caller input — the only
    # reason interpolating it here is not an injection.
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT COUNT(*), COUNT({column}) FROM sentinel_bars"
            " WHERE session BETWEEN %s AND %s", (start, end))
        n, present = cur.fetchone()
    return int(n or 0), int(present or 0)
