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
    # Dedicated total-return domain. Wealth Core is structurally unable to read
    # it; only sentinel.regime uses it when assembling a production observation.
    """CREATE TABLE IF NOT EXISTS sentinel_spy_total_return (
        session             DATE PRIMARY KEY,
        closeadj            DOUBLE PRECISION NOT NULL,
        last_written_run_id UUID)""",
    """CREATE INDEX IF NOT EXISTS idx_sentinel_spy_total_return_written_by
        ON sentinel_spy_total_return (last_written_run_id)
        WHERE last_written_run_id IS NOT NULL""",

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
        error_message TEXT)""",
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
