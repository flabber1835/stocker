"""Sentinel's own database — the corpus, and a DURABLE record of ingest progress.

One database, Sentinel's own. Reading `bt-postgres` would have been faster: it
already holds 35M rows of the same corpus. It was rejected because bt-postgres is
a Stocker-stack container running the Wealth Core rehearsals, and a Sentinel that
cannot start unless a retired platform's database is up is not a retirement.

## Progress is a TABLE, not a variable

`GET /wealth-core/progress` on bt-engine serves a snapshot held **in memory**.
That decision cost real diagnosis time this month: after a container restart the
endpoint returned empty while the run row still said `running`, so a dead job and
a healthy one that had not yet published looked identical — and on 2026-08-09 a
three-hour rehearsal was waited on for half an hour with no process behind it.

`feed_ingest_runs` is the correction. Every chunk COMMITS its progress, so any
other connection can read it, it survives the process, and "how far did it get
before it died" is answerable afterwards. A long seed the operator cannot watch
is a long seed the operator will interrupt.

## Tables

```text
sentinel_bars          one row per (security, session). The corpus
sentinel_actions       SHARADAR/ACTIONS, the authoritative corporate-action stream
sentinel_universe      SHARADAR/TICKERS snapshots, for identity and eligibility
feed_ingest_runs       progress and history, committed per chunk
```
"""
from __future__ import annotations

#: `close_unadjusted` is NOT NULL by construction: a bar without an as-traded
#: price cannot be marked or executed, and `domains.normalise_sep_rows` drops it
#: before it reaches here. The constraint makes that a schema property rather
#: than a convention someone can bypass with a direct INSERT.
DDL = [
    """CREATE TABLE IF NOT EXISTS sentinel_bars (
        security_id       TEXT        NOT NULL,
        session           DATE        NOT NULL,
        ticker            TEXT        NOT NULL,
        close_signal      DOUBLE PRECISION,
        close_unadjusted  DOUBLE PRECISION NOT NULL,
        open_unadjusted   DOUBLE PRECISION,
        volume            DOUBLE PRECISION,
        split_ratio       DOUBLE PRECISION NOT NULL DEFAULT 1.0,
        dividend_per_share DOUBLE PRECISION NOT NULL DEFAULT 0.0,
        PRIMARY KEY (security_id, session))""",
    """CREATE INDEX IF NOT EXISTS idx_sentinel_bars_session
        ON sentinel_bars (session)""",

    # RAW VENDOR ROWS THE INGEST REFUSED. Not a log — EVIDENCE.
    #
    # A SEP row whose ticker cannot be resolved to a permanent security is
    # dropped before `sentinel_bars`, correctly: keying it on the ticker would
    # re-introduce the reuse splice. But the terminal-identity accounting then
    # asks "did the vendor price this ticker in the window?" and reads the
    # answer from `sentinel_bars`, where the row no longer is — so a terminal
    # action for that ticker was classified SECURITY_ABSENT_FROM_CORPUS, which
    # is the one exclusion that must never be able to swallow an identity
    # failure. This table is what makes the raw presence survive the drop.
    # The PRICE and VOLUME are carried because certification has to answer
    # "could this dropped security have changed the universe, the ranking or
    # the selection?", and the eligibility floors decide that from an
    # as-traded price, a dollar volume and a session count. A rejection row
    # holding only a ticker and a date leaves that permanently UNDETERMINED —
    # which under a fail-closed certification rule blocks the rehearsal instead
    # of informing it.
    """CREATE TABLE IF NOT EXISTS sentinel_ingest_rejections (
        ticker           TEXT NOT NULL,
        session          DATE NOT NULL,
        reason           TEXT NOT NULL,
        close_unadjusted DOUBLE PRECISION,
        volume           DOUBLE PRECISION,
        first_seen       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        PRIMARY KEY (ticker, session, reason))""",
    # CREATE TABLE IF NOT EXISTS does nothing to a table that already exists,
    # so an already-seeded database would keep the two-column version and the
    # audit would read NULL prices forever while every test on a fresh schema
    # passed.
    """ALTER TABLE sentinel_ingest_rejections
        ADD COLUMN IF NOT EXISTS close_unadjusted DOUBLE PRECISION""",
    """ALTER TABLE sentinel_ingest_rejections
        ADD COLUMN IF NOT EXISTS volume DOUBLE PRECISION""",
    """CREATE INDEX IF NOT EXISTS idx_sentinel_rejections_session
        ON sentinel_ingest_rejections (session)""",

    """CREATE TABLE IF NOT EXISTS sentinel_actions (
        ticker       TEXT NOT NULL,
        session      DATE NOT NULL,
        action       TEXT NOT NULL,
        value        DOUBLE PRECISION,
        contraticker TEXT,
        PRIMARY KEY (ticker, session, action))""",

    """CREATE TABLE IF NOT EXISTS sentinel_universe (
        permaticker      TEXT NOT NULL,
        ticker           TEXT NOT NULL,
        category         TEXT,
        related_tickers  TEXT,
        first_price_date DATE,
        last_price_date  DATE,
        is_delisted      BOOLEAN,
        snapshot_date    DATE NOT NULL,
        PRIMARY KEY (permaticker, ticker, snapshot_date))""",

    # PROGRESS. Written per chunk and COMMITTED, so `feed-status` from another
    # process — or after a crash — sees the truth rather than a stale guess.
    """CREATE TABLE IF NOT EXISTS feed_ingest_runs (
        run_id        UUID PRIMARY KEY,
        kind          TEXT NOT NULL,
        status        TEXT NOT NULL DEFAULT 'running'
                      CHECK (status IN ('running','success','failed')),
        started_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        completed_at  TIMESTAMPTZ,
        date_from     DATE,
        date_to       DATE,
        chunks_total  INTEGER NOT NULL DEFAULT 0,
        chunks_done   INTEGER NOT NULL DEFAULT 0,
        rows_written  BIGINT  NOT NULL DEFAULT 0,
        rows_dropped  BIGINT  NOT NULL DEFAULT 0,
        current_chunk TEXT,
        error_message TEXT)""",
    """CREATE INDEX IF NOT EXISTS idx_feed_ingest_runs_started
        ON feed_ingest_runs (started_at DESC)""",
]

#: Marks a run abandoned by a process that died. Same `RESTART_ABORTED:` prefix
#: Stocker's services use, and for the same reason: a caller must be able to tell
#: "this failed" from "this was interrupted and can simply be re-run".
RESTART_ABORT_MARKER = "RESTART_ABORTED"

RECLAIM_ORPHANS = """
    UPDATE feed_ingest_runs
       SET status='failed', completed_at=NOW(),
           error_message=%(marker)s || ': the process running this ingest did not '
             'survive. Nothing is still working; re-run it. Rows already '
             'committed are kept — the upserts are idempotent, so a re-run '
             'resumes rather than duplicates.'
     WHERE status='running'
"""
