"""Disk-backed source witnesses for every observed identity/session collision."""
from __future__ import annotations

import hashlib
import json

from sentinel.source_diagnostic import COLLISION_PREFIX
from .dates import SeedIdentityCollision


def bar_witness(row):
    fields = ("ticker", "date", "open", "close", "closeunadj", "volume", "lastupdated")
    value = {key: None if row.get(key) is None else str(row[key])[:256] for key in fields}
    value["source_sha256"] = hashlib.sha256(json.dumps(
        dict(row), sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def require_no_collisions(db, *, projection, resolve, date_from, date_to):
    groups = db.execute(
        "SELECT session,permaticker,COUNT(*) FROM identity_collisions "
        "WHERE session BETWEEN ? AND ? GROUP BY session,permaticker "
        "ORDER BY session,permaticker", (date_from, date_to))
    digest = hashlib.sha256()
    examples = []
    total = bars_total = 0
    identity = getattr(getattr(resolve, "__self__", None), "projection", None)
    for session, sid, count in groups:
        total += 1
        bars_total += count
        bars = []
        symbols = []
        for ticker, payload in db.execute(
                "SELECT ticker,payload FROM identity_collisions "
                "WHERE session=? AND permaticker=? ORDER BY ticker", (session, sid)):
            digest.update(json.dumps([session, sid, ticker, payload],
                                     separators=(",", ":")).encode() + b"\n")
            if len(bars) < 4:
                bars.append(json.loads(payload))
            if len(symbols) < 16:
                symbols.append(ticker[:256])
        if len(examples) >= 8:
            continue
        keys = ("ticker", "permaticker", "category", "firstpricedate", "lastpricedate")
        def metadata(rows):
            selected = sorted((row for row in rows if str(row.get("permaticker")) == sid),
                              key=lambda row: json.dumps(row, sort_keys=True, default=str))
            return [{key: None if row.get(key) is None else str(row[key])[:256] for key in keys}
                    for row in selected[:8]]
        native = metadata(identity.rows) if identity is not None else [
            dict(ticker=item.ticker[:256], permaticker=item.permaticker[:256], category=item.category[:256],
                 firstpricedate=item.first_session, lastpricedate=item.last_session)
            for item in projection.records if item.permaticker == sid][:8]
        examples.append({
            "session": session, "permaticker": sid[:256], "source_tickers": symbols,
            "source_tickers_total": count, "source_bars": bars, "native_listings": native,
            "derived_aliases": metadata(identity.alias_rows) if identity is not None else [],
            "rename_events": [dict(date=edge.date, old=edge.old[:256], new=edge.new[:256],
                                   source_ids=[value[:256] for value in edge.source_ids[:16]])
                              for edge in identity.chains.get(sid, ())[:8]]
                             if identity is not None else [],
        })
    if total:
        evidence = {"session": examples[0]["session"], "interval": [date_from, date_to],
                    "identity_collision_total": total, "collision_source_rows_total": bars_total,
                    "identity_collisions": examples, "collision_sha256": digest.hexdigest()}
        # The NAS marker parser has a 32 KiB bound. Keep the total and digest
        # over every group even when its illustrative metadata cannot fit.
        encoded = json.dumps(evidence, separators=(",", ":"))
        while len(encoded) > 30000:
            if len(examples) > 1:
                examples.pop()
            else:
                for key in ("rename_events", "derived_aliases", "native_listings", "source_bars"):
                    if examples[0][key]:
                        examples[0][key].pop()
                        break
            encoded = json.dumps(evidence, separators=(",", ":"))
        raise SeedIdentityCollision(COLLISION_PREFIX + encoded)
