"""One exact owned-checkpoint read wrapper; no financial authority."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

BASE_REVISION = 'e4d8671cb84af325fb5000cf8eaa2a4e0cf454c7'
BASELINES = {
    'sentinel.rolling_checkpoint': 'ca31b054df204efcc1b2a2c231ca5faeab51e0032ba1e1cad91188bcbfc40c64',
    'sentinel.rolling_daily_checkpoint': 'b82768e4c925f73bcb14878d245672f93a069d3e7139f7e0f65a5d1762110f3e',
}
CANDIDATES = {'sentinel.rolling_checkpoint': '5ad70f4e6fef66ede7392bf7371693cac808046ff47e7657349438a51d70058b', 'sentinel.rolling_daily_checkpoint': '8f93be6f455c17c8b6eeb17ab1bf8a20936338e6dc4da63692e0a6c6caf9d57b'}
PROFILE_SHA256 = 'ee9aafe0c0cc5b0b7d612ab7c09366262239c4da3d599ca3970f694a976143cc'
PROFILE = Path(__file__).with_name('checkpoint-read-source-transition.json')
_WRAPPER = (b'def read(conn):\n    from sentinel import committed_read\n'
            b'    return committed_read.checkpoint(conn, cursor=CURSOR, read=_read)\n\n\n'
            b'def _read(conn):\n')


_CAS_MODULE = 'sentinel.rolling_daily_checkpoint'
CAS_CANDIDATE = '564fcd218fb5596c2db5888911df9c6e9eeb4509f8c7b3928eb53ea006e150fd'
_CAS_CHANGES = (
    (
        b'from pydantic import Field, PrivateAttr\n',
        b'from pydantic import Field\n',
    ),
    (
        b'    # Local to the transaction that authenticated the predecessor.\n'
        b'    _row_version: tuple | None = PrivateAttr(default=None)\n'
        b'\n'
        b'    def __eq__(self, other):\n'
        b'        # Physical metadata belongs to the write attempt, not the signed value.\n'
        b'        if type(self) is type(other):\n'
        b'            return self.__dict__ == other.__dict__\n'
        b'        return NotImplemented\n',
        b'',
    ),
    (
        b'    row = conn.execute(\n'
        b'        "SELECT session,state,tableoid,pg_relation_filenode(tableoid),xmin::text,ctid::text,"\n'
        b'        "pg_backend_pid(),transaction_timestamp(),"\n'
        b'        "floor(pg_snapshot_xmax(pg_current_snapshot())::text::numeric/4294967296)::bigint"\n'
        b'        " FROM sentinel_processed_sessions WHERE cursor_name=%s", (CURSOR,)).fetchone()\n',
        b'    row = conn.execute("SELECT session,state FROM sentinel_processed_sessions WHERE cursor_name=%s", (CURSOR,)).fetchone()\n',
    ),
    (
        b'    checkpoint._row_version = (row[0], *row[2:])\n',
        b'',
    ),
    (
        b'        witness = previous._row_version\n'
        b'        if witness is None:\n'
        b'            raise Refused("DAILY_CHECKPOINT_CAS_WITNESS_REQUIRED")\n'
        b'        # An in-place VACUUM freeze preserves xmin. Relation rewrites and\n'
        b'        # concurrent row replacements change the physical identity.\n',
        b'',
    ),
    (
        b'            " WHERE cursor_name=%s AND session=%s AND tableoid=%s"\n'
        b'            " AND pg_relation_filenode(tableoid)=%s AND xmin=%s::xid AND ctid=%s::tid"\n'
        b'            " AND pg_backend_pid()=%s AND transaction_timestamp()=%s"\n'
        b'            " AND floor(pg_snapshot_xmax(pg_current_snapshot())::text::numeric/4294967296)::bigint=%s",\n'
        b'            (checkpoint.session, raw, CURSOR, *witness))\n',
        b'            " WHERE cursor_name=%s AND state=%s::jsonb",\n'
        b'            (checkpoint.session, raw, CURSOR, canonical_json({"checkpoint": previous.model_dump(by_alias=True),\n'
        b'                                                           "hmac_sha256": signature(previous.model_dump(by_alias=True))})))\n',
    ),
)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _pairs(items):
    value = {}
    for key, item in items:
        if key in value:
            raise ValueError('CHECKPOINT_READ_SOURCE_DUPLICATE_KEY')
        value[key] = item
    return value


def _normalized(raw):
    value, count = re.subn(rb"^PROFILE_SHA256 = '[a-f0-9]{64}'$",
        b"PROFILE_SHA256 = '"+b'0'*64+b"'", raw, flags=re.M)
    if count != 1:
        raise ValueError('CHECKPOINT_READ_SOURCE_IMPLEMENTATION_CHANGED')
    return _sha(value)


def _profile():
    raw = PROFILE.read_bytes()
    if _sha(raw) != PROFILE_SHA256:
        raise ValueError('CHECKPOINT_READ_SOURCE_WITNESS_CHANGED')
    value = json.loads(raw, object_pairs_hook=_pairs)
    if (not isinstance(value, dict) or set(value) != {
            'schema', 'authority_effect', 'base_revision', 'readers', 'module_sha256'}
            or value['schema'] != 'sentinel.checkpoint-read-source-transition/1'
            or value['authority_effect'] != 'NONE' or value['base_revision'] != BASE_REVISION
            or not isinstance(value['readers'], dict) or set(value['readers']) != set(BASELINES)
            or set(CANDIDATES) != set(BASELINES)
            or value['module_sha256'] != _normalized(Path(__file__).read_bytes())):
        raise ValueError('CHECKPOINT_READ_SOURCE_WITNESS_INVALID')
    for module, record in value['readers'].items():
        if (not isinstance(record, dict) or set(record) != {'before', 'after'}
                or record['before'] != BASELINES[module] or record['after'] != CANDIDATES[module]):
            raise ValueError('CHECKPOINT_READ_SOURCE_MEMBER_INVALID')
    return value


def predecessor(module, raw):
    """Reverse only the complete sealed wrapper to independently pinned bytes."""
    if module == _CAS_MODULE and _sha(raw) == CAS_CANDIDATE:
        for current, previous in _CAS_CHANGES:
            if raw.count(current) != 1:
                raise ValueError('CHECKPOINT_CAS_SOURCE_RECIPE_CHANGED')
            raw = raw.replace(current, previous)
        if _sha(raw) != CANDIDATES[module]:
            raise ValueError('CHECKPOINT_CAS_SOURCE_PREDECESSOR_CHANGED')
    if module not in BASELINES or _sha(raw) != CANDIDATES.get(module):
        return raw
    value = _profile()
    if raw.count(_WRAPPER) != 1:
        raise ValueError('CHECKPOINT_READ_SOURCE_RECIPE_CHANGED')
    before = raw.replace(_WRAPPER, b'def read(conn):\n')
    if _sha(before) != value['readers'][module]['before']:
        raise ValueError('CHECKPOINT_READ_SOURCE_PREDECESSOR_CHANGED')
    return before
