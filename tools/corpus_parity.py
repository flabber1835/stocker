"""The SEEDED corpus against the CANONICAL Wealth Core corpus, bar for bar.

`tests/sentinel/test_loader_parity.py` compares the two loading paths on
controlled synthetic inputs. That found two real defects and it is not the same
claim as this one. It proves the two mappings agree on rows both were handed; it
cannot prove that the bars Sentinel actually seeded for 2021-2023 equal the ones
the canonical path produces from the Sharadar corpus it was certified against.

The difference is everything the synthetic test does not contain: real splits on
real securities, ticker reuse, delistings mid-window, ADR ratio changes, a
vendor restatement that landed in one store and not the other, and the ~2000
securities a session actually has. ACTIONS authority and `tradeable` semantics
BOTH changed in this batch, so a corpus seeded before them differs
economically — which is exactly the class of difference a synthetic fixture
cannot show.

```text
bt-postgres (Sharadar)              sentinel-postgres
      |                                    |
wealth_core_replay.load_bars        core.loader.load_window
      |                                    |
      +----------- compared, per (session, security) -----------+
```

## What a divergence means, in the order to read it

```text
MISSING / EXTRA securities   an identity or eligibility difference, not a price
                             one. Read this first: a field mismatch on a bar
                             that should not exist is noise
split_ratio                  the ACTIONS wiring. The most likely finding and
                             the most consequential — it is a share count
dividend_per_share           the same wiring, cash side
tradeable                    the zero-volume rule
raw_close / raw_open         a vendor restatement, or a price-domain error
```

## Why this is a TOOL and not a `sentinel` subcommand

The canonical module imports SQLAlchemy at module scope, and SQLAlchemy is a
retired-Stocker-stack dependency. Adding it to `Dockerfile.sentinel` to support
a certification-only activity would put the retired platform's ORM in the
runtime image that liquidates a brokerage account — and `tests/sentinel/
test_image_layout.py` caught exactly that when this file briefly lived under
`sentinel/`, which is the guard working.

So it lives here, runs from the CERTIFICATION image (which already carries the
backtester for the synthetic parity suite), and the runtime image keeps its
dependency set unchanged.

```bash
python -m tools.corpus_parity --start 2021-01-04 --end 2023-12-29
```

Exit codes: 0 agrees, 2 diverges OR could not be run. **An unreadable canonical
corpus is not a pass** — the comparison did not happen, and saying so is the
whole point of a fail-closed certification.

The comparison is bounded: `--max-report` divergences are named and the counts
are exact regardless. A parity failure that prints two million lines is a parity
failure nobody reads.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

#: Fields compared on every bar. `security_id` and `session` are the KEY, so
#: they are not in here — a difference in either is a membership difference,
#: which is reported separately and read first.
COMPARED_FIELDS = ("raw_close", "raw_open", "volume", "split_ratio",
                   "dividend_per_share", "tradeable", "ticker")

#: Floating comparison tolerance. Both sides compute the as-traded open by
#: scaling and rounding to 6 decimals, so an exact equality test would fail on
#: representation rather than on data.
TOLERANCE = 1e-9


@dataclass
class ParityReport:
    window: tuple[str, str]
    sentinel_bars: int = 0
    canonical_bars: int = 0
    missing_from_sentinel: list[tuple[str, str]] = field(default_factory=list)
    extra_in_sentinel: list[tuple[str, str]] = field(default_factory=list)
    field_divergences: dict[str, int] = field(default_factory=dict)
    examples: list[dict] = field(default_factory=list)
    truncated: int = 0
    unavailable: Optional[str] = None

    @property
    def agrees(self) -> bool:
        return (self.unavailable is None
                and not self.missing_from_sentinel
                and not self.extra_in_sentinel
                and not self.field_divergences)

    def to_dict(self) -> dict:
        return {"window": {"start": self.window[0], "end": self.window[1]},
                "unavailable": self.unavailable,
                "sentinel_bars": self.sentinel_bars,
                "canonical_bars": self.canonical_bars,
                "missing_from_sentinel": len(self.missing_from_sentinel),
                "extra_in_sentinel": len(self.extra_in_sentinel),
                "field_divergences": self.field_divergences,
                "examples": self.examples,
                "examples_truncated": self.truncated,
                "agrees": self.agrees}


#: Where `app.wealth_core_replay` can be found, in the two layouts that exist:
#: a repository checkout, and the certification image (which copies the
#: backtester to /work/services/backtester).
_BACKTESTER_DIRS = ("services/backtester", "/work/services/backtester")


def _add_backtester_to_path() -> None:
    import sys
    from pathlib import Path

    here = Path(__file__).resolve().parents[1]
    for cand in (here / _BACKTESTER_DIRS[0], Path(_BACKTESTER_DIRS[1])):
        p = str(cand)
        if cand.exists() and p not in sys.path:
            sys.path.insert(0, p)


def _close(a, b) -> bool:
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, bool) or isinstance(b, bool):
        return bool(a) is bool(b)
    try:
        return abs(float(a) - float(b)) <= TOLERANCE * max(
            1.0, abs(float(a)), abs(float(b)))
    except (TypeError, ValueError):
        return a == b


def compare(sentinel_bars: dict, canonical_bars: dict, *, window,
            max_report: int = 25) -> ParityReport:
    """Pure. Two `{session: [VendorBar]}` maps in, one report out."""
    mine = {(s, b.security_id): b
            for s, bars in sentinel_bars.items() for b in bars}
    theirs = {(s, b.security_id): b
              for s, bars in canonical_bars.items() for b in bars}
    rep = ParityReport(window=tuple(window), sentinel_bars=len(mine),
                       canonical_bars=len(theirs))
    rep.missing_from_sentinel = sorted(set(theirs) - set(mine))
    rep.extra_in_sentinel = sorted(set(mine) - set(theirs))

    for key in sorted(set(mine) & set(theirs)):
        a, b = mine[key], theirs[key]
        for f in COMPARED_FIELDS:
            if _close(getattr(a, f, None), getattr(b, f, None)):
                continue
            rep.field_divergences[f] = rep.field_divergences.get(f, 0) + 1
            if len(rep.examples) < max_report:
                rep.examples.append({
                    "session": key[0], "security_id": key[1], "field": f,
                    "sentinel": getattr(a, f, None),
                    "canonical": getattr(b, f, None)})
            else:
                rep.truncated += 1
    return rep


def run(sentinel_conn, *, start: str, end: str,
        bt_database_url: Optional[str] = None,
        max_report: int = 25) -> ParityReport:
    """Load both sides over the real window and compare.

    The canonical side reaches bt-postgres over `BT_DATABASE_URL` — the same
    published-host-port posture the evaluator's `bt_sql_query` already uses. No
    shared docker network, so Sentinel's isolation from the retired stack is
    unchanged: this reads a database, it does not depend on a Stocker service.
    """
    from sentinel.core import loader

    url = bt_database_url or os.environ.get("BT_DATABASE_URL")
    if not url:
        return ParityReport(window=(start, end), unavailable=(
            "BT_DATABASE_URL is unset, so the canonical Sharadar corpus could "
            "not be read. This is NOT a pass: the comparison did not happen."))

    # `app` is a top-level package INSIDE services/backtester, so that
    # directory has to be on the path in its own right — being under /work is
    # not enough. Inserted here as well as set in the image's PYTHONPATH,
    # because a tool that only works under one specific container's environment
    # is a tool that fails the first time anyone runs it anywhere else.
    _add_backtester_to_path()
    try:
        import sqlalchemy as sa                              # noqa: PLC0415
        from app import wealth_core_replay as bt             # noqa: PLC0415
    except Exception as exc:                                 # noqa: BLE001
        return ParityReport(window=(start, end), unavailable=(
            f"the canonical Wealth Core data path could not be imported "
            f"({exc!r}); it lives in the backtester and must be on the path"))

    try:
        engine = sa.create_engine(url)
        with engine.connect() as bt_conn:
            identity = bt.load_identity(bt_conn)
            actions = bt.load_actions(bt_conn, start, end)
            sessions = bt.load_sessions(bt_conn, start, end)
            splits = bt.split_ratios_from_actions(actions, sessions)
            divs = bt.dividends_from_actions(actions, sessions)
            canonical = bt.load_bars(bt_conn, start, end,
                                     authoritative_splits=splits,
                                     dividends=divs, identity=identity)
    except Exception as exc:                                 # noqa: BLE001
        return ParityReport(window=(start, end), unavailable=(
            f"the canonical corpus could not be read: {exc!r}"))

    mine = loader.load_window(sentinel_conn, start=start, end=end)
    return compare(mine.bars_by_session, canonical, window=(start, end),
                   max_report=max_report)


def _chunks(start: str, end: str, days: int):
    """Split a window into consecutive [a, b] date pairs, inclusive."""
    from datetime import date, timedelta
    a = date.fromisoformat(start)
    last = date.fromisoformat(end)
    while a <= last:
        b = min(a + timedelta(days=days - 1), last)
        yield a.isoformat(), b.isoformat()
        a = b + timedelta(days=1)


def merge(reports, *, window, max_report: int = 25) -> ParityReport:
    """Fold per-chunk reports into one verdict for the whole window.

    Sessions never span a chunk boundary and bars are keyed by
    `(session, security_id)`, so the union of the parts IS the whole: no bar
    can be missing in one chunk and present in another.

    The first `unavailable` wins and short-circuits — if one chunk could not be
    read, the window was not compared, and merging the rest would report a
    partial comparison as a complete one.
    """
    out = ParityReport(window=tuple(window))
    for rep in reports:
        if rep.unavailable:
            return ParityReport(window=tuple(window), unavailable=rep.unavailable)
        out.sentinel_bars += rep.sentinel_bars
        out.canonical_bars += rep.canonical_bars
        out.missing_from_sentinel.extend(rep.missing_from_sentinel)
        out.extra_in_sentinel.extend(rep.extra_in_sentinel)
        for f, n in rep.field_divergences.items():
            out.field_divergences[f] = out.field_divergences.get(f, 0) + n
        for ex in rep.examples:
            if len(out.examples) < max_report:
                out.examples.append(ex)
            else:
                out.truncated += 1
        out.truncated += rep.truncated
    return out


def run_chunked(sentinel_conn, *, start: str, end: str,
                bt_database_url: Optional[str] = None,
                max_report: int = 25, chunk_days: int = 92) -> ParityReport:
    """`run`, but with PEAK MEMORY bounded by the chunk rather than the window.

    The whole-window form was killed by the OOM reaper on a 7.7 GiB machine —
    silently, because SIGKILL leaves no traceback and the harness had already
    truncated the evidence file, so a three-year comparison reported as an
    empty JSON and a message telling you to read it.

    The cost is not the two loaded windows alone. `compare` builds a dict keyed
    `(session, security_id)` for each side — on 2021-2023 that is roughly 4.5M
    entries apiece — and then materialises THREE more collections over them:
    two set differences and a `sorted(set & set)` list of every shared key. The
    peak is several times the data, and it grows with the window, which is why
    a one-month probe survives and the certification window does not.

    Chunking is not a weaker check. Sessions do not span a boundary and bars
    are keyed by session, so the union of the chunks is exactly the window;
    `merge` sums the counters and keeps the same capped examples. A quarter is
    the default because it is ~63 sessions — small enough to bound the peak,
    large enough that the per-chunk query overhead stays irrelevant against a
    three-year run.
    """
    reports = []
    for a, b in _chunks(start, end, chunk_days):
        reports.append(run(sentinel_conn, start=a, end=b,
                           bt_database_url=bt_database_url,
                           max_report=max_report))
    if not reports:
        return ParityReport(window=(start, end),
                            unavailable=f"empty window {start}..{end}")
    return merge(reports, window=(start, end), max_report=max_report)


def main(argv=None) -> int:
    import argparse
    import json
    import sys

    from sentinel.feed import store as feed_store

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--bt-url", default=None,
                    help="canonical corpus DSN; defaults to $BT_DATABASE_URL")
    ap.add_argument("--sentinel-url", default=None,
                    help="defaults to $SENTINEL_DATABASE_URL")
    ap.add_argument("--max-report", type=int, default=25)
    # 0 disables chunking and restores the single-pass form — kept so the two
    # can be compared on a small window, which is how the chunked path is
    # proven to give the same answer rather than merely a survivable one.
    ap.add_argument("--chunk-days", type=int, default=92)
    args = ap.parse_args(argv)

    url = args.sentinel_url or os.environ.get("SENTINEL_DATABASE_URL")
    if not url:
        print("REFUSED: SENTINEL_DATABASE_URL is unset", file=sys.stderr)
        return 1

    conn = feed_store.connect(url)
    try:
        runner = run if args.chunk_days <= 0 else None
        if runner is not None:
            rep = runner(conn, start=args.start, end=args.end,
                         bt_database_url=args.bt_url,
                         max_report=args.max_report)
        else:
            rep = run_chunked(conn, start=args.start, end=args.end,
                              bt_database_url=args.bt_url,
                              max_report=args.max_report,
                              chunk_days=args.chunk_days)
    finally:
        conn.close()

    print(json.dumps(rep.to_dict(), indent=2, default=str))
    if rep.agrees:
        return 0
    if rep.unavailable:
        print(f"REFUSED: {rep.unavailable}", file=sys.stderr)
    else:
        print(f"REFUSED: the seeded corpus differs from the canonical one — "
              f"{len(rep.missing_from_sentinel)} missing, "
              f"{len(rep.extra_in_sentinel)} extra, field divergences "
              f"{rep.field_divergences}. Read membership first: a field "
              f"mismatch on a bar that should not exist is noise.",
              file=sys.stderr)
    return 2


__all__ = ["COMPARED_FIELDS", "ParityReport", "TOLERANCE", "compare", "main",
           "merge", "run", "run_chunked"]

if __name__ == "__main__":                                   # pragma: no cover
    raise SystemExit(main())
