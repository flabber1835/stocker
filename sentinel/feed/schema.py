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

    # EVIDENCE THAT EVIDENCE WAS LOST. `NormalisationReport` retains at most
    # `max_rejections` rejection rows per chunk and then only counts the rest,
    # which is correct — a broad identity outage must not put a million rows in
    # memory. What was NOT correct is that the count died with the process, so
    # certification reasoned over the retained subset and reported CLEAR while
    # the majority of the evidence had never been written anywhere.
    #
    # A truncation overlapping a certified interval makes that interval
    # UNCERTIFIABLE. Not a warning: the audit's whole claim is that it examined
    # every refused row, and here it demonstrably did not.
    """CREATE TABLE IF NOT EXISTS sentinel_rejection_truncation (
        run_id       UUID NOT NULL,
        chunk        TEXT NOT NULL,
        window_start DATE NOT NULL,
        window_end   DATE NOT NULL,
        retained     BIGINT NOT NULL,
        truncated    BIGINT NOT NULL,
        recorded_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        PRIMARY KEY (run_id, chunk))""",
    """CREATE INDEX IF NOT EXISTS idx_sentinel_trunc_window
        ON sentinel_rejection_truncation (window_start, window_end)""",

    # CORPUS ANOMALIES the ingest resolved but did not RESOLVE AWAY.
    #
    #   SPLIT_DISAGREEMENT   ACTIONS and the price domains describe different
    #                        events. ACTIONS wins, correctly — and one of the
    #                        two sources is wrong about this security, which is
    #                        a fact about the corpus, not a log line.
    #   SPLIT_ONLY_DERIVED   the prices show a split ACTIONS never recorded.
    #                        The fallback is working as designed, so this is
    #                        recorded and does NOT gate.
    #   UNUSABLE_DIVIDEND    a distribution with no stated amount. Nothing
    #                        accrues, which understates rather than invents —
    #                        but from a certification standpoint "unknown
    #                        amount" must not silently become 0.0.
    #
    # Persisted because a warning that scrolled past during a six-hour seed is
    # not something a certification can consult.
    """CREATE TABLE IF NOT EXISTS sentinel_corpus_anomalies (
        kind    TEXT NOT NULL,
        ticker  TEXT NOT NULL,
        session DATE NOT NULL,
        detail  TEXT,
        first_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        PRIMARY KEY (kind, ticker, session))""",
    """CREATE INDEX IF NOT EXISTS idx_sentinel_anomalies_session
        ON sentinel_corpus_anomalies (session)""",

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
    # ------------------------------------------------------------------
    # CORPUS VERSIONS. Architecture invariant #3 — "every snapshot and
    # decision records data_version" — was ADOPTED and UNIMPLEMENTED: there was
    # no version to record, and `sentinel_bars` is a destructive upsert, so a
    # Sharadar restatement rewrote the evidence under a decision already made.
    #
    # AN INGEST RUN IS NOT A CORPUS VERSION. A run that fails halfway has a
    # run_id, and it must never be citable. A version exists only when a
    # coherent, validated state was PUBLISHED.
    #
    # DETECTION tier: this answers "a decision read v47, the corpus is now v52,
    # so a replay may not reproduce it". It does NOT answer "show me v47" —
    # that is the RECONSTRUCTION tier, which needs revision history and is
    # deliberately deferred. See docs/sentinel-execution-contract.md §8.
    # ------------------------------------------------------------------
    """CREATE TABLE IF NOT EXISTS sentinel_corpus_publications (
        version          BIGSERIAL PRIMARY KEY,
        previous_version BIGINT,
        run_id           UUID,
        published_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        window_start     DATE,
        window_end       DATE,
        evidence         JSONB NOT NULL DEFAULT '{}'::jsonb)""",
    # A GAP IN THE CHAIN IS THE CORRUPTION SIGNAL: rows written by a run that
    # never published. Cheap to detect precisely because the link is explicit.
    """CREATE INDEX IF NOT EXISTS idx_sentinel_publications_prev
        ON sentinel_corpus_publications (previous_version)""",
    # PUBLISHED IS WHAT READABLE MEANS. Every corpus read carries
    # `publication.visible_predicate()`, whose EXISTS probes this column on a
    # table the planner would otherwise seq-scan once per query plan.
    """CREATE INDEX IF NOT EXISTS idx_sentinel_publications_run
        ON sentinel_corpus_publications (run_id)""",

    # WHICH INGEST LAST TOUCHED THIS ROW. Nearly free — `write_bars` already
    # runs inside an `IngestRun` — and it answers "which ingest produced this
    # value" without any revision history. ALTER rather than a column in the
    # CREATE, for the same reason the rejection columns are: CREATE TABLE IF NOT
    # EXISTS does nothing to an already-seeded database, so a fresh schema would
    # pass every test while the deployed corpus kept the old shape.
    """ALTER TABLE sentinel_bars
        ADD COLUMN IF NOT EXISTS last_written_run_id UUID""",
    """ALTER TABLE sentinel_actions
        ADD COLUMN IF NOT EXISTS last_written_run_id UUID""",
    # PARTIAL, on the non-NULL rows only. The coherence check asks "how many
    # rows belong to these unpublished runs?", and the answer is normally zero —
    # which an index turns into a lookup and a bare scan turns into reading
    # tens of millions of rows to prove a negative. NULLs are excluded because
    # they are the pre-provenance majority in an upgraded corpus and are never
    # the subject of the question.
    """CREATE INDEX IF NOT EXISTS idx_sentinel_bars_written_by
        ON sentinel_bars (last_written_run_id)
        WHERE last_written_run_id IS NOT NULL""",
    """CREATE INDEX IF NOT EXISTS idx_sentinel_actions_written_by
        ON sentinel_actions (last_written_run_id)
        WHERE last_written_run_id IS NOT NULL""",

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

    # ------------------------------------------------------------------
    # THE CHUNK SORT, moved out of the interpreter. See sentinel/feed/staging.py.
    #
    # `normalise_sep_rows` requires session order and the vendor's cursor-paged
    # API promises none, so the ingest sorted the chunk in memory — and a chunk
    # is a calendar year of the whole universe, ~2.5M vendor dicts, 1-2 GB
    # against a 2g container ceiling. PostgreSQL sorts with bounded memory and
    # spills to disk; the interpreter does not.
    #
    # UNLOGGED because every row is a verbatim copy of something the vendor will
    # serve again. WAL for 2.5M scratch rows a night protects data that is
    # cheaper to re-fetch than to replay, and an unclean shutdown truncating the
    # table is the CORRECT disposition for a partial chunk. Nothing durable is
    # ever read from here — `sentinel_bars` is the corpus.
    #
    # NO INDEX, deliberately. This is written once and read once, in full: a
    # btree would pay random-I/O maintenance on every insert to save a sort that
    # PostgreSQL does better as one sequential pass and a merge. The (run_id,
    # chunk) scoping is satisfied by the same scan.
    # ------------------------------------------------------------------
    """CREATE UNLOGGED TABLE IF NOT EXISTS sentinel_sep_staging (
        run_id     UUID NOT NULL,
        chunk      TEXT NOT NULL,
        session    DATE NOT NULL,
        ticker     TEXT NOT NULL,
        open       DOUBLE PRECISION,
        close      DOUBLE PRECISION,
        closeunadj DOUBLE PRECISION,
        volume     DOUBLE PRECISION)""",
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
