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

COMPARED_FIELDS = ("raw_close", "raw_open", "volume", "split_ratio",
                   "dividend_per_share", "tradeable", "ticker")
TOLERANCE = 1e-9
BT_CORPUS_LOCK_KEY = 0x4254_434F_5250_5553
CANONICAL_SECURITY_ID_PREFIX = "P:"


@dataclass
class ParityReport:
    """COUNTS are exact; the NAMED examples are capped."""
    window: tuple[str, str]
    sentinel_bars: int = 0
    canonical_bars: int = 0
    missing_count: int = 0
    extra_count: int = 0
    missing_from_sentinel: list[tuple[str, str]] = field(default_factory=list)
    extra_in_sentinel: list[tuple[str, str]] = field(default_factory=list)
    field_divergences: dict[str, int] = field(default_factory=dict)
    examples: list[dict] = field(default_factory=list)
    examples_truncated: int = 0
    identity_failure_count: int = 0
    identity_failure_sample: list[dict] = field(default_factory=list)
    unavailable: Optional[str] = None
    canonical_loader_failure: Optional[str] = None
    sentinel_data_version: Optional[int] = None
    canonical_data_version: Optional[str] = None
    canonical_source_mode: Optional[str] = None

    def note_missing(self, key, *, max_report: int) -> None:
        self.missing_count += 1
        if len(self.missing_from_sentinel) < max_report:
            self.missing_from_sentinel.append(key)

    def note_extra(self, key, *, max_report: int) -> None:
        self.extra_count += 1
        if len(self.extra_in_sentinel) < max_report:
            self.extra_in_sentinel.append(key)

    def note_identity_failure(self, failure: dict, *, max_report: int) -> None:
        self.identity_failure_count += 1
        if len(self.identity_failure_sample) < max_report:
            self.identity_failure_sample.append(failure)

    @property
    def agrees(self) -> bool:
        return (self.unavailable is None
                and self.canonical_loader_failure is None
                and not self.identity_failure_count
                and not self.missing_count
                and not self.extra_count
                and not self.field_divergences)

    def to_dict(self) -> dict:
        return {"window": {"start": self.window[0], "end": self.window[1]},
                "unavailable": self.unavailable,
                "canonical_loader_failure": self.canonical_loader_failure,
                "sentinel_bars": self.sentinel_bars,
                "canonical_bars": self.canonical_bars,
                "sentinel_data_version": self.sentinel_data_version,
                "canonical_data_version": self.canonical_data_version,
                "canonical_source_mode": self.canonical_source_mode,
                "identity_failures": self.identity_failure_count,
                "identity_failure_sample": self.identity_failure_sample,
                "missing_from_sentinel": self.missing_count,
                "extra_in_sentinel": self.extra_count,
                "missing_sample": [list(k) for k in self.missing_from_sentinel],
                "extra_sample": [list(k) for k in self.extra_in_sentinel],
                "field_divergences": self.field_divergences,
                "examples": self.examples,
                "examples_truncated": self.examples_truncated,
                "agrees": self.agrees}


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


def _permaticker_identity(security_id, *, source: str) -> str:
    """Return the opaque vendor permaticker carried by one loader.

    Sentinel stores the Sharadar permaticker verbatim.  The retained canonical
    loader wraps that same value in its explicit ``P:`` namespace.  The
    conversion is therefore SIDE-AWARE: removing ``P:`` from both sides would
    collapse two valid Sentinel permatickers such as ``"123"`` and
    ``"P:123"`` into one financial identity.

    No whitespace or type coercion is performed.  Both production loaders
    already emit stripped strings, and accepting a malformed value here would
    make a certification comparison repair evidence it is supposed to audit.
    """
    if source not in {"sentinel", "canonical"}:
        raise ValueError(f"unknown corpus identity source {source!r}")
    if not isinstance(security_id, str):
        raise ValueError("security_id is not a string")
    if not security_id:
        raise ValueError("security_id is empty")
    if security_id != security_id.strip():
        raise ValueError("security_id has surrounding whitespace")
    if source == "sentinel":
        return security_id
    if not security_id.startswith(CANONICAL_SECURITY_ID_PREFIX):
        raise ValueError(
            "canonical security_id lacks the required P: namespace")
    permaticker = security_id[len(CANONICAL_SECURITY_ID_PREFIX):]
    if not permaticker:
        raise ValueError("canonical security_id has an empty permaticker")
    if permaticker != permaticker.strip():
        raise ValueError("canonical permaticker has surrounding whitespace")
    return permaticker


def comparison_security_id(security_id, *, source: str) -> str:
    """Canonical display key for the same permanent security on either side."""
    return (CANONICAL_SECURITY_ID_PREFIX
            + _permaticker_identity(security_id, source=source))


def _index_session_bars(bars, *, source: str, session: str,
                        report: ParityReport, max_report: int
                        ) -> tuple[dict[str, object], bool]:
    """Index one session without silently dropping malformed/duplicate bars."""
    indexed: dict[str, object] = {}
    observed_ids: dict[str, str] = {}
    failed = False
    for bar in bars:
        security_id = getattr(bar, "security_id", None)
        try:
            permaticker = _permaticker_identity(security_id, source=source)
        except ValueError as exc:
            failed = True
            report.note_identity_failure({
                "session": str(session), "source": source,
                "security_id": security_id, "reason": str(exc),
            }, max_report=max_report)
            continue
        if permaticker in indexed:
            failed = True
            prior = observed_ids[permaticker]
            reason = ("duplicate security_id in one session"
                      if prior == security_id
                      else "distinct security_ids normalize to one permaticker")
            report.note_identity_failure({
                "session": str(session), "source": source,
                "security_id": security_id,
                "comparison_security_id": (
                    CANONICAL_SECURITY_ID_PREFIX + permaticker),
                "collides_with": prior, "reason": reason,
            }, max_report=max_report)
            continue
        indexed[permaticker] = bar
        observed_ids[permaticker] = security_id
    return indexed, failed


def compare(sentinel_bars: dict, canonical_bars: dict, *, window,
            max_report: int = 25) -> ParityReport:
    rep = ParityReport(window=tuple(window))
    for session in sorted(set(sentinel_bars) | set(canonical_bars)):
        mine_rows = tuple(sentinel_bars.get(session, ()))
        their_rows = tuple(canonical_bars.get(session, ()))
        rep.sentinel_bars += len(mine_rows)
        rep.canonical_bars += len(their_rows)
        mine, mine_failed = _index_session_bars(
            mine_rows, source="sentinel", session=str(session), report=rep,
            max_report=max_report)
        theirs, theirs_failed = _index_session_bars(
            their_rows, source="canonical", session=str(session), report=rep,
            max_report=max_report)
        # Membership and field claims over a partially indexed session would be
        # noise.  The identity failure itself is the fail-closed verdict.
        if mine_failed or theirs_failed:
            continue
        for sid in sorted(theirs.keys() - mine.keys()):
            rep.note_missing(
                (session, CANONICAL_SECURITY_ID_PREFIX + sid),
                max_report=max_report)
        for sid in sorted(mine.keys() - theirs.keys()):
            rep.note_extra(
                (session, CANONICAL_SECURITY_ID_PREFIX + sid),
                max_report=max_report)
        for sid in sorted(mine.keys() & theirs.keys()):
            a, b = mine[sid], theirs[sid]
            for f in COMPARED_FIELDS:
                if _close(getattr(a, f, None), getattr(b, f, None)):
                    continue
                rep.field_divergences[f] = rep.field_divergences.get(f, 0) + 1
                if len(rep.examples) < max_report:
                    rep.examples.append({
                        "session": session,
                        "security_id": CANONICAL_SECURITY_ID_PREFIX + sid,
                        "field": f,
                        "sentinel": getattr(a, f, None),
                        "canonical": getattr(b, f, None)})
                else:
                    rep.examples_truncated += 1
    return rep


def run(sentinel_conn, *, start: str, end: str,
        bt_database_url: Optional[str] = None,
        max_report: int = 25) -> ParityReport:
    """Load both sides over one pinned Sentinel + canonical DB snapshot."""
    from sentinel.core import loader
    from sentinel.feed import publication

    if end < start:
        return ParityReport(window=(start, end), unavailable=(
            "end precedes start; reversed corpus windows are refused before "
            "either database is read"))
    url = bt_database_url or os.environ.get("BT_DATABASE_URL")
    if not url:
        return ParityReport(window=(start, end), unavailable=(
            "BT_DATABASE_URL is unset, so the canonical Sharadar corpus could "
            "not be read. This is NOT a pass: the comparison did not happen."))

    _add_backtester_to_path()
    try:
        import sqlalchemy as sa                              # noqa: PLC0415
        from app import wealth_core_replay as bt             # noqa: PLC0415
    except Exception as exc:                                 # noqa: BLE001
        return ParityReport(window=(start, end), unavailable=(
            f"the canonical Wealth Core data path could not be imported "
            f"({exc!r}); it lives in the backtester and must be on the path"))

    try:
        with publication.pinned(sentinel_conn) as sentinel_publication:
            publication.assert_coherent(sentinel_conn)
            mine = loader.load_window(sentinel_conn, start=start, end=end)

        engine = sa.create_engine(url)
        with engine.connect() as bt_conn:
            with bt_conn.begin():
                bt_conn.execute(sa.text(
                    "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
                locked = bt_conn.execute(sa.text(
                    "SELECT pg_try_advisory_xact_lock_shared(:key)"),
                    {"key": BT_CORPUS_LOCK_KEY}).scalar_one()
                if not locked:
                    raise RuntimeError("canonical corpus publication is in progress")
                generation = bt_conn.execute(sa.text(
                    "SELECT version::text, status, source_mode "
                    "FROM bt_data_version WHERE id = 1")).first()
                if generation is None or str(generation[1]).upper() != "READY":
                    status = None if generation is None else generation[1]
                    raise RuntimeError(
                        f"canonical corpus is {status!r}, not READY")
                if not generation[0] or not generation[2]:
                    raise RuntimeError(
                        "READY canonical generation lacks version/source_mode")
                # In production this connection comes directly from
                # sqlalchemy.create_engine() above, so the financial domain gate
                # is mandatory. Focused unit tests replace the engine with a
                # deliberately tiny fake object and exercise ordering separately.
                if isinstance(bt_conn, sa.engine.Connection):
                    bt.assert_raw_price_domain(bt_conn, start, end)
                identity = bt.load_identity(bt_conn, as_of=end)
                actions = bt.load_actions(bt_conn, start, end)
                sessions = bt.load_sessions(bt_conn, start, end)
                splits = bt.split_ratios_from_actions(actions, sessions)
                divs = bt.dividends_from_actions(actions, sessions)
                canonical = bt.load_bars(bt_conn, start, end,
                                         authoritative_splits=splits,
                                         dividends=divs, identity=identity)
    except (bt.RawPriceDomainUnavailable,
            bt.IdentityAuthorityUnavailable,
            bt.CanonicalBarsUnavailable) as exc:
        kind = ("price_volume_domain" if isinstance(
                    exc, bt.RawPriceDomainUnavailable)
                else "identity_authority")
        return ParityReport(
            window=(start, end),
            sentinel_bars=sum(len(v) for v in mine.bars_by_session.values()),
            canonical_loader_failure=kind,
            unavailable=f"canonical {kind} failure: {exc}",
            sentinel_data_version=sentinel_publication.version,
            canonical_data_version=str(generation[0]),
            canonical_source_mode=str(generation[2]))
    except Exception as exc:                                 # noqa: BLE001
        return ParityReport(window=(start, end), unavailable=(
            f"the canonical corpus could not be read: {exc!r}"))

    report = compare(mine.bars_by_session, canonical, window=(start, end),
                     max_report=max_report)
    report.sentinel_data_version = sentinel_publication.version
    report.canonical_data_version = str(generation[0])
    report.canonical_source_mode = str(generation[2])
    return report


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
    args = ap.parse_args(argv)

    url = args.sentinel_url or os.environ.get("SENTINEL_DATABASE_URL")
    if not url:
        print("REFUSED: SENTINEL_DATABASE_URL is unset", file=sys.stderr)
        return 1
    conn = feed_store.connect(url)
    try:
        rep = run(conn, start=args.start, end=args.end,
                  bt_database_url=args.bt_url, max_report=args.max_report)
    finally:
        conn.close()

    print(json.dumps(rep.to_dict(), indent=2, default=str))
    if rep.agrees:
        return 0
    if rep.canonical_loader_failure:
        print(f"REFUSED: {rep.canonical_loader_failure}: {rep.unavailable}",
              file=sys.stderr)
    elif rep.unavailable:
        print(f"REFUSED: {rep.unavailable}", file=sys.stderr)
    else:
        print(f"REFUSED: the seeded corpus differs from the canonical one — "
              f"{rep.identity_failure_count} identity failures, "
              f"{rep.missing_count} missing, {rep.extra_count} extra, field "
              f"divergences {rep.field_divergences}. Read membership first: a "
              "field mismatch on a bar that should not exist is noise.",
              file=sys.stderr)
    return 2


__all__ = ["COMPARED_FIELDS", "ParityReport", "TOLERANCE", "compare",
           "comparison_security_id", "main", "run"]

if __name__ == "__main__":                                   # pragma: no cover
    raise SystemExit(main())
