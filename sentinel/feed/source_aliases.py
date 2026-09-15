"""Durable negative evidence for inferred aliases; never invents an identity."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from decimal import Decimal, InvalidOperation

from sentinel.feed import universe

KEY = "source_alias_rejections"
SCHEMA = "sentinel.source-alias-rejections/1"


def _valid_prices(bars):
    try:
        for bar in bars:
            for field in ("open", "close", "closeunadj", "volume"):
                value = Decimal(str(bar[field]))
                if not value.is_finite() or value < 0 or (field != "volume" and value == 0):
                    return False
    except (InvalidOperation, KeyError, TypeError):
        return False
    return True


def _encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def evidence(records=()):
    # One earliest witness per exact claim set, independent of arrival order.
    selected = {}
    for record in records:
        key = (record["permaticker"], tuple(record["source_ids"]))
        if key not in selected or (record["session"], _encoded(record)) < (
                selected[key]["session"], _encoded(selected[key])):
            selected[key] = record
    payload = {"schema": SCHEMA, "records": [selected[k] for k in sorted(selected)]}
    return {**payload, "sha256": hashlib.sha256(_encoded(payload).encode()).hexdigest()}


def validate(payload):
    if (not isinstance(payload, dict) or set(payload) != {"schema", "records", "sha256"}
            or payload.get("schema") != SCHEMA or not isinstance(payload["records"], list)):
        raise universe.HistoricalIdentityMutation("invalid source alias rejection evidence")
    try:
        for item in payload["records"]:
            if (set(item) != {"permaticker", "native_ticker", "session", "source_ids", "bars"}
                    or not item["permaticker"] or not item["native_ticker"]
                    or not item["source_ids"]
                    or sorted(set(item["source_ids"])) != item["source_ids"]
                    or len(item["bars"]) < 2 or not _valid_prices(item["bars"])):
                raise ValueError("invalid witness")
            dt.date.fromisoformat(item["session"])
            labels = [bar["ticker"] for bar in item["bars"]]
            if len(set(labels)) != len(labels) or item["native_ticker"] not in labels:
                raise ValueError("invalid source keys")
            for bar in item["bars"]:
                if bar["date"] != item["session"] or len(bar["source_sha256"]) != 64:
                    raise ValueError("invalid bar witness")
        if evidence(payload["records"]) != payload:
            raise ValueError("evidence digest or canonical order differs")
    except (ValueError, KeyError, TypeError) as exc:
        raise universe.HistoricalIdentityMutation("invalid source alias rejection witness") from exc
    return payload


def matches(identity, record):
    """Exactly one native label, plus wholly unanchored inferred labels."""
    sid, day = record["permaticker"], record["session"]
    chain = identity.chains.get(sid, ())
    if sorted({s for edge in chain for s in edge.source_ids}) != record["source_ids"]:
        return False
    symbols = {s for edge in chain for s in (edge.old, edge.new)}
    native = universe.IdentityResolver(universe.listings_from_rows(identity.rows))
    anchors = {str(row.get("ticker") or "").upper() for row in identity.rows}
    observed = {bar["ticker"] for bar in record["bars"]}
    label = record["native_ticker"]
    return (_valid_prices(record["bars"]) and label in observed and observed <= symbols
            and native.resolve(label, day) == sid
            and all(symbol not in anchors for symbol in observed - {label}))


def discover(coverage, identity):
    """Read every privately observed collision, never a truncated diagnostic."""
    records = []
    native = universe.IdentityResolver(universe.listings_from_rows(identity.rows))
    groups = coverage._db.execute(
        "SELECT session,permaticker FROM identity_collisions "
        "GROUP BY session,permaticker ORDER BY session,permaticker")
    for session, sid in groups:
        bars = [json.loads(row[0]) for row in coverage._db.execute(
            "SELECT payload FROM identity_collisions WHERE session=? AND permaticker=? ORDER BY ticker",
            (session, sid))]
        labels = [bar["ticker"] for bar in bars if native.resolve(bar["ticker"], session) == sid]
        if len(labels) != 1:
            continue
        record = {"permaticker": sid, "native_ticker": labels[0], "session": session,
                  "source_ids": sorted({s for edge in identity.chains.get(sid, ()) for s in edge.source_ids}),
                  "bars": bars}
        if matches(identity, record):
            records.append(record)
    return evidence(records)


def apply(identity, payload):
    identity.alias_rejections = validate(payload)
    identity.applied_alias_rejections = []
    for record in payload["records"]:
        if not matches(identity, record):
            continue
        sid = record["permaticker"]
        identity.chains.pop(sid)
        identity.alias_rows = [r for r in identity.alias_rows if str(r["permaticker"]) != sid]
        identity.applied_alias_rejections.append(record)


def load(conn, *, include_run_id=None):
    with conn.cursor() as cur:
        if include_run_id is not None:
            cur.execute("SELECT publication_recovery->%s FROM feed_ingest_runs WHERE run_id=%s",
                        (KEY, str(include_run_id)))
            row = cur.fetchone()
            if row and row[0] is not None:
                return validate(row[0])
        # Read immutable publication evidence, never another candidate's row.
        cur.execute("SELECT evidence->%s FROM sentinel_corpus_publications "
                    "WHERE evidence ? %s ORDER BY version DESC LIMIT 1", (KEY, KEY))
        row = cur.fetchone()
    return evidence() if not row else validate(row[0])


def record(conn, *, run_id, payload):
    payload = validate(payload)
    with conn.cursor() as cur:
        cur.execute("UPDATE feed_ingest_runs SET publication_recovery=jsonb_set("
                    "publication_recovery,ARRAY[%s],%s::jsonb,true),updated_at=NOW() "
                    "WHERE run_id=%s AND kind='seed' AND status='running' "
                    "AND NOT EXISTS (SELECT 1 FROM sentinel_corpus_publications p "
                    "WHERE p.run_id=feed_ingest_runs.run_id)", (KEY, _encoded(payload), str(run_id)))
        if cur.rowcount != 1:
            conn.rollback()
            raise universe.HistoricalIdentityMutation("alias evidence lost unpublished seed authority")
    conn.commit()


def require_current(identity, payload):
    """A changed source must earn a complete replay before changing this map."""
    if identity.applied_alias_rejections != validate(payload)["records"]:
        raise universe.HistoricalIdentityMutation(
            "source authority changed for a rejected inferred alias; retained history replay required")


def excludes(resolver, ticker):
    """Only an explicitly witnessed, still-unanchored label can leave CDC out."""
    owner = getattr(resolver, "__self__", resolver)
    projection = getattr(owner, "projection", None)
    if projection is None:
        return False
    if any(str(row.get("ticker") or "").upper() == ticker for row in projection.rows):
        return False
    return any(ticker != item["native_ticker"] and ticker in {bar["ticker"] for bar in item["bars"]}
               for item in projection.applied_alias_rejections)


def changed_identities(before, after):
    def mappings(payload):
        return {item["permaticker"]: (item["native_ticker"], tuple(item["source_ids"]))
                for item in validate(payload)["records"]}
    old, new = mappings(before), mappings(after)
    return sorted(sid for sid in old.keys() | new.keys() if old.get(sid) != new.get(sid))


def identity_changes(conn, *, run_id, corpus_lo, corpus_hi):
    return [{"permaticker": sid, "ticker": "", "kind": KEY,
             "published": [corpus_lo, corpus_hi], "candidate": [corpus_lo, corpus_hi]}
            for sid in changed_identities(load(conn), load(conn, include_run_id=run_id))]
