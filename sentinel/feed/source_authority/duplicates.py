"""Canonical SEP/SFP key uniqueness before stable fingerprints."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
from pathlib import Path
from typing import Iterable, Iterator, Mapping, Optional

from sentinel.feed import sharadar
from .dates import (
    CanonicalSourceDuplicate, SepUpdateEnvelope, _canonical_key,
    _canonical_row,
)


def _open_key_store():
    directory = tempfile.TemporaryDirectory(prefix="sentinel-source-keys-")
    conn = sqlite3.connect(Path(directory.name) / "keys.sqlite3")
    conn.execute("PRAGMA journal_mode=OFF")
    conn.execute("PRAGMA synchronous=OFF")
    conn.execute("PRAGMA temp_store=FILE")
    conn.executescript("""
        CREATE TABLE source_keys (
            ticker TEXT NOT NULL, session TEXT NOT NULL,
            payload TEXT NOT NULL, fingerprint TEXT NOT NULL,
            PRIMARY KEY (ticker,session)) WITHOUT ROWID;
        CREATE TABLE duplicate_keys (
            ticker TEXT NOT NULL, session TEXT NOT NULL,
            multiplicity INTEGER NOT NULL,
            PRIMARY KEY (ticker,session)) WITHOUT ROWID;
        CREATE TABLE duplicate_variants (
            ticker TEXT NOT NULL, session TEXT NOT NULL,
            fingerprint TEXT NOT NULL, payload TEXT NOT NULL,
            multiplicity INTEGER NOT NULL,
            PRIMARY KEY (ticker,session,fingerprint)) WITHOUT ROWID;
    """)
    return directory, conn


def validated_source_rows(
        table: str, rows: Iterable[Mapping], *,
        update_envelope: Optional[SepUpdateEnvelope] = None) -> Iterator[dict]:
    expected = str(table).upper()
    if expected not in {sharadar.SEP, sharadar.SFP}:
        raise ValueError("canonical source-key validation applies only to SEP/SFP")
    if update_envelope is not None and expected != sharadar.SEP:
        raise ValueError("lastupdated envelopes apply only to SEP")

    directory, conn = _open_key_store()
    duplicate_seen = False
    try:
        for raw in rows:
            row = dict(raw)
            ticker, session = _canonical_key(expected, row)
            if update_envelope is not None:
                update_envelope.validate(
                    row.get("lastupdated"), ticker=ticker, session=session)
            payload = json.dumps(
                _canonical_row(row), sort_keys=True, separators=(",", ":"))
            fingerprint = hashlib.sha256(payload.encode("utf-8")).hexdigest()
            try:
                conn.execute(
                    "INSERT INTO source_keys"
                    " (ticker,session,payload,fingerprint) VALUES (?,?,?,?)",
                    (ticker, session, payload, fingerprint))
            except sqlite3.IntegrityError:
                duplicate_seen = True
                prior = conn.execute(
                    "SELECT payload,fingerprint FROM source_keys"
                    " WHERE ticker=? AND session=?", (ticker, session)).fetchone()
                conn.execute(
                    "INSERT INTO duplicate_keys(ticker,session,multiplicity)"
                    " VALUES (?,?,2) ON CONFLICT(ticker,session) DO UPDATE SET"
                    " multiplicity=duplicate_keys.multiplicity+1",
                    (ticker, session))
                conn.execute(
                    "INSERT OR IGNORE INTO duplicate_variants"
                    " (ticker,session,fingerprint,payload,multiplicity)"
                    " VALUES (?,?,?,?,1)",
                    (ticker, session, str(prior[1]), str(prior[0])))
                conn.execute(
                    "INSERT INTO duplicate_variants"
                    " (ticker,session,fingerprint,payload,multiplicity)"
                    " VALUES (?,?,?,?,1)"
                    " ON CONFLICT(ticker,session,fingerprint) DO UPDATE SET"
                    " multiplicity=duplicate_variants.multiplicity+1",
                    (ticker, session, fingerprint, payload))
                continue
            yield row
        if duplicate_seen:
            raise _duplicate_refusal(expected, conn)
    finally:
        conn.close()
        directory.cleanup()


def _duplicate_refusal(table: str, conn: sqlite3.Connection
                       ) -> CanonicalSourceDuplicate:
    ticker, session, multiplicity = conn.execute(
        "SELECT ticker,session,multiplicity FROM duplicate_keys"
        " ORDER BY ticker,session LIMIT 1").fetchone()
    variants = conn.execute(
        "SELECT fingerprint,payload,multiplicity FROM duplicate_variants"
        " WHERE ticker=? AND session=? ORDER BY fingerprint",
        (ticker, session)).fetchall()
    decoded = [json.loads(str(payload)) for _fp, payload, _n in variants]
    fields = sorted({field for row in decoded for field in row})
    conflicting = []
    values = {}
    for field in fields:
        observed = sorted({json.dumps(row.get(field), sort_keys=True,
                                      separators=(",", ":")) for row in decoded})
        if len(observed) > 1:
            conflicting.append(field)
            values[field] = [json.loads(item) for item in observed]
    evidence = {
        "table": table,
        "key": {"ticker": str(ticker), "date": str(session)},
        "multiplicity": int(multiplicity),
        "row_fingerprints": [
            {"sha256": str(fp), "count": int(count)}
            for fp, _payload, count in variants],
        "conflicting_fields": conflicting,
        "conflicting_values": values,
        "identical_duplicate_policy": "reject",
    }
    return CanonicalSourceDuplicate(
        "Sharadar canonical source-key duplicate refused: "
        + json.dumps(evidence, sort_keys=True, separators=(",", ":")))


class CanonicalSourceFetch:
    def __init__(self, fetch, *,
                 sep_update_envelope: Optional[SepUpdateEnvelope] = None):
        self._fetch = fetch
        self._sep_update_envelope = sep_update_envelope

    def __call__(self, table, params=None, **kwargs):
        rows = self._fetch(table, params, **kwargs)
        if table not in {sharadar.SEP, sharadar.SFP}:
            return rows
        envelope = None
        if (table == sharadar.SEP and self._sep_update_envelope is not None
                and _is_matching_update_request(
                    params or {}, self._sep_update_envelope)):
            envelope = self._sep_update_envelope
        return validated_source_rows(table, rows, update_envelope=envelope)


def _is_matching_update_request(params: Mapping,
                                envelope: SepUpdateEnvelope) -> bool:
    if envelope.lower is None:
        return True
    return (
        str(params.get("lastupdated.gte") or "") == envelope.lower.isoformat()
        and str(params.get("lastupdated.lte") or "") == envelope.upper.isoformat())
