"""Strategy validation of immutable data, separate from acquisition ownership.

Receipts describe DATA_ONLY input eligibility. They never authorize a book,
plan, broker operation or source observation, and never amend an old job.
"""
from __future__ import annotations

from sentinel.feed.rolling_contract import Contract, Digest, canonical_json, digest
from sentinel.transaction_contract import TransactionPort, borrow

TABLE = 'sentinel_generation_strategy_admissions'
extension_tables = frozenset({TABLE})
extension_views = frozenset()
extension_functions = frozenset({'sentinel_generation_admission_immutable'})
extension_triggers = frozenset({'generation_admission_immutable','generation_admission_no_truncate'})
extension_trigger_pairs = frozenset((TABLE,name) for name in extension_triggers)
DDL = (
    f"""CREATE TABLE {TABLE} (
        publication_version BIGINT NOT NULL REFERENCES sentinel_corpus_publications(version),
        strategy_sha256 TEXT NOT NULL CHECK(strategy_sha256 ~ '^[0-9a-f]{{64}}$'),
        generation_sha256 TEXT NOT NULL CHECK(generation_sha256 ~ '^[0-9a-f]{{64}}$'),
        receipt_sha256 TEXT NOT NULL CHECK(receipt_sha256 ~ '^[0-9a-f]{{64}}$'),
        receipt JSONB NOT NULL, hmac_sha256 TEXT NOT NULL CHECK(hmac_sha256 ~ '^[0-9a-f]{{64}}$'),
        admitted_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
        PRIMARY KEY(publication_version,strategy_sha256))""",
    """CREATE FUNCTION sentinel_generation_admission_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN RAISE EXCEPTION 'generation strategy admission is immutable'; END $$""",
    f'CREATE TRIGGER generation_admission_immutable BEFORE UPDATE OR DELETE ON {TABLE} FOR EACH ROW EXECUTE FUNCTION sentinel_generation_admission_immutable()',
    f'CREATE TRIGGER generation_admission_no_truncate BEFORE TRUNCATE ON {TABLE} FOR EACH STATEMENT EXECUTE FUNCTION sentinel_generation_admission_immutable()',
)


class GenerationRefused(ValueError):
    pass


class DataGeneration(Contract):
    publication_version: int
    publication_sha256: Digest
    snapshot_id: Digest
    reference_sha256: Digest
    source_evidence_sha256: Digest
    requirements_sha256: Digest

    @property
    def sha256(self):
        return digest(self.model_dump())


def require_schema(conn, *, allow_absent=False):
    from sentinel import operational_catalog
    return operational_catalog.require_extension(conn,__name__,allow_absent=allow_absent)


def install(conn: TransactionPort):
    conn = borrow(conn)
    if require_schema(conn,allow_absent=True):
        return
    for statement in DDL:
        conn.execute(statement)
    require_schema(conn)


def generation(conn, pub):
    from sentinel.feed import operational_snapshot, rolling_store
    binding = operational_snapshot._bound(conn,pub)
    manifest = rolling_store.manifest(conn,binding['candidate_id'])
    return DataGeneration(publication_version=pub.version,publication_sha256=digest(pub.to_dict()),
        snapshot_id=manifest.snapshot_id,reference_sha256=manifest.reference_sha256,
        source_evidence_sha256=manifest.source_evidence_sha256,
        requirements_sha256=digest(manifest.requirements.model_dump()))


def _payload(value, strategy):
    return dict(schema='sentinel.data-generation-strategy-admission/1',scope='DATA_ONLY',
        operational_go=False,generation=value.model_dump(),generation_sha256=value.sha256,
        strategy_sha256=digest(strategy),verification_policy='sentinel.operational-verification/1')


def _signature(payload):
    from sentinel.feed.publication import _receipt_hmac
    return _receipt_hmac(dict(purpose='data-generation-strategy-admission',receipt=payload))


def admitted(conn, pub, strategy):
    import hmac
    if not require_schema(conn,allow_absent=True):
        return False
    row = conn.execute(f'SELECT generation_sha256,receipt_sha256,receipt,hmac_sha256 FROM {TABLE} '
        'WHERE publication_version=%s AND strategy_sha256=%s', (pub.version,digest(strategy))).fetchone()
    if row is None:
        return False
    expected = _payload(generation(conn,pub),strategy)
    if (row[0] != expected['generation_sha256'] or row[1] != digest(expected)
            or row[2] != expected or not hmac.compare_digest(row[3],_signature(expected))):
        raise GenerationRefused('DATA_GENERATION_STRATEGY_ADMISSION_CHANGED')
    return True


def _require_current_strategy(strategy):
    from sentinel.feed.rolling_go_inputs import production_strategy
    _, selected = production_strategy()
    if digest(strategy) != digest(selected):
        raise GenerationRefused('DATA_GENERATION_STRATEGY_NOT_CURRENT')


def admit_current(conn, pub, *, strategy, target):
    """Caller owns pin/transaction; independently verify full existing readiness."""
    from sentinel.feed import rolling_go_inputs, readiness_scope
    readiness_scope.require_owned_publication(conn,pub)
    _require_current_strategy(strategy)
    require_schema(conn)
    binding, material, report = rolling_go_inputs._assess_material(conn,pub,target=target,summary_only=True)
    rolling_go_inputs._require_ready(report,available_session=material.session,target=target)
    value = generation(conn,pub)
    payload = _payload(value,strategy)
    readiness_scope.require_owned_publication(conn,pub)
    _require_current_strategy(strategy)
    conn.execute(f'INSERT INTO {TABLE}(publication_version,strategy_sha256,generation_sha256,receipt_sha256,receipt,hmac_sha256) '
        'VALUES(%s,%s,%s,%s,%s::jsonb,%s) ON CONFLICT DO NOTHING',
        (pub.version,digest(strategy),value.sha256,digest(payload),canonical_json(payload),_signature(payload)))
    if not admitted(conn,pub,strategy):
        raise GenerationRefused('DATA_GENERATION_STRATEGY_ADMISSION_MISSING')
    return binding, report
