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
sentinel_defensive_bars fixed-identity BIL execution/return fields from SFP
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
    # Exact predecessor lookup needs mixed ordering. The primary key can produce
    # ASC/ASC or DESC/DESC globally, not security ASC with session DESC. INCLUDE
    # keeps the one-row-per-security probe on the index instead of turning it
    # into thousands of random heap reads on the NAS.
    """CREATE INDEX IF NOT EXISTS idx_sentinel_bars_predecessor
        ON sentinel_bars (security_id ASC, session DESC)
        INCLUDE (close_signal, close_unadjusted)""",
    # Dedicated total-return domain. Wealth Core is structurally unable to read
    # it; only sentinel.regime uses it when assembling a production observation.
    """CREATE TABLE IF NOT EXISTS sentinel_spy_total_return (
        session             DATE PRIMARY KEY,
        closeadj            DOUBLE PRECISION NOT NULL,
        last_written_run_id UUID)""",
    """CREATE INDEX IF NOT EXISTS idx_sentinel_spy_total_return_written_by
        ON sentinel_spy_total_return (last_written_run_id)
        WHERE last_written_run_id IS NOT NULL""",
    # BIL is an execution instrument, not an SEP company.  Keep the fixed
    # Sentinel identity and the four consumed SFP price fields outside Wealth
    # Core's equity corpus. ``open_signal * close_adjusted / close_signal`` is
    # the canonical total-return adjusted open used by next-open scalar
    # accounting. ``close_unadjusted`` remains the tradable broker mark;
    # ``close_signal`` also translates ACTIONS dividends from the split-adjusted
    # source basis onto raw paper shares.
    """CREATE TABLE IF NOT EXISTS sentinel_defensive_bars (
        security_id         TEXT NOT NULL DEFAULT 'SENTINEL:BIL'
                            CHECK (security_id = 'SENTINEL:BIL'),
        session             DATE PRIMARY KEY,
        ticker              TEXT NOT NULL DEFAULT 'BIL'
                            CHECK (ticker = 'BIL'),
        open_signal         DOUBLE PRECISION
                            CONSTRAINT sentinel_defensive_bars_open_signal_valid
                            CHECK (open_signal IS NULL OR
                                   (open_signal > 0
                                    AND open_signal NOT IN
                                        ('NaN'::DOUBLE PRECISION,
                                         'Infinity'::DOUBLE PRECISION))),
        close_signal        DOUBLE PRECISION NOT NULL
                            CHECK (close_signal > 0
                                   AND close_signal NOT IN
                                       ('NaN'::DOUBLE PRECISION,
                                        'Infinity'::DOUBLE PRECISION)),
        close_adjusted      DOUBLE PRECISION
                            CONSTRAINT sentinel_defensive_bars_close_adjusted_valid
                            CHECK (close_adjusted IS NULL OR
                                   (close_adjusted > 0
                                    AND close_adjusted NOT IN
                                        ('NaN'::DOUBLE PRECISION,
                                         'Infinity'::DOUBLE PRECISION))),
        close_unadjusted    DOUBLE PRECISION NOT NULL
                            CHECK (close_unadjusted > 0
                                   AND close_unadjusted NOT IN
                                       ('NaN'::DOUBLE PRECISION,
                                        'Infinity'::DOUBLE PRECISION)),
        last_written_run_id UUID)""",
    # Existing appliances already hold published BIL marks. Neither of these
    # source fields can be reconstructed honestly from the two retained closes,
    # so the explicit migration adds nullable columns and readiness refuses the
    # legacy NULL tail until a bounded SFP ingest rewrites it. A synthetic
    # backfill would make historical scalar returns look authoritative when they
    # are not.
    """ALTER TABLE sentinel_defensive_bars
        ADD COLUMN IF NOT EXISTS open_signal DOUBLE PRECISION""",
    """ALTER TABLE sentinel_defensive_bars
        ADD COLUMN IF NOT EXISTS close_adjusted DOUBLE PRECISION""",
    """DO $$
        BEGIN
          IF NOT EXISTS (
              SELECT 1 FROM pg_constraint
               WHERE conrelid = 'sentinel_defensive_bars'::regclass
                 AND conname = 'sentinel_defensive_bars_open_signal_valid') THEN
            ALTER TABLE sentinel_defensive_bars
              ADD CONSTRAINT sentinel_defensive_bars_open_signal_valid
              CHECK (open_signal IS NULL OR
                     (open_signal > 0 AND open_signal NOT IN
                         ('NaN'::DOUBLE PRECISION,
                          'Infinity'::DOUBLE PRECISION)));
          END IF;
          IF NOT EXISTS (
              SELECT 1 FROM pg_constraint
               WHERE conrelid = 'sentinel_defensive_bars'::regclass
                 AND conname = 'sentinel_defensive_bars_close_adjusted_valid') THEN
            ALTER TABLE sentinel_defensive_bars
              ADD CONSTRAINT sentinel_defensive_bars_close_adjusted_valid
              CHECK (close_adjusted IS NULL OR
                     (close_adjusted > 0 AND close_adjusted NOT IN
                         ('NaN'::DOUBLE PRECISION,
                          'Infinity'::DOUBLE PRECISION)));
          END IF;
        END $$""",
    """CREATE INDEX IF NOT EXISTS idx_sentinel_defensive_bars_written_by
        ON sentinel_defensive_bars (last_written_run_id)
        WHERE last_written_run_id IS NOT NULL""",

    # RAW VENDOR ROWS THE INGEST REFUSED. Append-only observations, not a
    # mutable statement that this ticker/date is rejected forever. Publication
    # chooses which generation became authoritative, and a later published bar
    # can resolve the active rejection without erasing the failed history.
    """CREATE TABLE IF NOT EXISTS sentinel_ingest_rejections (
        observation_id    BIGSERIAL PRIMARY KEY,
        ticker            TEXT NOT NULL,
        session           DATE NOT NULL,
        reason            TEXT NOT NULL,
        close_unadjusted  DOUBLE PRECISION,
        volume            DOUBLE PRECISION,
        first_seen        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        last_written_run_id UUID)""",
    # Upgrade the legacy mutable (ticker,session,reason) table in place. Legacy
    # observations retain NULL provenance; that is UNKNOWN, not permission to
    # invent the ingest that produced them. A later publication timestamp can
    # still prove current resolution without guessing their producer.
    """ALTER TABLE sentinel_ingest_rejections
        ADD COLUMN IF NOT EXISTS close_unadjusted DOUBLE PRECISION""",
    """ALTER TABLE sentinel_ingest_rejections
        ADD COLUMN IF NOT EXISTS volume DOUBLE PRECISION""",
    """ALTER TABLE sentinel_ingest_rejections
        ADD COLUMN IF NOT EXISTS observation_id BIGSERIAL""",
    """ALTER TABLE sentinel_ingest_rejections
        ADD COLUMN IF NOT EXISTS last_written_run_id UUID""",
    """DO $$
        DECLARE old_primary_key TEXT;
        BEGIN
          SELECT c.conname INTO old_primary_key
            FROM pg_constraint c
           WHERE c.conrelid = 'sentinel_ingest_rejections'::regclass
             AND c.contype = 'p'
             AND c.conkey <> ARRAY[(SELECT attnum FROM pg_attribute
                                     WHERE attrelid = c.conrelid
                                       AND attname = 'observation_id')]::smallint[];
          IF old_primary_key IS NOT NULL THEN
            EXECUTE format('ALTER TABLE sentinel_ingest_rejections DROP CONSTRAINT %I',
                           old_primary_key);
          END IF;
          IF NOT EXISTS (
              SELECT 1 FROM pg_constraint
               WHERE conrelid = 'sentinel_ingest_rejections'::regclass
                 AND contype = 'p') THEN
            ALTER TABLE sentinel_ingest_rejections
              ADD CONSTRAINT sentinel_ingest_rejections_pkey
              PRIMARY KEY (observation_id);
          END IF;
        END $$""",
    """CREATE INDEX IF NOT EXISTS idx_sentinel_rejections_session
        ON sentinel_ingest_rejections (session)""",
    """CREATE INDEX IF NOT EXISTS idx_sentinel_rejections_written_by
        ON sentinel_ingest_rejections (last_written_run_id)
        WHERE last_written_run_id IS NOT NULL""",
    """CREATE UNIQUE INDEX IF NOT EXISTS uq_sentinel_rejection_run_observation
        ON sentinel_ingest_rejections
           (ticker, session, reason, last_written_run_id)
        WHERE last_written_run_id IS NOT NULL""",
    """CREATE UNIQUE INDEX IF NOT EXISTS uq_sentinel_rejection_legacy_observation
        ON sentinel_ingest_rejections (ticker, session, reason)
        WHERE last_written_run_id IS NULL""",
    # The active projection partitions by case-folded ticker/session/reason.
    # Keep that expression indexable rather than forcing a sort over the raw
    # observation history every time rejection-audit asks for current evidence.
    """CREATE INDEX IF NOT EXISTS idx_sentinel_rejections_active_projection_key
        ON sentinel_ingest_rejections
           (UPPER(ticker), session, reason, observation_id DESC)""",

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

    # CORPUS ANOMALY OBSERVATIONS. Append-only history; publication chooses the
    # active disposition. A failed ingest must not erase the last published
    # blocker merely because it wrote a newer candidate row.
    #
    #   SPLIT_DISAGREEMENT   ACTIONS and the price domains describe different
    #                        events. ACTIONS wins, correctly — and one of the
    #                        two sources is wrong about this security, which is
    #                        a fact about the corpus, not a log line.
    #   SPLIT_ONLY_DERIVED   the prices show a split ACTIONS never recorded.
    #                        It gates absent a full-interval equivalence proof.
    #   UNUSABLE_DIVIDEND    a distribution with no stated amount. Nothing
    #                        accrues, which understates rather than invents —
    #                        but from a certification standpoint "unknown
    #                        amount" must not silently become 0.0.
    #
    # NULL last_written_run_id is the deterministic legacy baseline. Schema
    # upgrade keeps those rows active rather than inventing provenance or
    # silently resetting durable evidence.
    """CREATE TABLE IF NOT EXISTS sentinel_corpus_anomalies (
        observation_id BIGSERIAL PRIMARY KEY,
        kind            TEXT NOT NULL,
        ticker          TEXT NOT NULL,
        session         DATE NOT NULL,
        detail          TEXT,
        first_seen      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        last_written_run_id UUID)""",
    # Upgrade the former (kind,ticker,session) mutable set in place. Adding a
    # BIGSERIAL fills every legacy row with a durable identity. The old PK is
    # dropped only when it is not already the observation-id PK.
    """ALTER TABLE sentinel_corpus_anomalies
        ADD COLUMN IF NOT EXISTS observation_id BIGSERIAL""",
    """ALTER TABLE sentinel_corpus_anomalies
        ADD COLUMN IF NOT EXISTS last_written_run_id UUID""",
    """DO $$
        DECLARE old_primary_key TEXT;
        BEGIN
          SELECT c.conname INTO old_primary_key
            FROM pg_constraint c
           WHERE c.conrelid = 'sentinel_corpus_anomalies'::regclass
             AND c.contype = 'p'
             AND c.conkey <> ARRAY[(SELECT attnum FROM pg_attribute
                                     WHERE attrelid = c.conrelid
                                       AND attname = 'observation_id')]::smallint[];
          IF old_primary_key IS NOT NULL THEN
            EXECUTE format('ALTER TABLE sentinel_corpus_anomalies DROP CONSTRAINT %I',
                           old_primary_key);
          END IF;
          IF NOT EXISTS (
              SELECT 1 FROM pg_constraint
               WHERE conrelid = 'sentinel_corpus_anomalies'::regclass
                 AND contype = 'p') THEN
            ALTER TABLE sentinel_corpus_anomalies
              ADD CONSTRAINT sentinel_corpus_anomalies_pkey
              PRIMARY KEY (observation_id);
          END IF;
        END $$""",
    """CREATE INDEX IF NOT EXISTS idx_sentinel_anomalies_session
        ON sentinel_corpus_anomalies (session)""",
    """CREATE INDEX IF NOT EXISTS idx_sentinel_anomalies_written_by
        ON sentinel_corpus_anomalies (last_written_run_id)
        WHERE last_written_run_id IS NOT NULL""",
    # Repeating a chunk in one ingest updates that run's observation instead of
    # multiplying history. Legacy callers retain their old idempotent key.
    """CREATE UNIQUE INDEX IF NOT EXISTS uq_sentinel_anomaly_run_observation
        ON sentinel_corpus_anomalies
           (kind, ticker, session, last_written_run_id)
        WHERE last_written_run_id IS NOT NULL""",
    """CREATE UNIQUE INDEX IF NOT EXISTS uq_sentinel_anomaly_legacy_observation
        ON sentinel_corpus_anomalies (kind, ticker, session)
        WHERE last_written_run_id IS NULL""",
    # One split disposition per economic event per candidate generation. A
    # legacy baseline can contain ties; those predate this invariant and the
    # active reader deliberately keeps every tie so unsafe evidence still wins.
    """DROP INDEX IF EXISTS uq_sentinel_anomaly_split_event_run""",
    """CREATE UNIQUE INDEX uq_sentinel_anomaly_split_event_run
        ON sentinel_corpus_anomalies (ticker, session, last_written_run_id)
        WHERE last_written_run_id IS NOT NULL AND kind IN (
          'SPLIT_AUTHORITATIVE_APPLIED', 'SPLIT_CORROBORATED_DERIVED',
          'SPLIT_ONLY_DERIVED', 'SEAM_SPLIT_UNCORROBORATED',
          'SPLIT_DISAGREEMENT', 'AMBIGUOUS_SPLIT_MULTIPLICITY',
          'SPLIT_RESOLVED_NO_EVENT')""",

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
        sector           TEXT,
        related_tickers  TEXT,
        first_price_date DATE,
        last_price_date  DATE,
        is_delisted      BOOLEAN,
        snapshot_date    DATE NOT NULL,
        PRIMARY KEY (permaticker, ticker, snapshot_date))""",
    """ALTER TABLE sentinel_universe ADD COLUMN IF NOT EXISTS sector TEXT""",
    """ALTER TABLE sentinel_universe
        ADD COLUMN IF NOT EXISTS last_written_run_id UUID""",

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
    # Current rejection state is a PROJECTION of immutable observations. A
    # published rejection remains active until a later published bar for the
    # same ticker/session proves it was repaired. Failed/unpublished rejection
    # candidates never become active. Legacy NULL-run observations are not
    # attributed by guess: only a provenance-tracked publication occurring
    # after their durable `first_seen` timestamp may resolve them.
    """DROP VIEW IF EXISTS sentinel_active_ingest_rejections""",
    """CREATE VIEW sentinel_active_ingest_rejections AS
        WITH candidates AS (
          SELECT r.observation_id,r.ticker,r.session,r.reason,
                 r.close_unadjusted,r.volume,r.first_seen,
                 r.last_written_run_id,p.version AS publication_version
            FROM sentinel_ingest_rejections r
            LEFT JOIN sentinel_corpus_publications p
              ON p.run_id=r.last_written_run_id
           WHERE r.last_written_run_id IS NULL OR p.run_id IS NOT NULL
        ), unresolved AS (
          SELECT c.*
            FROM candidates c
           WHERE NOT EXISTS (
             SELECT 1
               FROM sentinel_bars b
               JOIN sentinel_corpus_publications bp
                 ON bp.run_id=b.last_written_run_id
              WHERE UPPER(b.ticker)=UPPER(c.ticker)
                AND b.session=c.session
                AND ((c.last_written_run_id IS NOT NULL
                      AND bp.version > c.publication_version)
                     OR (c.last_written_run_id IS NULL
                         AND bp.published_at >= c.first_seen)))
        ), ranked AS (
          SELECT u.*,
                 ROW_NUMBER() OVER (
                   PARTITION BY UPPER(ticker),session,reason
                   ORDER BY COALESCE(publication_version,0) DESC,
                            observation_id DESC) AS active_rank
            FROM unresolved u
        )
        SELECT observation_id,ticker,session,reason,close_unadjusted,volume,
               first_seen,last_written_run_id,publication_version
          FROM ranked WHERE active_rank=1""",
    # PARTIAL, on the non-NULL rows only. The coherence check asks "how many
    # rows belong to these unpublished runs?", and the answer is normally zero —
    # which an index turns into a lookup and a bare scan turns into reading
    # tens of millions of rows to prove a negative. NULLs are excluded because
    # they are the pre-provenance majority in an upgraded corpus and are never
    # the subject of the question.
    """CREATE INDEX IF NOT EXISTS idx_sentinel_bars_written_by
        ON sentinel_bars (last_written_run_id)
        WHERE last_written_run_id IS NOT NULL""",
    # Active-rejection resolution is a case-insensitive ticker/session anti-join.
    # Without the matching expression index, each candidate can force scans over
    # the multi-million-row bar table even though the economic key is selective.
    """CREATE INDEX IF NOT EXISTS idx_sentinel_bars_active_rejection_lookup
        ON sentinel_bars (UPPER(ticker), session, last_written_run_id)
        WHERE last_written_run_id IS NOT NULL""",
    """CREATE INDEX IF NOT EXISTS idx_sentinel_actions_written_by
        ON sentinel_actions (last_written_run_id)
        WHERE last_written_run_id IS NOT NULL""",
    """CREATE INDEX IF NOT EXISTS idx_sentinel_universe_written_by
        ON sentinel_universe (last_written_run_id)
        WHERE last_written_run_id IS NOT NULL""",

    # APPLIED REPAIRS ARE APPEND-ONLY GENERATIONS. A repair must not UPDATE the
    # base bar a published decision may already name. Readers overlay the newest
    # repair whose run has a publication; an interrupted repair therefore leaves
    # the preceding effective ratio intact rather than hiding or rewriting it.
    """CREATE TABLE IF NOT EXISTS sentinel_bar_split_repairs (
        security_id        TEXT NOT NULL,
        session            DATE NOT NULL,
        split_ratio        DOUBLE PRECISION NOT NULL CHECK (split_ratio > 0),
        prior_split_ratio  DOUBLE PRECISION NOT NULL CHECK (prior_split_ratio > 0),
        last_written_run_id UUID NOT NULL,
        repaired_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        PRIMARY KEY (security_id, session, last_written_run_id),
        FOREIGN KEY (security_id, session)
            REFERENCES sentinel_bars (security_id, session) ON DELETE CASCADE)""",
    """CREATE INDEX IF NOT EXISTS idx_sentinel_split_repairs_written_by
        ON sentinel_bar_split_repairs (last_written_run_id)""",
    """CREATE INDEX IF NOT EXISTS idx_sentinel_split_repairs_bar
        ON sentinel_bar_split_repairs (security_id, session)""",

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
        error_message TEXT,
        source_git_commit TEXT,
        runtime_image_digest TEXT)""",
    # Existing ingest history predates deployment binding and remains readable
    # as explicitly unbound NULL provenance. Every new IngestRun supplies both
    # fields and every new run-backed publication refuses their absence.
    """ALTER TABLE feed_ingest_runs
        ADD COLUMN IF NOT EXISTS source_git_commit TEXT""",
    """ALTER TABLE feed_ingest_runs
        ADD COLUMN IF NOT EXISTS runtime_image_digest TEXT""",
    """CREATE INDEX IF NOT EXISTS idx_feed_ingest_runs_started
        ON feed_ingest_runs (started_at DESC)""",

    # ACTIONS is delivered as a COMPLETE snapshot for an explicitly requested
    # raw-date window.  An upsert cannot represent a row that disappeared from
    # that response, so post-upgrade ingests append a generation plus PRESENT /
    # REMOVED observations.  The original table remains the immutable legacy
    # baseline: discarding or rewriting it during upgrade would silently erase
    # durable corporate-action evidence already present on an appliance.
    """CREATE TABLE IF NOT EXISTS sentinel_action_generations (
        last_written_run_id UUID PRIMARY KEY,
        window_start        DATE NOT NULL,
        window_end          DATE NOT NULL,
        source_rows         BIGINT NOT NULL CHECK (source_rows >= 0),
        observed_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CHECK (window_start <= window_end))""",
    """CREATE TABLE IF NOT EXISTS sentinel_action_observations (
        source_row_id        TEXT NOT NULL,
        source_payload       JSONB NOT NULL,
        ticker              TEXT NOT NULL,
        session             DATE NOT NULL,
        action              TEXT NOT NULL,
        name                TEXT,
        value               DOUBLE PRECISION,
        contraticker        TEXT,
        contraname          TEXT,
        disposition         TEXT NOT NULL
                            CHECK (disposition IN ('PRESENT','REMOVED')),
        last_written_run_id UUID NOT NULL,
        observed_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        PRIMARY KEY (last_written_run_id, source_row_id))""",
    # PR #86 shipped the table at the invalid economic-event grain.  Upgrade it
    # transactionally: preserve every append-only observation, give old rows a
    # deterministic legacy identity from the content they retained, then move
    # the key.  If any statement fails ensure_schema rolls the whole migration
    # back; a partially keyed table can never look initialized.
    """ALTER TABLE sentinel_action_observations
        ADD COLUMN IF NOT EXISTS source_row_id TEXT""",
    """ALTER TABLE sentinel_action_observations
        ADD COLUMN IF NOT EXISTS source_payload JSONB""",
    """ALTER TABLE sentinel_action_observations
        ADD COLUMN IF NOT EXISTS name TEXT""",
    """ALTER TABLE sentinel_action_observations
        ADD COLUMN IF NOT EXISTS contraname TEXT""",
    """UPDATE sentinel_action_observations
           SET source_payload=jsonb_build_object(
                 'date',session::TEXT,'action',action,'ticker',ticker,
                 'name',name,
                 'value',CASE WHEN value IS NULL THEN NULL
                              ELSE value::TEXT END,
                 'contraticker',contraticker,'contraname',contraname)
         WHERE source_payload IS NULL""",
    """UPDATE sentinel_action_observations
           SET source_row_id='legacy-v1:' || md5(source_payload::TEXT)
         WHERE source_row_id IS NULL""",
    """DO $$
        DECLARE old_primary_key TEXT;
        BEGIN
          SELECT c.conname INTO old_primary_key
            FROM pg_constraint c
           WHERE c.conrelid='sentinel_action_observations'::regclass
             AND c.contype='p'
             AND c.conkey <> ARRAY[
               (SELECT attnum FROM pg_attribute WHERE attrelid=c.conrelid
                  AND attname='last_written_run_id'),
               (SELECT attnum FROM pg_attribute WHERE attrelid=c.conrelid
                  AND attname='source_row_id')]::smallint[];
          IF old_primary_key IS NOT NULL THEN
            EXECUTE format('ALTER TABLE sentinel_action_observations DROP CONSTRAINT %I',
                           old_primary_key);
          END IF;
          ALTER TABLE sentinel_action_observations
            ALTER COLUMN source_row_id SET NOT NULL,
            ALTER COLUMN source_payload SET NOT NULL;
          IF NOT EXISTS (
              SELECT 1 FROM pg_constraint
               WHERE conrelid='sentinel_action_observations'::regclass
                 AND contype='p') THEN
            ALTER TABLE sentinel_action_observations
              ADD CONSTRAINT sentinel_action_observations_pkey
              PRIMARY KEY (last_written_run_id,source_row_id);
          END IF;
        END $$""",
    """CREATE INDEX IF NOT EXISTS idx_sentinel_action_obs_written_by
        ON sentinel_action_observations (last_written_run_id)""",
    """DROP INDEX IF EXISTS idx_sentinel_action_obs_window""",
    """CREATE INDEX IF NOT EXISTS idx_sentinel_action_obs_window
        ON sentinel_action_observations (session, ticker, action, source_row_id)""",
    """CREATE TABLE IF NOT EXISTS sentinel_action_generation_events (
        event_id          BIGSERIAL PRIMARY KEY,
        generation_run_id UUID NOT NULL REFERENCES sentinel_action_generations
                          (last_written_run_id) ON DELETE RESTRICT,
        state             TEXT NOT NULL CHECK (state IN
                          ('PENDING','PUBLISHED','ABORTED','SUPERSEDED')),
        actor_run_id      UUID,
        reason            TEXT NOT NULL,
        occurred_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE (generation_run_id,state))""",
    """CREATE INDEX IF NOT EXISTS idx_sentinel_action_generation_events_latest
        ON sentinel_action_generation_events (generation_run_id,event_id DESC)""",
    """CREATE UNIQUE INDEX IF NOT EXISTS uq_sentinel_action_generation_terminal
        ON sentinel_action_generation_events (generation_run_id)
        WHERE state IN ('PUBLISHED','ABORTED','SUPERSEDED')""",
    """INSERT INTO sentinel_action_generation_events
          (generation_run_id,state,actor_run_id,reason)
        SELECT g.last_written_run_id,
               CASE WHEN p.run_id IS NOT NULL THEN 'PUBLISHED'
                    WHEN r.status='failed' THEN 'ABORTED'
                    ELSE 'PENDING' END,
               g.last_written_run_id,
               CASE WHEN p.run_id IS NOT NULL
                    THEN 'schema upgrade: generation belongs to a publication'
                    WHEN r.status='failed'
                    THEN 'schema upgrade: durable failed run classified aborted'
                    ELSE 'schema upgrade: unresolved candidate remains pending'
               END
          FROM sentinel_action_generations g
          LEFT JOIN sentinel_corpus_publications p
            ON p.run_id=g.last_written_run_id
          LEFT JOIN feed_ingest_runs r ON r.run_id=g.last_written_run_id
         WHERE NOT EXISTS (
           SELECT 1 FROM sentinel_action_generation_events e
            WHERE e.generation_run_id=g.last_written_run_id)
        ON CONFLICT (generation_run_id,state) DO NOTHING""",
    # One publication-ranked action set for every reader.  Legacy stamped rows
    # are visible only when their old writer published; NULL provenance remains
    # the oldest baseline.  A REMOVED winner is retained in history but omitted
    # from the active projection.
    # CREATE OR REPLACE cannot prepend/change view columns on the PR #86 shape.
    # Drop/recreate is transactional; a failure rolls back to the intact old
    # view instead of exposing a partial projection.
    """DROP VIEW IF EXISTS sentinel_active_actions""",
    """CREATE VIEW sentinel_active_actions AS
        WITH candidates AS (
          SELECT ('legacy-v1:' || md5(jsonb_build_object(
                   'date',a.session::TEXT,'action',a.action,'ticker',a.ticker,
                   'name',NULL,
                   'value',CASE WHEN a.value IS NULL THEN NULL
                                ELSE a.value::TEXT END,
                   'contraticker',a.contraticker,'contraname',NULL)::TEXT))
                   AS source_row_id,
                 jsonb_build_object('date',a.session::TEXT,'action',a.action,
                   'ticker',a.ticker,'name',NULL,
                   'value',CASE WHEN a.value IS NULL THEN NULL
                                ELSE a.value::TEXT END,
                   'contraticker',a.contraticker,'contraname',NULL)
                   AS source_payload,
                 a.ticker,a.session,a.action,NULL::TEXT AS name,a.value,
                 a.contraticker,NULL::TEXT AS contraname,
                 'PRESENT'::TEXT AS disposition,
                 a.last_written_run_id,
                 COALESCE(p.version,0::BIGINT) AS publication_version,
                 0 AS source_rank
            FROM sentinel_actions a
            LEFT JOIN sentinel_corpus_publications p
              ON p.run_id=a.last_written_run_id
           WHERE a.last_written_run_id IS NULL OR p.run_id IS NOT NULL
          UNION ALL
          SELECT o.source_row_id,o.source_payload,o.ticker,o.session,o.action,
                 o.name,o.value,o.contraticker,o.contraname,
                 o.disposition,o.last_written_run_id,p.version,1
            FROM sentinel_action_observations o
            JOIN sentinel_corpus_publications p
              ON p.run_id=o.last_written_run_id
        ), ranked AS (
          SELECT c.*,RANK() OVER (
                   PARTITION BY source_row_id
                   ORDER BY publication_version DESC,source_rank DESC) AS rank
            FROM candidates c
        )
        SELECT source_row_id,source_payload,ticker,session,action,name,value,
               contraticker,contraname,last_written_run_id,publication_version
          FROM ranked WHERE rank=1 AND disposition='PRESENT'""",

    # Immutable state transitions for stamped anomaly observations.  The
    # observation remains append-only history; this table says whether an
    # unpublished candidate is still genuinely unresolved or reached a durable
    # terminal outcome.  One row per state makes every retry idempotent while
    # preserving the complete transition trail.
    """CREATE TABLE IF NOT EXISTS sentinel_anomaly_observation_events (
        event_id        BIGSERIAL PRIMARY KEY,
        observation_id  BIGINT NOT NULL REFERENCES sentinel_corpus_anomalies
                        (observation_id) ON DELETE RESTRICT,
        state           TEXT NOT NULL CHECK (state IN
                        ('PENDING','PUBLISHED','ABORTED','SUPERSEDED')),
        actor_run_id    UUID,
        reason          TEXT NOT NULL,
        occurred_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE (observation_id, state))""",
    """CREATE INDEX IF NOT EXISTS idx_sentinel_anomaly_events_latest
        ON sentinel_anomaly_observation_events (observation_id, event_id DESC)""",
    """CREATE UNIQUE INDEX IF NOT EXISTS uq_sentinel_anomaly_terminal_event
        ON sentinel_anomaly_observation_events (observation_id)
        WHERE state IN ('PUBLISHED','ABORTED','SUPERSEDED')""",
    # Deterministic fail-closed upgrade.  Published history is published;
    # terminal failed runs are explicitly aborted; every other stamped legacy
    # candidate remains pending and therefore coherence-blocking.  Existing
    # lifecycle history always wins and is never reset by ensure_schema.
    """INSERT INTO sentinel_anomaly_observation_events
          (observation_id,state,actor_run_id,reason)
        SELECT a.observation_id,
               CASE WHEN p.run_id IS NOT NULL THEN 'PUBLISHED'
                    WHEN r.status = 'failed' THEN 'ABORTED'
                    ELSE 'PENDING' END,
               a.last_written_run_id,
               CASE WHEN p.run_id IS NOT NULL
                    THEN 'schema upgrade: observation belongs to a publication'
                    WHEN r.status = 'failed'
                    THEN 'schema upgrade: durable failed run classified aborted'
                    ELSE 'schema upgrade: unresolved candidate remains pending'
               END
          FROM sentinel_corpus_anomalies a
          LEFT JOIN sentinel_corpus_publications p
            ON p.run_id=a.last_written_run_id
          LEFT JOIN feed_ingest_runs r
            ON r.run_id=a.last_written_run_id
         WHERE a.last_written_run_id IS NOT NULL
           AND NOT EXISTS (
             SELECT 1 FROM sentinel_anomaly_observation_events e
              WHERE e.observation_id=a.observation_id)
        ON CONFLICT (observation_id,state) DO NOTHING""",

    # ------------------------------------------------------------------
    # READINESS VERDICTS, kept. See sentinel/feed/readiness.py save_snapshot.
    #
    # The panel used to COMPUTE the data contract inside a page load, under the
    # tightest of its three timeouts — and its own comment explained why: the
    # check is the expensive read, and during a seed it legitimately takes
    # minutes. Both true, and together they blanked the page on exactly the
    # question it exists to answer. An operator watching a six-hour seed could
    # not tell a corpus still building from one that had failed a clause.
    #
    # No timeout fixes it: the check reads the corpus, the corpus is what is
    # under load, and any budget short enough to protect a page load is short
    # enough to lose under contention. A page must READ a verdict somebody else
    # computed and say how old it is.
    #
    # APPEND-ONLY, not one mutable row. "When did readiness last change?" is
    # asked after an incident, and an upsert would have overwritten the answer.
    # ------------------------------------------------------------------
    """CREATE TABLE IF NOT EXISTS sentinel_readiness_snapshots (
        snapshot_id   BIGSERIAL PRIMARY KEY,
        computed_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        ready         BOOLEAN NOT NULL,
        checks_passed INTEGER NOT NULL,
        checks_total  INTEGER NOT NULL,
        -- EVERY CLAUSE, not just the boolean. The whole design of this check is
        -- one verdict per clause; keeping only `ready` throws away the part
        -- that tells an operator which fetch to re-run.
        checks        JSONB NOT NULL DEFAULT '[]'::jsonb)""",
    """CREATE INDEX IF NOT EXISTS idx_sentinel_readiness_computed
        ON sentinel_readiness_snapshots (computed_at DESC)""",

    # ------------------------------------------------------------------
    # PUBLISHED STRATEGY EVIDENCE IS IMMUTABLE UNDER ITS PUBLISHED IDENTITY.
    #
    # A legitimate restatement must move the row to a distinct durable ingest
    # run that has not published yet.  That makes the candidate invisible to
    # readers until validation publishes a NEW data_version.  Direct SQL that
    # changes bytes while leaving published ownership in place is exactly the
    # same-version corruption #122 exists to prevent.  Unstamped legacy rows
    # have no published identity and retain the pre-versioning upsert surface;
    # their first governed write stamps a durable ingest run.
    # ------------------------------------------------------------------
    """CREATE OR REPLACE FUNCTION sentinel_guard_strategy_row_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
          old_protected BOOLEAN;
          new_status TEXT;
        BEGIN
          old_protected := OLD.last_written_run_id IS NOT NULL AND EXISTS (
            SELECT 1 FROM sentinel_corpus_publications p
             WHERE p.run_id=OLD.last_written_run_id);
          IF NOT old_protected THEN
            IF TG_OP='DELETE' THEN RETURN OLD; END IF;
            RETURN NEW;
          END IF;
          IF TG_OP='DELETE' THEN
            RAISE EXCEPTION USING ERRCODE='23000', MESSAGE=format(
              '%s: published strategy evidence is append-only; DELETE refused',
              TG_TABLE_NAME);
          END IF;
          IF NEW.last_written_run_id IS NULL
             OR NEW.last_written_run_id IS NOT DISTINCT FROM OLD.last_written_run_id THEN
            RAISE EXCEPTION USING ERRCODE='23000', MESSAGE=format(
              '%s: strategy evidence cannot change under the same published identity',
              TG_TABLE_NAME);
          END IF;
          IF EXISTS (SELECT 1 FROM sentinel_corpus_publications p
                      WHERE p.run_id=NEW.last_written_run_id) THEN
            RAISE EXCEPTION USING ERRCODE='23000', MESSAGE=format(
              '%s: restatement target run is already published', TG_TABLE_NAME);
          END IF;
          SELECT r.status INTO new_status FROM feed_ingest_runs r
           WHERE r.run_id=NEW.last_written_run_id;
          IF new_status IS NULL OR new_status='failed' THEN
            RAISE EXCEPTION USING ERRCODE='23000', MESSAGE=format(
              '%s: restatement requires a durable non-failed unpublished ingest run',
              TG_TABLE_NAME);
          END IF;
          RETURN NEW;
        END $$""",
    """CREATE OR REPLACE FUNCTION sentinel_refuse_append_only_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          RAISE EXCEPTION USING ERRCODE='23000', MESSAGE=format(
            '%s is append-only; %s refused', TG_TABLE_NAME, TG_OP);
        END $$""",
    """DROP TRIGGER IF EXISTS sentinel_guard_strategy_row_mutation ON sentinel_bars""",
    """CREATE TRIGGER sentinel_guard_strategy_row_mutation
        BEFORE UPDATE OR DELETE ON sentinel_bars
        FOR EACH ROW EXECUTE FUNCTION sentinel_guard_strategy_row_mutation()""",
    """DROP TRIGGER IF EXISTS sentinel_guard_strategy_row_mutation ON sentinel_spy_total_return""",
    """CREATE TRIGGER sentinel_guard_strategy_row_mutation
        BEFORE UPDATE OR DELETE ON sentinel_spy_total_return
        FOR EACH ROW EXECUTE FUNCTION sentinel_guard_strategy_row_mutation()""",
    """DROP TRIGGER IF EXISTS sentinel_guard_strategy_row_mutation ON sentinel_defensive_bars""",
    """CREATE TRIGGER sentinel_guard_strategy_row_mutation
        BEFORE UPDATE OR DELETE ON sentinel_defensive_bars
        FOR EACH ROW EXECUTE FUNCTION sentinel_guard_strategy_row_mutation()""",
    """DROP TRIGGER IF EXISTS sentinel_guard_strategy_row_mutation ON sentinel_universe""",
    """CREATE TRIGGER sentinel_guard_strategy_row_mutation
        BEFORE UPDATE OR DELETE ON sentinel_universe
        FOR EACH ROW EXECUTE FUNCTION sentinel_guard_strategy_row_mutation()""",
    """DROP TRIGGER IF EXISTS sentinel_guard_strategy_row_mutation ON sentinel_actions""",
    """CREATE TRIGGER sentinel_guard_strategy_row_mutation
        BEFORE UPDATE OR DELETE ON sentinel_actions
        FOR EACH ROW EXECUTE FUNCTION sentinel_guard_strategy_row_mutation()""",
    """DROP TRIGGER IF EXISTS sentinel_guard_strategy_row_mutation ON sentinel_bar_split_repairs""",
    """CREATE TRIGGER sentinel_guard_strategy_row_mutation
        BEFORE UPDATE OR DELETE ON sentinel_bar_split_repairs
        FOR EACH ROW EXECUTE FUNCTION sentinel_guard_strategy_row_mutation()""",
    """DROP TRIGGER IF EXISTS sentinel_guard_strategy_row_mutation ON sentinel_action_generations""",
    """CREATE TRIGGER sentinel_guard_strategy_row_mutation
        BEFORE UPDATE OR DELETE ON sentinel_action_generations
        FOR EACH ROW EXECUTE FUNCTION sentinel_guard_strategy_row_mutation()""",
    """DROP TRIGGER IF EXISTS sentinel_guard_strategy_row_mutation ON sentinel_action_observations""",
    """CREATE TRIGGER sentinel_guard_strategy_row_mutation
        BEFORE UPDATE OR DELETE ON sentinel_action_observations
        FOR EACH ROW EXECUTE FUNCTION sentinel_guard_strategy_row_mutation()""",
    """DROP TRIGGER IF EXISTS sentinel_guard_strategy_row_mutation ON sentinel_corpus_anomalies""",
    """CREATE TRIGGER sentinel_guard_strategy_row_mutation
        BEFORE UPDATE OR DELETE ON sentinel_corpus_anomalies
        FOR EACH ROW EXECUTE FUNCTION sentinel_guard_strategy_row_mutation()""",
    """DROP TRIGGER IF EXISTS sentinel_guard_strategy_row_mutation ON sentinel_ingest_rejections""",
    """CREATE TRIGGER sentinel_guard_strategy_row_mutation
        BEFORE UPDATE OR DELETE ON sentinel_ingest_rejections
        FOR EACH ROW EXECUTE FUNCTION sentinel_guard_strategy_row_mutation()""",
    """DROP TRIGGER IF EXISTS sentinel_refuse_append_only_mutation ON sentinel_corpus_publications""",
    """CREATE TRIGGER sentinel_refuse_append_only_mutation
        BEFORE UPDATE OR DELETE ON sentinel_corpus_publications
        FOR EACH ROW EXECUTE FUNCTION sentinel_refuse_append_only_mutation()""",
    """DROP TRIGGER IF EXISTS sentinel_refuse_append_only_mutation ON sentinel_action_generation_events""",
    """CREATE TRIGGER sentinel_refuse_append_only_mutation
        BEFORE UPDATE OR DELETE ON sentinel_action_generation_events
        FOR EACH ROW EXECUTE FUNCTION sentinel_refuse_append_only_mutation()""",
    """DROP TRIGGER IF EXISTS sentinel_refuse_append_only_mutation ON sentinel_anomaly_observation_events""",
    """CREATE TRIGGER sentinel_refuse_append_only_mutation
        BEFORE UPDATE OR DELETE ON sentinel_anomaly_observation_events
        FOR EACH ROW EXECUTE FUNCTION sentinel_refuse_append_only_mutation()""",

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
        closeadj   DOUBLE PRECISION,
        volume     DOUBLE PRECISION)""",
    """ALTER TABLE sentinel_sep_staging
        ADD COLUMN IF NOT EXISTS closeadj DOUBLE PRECISION""",
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
