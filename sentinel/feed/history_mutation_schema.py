"""Migration-owned durable footprints of changed published economic rows."""

TRACKED_TABLES = (
    "sentinel_bars", "sentinel_spy_total_return", "sentinel_defensive_bars",
    "sentinel_bar_split_repairs",
)

DDL = [
    """CREATE INDEX IF NOT EXISTS idx_sentinel_publication_window_end
        ON sentinel_corpus_publications (window_end DESC)""",
    """CREATE TABLE IF NOT EXISTS sentinel_history_mutations (
        base_version BIGINT NOT NULL,
        writer_run_id TEXT NOT NULL,
        source_table TEXT NOT NULL,
        affected_session DATE NOT NULL,
        PRIMARY KEY (base_version,writer_run_id,source_table,affected_session))""",
    """CREATE OR REPLACE FUNCTION sentinel_record_history_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
          before_row JSONB;
          after_row JSONB;
          changed_row JSONB;
          prior_version BIGINT;
          frontier DATE;
          affected DATE;
        BEGIN
          IF TG_OP <> 'INSERT' THEN before_row := to_jsonb(OLD); END IF;
          IF TG_OP <> 'DELETE' THEN after_row := to_jsonb(NEW); END IF;
          IF TG_OP='UPDATE' AND
             (before_row - 'last_written_run_id' - 'repaired_at') IS NOT DISTINCT FROM
             (after_row - 'last_written_run_id' - 'repaired_at') THEN
            RETURN NEW;
          END IF;
          SELECT MAX(version),MAX(window_end) INTO prior_version,frontier
            FROM sentinel_corpus_publications;
          IF prior_version IS NULL THEN
            IF TG_OP='DELETE' THEN RETURN OLD; END IF;
            RETURN NEW;
          END IF;
          changed_row := COALESCE(after_row,before_row);
          affected := (changed_row->>'session')::DATE;
          IF before_row IS NOT NULL THEN
            affected := LEAST(affected,(before_row->>'session')::DATE);
          END IF;
          IF TG_OP <> 'INSERT' OR frontier IS NULL OR affected <= frontier THEN
            INSERT INTO sentinel_history_mutations
                (base_version,writer_run_id,source_table,affected_session)
              VALUES (prior_version,
                COALESCE(changed_row->>'last_written_run_id','UNTRACKED'),
                TG_TABLE_NAME,affected) ON CONFLICT DO NOTHING;
          END IF;
          IF TG_OP='DELETE' THEN RETURN OLD; END IF;
          RETURN NEW;
        END $$""",
    """DROP TRIGGER IF EXISTS sentinel_refuse_append_only_mutation
        ON sentinel_history_mutations""",
    """CREATE TRIGGER sentinel_refuse_append_only_mutation
        BEFORE UPDATE OR DELETE ON sentinel_history_mutations
        FOR EACH ROW EXECUTE FUNCTION sentinel_refuse_append_only_mutation()""",
]
for table in TRACKED_TABLES:
    DDL.extend([
        f"DROP TRIGGER IF EXISTS sentinel_record_history_mutation ON {table}",
        f"""CREATE TRIGGER sentinel_record_history_mutation
            AFTER INSERT OR UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION sentinel_record_history_mutation()""",
    ])
