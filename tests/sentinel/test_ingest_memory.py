"""#9/#10 — the ingest holds a universe-scale YEAR in memory, by design.

THE FAILURE, written before the fix.

`normalise_sep_rows` refuses an out-of-order stream, correctly: the split ratio
is recovered from the previous observation of the same security, so unordered
rows produce ratios against the wrong bar — silently, permanently, in the stored
share counts. The vendor's HTTP API cursor-pages and promises no order. So the
ingest sorts:

```python
def _sorted_sep(rows):
    return sorted(rows, key=lambda r: (str(r["date"]), str(r["ticker"])))
```

Its own docstring says the sort is done "at the call site that can afford it —
one chunk is a year, not a corpus — rather than inside the generator, where
buffering would make a universe-scale year quietly resident in memory."

A chunk IS a universe-scale year. ~10,000 securities x ~252 sessions is ~2.5M
vendor dicts, and `sorted()` over a generator keeps every one of them alive at
once — CPython dicts of that shape run 400-700 bytes each, so the list alone is
1-2 GB before anything is normalised. The container ceiling in
`docker-compose.sentinel.yml` is 2g. The comment describes the defect and then
places it one line higher up.

Nothing here is a tuning problem. Any in-process sort of the whole chunk has
this shape; the only fix is for the sort to happen somewhere with bounded memory
and a disk to spill to, which is the database that is already open.

THE PROPERTY BEING BOUGHT: **the number of vendor rows alive at once does not
scale with chunk length.**

MEASURED EXACTLY, not sampled. The first version of this test used
`tracemalloc` peaks at two chunk sizes and did not falsify: restoring the
`sorted()` still passed it, because the peak was dominated by
`exchange_calendars` constructing its calendar on first use inside the smaller
run's measurement window and being cached for the larger one. A memory
assertion built on an allocator statistic measures the allocator.

So the rows count themselves. A `dict` subclass with a `__del__` keeps an exact
live count, CPython drops it the instant its last reference goes, and the peak
is read at every yield. No warm-up sensitivity, no allocator noise, no
threshold to tune — with the sort the count reaches the whole chunk, and
without it, it does not.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "shared"))

from tests.support.postgres import _EphemeralPostgres  # noqa: E402
from tests.support.source import code_of  # noqa: E402

from sentinel.feed import ingest, sharadar  # noqa: E402
from sentinel.feed import store as S  # noqa: E402

#: Held CONSTANT while sessions scale. Every other per-chunk structure — the
#: previous-observation map, the identity resolver, the action maps — is bounded
#: by the universe, so scaling securities would grow them too and the
#: measurement could not say which structure was responsible.
SECURITIES = 25

#: Live-count state for `TrackedRow`. Module-level rather than a fixture because
#: `__del__` fires from the garbage collector, which has no fixture in scope.
_LIVE = {"now": 0, "peak": 0}


class TrackedRow(dict):
    """A vendor row that reports its own lifetime.

    A `dict` subclass so every consumer — `r["date"]`, `r.get("close")`,
    `"closeunadj" in r` — behaves identically to the real thing and no
    production code can tell the difference.

    `__del__` rather than a weakref callback: CPython refcounting invokes it the
    moment the last reference drops, which makes the count EXACT and the test
    deterministic. A `WeakSet` would need `len()` per row, turning the
    measurement into an O(n^2) walk of the very structure being measured.
    """

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        _LIVE["now"] += 1
        if _LIVE["now"] > _LIVE["peak"]:
            _LIVE["peak"] = _LIVE["now"]

    def __del__(self):
        _LIVE["now"] -= 1


def measuring_rows():
    """Reset the counters and return a reader for the peak."""
    import gc

    gc.collect()
    _LIVE["now"] = 0
    _LIVE["peak"] = 0
    return lambda: _LIVE["peak"]


def sep_rows(n_sessions: int, tracked: bool = False):
    """A generator, deliberately. A list would put the baseline's whole chunk in
    memory before `sorted()` was reached and hide exactly what is measured.

    The synthetic source uses actual XNYS sessions from one calendar-year chunk.
    Consecutive calendar ordinals would inject weekends/holidays and rows outside
    the requested source envelope, which is not a valid Sharadar session stream.

    Rows are shaped like real SEP rows — ten keys, not two — so a consumer that
    reads a field the staging table does not carry fails here rather than in
    production.
    """
    from sentinel.feed import calendar

    make = TrackedRow if tracked else dict
    sessions = calendar.sessions_in_range("2021-01-01", "2021-12-31")
    if n_sessions < 0 or n_sessions > len(sessions):
        raise ValueError(
            f"memory fixture requested {n_sessions} sessions; 2021 exposes "
            f"{len(sessions)} XNYS sessions")

    def gen():
        for day in sessions[:n_sessions]:
            for s in range(SECURITIES):
                t = f"T{s:03d}"
                yield make({"ticker": t, "date": day, "open": 10.0,
                            "high": 10.5, "low": 9.5, "close": 10.0,
                            "closeadj": 10.0, "closeunadj": 10.0,
                            "volume": 1_000_000.0, "dividends": 0.0,
                            "lastupdated": day})
    return gen()


def a_fetch(n_sessions: int, tracked: bool = False):
    """Stands in for `sharadar.fetch_table`, one table at a time."""
    def fetch(table, params=None, **kw):
        params = dict(params or {})
        if table == sharadar.SEP:
            return sep_rows(n_sessions, tracked=tracked)
        if table == sharadar.ACTIONS and params.get("date.gte") == "1900-01-01":
            return iter([{"ticker": "__SOURCE_HEALTH__", "date": "1900-01-02",
                          "action": "listed", "value": None,
                          "contraticker": None}])
        return iter(())            # no relevant ACTIONS/TICKERS; both are bounded
    return fetch


@pytest.fixture(scope="module")
def pg():
    try:
        server = _EphemeralPostgres()
        server.start()
    except Exception as exc:                                  # noqa: BLE001
        pytest.skip(f"ephemeral Postgres unavailable: {exc}")
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture()
def conn(pg):
    c = S.connect(pg.sync_dsn)
    with c.cursor() as cur:
        # Child first: dropping sentinel_bars CASCADE while leaving the repair
        # table would remove only its FK. CREATE TABLE IF NOT EXISTS would then
        # keep that constraint-free child for the next parameterized test.
        for t in ("sentinel_processed_sessions",
                  "sentinel_anomaly_observation_events",
                  "sentinel_action_generation_events",
                  "sentinel_action_observations", "sentinel_action_generations",
                  "sentinel_bar_split_repairs", "sentinel_bars",
                  "sentinel_actions", "sentinel_universe",
                  "sentinel_corpus_publications", "feed_ingest_runs",
                  "sentinel_sep_staging", "sentinel_corpus_anomalies",
                  "sentinel_ingest_rejections"):
            cur.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
    c.commit()
    S.ensure_schema(c)
    yield c
    c.close()


def peak_live_rows(conn, n_sessions: int) -> tuple[int, int]:
    """(peak simultaneously-live vendor rows, total rows in the chunk)."""
    with conn.cursor() as cur:
        # Keep the production FK load-bearing: PostgreSQL will not TRUNCATE a
        # referenced parent even when the child is empty or ON DELETE CASCADE.
        # Name both tables instead of using broad CASCADE, so a new dependent
        # table cannot be erased by this memory-test reset without review.
        cur.execute("TRUNCATE sentinel_bar_split_repairs, sentinel_bars")
    conn.commit()

    peak = measuring_rows()
    ingest.seed(conn, fetch=a_fetch(n_sessions, tracked=True),
                resolve_identity=lambda t, s: f"P-{t}",
                date_from="2021-01-01", date_to="2021-12-31")
    return peak(), n_sessions * SECURITIES


class TestTheFailure:
    def test_the_whole_chunk_is_never_RESIDENT_AT_ONCE(self, conn):
        """The headline. `sorted()` holds every row of the chunk alive; nothing
        else in the ingest does.

        The bound is absolute rather than a ratio: `stage` buffers TUPLES, not
        the vendor dicts, and each dict's last reference drops the moment its
        tuple is appended — so the live count is a handful regardless of chunk
        length. 64 is slack for the generator's own frame and whatever the
        collector has not swept, not a tuning knob.
        """
        live, total = peak_live_rows(conn, 240)
        assert total == 6_000
        assert live <= 64, (
            f"{live} of {total} vendor rows were alive at once. On a real "
            f"chunk — ~10k securities x ~252 sessions — that ratio is 1-2 GB "
            f"against a 2g container ceiling.")

    def test_and_it_does_not_grow_with_the_chunk(self, conn):
        """Four times the rows, the same live count. Stated separately from the
        absolute bound because they fail differently: a fixed-size buffer that
        is simply too large satisfies neither, while a fix that streams but
        accumulates something per-row satisfies only the first at small sizes.
        """
        small, _ = peak_live_rows(conn, 60)
        large, _ = peak_live_rows(conn, 240)
        assert large <= small + 8, (
            f"live rows went {small} -> {large} for 4x the chunk; something "
            f"is retained per row")

    def test_the_in_process_sort_is_GONE(self, conn):
        """Structural, alongside the measurement. The two catch different
        regressions: a reintroduced sort somewhere the measurement's synthetic
        chunk happens not to exercise would pass the arithmetic and fail here.
        """
        assert not hasattr(ingest, "_sorted_sep"), (
            "the chunk sort belongs in the database, which has bounded memory "
            "and a disk to spill to")
        for name in ("seed", "daily"):
            src = code_of(getattr(ingest, name))
            assert "sorted(" not in src, f"{name} sorts the chunk in process"


class TestTheOrderingSURVIVES:
    """The sort existed for a reason. A fix that loses the ordering guarantee
    trades a memory bug for a silent share-count bug, which is worse."""

    def test_a_SHUFFLED_vendor_stream_still_stores_ordered_bars(self, conn):
        import random

        def shuffled_fetch(table, params=None, **kw):
            params = dict(params or {})
            if table == sharadar.ACTIONS and params.get("date.gte") == "1900-01-01":
                return iter([{"ticker": "__SOURCE_HEALTH__", "date": "1900-01-02",
                              "action": "listed", "value": None,
                              "contraticker": None}])
            if table != sharadar.SEP:
                return iter(())
            rows = list(sep_rows(12))
            random.Random(20260811).shuffle(rows)
            return iter(rows)

        ingest.seed(conn, fetch=shuffled_fetch,
                    resolve_identity=lambda t, s: f"P-{t}",
                    date_from="2021-01-01", date_to="2021-12-31")

        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*), COUNT(DISTINCT session)"
                        " FROM sentinel_bars")
            n, sessions = cur.fetchone()
        assert sessions == 12 and n == 12 * SECURITIES

    def test_the_normaliser_still_REFUSES_an_unordered_stream(self):
        """The guard itself must not have been relaxed to make the staging read
        easier. It is the thing that makes the ordering a property rather than
        an intention."""
        from sentinel.feed import domains

        rows = [{"ticker": "A", "date": "2021-03-02", "close": 1.0,
                 "closeunadj": 1.0, "volume": 1.0},
                {"ticker": "A", "date": "2021-03-01", "close": 1.0,
                 "closeunadj": 1.0, "volume": 1.0}]
        with pytest.raises(domains.SessionsOutOfOrder):
            list(domains.normalise_sep_rows(iter(rows)))


class TestNothingIsLostInTheRoundTrip:
    def test_every_field_the_normaliser_READS_survives_staging(self, conn):
        """The failure mode a staging table introduces that a sort cannot: a
        vendor key that is not carried across arrives as None, and None is a
        plausible value for every one of these. Derived from the normaliser's
        own source, so adding a key there without a column fails HERE rather
        than silently degrading a corpus."""
        import ast

        from sentinel.feed import domains, staging

        read: set[str] = set()
        tree = ast.parse(code_of(domains.normalise_sep_rows))
        for node in ast.walk(tree):
            # r.get("x")
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "get"
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "r"
                    and node.args
                    and isinstance(node.args[0], ast.Constant)):
                read.add(node.args[0].value)
            # r["x"]  and  "x" in r
            if (isinstance(node, ast.Subscript)
                    and isinstance(node.value, ast.Name)
                    and node.value.id == "r"
                    and isinstance(node.slice, ast.Constant)):
                read.add(node.slice.value)
            if (isinstance(node, ast.Compare)
                    and isinstance(node.left, ast.Constant)
                    and any(isinstance(o, ast.In) for o in node.ops)
                    and any(isinstance(c, ast.Name) and c.id == "r"
                            for c in node.comparators)):
                read.add(node.left.value)

        assert read, "the extraction found nothing; it has stopped checking"
        # `close_unadjusted` is the DATABASE spelling, used by the parity
        # loader which never goes through staging. The vendor sends
        # `closeunadj`, and staging speaks the vendor's dialect.
        missing = read - staging.CARRIED - {"close_unadjusted"}
        assert not missing, (
            f"normalise_sep_rows reads {sorted(missing)}, which staging does "
            f"not carry. Those arrive as None — a plausible value for every "
            f"one of them, so nothing downstream would report it.")

    def test_a_staged_row_comes_back_byte_for_byte_on_the_carried_fields(self, conn):
        from sentinel.feed import staging

        row = {"ticker": "ZZZ", "date": "2021-06-01", "open": 1.25,
               "close": 2.5, "closeunadj": 40.0, "volume": 123456.0,
               "closeadj": 9.0, "ignored": "dropped on purpose"}
        staging.stage(conn, iter([row]), run_id=RUN, chunk="c")
        back = list(staging.staged(conn, run_id=RUN, chunk="c"))
        assert len(back) == 1
        for k in staging.CARRIED:
            assert back[0][k] == row[k], k


RUN = "00000000-0000-0000-0000-0000000000aa"


class TestStagingIsScratch:
    def test_a_chunk_CLEANS_UP_after_itself(self, conn):
        """Scratch that is never deleted is a second corpus, unversioned, that
        grows by a universe-year every night."""
        ingest.seed(conn, fetch=a_fetch(5),
                    resolve_identity=lambda t, s: f"P-{t}",
                    date_from="2021-01-01", date_to="2021-12-31")
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM sentinel_sep_staging")
            assert cur.fetchone()[0] == 0

    def test_one_runs_scratch_is_INVISIBLE_to_another(self, conn):
        """A crashed ingest leaves rows behind — `reclaim_orphans` exists
        because that happens. They must not be read by the next run as if they
        were its own, which would splice two fetches into one ordered stream."""
        from sentinel.feed import staging

        other = "00000000-0000-0000-0000-0000000000bb"
        staging.stage(conn, sep_rows(3), run_id=other, chunk="c")
        staging.stage(conn, sep_rows(2), run_id=RUN, chunk="c")

        mine = list(staging.staged(conn, run_id=RUN, chunk="c"))
        assert len(mine) == 2 * SECURITIES

    def test_restaging_the_same_chunk_REPLACES_rather_than_appends(self, conn):
        """A resumed chunk re-fetches. Appending would present every row twice
        in one ordered stream, and the second copy of a bar derives a 1.0 split
        against the first — a real ratio silently overwritten by 'no split'."""
        from sentinel.feed import staging

        staging.stage(conn, sep_rows(3), run_id=RUN, chunk="c")
        staging.stage(conn, sep_rows(3), run_id=RUN, chunk="c")
        assert len(list(staging.staged(conn, run_id=RUN, chunk="c"))) == \
            3 * SECURITIES

    def test_the_staged_read_is_ORDERED_by_session_then_ticker(self, conn):
        from sentinel.feed import staging

        import random
        rows = list(sep_rows(6))
        random.Random(7).shuffle(rows)
        staging.stage(conn, iter(rows), run_id=RUN, chunk="c")

        got = [(r["date"], r["ticker"])
               for r in staging.staged(conn, run_id=RUN, chunk="c")]
        assert got == sorted(got)
