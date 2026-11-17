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
PROFILE_SHA256 = '6b96d8423d13b0bb91f0a6cf4c08dfd148cb5fbac7af3cdf373e29f22dbf2189'
PROFILE = Path(__file__).with_name('checkpoint-read-source-transition.json')
_WRAPPER = (b'def read(conn):\n    from sentinel import committed_read\n'
            b'    return committed_read.checkpoint(conn, cursor=CURSOR, read=_read)\n\n\n'
            b'def _read(conn):\n')


_CAS_MODULE = 'sentinel.rolling_daily_checkpoint'
CAS_CANDIDATE = '564fcd218fb5596c2db5888911df9c6e9eeb4509f8c7b3928eb53ea006e150fd'
STORAGE_CANDIDATE = '09c511ad5dc3aaa1aec51bf46980c3f88f83a32eec08a7cc4fe7c6cbcc5b4048'
_STORAGE_HELPER = Path(__file__).with_name('checkpoint_input_storage.py')
_STORAGE_HELPER_SHA256 = '880569f25a358fe81c0a78b9c63eee0939bab4725381b12723667d975fd2ee59'
_STORAGE_ADDITIONS = (
    b'from sentinel import checkpoint_input_storage as input_storage\n',
    b'    _authenticated_input_sha256: str | None = PrivateAttr(default=None)\n',
)
# The complete candidate and codec hashes bind every byte of the regions below.
# Keep only the predecessor regions here so the witness does not duplicate the
# new implementation as well.
_STORAGE_REGIONS = (
    (
        b'def archive_input(conn, checkpoint):\n', b'def read(conn):\n',
        b'def archive_input(conn, checkpoint):\n'
        b'    result = conn.execute(\n'
        b'        "INSERT INTO sentinel_processed_sessions (cursor_name,session,state) VALUES (%s,%s,%s::jsonb)"\n'
        b'        " ON CONFLICT DO NOTHING",\n'
        b'        (input_name(checkpoint.observation_id, checkpoint.session), checkpoint.session,\n'
        b'         canonical_json(checkpoint.input_value)))\n'
        b'    if result.rowcount != 1:\n'
        b'        raise Refused("DAILY_INPUT_ARCHIVE_ALREADY_EXISTS")\n\n\n'
        b'def require_input(conn, checkpoint):\n'
        b'    row = conn.execute("SELECT session,state FROM sentinel_processed_sessions WHERE cursor_name=%s",\n'
        b'                       (input_name(checkpoint.observation_id, checkpoint.session),)).fetchone()\n'
        b'    if row is None or str(row[0]) != checkpoint.session or row[1] != checkpoint.input_value:\n'
        b'        raise Refused("DAILY_INPUT_ARCHIVE_CHANGED")\n\n\n',
    ),
    (
        b'    raw = row[1]\n', b'    checkpoint._row_version = (row[0], *row[2:])\n',
        b'    raw = row[1]\n'
        b'    if (not isinstance(raw, dict) or set(raw) != {"checkpoint", "hmac_sha256"}\n'
        b'            or not hmac.compare_digest(str(raw["hmac_sha256"]), signature(raw["checkpoint"]))):\n'
        b'        raise Refused("DAILY_CHECKPOINT_AUTHENTICATION_FAILED")\n'
        b'    model = (ReconstructionCheckpoint if raw["checkpoint"].get("schema") ==\n'
        b'             "sentinel.rolling-reconstruction-checkpoint/1" else Checkpoint)\n'
        b'    checkpoint = model.model_validate(raw["checkpoint"])\n'
        b'    if str(row[0]) != checkpoint.session or raw["checkpoint"] != checkpoint.model_dump(by_alias=True):\n'
        b'        raise Refused("DAILY_CHECKPOINT_SHAPE_CHANGED")\n',
    ),
    (
        b'    payload = checkpoint.model_dump(by_alias=True)\n', b'    if isinstance(previous, Checkpoint):\n',
        b'    payload = checkpoint.model_dump(by_alias=True)\n'
        b'    raw = canonical_json({"checkpoint": payload, "hmac_sha256": signature(payload)})\n',
    ),
    (
        b'    input_sha256 = checkpoint._authenticated_input_sha256\n',
        b'    observer = shadow.ShadowObserver.resume_checkpoint(\n',
        b'    require_input(conn, checkpoint)\n',
    ),
)
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
    if module == _CAS_MODULE and _sha(raw) == STORAGE_CANDIDATE:
        if _sha(_STORAGE_HELPER.read_bytes()) != _STORAGE_HELPER_SHA256:
            raise ValueError('CHECKPOINT_STORAGE_SOURCE_CODEC_CHANGED')
        for added in _STORAGE_ADDITIONS:
            if raw.count(added) != 1:
                raise ValueError('CHECKPOINT_STORAGE_SOURCE_RECIPE_CHANGED')
            raw = raw.replace(added, b'')
        for start, end, previous in _STORAGE_REGIONS:
            if raw.count(start) != 1 or raw.count(end) != 1 or raw.index(start) >= raw.index(end):
                raise ValueError('CHECKPOINT_STORAGE_SOURCE_RECIPE_CHANGED')
            raw = raw[:raw.index(start)] + previous + raw[raw.index(end):]
        raw = raw.replace(b'or input_sha256 != rows[0]["input_sha256"]',
                          b'or digest(checkpoint.input_value) != rows[0]["input_sha256"]')
        if _sha(raw) != CAS_CANDIDATE:
            raise ValueError('CHECKPOINT_STORAGE_SOURCE_PREDECESSOR_CHANGED')
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
