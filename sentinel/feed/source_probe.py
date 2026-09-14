"""Small retry probes for an already identified source coverage failure.

Success only authorizes another full source proof. It cannot publish data or
authorize execution. The hint is ordinary durable automation diagnostic data.
"""
from __future__ import annotations

import datetime as dt
import json
from itertools import islice
import re

from sentinel.automation.model import SourceDataPending
from sentinel.feed import authority, sharadar, symbol_identity


def _bounded(rows, limit):
    iterator = iter(rows)
    try:
        result = list(islice(iterator, limit + 1))
    finally:
        close = getattr(iterator, "close", None)
        if close is not None:
            close()
    if len(result) > limit:
        raise SourceDataPending("source probe exceeds its row bound")
    return result


def _validate_hint(value):
    if not isinstance(value, dict) or set(value) != {"session", "identities"}:
        raise ValueError("invalid source probe hint")
    session = dt.date.fromisoformat(value["session"]).isoformat()
    identities = value["identities"]
    if (not isinstance(identities, list) or not 1 <= len(identities) <= 16
            or any(not isinstance(v, str) or not re.fullmatch(r"[0-9]{1,20}", v)
                   for v in identities) or len(set(identities)) != len(identities)):
        raise ValueError("invalid source probe identities")
    return {"session": session, "identities": sorted(identities)}


def coverage_hint(detail: str):
    marker = "Sharadar SEP seed eligible-set coverage refused: "
    if marker not in detail:
        return None
    try:
        evidence = json.loads(detail.split(marker, 1)[1])
        missing = evidence["missing_eligible"]
        if evidence["missing_eligible_total"] != len(missing):
            return None
        return _validate_hint({"session": evidence["session"],
                               "identities": [str(v["permaticker"]) for v in missing]})
    except (ValueError, TypeError, KeyError):
        return None


def require_recovery_probe(hint, *, through: str, fetch=None) -> None:
    if hint is None:
        return
    request = _validate_hint(hint)
    if request["session"] > through:
        raise ValueError("source probe session is beyond the decision horizon")
    fetch = fetch or sharadar.fetch_table
    # The permanent key survives a provider relabelling. It also prevents an
    # old symbol reused by another company from making this probe pass.
    params = {"table": "SEP", "permaticker": ",".join(request["identities"])}
    rows = _bounded(fetch(sharadar.TICKERS, params), 64)
    from sentinel.feed import coherence
    second = _bounded(fetch(sharadar.TICKERS, params), 64)
    authority.require_stable(sharadar.TICKERS, coherence.observe_tickers(rows),
                             coherence.observe_tickers(second))
    if {str(row.get("permaticker")) for row in rows} != set(request["identities"]):
        raise SourceDataPending("source identity probe is still incomplete")
    symbols = sorted({str(row.get("ticker") or "") for row in rows})
    if any(not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,19}", v) for v in symbols):
        raise SourceDataPending("source identity probe has invalid labels")
    # Follow only explicit rename rows connected to the small failed key set.
    actions, pending, queried = [], set(symbols), set()
    context = {(str(row.get("permaticker")), str(row.get("ticker"))): row for row in rows}
    while pending:
        if len(queried | pending) > 64:
            raise SourceDataPending("source rename probe exceeds its identity bound")
        batch = sorted(pending)
        queried.update(pending)
        pending = set()
        # Permanent-ID-only queries hide competing listings for reused labels.
        # Include every discovered spelling's metadata in the same projection
        # the complete seed uses, while retaining the fixed request/row bounds.
        ticker_params = {"table": "SEP", "ticker": ",".join(batch)}
        metadata = _bounded(fetch(sharadar.TICKERS, ticker_params), 256)
        metadata_second = _bounded(fetch(sharadar.TICKERS, ticker_params), 256)
        authority.require_stable(sharadar.TICKERS, coherence.observe_tickers(metadata),
                                 coherence.observe_tickers(metadata_second))
        for row in metadata:
            key = (str(row.get("permaticker")), str(row.get("ticker")))
            if key in context:
                authority.require_stable(sharadar.TICKERS,
                    coherence.observe_tickers([context[key]]), coherence.observe_tickers([row]))
            context[key] = row
        if len(context) > 256:
            raise SourceDataPending("source metadata probe exceeds its row bound")
        for field in ("ticker", "contraticker"):
            action_params = {field: ",".join(batch), "date.gte": "1900-01-01",
                             "date.lte": through, "action": ",".join(symbol_identity.RENAME_TYPES)}
            received = _bounded(fetch(sharadar.ACTIONS, action_params), 256)
            repeated = _bounded(fetch(sharadar.ACTIONS, action_params), 256)
            authority.require_stable(sharadar.ACTIONS, authority.observe_actions(received),
                                     authority.observe_actions(repeated))
            actions.extend(received)
            for row in received:
                for name in ("ticker", "contraticker"):
                    token = str(row.get(name) or "")
                    if token not in queried and re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,19}", token):
                        pending.add(token)
    projection = symbol_identity.SymbolProjection(context.values(), actions, through=through)
    resolver = projection.resolver()
    symbols = sorted({str(r["ticker"]) for r in (*projection.rows, *projection.alias_rows)
                      if str(r.get("permaticker")) in request["identities"]
                      and resolver.resolve(str(r["ticker"]), request["session"])
                      == str(r["permaticker"])})
    if not symbols:
        raise SourceDataPending("source identity probe has no unambiguous labels")
    bars = _bounded(fetch(sharadar.SEP, {"ticker": ",".join(symbols),
                                   "date.gte": request["session"],
                                   "date.lte": request["session"]}), 64)
    found = [resolver.resolve(str(row.get("ticker") or ""), request["session"])
             for row in bars if str(row.get("date")) == request["session"]
             and float(row.get("closeunadj") or 0) > 0]
    if (set(found) != set(request["identities"]) or len(found) != len(set(found))):
        raise SourceDataPending("source membership probe is still incomplete or ambiguous")


__all__ = ["coverage_hint", "require_recovery_probe"]
