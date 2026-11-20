"""Read the two protected feed installations used by historical DDL witnesses."""
import json
from pathlib import Path

from sentinel import schema
from sentinel.chain_progress_recovery import RecoveryRefused
from sentinel.execution.evidence_projection import digest
from sentinel.feed.runtime_schema import _SCHEMA_LOCK


ORIGINAL = '595b6353237c5f6f7705c0171fc0eba9504bc7f4de38fee711e1e90e31f36552'
POST_COMPACTION = '7ab9763812ed25ac8c822d82b624abd87d006501303e63e8eb3272f86ef3df37'
_MANIFEST = Path(__file__).with_name('coverage-feed-catalog-v1.json')
_SHA256 = 'f8aed8ed44220c203549b5b74a61f2b50635390dda634be74b3187c4ec928a1c'


def require(conn, *, expected=None):
    """Identify an installed release from its tables, indexes, views and guards."""
    manifest = json.loads(_MANIFEST.read_text(encoding='utf-8'))
    if digest(manifest) != _SHA256:
        raise RecoveryRefused('historical feed catalog manifest changed')
    with conn.transaction(force_rollback=True), conn.cursor() as cur:
        cur.execute('SET LOCAL search_path = pg_catalog, public')
        cur.execute('SELECT pg_try_advisory_xact_lock_shared(%s,%s)', _SCHEMA_LOCK)
        if cur.fetchone() != (True,):
            raise RecoveryRefused('historical feed catalog migration in progress')
        catalog = schema._read_runtime_catalog(cur)
        if schema._semantic_catalog_sha256(*catalog, manifest['relations']) != manifest['catalog_sha256']:
            raise RecoveryRefused('historical feed catalog differs')
        cur.execute("SELECT name, pg_get_viewdef(to_regclass('public.' || name),true) "
                    'FROM unnest(%s::text[]) t(name)', (manifest['views'],))
        if digest(dict(cur.fetchall())) != manifest['view_sha256']:
            raise RecoveryRefused('historical feed views differ')
        cur.execute('SELECT t.name,pg_get_functiondef(p.oid) FROM unnest(%s::text[]) t(name) '
                    "JOIN pg_proc p ON p.oid=to_regprocedure('public.' || t.name)",
                    (manifest['functions'],))
        guards = digest(dict(cur.fetchall()))
        for contract, release in manifest['releases'].items():
            if release['function_sha256'] == guards and expected in (None, contract):
                return contract
        raise RecoveryRefused('historical feed protection functions differ')
