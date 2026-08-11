"""Finding and fixing split ratios the windowed ingest got wrong.

PREVENTION IS NOT REPAIR. Seeding `prev` from the corpus stops the leading edge
of the next window deriving "no split", and the non-downgrade rule in
`_BAR_UPSERT` stops a future run overwriting a good value. Neither touches what
is already stored, and a correct loader reading a corrupted stored value is still
wrong — the certified Wealth Core path reads `split_ratio` straight out of
`sentinel_bars` and turns it into a SHARE COUNT.

So this module answers two different questions, and it is careful about which one
it can actually answer:

```text
audit()     which stored bars are PROVABLY wrong?          a LOWER BOUND
repair()    make those bars agree with ACTIONS             exact, and audited
```

## Why the audit is only a lower bound, and why it is still worth having

`sentinel_actions` is an independent record of corporate actions, so any bar
holding `split_ratio = 1.0` on a session where ACTIONS states a split is
CONFIRMED wrong — two sources, one of them authoritative, in flat contradiction.
That set can be produced with one query and no re-fetch.

What it CANNOT see is the population most at risk: splits ACTIONS never recorded
at all. Those are exactly the ones the derived fallback existed to catch, and
exactly the ones the empty-`prev` bug silently dropped. There is no local witness
for them — establishing that set requires re-deriving the ratio from a contiguous
re-fetch, which is `reseed`, not `audit`.

Reporting a lower bound is therefore the honest shape: it SIZES the damage
cheaply, it gives the repair an exact acceptance test (`confirmed == 0`
afterwards), and it never licenses the claim that the corpus is clean. That claim
needs the reseed.

## Why re-running `daily` is not a repair

The daily window opens 14 days behind the frontier. Re-running it re-derives the
same leading edge against the same absent predecessor and reproduces the defect
one window further along. A repair has to be a CONTIGUOUS re-derivation with the
predecessor supplied — which, now that `normalise_sep_rows` accepts
`prior_observations`, an ordinary `seed` over the affected span performs.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sentinel.feed import actions_map, calendar


@dataclass(frozen=True)
class Discrepancy:
    """One bar whose stored ratio contradicts the authoritative ACTIONS row."""

    security_id: str
    ticker: str
    session: str
    stored: float
    authoritative: float

    @property
    def is_missing_split(self) -> bool:
        """A split ACTIONS states and the corpus does not hold.

        Distinguished from a mere disagreement because it is the signature of
        the empty-`prev` defect specifically: the derived path produced 1.0
        because it had nothing to compare against.
        """
        return self.stored == 1.0

    def to_dict(self) -> dict:
        return {"security_id": self.security_id, "ticker": self.ticker,
                "session": self.session, "stored": self.stored,
                "authoritative": self.authoritative,
                "kind": "MISSING_SPLIT" if self.is_missing_split
                        else "RATIO_DISAGREEMENT"}


@dataclass
class AuditResult:
    start: str
    end: str
    bars_examined: int = 0
    actions_splits: int = 0
    confirmed: list = field(default_factory=list)
    seam_anomalies: list = field(default_factory=list)

    @property
    def clean(self) -> bool:
        """No PROVABLE corruption. Deliberately not named `certifiable`.

        A clean audit means the corpus does not contradict ACTIONS. It does not
        mean the corpus is correct: an unrecorded split contradicts nothing.
        """
        return not self.confirmed

    def to_dict(self) -> dict:
        return {
            "window": [self.start, self.end],
            "bars_examined": self.bars_examined,
            "actions_splits_in_window": self.actions_splits,
            "confirmed_discrepancies": len(self.confirmed),
            "missing_splits": sum(1 for d in self.confirmed if d.is_missing_split),
            "ratio_disagreements": sum(1 for d in self.confirmed
                                       if not d.is_missing_split),
            "seam_anomalies_recorded": len(self.seam_anomalies),
            "clean": self.clean,
            "bound": "LOWER — a split ACTIONS never recorded is invisible here; "
                     "only a contiguous reseed can rule that out",
            "discrepancies": [d.to_dict() for d in self.confirmed],
            "seam_anomalies": self.seam_anomalies,
        }


def _authoritative_splits(conn, start: str, end: str) -> dict:
    """ACTIONS splits for the window, snapped onto real sessions.

    Snapped with the EXCHANGE CALENDAR, exactly as the ingest does, and for the
    same reason: an ex-date can fall on a weekend or a holiday, and comparing
    against the raw date would report every such split as missing from a corpus
    that holds it correctly on the following session. Using the ingest's own
    mapping is what makes the audit's answer the same question the ingest asked.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT ticker, session, action, value FROM sentinel_actions"
                    " WHERE session BETWEEN %s AND %s", (start, end))
        rows = [{"ticker": t, "date": str(d), "action": a, "value": v}
                for t, d, a, v in cur.fetchall()]
    return actions_map.split_ratios_from_actions(
        rows, calendar.sessions_in_range(start, end))


def audit(conn, *, start: str, end: str) -> AuditResult:
    """Which stored bars provably contradict ACTIONS over `[start, end]`?"""
    result = AuditResult(start=start, end=end)
    splits = _authoritative_splits(conn, start, end)
    result.actions_splits = len(splits)

    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM sentinel_bars"
                    " WHERE session BETWEEN %s AND %s", (start, end))
        result.bars_examined = int(cur.fetchone()[0])

        # Only the bars ACTIONS has an opinion about. Pulling the window's bars
        # and filtering in Python would read a universe-scale frame to examine a
        # handful of rows — the audit must be cheap enough to run routinely, or
        # it will not be run.
        for (tkr, sess), stated in sorted(splits.items()):
            cur.execute("SELECT security_id, split_ratio FROM sentinel_bars"
                        " WHERE ticker = %s AND session = %s", (tkr, sess))
            row = cur.fetchone()
            if row is None:
                # No bar at all is a COVERAGE question, not a ratio one, and it
                # belongs to the rejection audit which already reports it. Silent
                # here rather than double-counted there.
                continue
            sid, stored = str(row[0]), float(row[1])
            if abs(stored - float(stated)) > 1e-9:
                result.confirmed.append(Discrepancy(
                    security_id=sid, ticker=tkr, session=sess,
                    stored=stored, authoritative=float(stated)))

        # Seam anomalies the ingest recorded but did NOT apply. They are not
        # discrepancies — nothing contradicts anything — but they are the
        # population an operator has to adjudicate, so an audit that omitted
        # them would report a corpus as clean while a recorded question about it
        # sat unanswered in another table.
        cur.execute("SELECT ticker, session, detail FROM sentinel_corpus_anomalies"
                    " WHERE kind = 'SEAM_SPLIT_UNCORROBORATED'"
                    " AND session BETWEEN %s AND %s ORDER BY session, ticker",
                    (start, end))
        result.seam_anomalies = [
            {"ticker": t, "session": str(s), "detail": d}
            for t, s, d in cur.fetchall()]

    return result


def repair(conn, *, start: str, end: str, dry_run: bool = True) -> dict:
    """Make every provably-wrong bar agree with ACTIONS.

    A DIRECT UPDATE, deliberately, and the only place in the package that is
    allowed to lower a `split_ratio`. The ingest's upsert refuses to downgrade a
    ratio to 1.0 because absence of evidence must not overwrite evidence; a
    repair is the opposite situation — evidence, applied on purpose, by a human
    who invoked it, with the before-and-after recorded.

    Dry by default. The command that rewrites share counts is not one to make
    convenient.
    """
    result = audit(conn, start=start, end=end)
    applied = 0
    if not dry_run and result.confirmed:
        with conn.cursor() as cur:
            for d in result.confirmed:
                cur.execute(
                    "UPDATE sentinel_bars SET split_ratio = %s"
                    " WHERE security_id = %s AND session = %s",
                    (d.authoritative, d.security_id, d.session))
                applied += cur.rowcount
                cur.execute(
                    "INSERT INTO sentinel_corpus_anomalies"
                    " (kind, ticker, session, detail) VALUES (%s,%s,%s,%s)"
                    " ON CONFLICT (kind, ticker, session) DO UPDATE SET"
                    " detail = EXCLUDED.detail",
                    ("SPLIT_RATIO_REPAIRED", d.ticker, d.session,
                     f"stored={d.stored:.6g} -> ACTIONS={d.authoritative:.6g}"))
        conn.commit()

    out = result.to_dict()
    out["dry_run"] = dry_run
    out["rows_updated"] = applied
    out["residual_risk"] = (
        "Splits ACTIONS never recorded are NOT repaired by this command and are "
        "not visible to its audit. Only a contiguous reseed over the affected "
        "span — with prior_observations supplied — can establish that set.")
    return out
