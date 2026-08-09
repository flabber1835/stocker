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
            bars = domains.normalise_sep_rows(
                fetch(sharadar.SEP, sharadar.date_params(lo, hi)),
                resolve_identity=resolver, report=report)
            written = feed_store.write_bars(conn, bars)
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
        bars = domains.normalise_sep_rows(
            fetch(sharadar.SEP, sharadar.date_params(start, to)),
            resolve_identity=resolve_identity or universe.load_resolver(conn).resolve,
            report=report)
        run.progress.rows_written += feed_store.write_bars(conn, bars)
        run.progress.rows_dropped += (report.dropped_no_raw_close
                                      + report.dropped_no_identity)
        # Checked on the DAILY path, where a vendor outage looks like a quiet
        # market. A seed spanning decades would be dominated by legitimately
        # sparse early years, so the same threshold there would refuse a healthy
        # load.
        domains.assert_raw_price_domain(report)

    run.finish("success")
    return run.progress
