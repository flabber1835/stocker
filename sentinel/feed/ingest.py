"""Seed and daily ingest — fetch, normalise, write, publish progress.

```text
SHARADAR  ->  domains.normalise_sep_rows  ->  store.write_bars
                        |                            |
                        +--------- IngestRun.chunk ---+
                                     publishes committed progress per year
```

Two modes, one path:

```text
seed    the full history, one CALENDAR YEAR per chunk. Hours. Watchable.
daily   everything since the newest session already stored, plus a small
        re-fetch window so a vendor restatement of recent bars is picked up
```

**The daily fetch deliberately overlaps.** Resuming strictly after the last
stored session would never revisit a bar, and Sharadar restates: a split or a
correction lands on rows already written. The upserts are idempotent, so
re-fetching a short tail costs one small request and repairs silently. Resuming
without overlap would leave a stale bar in place forever, and the trailing stop
reads exactly those closes.
"""
from __future__ import annotations

import datetime as _dt
import logging
from typing import Callable, Iterable, Optional

from sentinel.feed import domains, sharadar, universe
from sentinel.feed import store as feed_store

log = logging.getLogger(__name__)

#: Sessions re-fetched behind the frontier on a daily run. Ten trading days is
#: comfortably longer than a vendor's correction lag and still one small request.
DAILY_OVERLAP_DAYS = 14

#: Wealth Core needs 126 sessions of history before it can plan, and the
#: deployment doc prefers 252 for margin. The seed default reaches far enough
#: back that neither is ever the constraint.
DEFAULT_SEED_START = "1998-01-01"


def _today() -> str:
    return _dt.date.today().isoformat()


def _report_split_disagreements(report, authoritative) -> list:
    """LOUD when the stated and derived split ratios describe different events.

    The authoritative value wins — it is the vendor stating a corporate action,
    while the derived one is inferred from two prices — but a material
    disagreement means one of the two inputs is wrong about this security, and
    silently preferring either turns a data problem into a share count nobody
    questions.
    """
    from sentinel.feed import actions_map

    bad = actions_map.split_disagreements(report, authoritative)
    for d in bad[:20]:
        log.warning(
            "sentinel: SPLIT DISAGREEMENT %s %s stated=%.6g derived=%.6g — "
            "using the ACTIONS value; one of the two sources is wrong about "
            "this security", d["ticker"], d["session"], d["stated"],
            d["derived"])
    if len(bad) > 20:
        log.warning("sentinel: +%d further split disagreements", len(bad) - 20)

    # The OTHER half, and the half that is easy to leave silent because the
    # fallback handles it: a split the prices show and ACTIONS never recorded.
    # Summarised rather than listed per row — in thin early history this is a
    # coverage statement about the actions feed, not a per-security fault.
    only = actions_map.splits_only_derived(report, authoritative)
    if only:
        log.warning(
            "sentinel: %d split(s) inferred from prices with NO ACTIONS row "
            "(using the derived ratio; e.g. %s) — ACTIONS does not cover every "
            "split in this window", len(only),
            ", ".join(f"{d['ticker']} {d['session']} x{d['derived']:.6g}"
                      for d in only[:5]))
    return bad


#: Calendar days of ACTIONS read from BEFORE a chunk's own window. An ex-date
#: on the last few days of the previous chunk can be a weekend or a holiday
#: whose next real session belongs to THIS chunk; without the lookback that
#: entitlement is dropped by both chunks — the earlier one has no session at or
#: after it, and the later one never reads the row.
_ACTION_LOOKBACK_DAYS = 10


def _action_maps(conn, start: str, end: str):
    """(authoritative_splits, dividends) for [start, end], from the ACTIONS rows
    ALREADY STORED for this window.

    Read back from `sentinel_actions` rather than from the fetch response, so a
    resumed or re-run chunk uses exactly what the corpus holds — the derived
    ratio would otherwise depend on whether this process happened to be the one
    that downloaded the actions.

    THE SESSION AXIS IS THE EXCHANGE CALENDAR, NOT THE STORED BARS. The ex-date
    is a CALENDAR date and can fall on a weekend or a holiday, so both maps snap
    forward to the first real session; an event dated on a non-session never
    fires and would leave the entitlement outstanding. Snapping against the
    sessions already in `sentinel_bars` looks equivalent and is not: this runs
    BEFORE the chunk's own bars are written, so on a seed the stored set is
    empty and every weekend ex-date silently vanished. The corpus cannot be its
    own witness for a day it does not yet hold — the same argument
    `feed/calendar.py` exists under.
    """
    from sentinel.feed import actions_map, calendar

    lo = (_dt.date.fromisoformat(str(start))
          - _dt.timedelta(days=_ACTION_LOOKBACK_DAYS)).isoformat()
    with conn.cursor() as cur:
        cur.execute("SELECT ticker, session, action, value FROM sentinel_actions"
                    " WHERE session BETWEEN %s AND %s", (lo, end))
        rows = [{"ticker": t, "date": str(d), "action": a, "value": v}
                for t, d, a, v in cur.fetchall()]
    sessions = calendar.sessions_in_range(start, end)
    return (actions_map.split_ratios_from_actions(rows, sessions),
            actions_map.dividends_from_actions(rows, sessions),
            rows)


def _sorted_sep(rows: Iterable[dict]) -> list[dict]:
    """Vendor price rows in (date, ticker) order, materialised.

    `normalise_sep_rows` now RAISES on an out-of-order stream rather than
    silently recovering split ratios against the wrong bar, so the ordering has
    to come from somewhere. It cannot come from the vendor: `fetch_table`
    cursor-pages an HTTP API that requests no sort and promises none, so a
    correct corpus rested on an undocumented property of someone else's
    service.

    The sort is done HERE, at the call site that can afford it — one chunk is a
    year, not a corpus — rather than inside the generator, where buffering
    would make a universe-scale year quietly resident in memory.
    """
    return sorted(rows, key=lambda r: (str(r.get("date")), str(r.get("ticker"))))


def _persist_chunk_evidence(conn, run, chunk: str, lo: str, hi: str,
                            report, splits, action_rows) -> None:
    """Everything the chunk learned that is not a bar.

    All of it durable, because a certification runs in a different process
    hours later and cannot consult a log line that scrolled past during a
    six-hour seed.
    """
    from sentinel.feed import actions_map

    # 1. the refused rows themselves
    feed_store.write_rejections(conn, report.rejections)

    # 2. THAT SOME REFUSALS WERE NOT KEPT. The report retains at most
    #    `max_rejections` rows and counts the rest, which is right — a broad
    #    identity outage must not sit in memory. What was wrong is that the
    #    count died with the process, so an audit could examine 50,000 of
    #    175,000 refusals and report CLEAR.
    feed_store.write_rejection_truncation(
        conn, run_id=run.progress.run_id, chunk=chunk, window_start=lo, window_end=hi,
        retained=len(report.rejections), truncated=report.rejections_truncated)

    # 3. anomalies that were RESOLVED but not resolved away
    anomalies = []
    for d in _report_split_disagreements(report, splits):
        anomalies.append({
            "kind": "SPLIT_DISAGREEMENT", "ticker": d["ticker"],
            "session": d["session"],
            "detail": f"stated={d['stated']:.6g} derived={d['derived']:.6g}"})
    for d in actions_map.splits_only_derived(report, splits):
        anomalies.append({
            "kind": "SPLIT_ONLY_DERIVED", "ticker": d["ticker"],
            "session": d["session"], "detail": f"derived={d['derived']:.6g}"})
    for row in actions_map.unusable_dividend_rows_detail(action_rows):
        anomalies.append({
            "kind": "UNUSABLE_DIVIDEND", "ticker": row["ticker"],
            "session": row["date"],
            "detail": f"action={row['action']} value={row['value']!r}"})
    if anomalies:
        feed_store.write_anomalies(conn, anomalies)


def seed(conn, *, date_from: str = DEFAULT_SEED_START, date_to: Optional[str] = None,
         fetch: Callable[..., Iterable[dict]] = sharadar.fetch_table,
         resolve_identity=None) -> feed_store.IngestProgress:
    """Load the full history, one calendar year per chunk.

    Idempotent by construction: every write is an upsert keyed on
    (security_id, session), so an interrupted seed is resumed by running it
    again. That is why the orphan reclaim keeps a dead run's committed rows
    rather than rolling them back.
    """
    date_to = date_to or _today()
    chunks = sharadar.year_chunks(date_from, date_to)
    run = feed_store.IngestRun(conn, "seed", date_from=date_from,
                               date_to=date_to, chunks_total=len(chunks) + 2)

    # TICKERS FIRST. Identity is not decoration on the price load — a bar keyed
    # on the SYMBOL splices two unrelated companies that reused it, and the
    # momentum computed across that seam is wrong for as long as the corpus
    # lives. Loading prices before identity would mean re-loading them after.
    with run.chunk("tickers"):
        rows = list(fetch(sharadar.TICKERS))
        run.progress.rows_written += universe.write_universe(conn, rows, date_to)

    # ACTIONS first, and as its own chunk. It is small, it is the AUTHORITATIVE
    # corporate-action stream, and having it before the prices means the split
    # ratio derived from the two price domains has something to be cross-checked
    # against from the first year rather than the last.
    with run.chunk("actions"):
        rows = list(fetch(sharadar.ACTIONS,
                          sharadar.date_params(date_from, date_to)))
        run.progress.rows_written += feed_store.write_actions(conn, rows)

    # Built ONCE from what was just stored, then reused for every year. Rebuilding
    # per chunk would be correct and would re-read the whole universe 29 times.
    resolver = resolve_identity or universe.load_resolver(conn).resolve

    for lo, hi in chunks:
        with run.chunk(lo[:4]):
            report = domains.NormalisationReport()
            # ACTIONS IS AUTHORITATIVE for splits and dividends, and this call
            # site is the defect being fixed: ACTIONS was fetched, stored and
            # then NOT passed here, so every dividend was 0.0 and every split
            # ratio came from price-domain inference. A genuine 3:2 is 1.5,
            # equidistant from the 1 and 2 the derived ratio snaps to, and S5
            # made that error matter by preserving fractional entitlement.
            splits, divs, action_rows = _action_maps(conn, lo, hi)
            bars = domains.normalise_sep_rows(
                _sorted_sep(fetch(sharadar.SEP, sharadar.date_params(lo, hi))),
                resolve_identity=resolver,
                authoritative_splits=splits, dividends=divs, report=report)
            written = feed_store.write_bars(conn, bars)
            # PERSIST THE EVIDENCE in the same breath as the bars. A refusal,
            # a truncation or an anomaly recorded only in memory dies with the
            # process, and the certification that needs it runs in a different
            # one, hours later.
            _persist_chunk_evidence(conn, run, lo[:4], lo, hi, report, splits,
                                    action_rows)
            run.progress.rows_written += written
            run.progress.rows_dropped += (report.dropped_no_raw_close
                                          + report.dropped_no_identity)

    run.finish("success")
    return run.progress


def daily(conn, *, fetch: Callable[..., Iterable[dict]] = sharadar.fetch_table,
          resolve_identity=None, overlap_days: int = DAILY_OVERLAP_DAYS,
          today: Optional[str] = None) -> feed_store.IngestProgress:
    """Fetch from `overlap_days` behind the stored frontier through today."""
    to = today or _today()
    frontier = feed_store.latest_session(conn)
    if frontier is None:
        raise RuntimeError(
            "the corpus is empty, so there is no frontier to resume from. Run "
            "`feed-seed` first — a daily fetch would silently load a two-week "
            "window and leave Wealth Core with far less history than the 126 "
            "sessions it needs, which surfaces as an eligibility failure rather "
            "than as the missing seed it actually is.")
    start = (_dt.date.fromisoformat(frontier)
             - _dt.timedelta(days=overlap_days)).isoformat()

    run = feed_store.IngestRun(conn, "daily", date_from=start, date_to=to,
                               chunks_total=3)
    # Refreshed daily, not just at seed. Listings change: an IPO or a rename
    # arrives with no stored identity, and every one of its bars would be dropped
    # as unresolvable — silently, since dropping is the correct response to an
    # unknown security and looks identical to one.
    with run.chunk("tickers"):
        rows = list(fetch(sharadar.TICKERS))
        run.progress.rows_written += universe.write_universe(conn, rows, to)

    with run.chunk("actions"):
        rows = list(fetch(sharadar.ACTIONS, sharadar.date_params(start, to)))
        run.progress.rows_written += feed_store.write_actions(conn, rows)

    with run.chunk("prices"):
        report = domains.NormalisationReport()
        splits, divs, action_rows = _action_maps(conn, start, to)
        bars = domains.normalise_sep_rows(
            _sorted_sep(fetch(sharadar.SEP, sharadar.date_params(start, to))),
            resolve_identity=resolve_identity or universe.load_resolver(conn).resolve,
            authoritative_splits=splits, dividends=divs, report=report)
        run.progress.rows_written += feed_store.write_bars(conn, bars)
        _persist_chunk_evidence(conn, run, "prices", start, to, report, splits,
                                action_rows)
        run.progress.rows_dropped += (report.dropped_no_raw_close
                                      + report.dropped_no_identity)
        # Checked on the DAILY path, where a vendor outage looks like a quiet
        # market. A seed spanning decades would be dominated by legitimately
        # sparse early years, so the same threshold there would refuse a healthy
        # load.
        domains.assert_raw_price_domain(report)

    run.finish("success")
    return run.progress
