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

`sentinel_actions` is an independent record of corporate actions. A stored bar
is CONFIRMED wrong only when the shared resolver supports a different direct
multiplier from the available predecessor price domains. A real predecessor
whose domains show no event is a conflict (or a proved no-listed-event), not
permission for this audit to let ACTIONS silently overrule the corpus. That set
can be produced with bounded indexed reads and no re-fetch.

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

from sentinel.feed import actions_map, anomalies, calendar, publication
from stock_strategy_shared.split_reconciliation import (
    raw_prices_refute_listed_split,
)


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
    unresolved_orientation: list = field(default_factory=list)

    @property
    def clean(self) -> bool:
        """No PROVABLE corruption. Deliberately not named `certifiable`.

        A clean audit means the corpus does not contradict ACTIONS. It does not
        mean the corpus is correct: an unrecorded split contradicts nothing.
        """
        return not self.confirmed and not self.unresolved_orientation

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
            "unresolved_orientation": self.unresolved_orientation,
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
    raw_start, raw_end = calendar.action_date_window(start, end)
    with conn.cursor() as cur:
        cur.execute("SELECT source_row_id,ticker,session,action,name,value,"
                    " contraticker,contraname"
                    " FROM sentinel_active_actions"
                    " WHERE session BETWEEN %s AND %s",
                    (raw_start, raw_end))
        rows = [{"source_row_id": source_row_id, "ticker": ticker,
                 "date": str(session), "action": action, "name": name,
                 "value": value, "contraticker": contraticker,
                 "contraname": contraname}
                for (source_row_id, ticker, session, action, name, value,
                     contraticker, contraname) in cur.fetchall()]
    ratios, ambiguous = actions_map.split_rows_from_actions(
        rows, calendar.sessions_in_range(start, end))
    if ambiguous:
        raise RuntimeError(
            "split repair refused ambiguous ACTIONS multiplicity; certification "
            "evidence must be resolved before a multiplier can be repaired")
    return ratios


def audit(conn, *, start: str, end: str) -> AuditResult:
    """Which stored bars provably contradict ACTIONS over `[start, end]`?"""
    from sentinel.feed.sharadar import validate_date_range

    start, end = validate_date_range(start, end)
    result = AuditResult(start=start, end=end)
    splits = _authoritative_splits(conn, start, end)
    result.actions_splits = len(splits)

    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM sentinel_bars b"
                    " WHERE session BETWEEN %s AND %s"
                    f" AND {publication.visible_predicate('b')}", (start, end))
        result.bars_examined = int(cur.fetchone()[0])

        # Only the bars ACTIONS has an opinion about. Pulling the window's bars
        # and filtering in Python would read a universe-scale frame to examine a
        # handful of rows — the audit must be cheap enough to run routinely, or
        # it will not be run.
        from sentinel.feed import domains

        for (tkr, sess), stated in sorted(splits.items()):
            cur.execute(
                "SELECT security_id, close_signal, close_unadjusted,"
                f" {publication.effective_split_ratio('b')}"
                " FROM sentinel_bars b WHERE ticker = %s AND session = %s"
                f" AND {publication.visible_predicate('b')}", (tkr, sess))
            row = cur.fetchone()
            if row is None:
                # No bar at all is a COVERAGE question, not a ratio one, and it
                # belongs to the rejection audit which already reports it. Silent
                # here rather than double-counted there.
                continue
            sid, close, raw, stored = (str(row[0]), row[1], row[2], float(row[3]))
            cur.execute(
                "SELECT close_signal,close_unadjusted FROM sentinel_bars b"
                " WHERE security_id=%s AND session<%s"
                f" AND {publication.visible_predicate('b')}"
                " ORDER BY session DESC LIMIT 1", (sid, sess))
            prior = cur.fetchone()
            derived = (domains.unsnapped_split_ratio(
                prior[0], prior[1], close, raw) if prior else None)
            canonical, disposition = actions_map.resolve_split_orientation(
                float(stated), derived,
                explicit_no_event=(
                    prior is not None
                    and actions_map.split_price_evidence(derived) is None),
                raw_refutes_event=(
                    prior is not None
                    and raw_prices_refute_listed_split(
                        float(stated), prior[1], raw)))
            if disposition == actions_map.SPLIT_UNRESOLVED:
                result.unresolved_orientation.append({
                    "ticker": tkr, "session": sess, "stated": float(stated),
                    "derived": derived, "stored": stored})
                continue
            if abs(stored - canonical) > 1e-9:
                result.confirmed.append(Discrepancy(
                    security_id=sid, ticker=tkr, session=sess,
                    stored=stored, authoritative=canonical))

        # Seam anomalies the ingest recorded but did NOT apply. They are not
        # discrepancies — nothing contradicts anything — but they are the
        # population an operator has to adjudicate, so an audit that omitted
        # them would report a corpus as clean while a recorded question about it
        # sat unanswered in another table.
        result.seam_anomalies = [
            {"ticker": row["ticker"], "session": row["session"],
             "detail": row["detail"]}
            for row in anomalies.active_rows(
                conn, start=start, end=end,
                kinds=("SEAM_SPLIT_UNCORROBORATED",))]

    return result


def repair(conn, *, start: str, end: str, dry_run: bool = True) -> dict:
    """Make every provably-wrong bar agree with ACTIONS.

    The effective ratio may move down as well as up, but the visible base row is
    never edited. The repair is a stamped append-only overlay and becomes
    readable only through its atomic corpus publication.

    Dry by default. The command that rewrites share counts is not one to make
    convenient.
    """
    if dry_run:
        result = audit(conn, start=start, end=end)
        applied = 0
        published = None
    else:
        from sentinel.feed import store

        # Applied repairs are append-only overlays.  The base bar a visible
        # generation names is never updated.  Candidate rows and the publication
        # pointer commit together while readers are excluded by this lock.
        with store.corpus_write_lock(conn):
            publication.assert_coherent(conn)
            result = audit(conn, start=start, end=end)
            applied = 0
            published = None
            if result.confirmed:
                run = store.IngestRun(
                    conn, "repair", date_from=start, date_to=end, chunks_total=1)
                try:
                    anomaly_rows = []
                    with conn.cursor() as cur:
                        for d in result.confirmed:
                            cur.execute(
                                "INSERT INTO sentinel_bar_split_repairs"
                                " (security_id,session,split_ratio,"
                                "  prior_split_ratio,last_written_run_id)"
                                " VALUES (%s,%s,%s,%s,%s)",
                                (d.security_id, d.session, d.authoritative,
                                 d.stored, run.progress.run_id))
                            applied += cur.rowcount
                            detail = (f"run={run.progress.run_id} "
                                      f"stored={d.stored:.6g} -> "
                                      f"ACTIONS={d.authoritative:.6g}")
                            anomaly_rows.extend((
                                {"kind": "SPLIT_RATIO_REPAIRED",
                                 "ticker": d.ticker, "session": d.session,
                                 "detail": detail},
                                {"kind": "SPLIT_AUTHORITATIVE_APPLIED",
                                 "ticker": d.ticker, "session": d.session,
                                 "detail": detail},
                            ))
                    store.write_anomalies(
                        conn, anomaly_rows, run_id=run.progress.run_id,
                        require_lock=True, commit=False)
                    with conn.cursor() as cur:
                        cur.execute(
                            "UPDATE feed_ingest_runs SET status='success',"
                            " chunks_done=1, rows_written=%s, completed_at=NOW(),"
                            " updated_at=NOW(), current_chunk='repairs'"
                            " WHERE run_id=%s", (applied, run.progress.run_id))
                    # `publish` commits the candidate overlay, run state, and
                    # publication pointer atomically.  It propagates failure.
                    published = publication.publish(
                        conn, run_id=run.progress.run_id,
                        window_start=start, window_end=end,
                        evidence={"kind": "repair", "rows_written": applied})
                except BaseException as exc:                    # noqa: BLE001
                    conn.rollback()
                    run.finish("failed", f"{type(exc).__name__}: {exc}")
                    raise

    out = result.to_dict()
    out["dry_run"] = dry_run
    out["rows_updated"] = applied
    out["published_version"] = published.version if published else None
    out["residual_risk"] = (
        "Splits ACTIONS never recorded are NOT repaired by this command and are "
        "not visible to its audit. Only a contiguous reseed over the affected "
        "span — with prior_observations supplied — can establish that set.")
    return out
