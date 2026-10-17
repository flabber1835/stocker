"""Logged reusable acquisition payloads, bindings and bounded restart lineage."""

DDL = [
    """CREATE TABLE IF NOT EXISTS sentinel_acquisition_price_links (
        part_id TEXT PRIMARY KEY, payload_part_id TEXT NOT NULL,
        CHECK(part_id<>payload_part_id))""",
    "CREATE INDEX IF NOT EXISTS sentinel_acquisition_price_links_payload ON sentinel_acquisition_price_links(payload_part_id)",
    """CREATE TABLE IF NOT EXISTS sentinel_acquisition_parts (
        part_id TEXT PRIMARY KEY CHECK(part_id ~ '^[0-9a-f]{64}$'),
        manifest JSONB NOT NULL, reference_payload JSONB,
        created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp())""",
    """ALTER TABLE sentinel_acquisition_parts ADD COLUMN IF NOT EXISTS canonical_reference TEXT
        CHECK(canonical_reference IS NULL OR (reference_payload IS NULL
          AND octet_length(canonical_reference)<=268435456
          AND (manifest->>'content_sha256') IS NOT NULL
           AND encode(sha256(convert_to(canonical_reference,'UTF8')),'hex')=
             COALESCE(manifest->>'reference_sha256',manifest->>'content_sha256')))""",
    "ALTER TABLE sentinel_acquisition_parts DROP CONSTRAINT IF EXISTS sentinel_acquisition_parts_canonical_reference_check",
    """ALTER TABLE sentinel_acquisition_parts ADD CONSTRAINT sentinel_acquisition_parts_canonical_reference_check
        CHECK(canonical_reference IS NULL OR (reference_payload IS NULL
          AND octet_length(canonical_reference)<=268435456
          AND (manifest->>'content_sha256') IS NOT NULL
          AND encode(sha256(convert_to(canonical_reference,'UTF8')),'hex')=
            COALESCE(manifest->>'reference_sha256',manifest->>'content_sha256')))""",
    """CREATE TABLE IF NOT EXISTS sentinel_acquisition_prices (
        part_id TEXT NOT NULL REFERENCES sentinel_acquisition_parts,
        session DATE NOT NULL, ticker TEXT NOT NULL, payload TEXT NOT NULL,
        PRIMARY KEY(part_id,session,ticker))""",
    """CREATE TABLE IF NOT EXISTS sentinel_acquisition_bindings (
        job_id UUID NOT NULL REFERENCES sentinel_snapshot_jobs,
        component TEXT NOT NULL, part_id TEXT NOT NULL,
        PRIMARY KEY(job_id,component))""",
    """CREATE TABLE IF NOT EXISTS sentinel_acquisition_successors (
        parent_job_id UUID PRIMARY KEY REFERENCES sentinel_snapshot_jobs,
        child_job_id UUID NOT NULL UNIQUE REFERENCES sentinel_snapshot_jobs,
        excluded_component TEXT NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS sentinel_acquisition_bindings_part "
    "ON sentinel_acquisition_bindings(part_id,job_id)",
]

# Payloads are immutable; deletion is confined to the existing retention owner.
for _table in ("sentinel_acquisition_parts", "sentinel_acquisition_prices"):
    DDL.extend([
        f"DROP TRIGGER IF EXISTS acquisition_no_update ON {_table}",
        f"CREATE TRIGGER acquisition_no_update BEFORE UPDATE ON {_table} "
        "FOR EACH ROW EXECUTE FUNCTION sentinel_snapshot_immutable()",
    ])
DDL.append("""CREATE OR REPLACE FUNCTION sentinel_acquisition_part_pinned(target TEXT)
    RETURNS BOOLEAN LANGUAGE sql STABLE AS $$
      WITH RECURSIVE live(job_id) AS (
        SELECT job_id FROM sentinel_snapshot_jobs WHERE state NOT IN ('REFUSED','ABORTED','PUBLISHED')
          OR (state='REFUSED' AND reason='SOURCE_GENERATION_CHANGED' AND deadline>clock_timestamp())
        UNION
        SELECT s.parent_job_id FROM sentinel_acquisition_successors s JOIN live l ON s.child_job_id=l.job_id)
       SELECT EXISTS(SELECT 1 FROM sentinel_acquisition_bindings b JOIN live USING(job_id)
                     LEFT JOIN sentinel_acquisition_price_links l USING(part_id)
                     WHERE b.part_id=target OR l.payload_part_id=target)
        OR EXISTS(SELECT 1 FROM sentinel_acquisition_bindings b
          JOIN sentinel_acquisition_parts a USING(part_id)
          JOIN sentinel_operational_snapshots o USING(job_id)
          LEFT JOIN sentinel_acquisition_price_links l ON l.part_id=b.part_id
          WHERE (b.part_id=target OR l.payload_part_id=target)
            AND (b.component='TICKERS' OR b.component LIKE 'SEP.%')
            AND a.manifest->'generation'->>'provider'='ALPACA_OPENFIGI'
            AND o.publication_version=(SELECT max(version) FROM sentinel_corpus_publications))
    $$""")
DDL.append("""CREATE OR REPLACE FUNCTION sentinel_acquisition_delete_guard()
    RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
      PERFORM sentinel_retention_locks();
      IF sentinel_acquisition_part_pinned(OLD.part_id) THEN
        RAISE EXCEPTION 'active acquisition part cannot be retired';
      END IF;
      RETURN OLD;
    END $$""")
DDL.append("""CREATE OR REPLACE FUNCTION sentinel_acquisition_price_insert_guard()
    RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
      PERFORM 1 FROM sentinel_acquisition_parts WHERE part_id=NEW.part_id FOR SHARE;
      IF EXISTS(SELECT 1 FROM sentinel_acquisition_bindings WHERE part_id=NEW.part_id) THEN
        RAISE EXCEPTION 'completed acquisition part cannot receive more prices';
      END IF;
      RETURN NEW;
    END $$""")
DDL.extend([
    "DROP TRIGGER IF EXISTS acquisition_price_insert_guard ON sentinel_acquisition_prices",
    "CREATE TRIGGER acquisition_price_insert_guard BEFORE INSERT ON sentinel_acquisition_prices "
    "FOR EACH ROW EXECUTE FUNCTION sentinel_acquisition_price_insert_guard()",
])
for _table in ("sentinel_acquisition_parts", "sentinel_acquisition_prices"):
    DDL.extend([
        f"DROP TRIGGER IF EXISTS acquisition_delete_guard ON {_table}",
        f"CREATE TRIGGER acquisition_delete_guard BEFORE DELETE ON {_table} "
        "FOR EACH ROW EXECUTE FUNCTION sentinel_acquisition_delete_guard()",
    ])
for _table in ("sentinel_acquisition_bindings", "sentinel_acquisition_successors", "sentinel_acquisition_price_links"):
    DDL.extend([
        f"DROP TRIGGER IF EXISTS snapshot_immutable ON {_table}",
        f"CREATE TRIGGER snapshot_immutable BEFORE UPDATE OR DELETE ON {_table} "
        "FOR EACH ROW EXECUTE FUNCTION sentinel_snapshot_immutable()",
    ])
for _table in ("sentinel_acquisition_parts", "sentinel_acquisition_prices",
               "sentinel_acquisition_bindings", "sentinel_acquisition_successors", "sentinel_acquisition_price_links"):
    DDL.extend([
        f"DROP TRIGGER IF EXISTS snapshot_no_truncate ON {_table}",
        f"CREATE TRIGGER snapshot_no_truncate BEFORE TRUNCATE ON {_table} "
        "FOR EACH STATEMENT EXECUTE FUNCTION sentinel_snapshot_immutable()",
    ])

COLUMNS = {
    "sentinel_acquisition_parts": {
        "part_id": ("text", True), "manifest": ("jsonb", True),
        "reference_payload": ("jsonb", False), "canonical_reference": ("text", False),
        "created_at": ("timestamp with time zone", True)},
    "sentinel_acquisition_prices": {
        "part_id": ("text", True), "session": ("date", True),
        "ticker": ("text", True), "payload": ("text", True)},
    "sentinel_acquisition_bindings": {
        "job_id": ("uuid", True), "component": ("text", True), "part_id": ("text", True)},
    "sentinel_acquisition_successors": {
        "parent_job_id": ("uuid", True), "child_job_id": ("uuid", True),
        "excluded_component": ("text", True)},
}
PRIMARY_KEYS = dict(zip(COLUMNS, (
    "primary key (part_id)", "primary key (part_id, session, ticker)",
    "primary key (job_id, component)", "primary key (parent_job_id)")))
TRIGGERS = {name: {"snapshot_no_truncate": (
    "before truncate", "for each statement", "execute function sentinel_snapshot_immutable()")}
    for name in COLUMNS}
for _table in tuple(COLUMNS)[:2]:
    TRIGGERS[_table].update(
        acquisition_no_update=("before update", "for each row", "execute function sentinel_snapshot_immutable()"),
        acquisition_delete_guard=("before delete", "for each row", "execute function sentinel_acquisition_delete_guard()"))
for _table in tuple(COLUMNS)[2:]:
    TRIGGERS[_table]["snapshot_immutable"] = (
        "before delete or update", "for each row", "execute function sentinel_snapshot_immutable()")
TRIGGERS["sentinel_acquisition_prices"]["acquisition_price_insert_guard"] = (
    "before insert", "for each row", "execute function sentinel_acquisition_price_insert_guard()")
CONSTRAINTS = {
    "sentinel_acquisition_parts": (("c", ("canonical_reference", "reference_payload is null",
        "octet_length(canonical_reference)", "268435456", "sha256", "content_sha256")),),
    "sentinel_acquisition_prices": (("f", ("foreign key (part_id)", "sentinel_acquisition_parts")),),
    "sentinel_acquisition_bindings": (("f", ("foreign key (job_id)", "sentinel_snapshot_jobs")),),
    "sentinel_acquisition_successors": (
        ("f", ("foreign key (parent_job_id)", "sentinel_snapshot_jobs")),
        ("f", ("foreign key (child_job_id)", "sentinel_snapshot_jobs")),
        ("u", ("unique (child_job_id)",))),
}


# A wait hint can only cause a re-probe/full revalidation, never waive coverage.
DDL.extend([
    """CREATE TABLE IF NOT EXISTS sentinel_acquisition_source_wait (
        job_id UUID PRIMARY KEY REFERENCES sentinel_snapshot_jobs,
        evidence_sha256 TEXT NOT NULL CHECK(evidence_sha256 ~ '^[0-9a-f]{64}$'),
        payload JSONB NOT NULL CHECK(jsonb_typeof(payload)='object'))""",
    "DROP TRIGGER IF EXISTS snapshot_no_truncate ON sentinel_acquisition_source_wait",
    "CREATE TRIGGER snapshot_no_truncate BEFORE TRUNCATE ON sentinel_acquisition_source_wait "
    "FOR EACH STATEMENT EXECUTE FUNCTION sentinel_snapshot_immutable()",
])
COLUMNS['sentinel_acquisition_source_wait'] = {
    'job_id': ('uuid', True), 'evidence_sha256': ('text', True), 'payload': ('jsonb', True)}
PRIMARY_KEYS['sentinel_acquisition_source_wait'] = 'primary key (job_id)'
TRIGGERS['sentinel_acquisition_source_wait'] = {'snapshot_no_truncate': (
    'before truncate', 'for each statement', 'execute function sentinel_snapshot_immutable()')}
CONSTRAINTS['sentinel_acquisition_source_wait'] = (
    ('f', ('foreign key (job_id)', 'sentinel_snapshot_jobs')),
    ('c', ('evidence_sha256', '[0-9a-f]{64}')),
    ('c', ('jsonb_typeof(payload)', 'object')))

DDL.extend([
    """CREATE OR REPLACE FUNCTION sentinel_acquisition_link_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE own JSONB; source JSONB;
    BEGIN
      IF NOT pg_try_advisory_xact_lock_shared(1579663541) THEN
        RAISE EXCEPTION 'acquisition payload sharing requires a current corpus pin';
      END IF;
      PERFORM 1 FROM sentinel_acquisition_parts WHERE part_id IN (NEW.part_id,NEW.payload_part_id) FOR SHARE;
      SELECT manifest INTO own FROM sentinel_acquisition_parts WHERE part_id=NEW.part_id;
      SELECT manifest INTO source FROM sentinel_acquisition_parts WHERE part_id=NEW.payload_part_id;
      IF own IS NULL OR source IS NULL OR own->>'component' NOT LIKE 'SEP.%'
        OR own->>'component'<>source->>'component'
        OR own->>'content_sha256'<>source->>'content_sha256' OR own->>'rows'<>source->>'rows'
        OR EXISTS(SELECT 1 FROM sentinel_acquisition_price_links WHERE part_id=NEW.payload_part_id)
        OR EXISTS(SELECT 1 FROM sentinel_acquisition_prices WHERE part_id=NEW.part_id)
        OR NOT EXISTS(SELECT 1 FROM sentinel_acquisition_prices WHERE part_id=NEW.payload_part_id)
        OR EXISTS(SELECT 1 FROM sentinel_acquisition_bindings WHERE part_id=NEW.part_id)
      THEN RAISE EXCEPTION 'acquisition payload sharing is not bound to equal complete parts'; END IF;
      RETURN NEW;
    END $$""",
    "DROP TRIGGER IF EXISTS acquisition_link_guard ON sentinel_acquisition_price_links",
    "CREATE TRIGGER acquisition_link_guard BEFORE INSERT ON sentinel_acquisition_price_links FOR EACH ROW EXECUTE FUNCTION sentinel_acquisition_link_guard()",
])
COLUMNS['sentinel_acquisition_price_links'] = {'part_id':('text',True),'payload_part_id':('text',True)}
PRIMARY_KEYS['sentinel_acquisition_price_links'] = 'primary key (part_id)'
TRIGGERS['sentinel_acquisition_price_links'] = {
    'snapshot_immutable':('before delete or update','for each row','execute function sentinel_snapshot_immutable()'),
    'snapshot_no_truncate':('before truncate','for each statement','execute function sentinel_snapshot_immutable()'),
    'acquisition_link_guard':('before insert','for each row','execute function sentinel_acquisition_link_guard()')}
CONSTRAINTS['sentinel_acquisition_price_links'] = (('c',('part_id <> payload_part_id',)),)

DDL.extend([
    """CREATE OR REPLACE FUNCTION sentinel_acquisition_price_delete_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      PERFORM sentinel_retention_locks();
      IF EXISTS(SELECT 1 FROM (SELECT DISTINCT part_id FROM retired_prices) d
                WHERE sentinel_acquisition_part_pinned(d.part_id))
      THEN RAISE EXCEPTION 'active acquisition part cannot be retired'; END IF;
      RETURN NULL;
    END $$""",
    'DROP TRIGGER IF EXISTS acquisition_delete_guard ON sentinel_acquisition_prices',
    'CREATE TRIGGER acquisition_delete_guard AFTER DELETE ON sentinel_acquisition_prices REFERENCING OLD TABLE AS retired_prices FOR EACH STATEMENT EXECUTE FUNCTION sentinel_acquisition_price_delete_guard()',
])
TRIGGERS['sentinel_acquisition_prices']['acquisition_delete_guard'] = (
    'after delete', 'referencing old table as retired_prices', 'for each statement',
    'execute function sentinel_acquisition_price_delete_guard()')
