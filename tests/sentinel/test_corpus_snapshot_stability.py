"""P0 — the pin froze the VERSION NUMBER, not the rows it names.

THE FAILURE, written before the fix.

`visible_predicate` makes a row visible when its CURRENT `last_written_run_id`
belongs to some published run. A reader's shared advisory lock stops a new
PUBLICATION landing mid-session. It does nothing about the rows themselves, and
`sentinel_bars` is a destructive in-place upsert:

```text
v41 is published; AAA/2026-08-10 is visible
Wealth Core pins v41 and starts reading
        |
        v
the daily ingest starts and UPSERTs AAA/2026-08-10
last_written_run_id becomes run42, which nothing has published
        |
        v
visible_predicate now HIDES that row
        |
        v
the same calculation, still nominally reading v41, sees a different corpus
```

The published version has not moved. `require_current` still answers 41. And the
contents of "v41", as seen by a reader in the middle of using it, changed
underneath it. A bar can vanish mid-window, or reappear with a restated split
ratio, and the decision that comes out carries `data_version = 41` describing a
snapshot that never existed as a whole.

"Published is what readable means" bought the right property against a corpus
that only ever GROWS. Against one that is rewritten in place it is not enough:
the predicate is evaluated per query, and the thing it evaluates is mutable.

THE PROPERTY BEING BOUGHT: **while a session holds the corpus pinned, the rows
that pin names do not change.** Not "the version number is stable" — the
snapshot is.
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "shared"))

from tests.support.postgres import _EphemeralPostgres  # noqa: E402

from sentinel.core import loader  # noqa: E402
from sentinel.feed import publication as P  # noqa: E402
from sentinel.feed import store as S  # noqa: E402


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
        cur.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'")
        for (t,) in cur.fetchall():
            cur.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
    c.commit()
    S.ensure_schema(c)
    yield c
    c.close()


class Bar:
    """The shape `write_bars` accepts."""

    def __init__(self, sid, session, ticker="AAA", close=10.0, ratio=1.0):
        self.security_id, self.session, self.ticker = sid, session, ticker
        self.raw_close = self.raw_open = close
        self.volume, self.split_ratio, self.dividend_per_share = 1000.0, ratio, 0.0


def a_published_corpus(conn):
    run = S.IngestRun(conn, "seed").progress.run_id
    S.write_bars(conn, [Bar("P-AAA", "2026-08-10")], run_id=run)
    P.publish(conn, run_id=run)
    return run


class TestTheFailure:
    def test_an_ingest_CANNOT_rewrite_rows_a_reader_has_pinned(self, conn, pg):
        """The headline, as a race.

        A reader holds the pin. A second connection — the daily ingest — tries
        to upsert a row inside the pinned window. It must not succeed while the
        pin is held; the snapshot the reader is describing as v41 has to stay
        the rows v41 named.
        """
        a_published_corpus(conn)
        writer = S.connect(pg.sync_dsn)
        blocked = {}

        with P.pinned(conn) as pin:
            assert pin.version == 1

            def try_to_write():
                # EXACTLY WHAT AN INGEST DOES: take the write lock, then write
                # under it. The exclusion happens at acquisition — that is the
                # production sequence, and a raw `write_bars` here would test a
                # path no ingest takes.
                try:
                    with S.corpus_write_lock(writer):
                        run2 = S.IngestRun(writer, "daily").progress.run_id
                        S.write_bars(writer,
                                     [Bar("P-AAA", "2026-08-10", ratio=2.0)],
                                     run_id=run2, require_lock=True)
                    blocked["result"] = "WROTE"
                except Exception as exc:                      # noqa: BLE001
                    blocked["result"] = type(exc).__name__

            t = threading.Thread(target=try_to_write)
            t.start()
            t.join(timeout=5)

            # The reader's view, taken WHILE the writer was trying.
            window = loader.load_window(conn, start="2026-08-01", end="2026-08-31")
            assert window.sessions == ["2026-08-10"], (
                "the pinned row vanished mid-session — the ingest re-stamped it "
                "with an unpublished run and the predicate hid it")

        t.join(timeout=5)
        writer.close()
        assert blocked.get("result") == "CorpusBusy", (
            "the ingest rewrote a row while a reader held the corpus pinned")

    def test_the_row_CONTENT_is_stable_across_the_whole_pin(self, conn, pg):
        """Hiding is not the only way a snapshot moves. A restated split ratio
        rewrites a SHARE COUNT under a calculation already using it, and that
        one does not even change the row count."""
        a_published_corpus(conn)
        writer = S.connect(pg.sync_dsn)

        with P.pinned(conn):
            before = loader.load_window(conn, start="2026-08-01",
                                        end="2026-08-31")
            ratio_before = before.bars_by_session["2026-08-10"][0].split_ratio

            def try_to_write():
                try:
                    with S.corpus_write_lock(writer):
                        run2 = S.IngestRun(writer, "daily").progress.run_id
                        S.write_bars(writer,
                                     [Bar("P-AAA", "2026-08-10", ratio=2.0)],
                                     run_id=run2, require_lock=True)
                except Exception:                             # noqa: BLE001
                    pass

            t = threading.Thread(target=try_to_write)
            t.start()
            t.join(timeout=5)

            after = loader.load_window(conn, start="2026-08-01", end="2026-08-31")
            assert after.bars_by_session["2026-08-10"][0].split_ratio \
                == ratio_before

        t.join(timeout=5)
        writer.close()


class TestTheWriterSideIsSTRUCTURAL:
    def test_write_bars_REFUSES_without_the_corpus_lock(self, conn):
        """Not a documented prerequisite — an enforced one. A rule that lives
        in a docstring is a rule the next ingest path can simply not follow,
        and this one is the difference between a stable snapshot and a
        plausible wrong number.
        """
        with pytest.raises(P.CorpusBusy, match="lock"):
            S.write_bars(conn, [Bar("P-AAA", "2026-08-11")],
                         run_id=None, require_lock=True)

    def test_the_INGEST_takes_it_for_its_whole_duration(self, conn):
        """Per-chunk acquisition would leave a window between chunks in which a
        reader could pin a half-written corpus, which is the same defect one
        level down."""
        from tests.support.source import code_of

        from sentinel.feed import ingest

        for name in ("seed", "daily"):
            src = code_of(getattr(ingest, name))
            assert "corpus_write_lock" in src, (
                f"{name} writes the corpus without holding it still")

    def test_a_reader_CANNOT_pin_while_an_ingest_holds_it(self, conn, pg):
        """The other direction. Pinning a corpus mid-rewrite would stamp a
        decision with a version whose rows are half of one generation and half
        of another."""
        a_published_corpus(conn)
        writer = S.connect(pg.sync_dsn)
        try:
            with S.corpus_write_lock(writer):
                with pytest.raises(P.CorpusBusy):
                    with P.pinned(conn):
                        pass                                  # pragma: no cover
        finally:
            writer.close()


class TestItStillLetsTheORDINARYCaseThrough:
    def test_an_ingest_with_no_reader_writes_normally(self, conn):
        run = S.IngestRun(conn, "daily").progress.run_id
        with S.corpus_write_lock(conn):
            n = S.write_bars(conn, [Bar("P-AAA", "2026-08-12")], run_id=run,
                             require_lock=True)
        assert n == 1

    def test_a_reader_with_no_ingest_pins_normally(self, conn):
        a_published_corpus(conn)
        with P.pinned(conn) as pin:
            assert pin.version == 1

    def test_two_readers_may_hold_the_pin_at_once(self, conn, pg):
        """SHARED, not exclusive. The panel and a decision session both read;
        making them queue behind each other would be a self-inflicted outage
        with no safety benefit — neither of them writes."""
        a_published_corpus(conn)
        other = S.connect(pg.sync_dsn)
        try:
            with P.pinned(conn):
                with P.pinned(other) as second:
                    assert second.version == 1
        finally:
            other.close()
