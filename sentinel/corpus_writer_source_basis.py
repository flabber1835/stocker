"""One exact scheduling successor, composed with the retained diagnostic seam."""
from __future__ import annotations

import hashlib

MODULE = 'sentinel.feed.rolling_publisher'
BASE_REVISION = '131cc833923610d095492ca6b6890eadfbe8e163'
BASE_SHA256 = 'b31e0429c4e9c235c9ae18b39f98ce93b03f6817a973107c8aa83d9889c9d443'
REVIEWED_SHA256 = '0911777fdce9a86a27e253856b6f0b9ed927a52124f8dcb4f078311a22a9d8e7'
BASE_AST_SHA256 = 'fbe84f12c7c3f7c6a3a4298bf4a832c62d62940372e82eef5698629601e1677d'
SCHEDULING_IMPORT = 'from sentinel.feed import writer_schedule'
SCHEDULING_CONTEXT = 'writer_schedule.turn(conn, lease)'
INITIALIZATION = 'discard_connection = False'
DISPOSAL_OBSERVATION = 'discard_connection = writer_schedule.connection_discarded(exc)'
REUSABLE_GUARD = 'not discard_connection and not conn.closed'


def normalize_reviewed_source(raw: bytes) -> bytes:
    """Invert only this byte-exact successor before the existing closed seam.

    Unknown source is returned unchanged so the caller hashes its actual bytes.
    This never masks an arbitrary neighboring edit by matching an AST pattern.
    """
    if hashlib.sha256(raw).hexdigest() != REVIEWED_SHA256:
        return raw
    replacements = (
        (f'{SCHEDULING_IMPORT}\n'.encode(), b'', 1),
        (f'{SCHEDULING_CONTEXT}, '.encode(), b'', 3),
        (f'    {INITIALIZATION}\n'.encode(), b'', 1),
        (f'        {DISPOSAL_OBSERVATION}\n'.encode(), b'', 1),
        ((f'        if {REUSABLE_GUARD}:\n'
          '            _record_failure(conn, lease, exc, operational=operational)\n').encode(),
         b'        _record_failure(conn, lease, exc, operational=operational)\n', 1),
        ((f'        if {REUSABLE_GUARD}:\n'
          '            conn.rollback()\n'
          '            staging.clear(conn, run_id=lease.owner)\n'
          '            if operational:\n'
          '                from sentinel.feed import retention\n'
          '                conn.commit()\n'
          '                retention.maintain(conn)\n').encode(),
         (b'        conn.rollback()\n'
          b'        staging.clear(conn, run_id=lease.owner)\n'
          b'        if operational:\n'
          b'            from sentinel.feed import retention\n'
          b'            conn.commit()\n'
          b'            retention.maintain(conn)\n'), 1),
    )
    normalized = raw
    for before, after, count in replacements:
        if normalized.count(before) != count:
            raise ValueError('reviewed publisher scheduling source changed')
        normalized = normalized.replace(before, after)
    if hashlib.sha256(normalized).hexdigest() != BASE_SHA256:
        raise ValueError('reviewed publisher scheduling baseline changed')
    return normalized
