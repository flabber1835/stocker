"""Publication-owned sparse action evidence, independent of rolling prices.

No broker state is read here. The execution reader remains the sole interpreter
of scalar and material events; this module preserves its evidence and outputs.
"""
from collections import defaultdict
from datetime import date
from decimal import Decimal

from sentinel.feed import calendar, rolling_store
from sentinel.feed.rolling_contract import canonical_json, digest

SCHEMA = "sentinel.retained-action-history/1"


def _event(value):
    from sentinel.execution.reconcile import CorporateActionEvent
    value = dict(value, session=date.fromisoformat(value["session"]))
    if "canonical_multiplier" in value:
        value["canonical_multiplier"] = Decimal(value["canonical_multiplier"])
    return CorporateActionEvent(**value)


def _economics(value, symbol):
    return {kind: sorted([(e["security_id"], e["ticker"], e["action"],
                          e.get("canonical_multiplier"), e.get("canonical_numerator"),
                          e.get("canonical_denominator")) for e in (value or {}).get(kind, [])
                         if e['ticker'] == symbol], key=str)
            for kind in ("scalar", "unsupported", "unresolved")}


def verify_coverage_chain(conn, *, version):
    """Enumerate required history from publications, never from surviving rows."""
    rows = conn.execute(
        "SELECT p.version,p.evidence,c.payload,c.payload_sha256,c.basis,c.through "
        "FROM sentinel_corpus_publications p LEFT JOIN sentinel_action_coverage c "
        "ON c.publication_version=p.version WHERE p.version<=%s "
        "AND p.evidence ? 'action_history' ORDER BY p.version", (version,)).fetchall()
    for number, evidence, payload, sha, basis, through in rows:
        if payload is None:
            raise ValueError("RETAINED_ACTION_COVERAGE_MISSING: " + str(number))
        if (digest(payload) != sha or evidence['action_history'] != sha
                or payload['basis'] != str(basis) or payload['through'] != str(through)):
            raise ValueError("RETAINED_ACTION_COVERAGE_CORRUPT: " + str(number))


def records(conn, *, version, start, end):
    verify_coverage_chain(conn, version=version)
    rows = conn.execute(
        "SELECT e.key,h.payload,h.payload_sha256,e.value,c.payload,c.payload_sha256,p.evidence "
        "FROM sentinel_action_coverage c JOIN sentinel_corpus_publications p ON p.version=c.publication_version "
        "CROSS JOIN LATERAL jsonb_each_text(c.payload->'added') e "
        "LEFT JOIN sentinel_action_history h ON h.session=e.key::date AND h.publication_version=c.publication_version "
        "WHERE c.publication_version<=%s AND e.key::date>%s AND e.key::date<=%s ORDER BY e.key,c.publication_version",
        (version, start, end)).fetchall()
    result = {}
    for day, payload, sha, expected, cover, cover_sha, publication in rows:
        if (payload is None or digest(payload) != sha or sha != expected
                or digest(cover) != cover_sha or publication.get('action_history') != cover_sha):
            raise ValueError("RETAINED_ACTION_EVIDENCE_CORRUPT")
        result[str(day)] = payload
    return result


def coverage(conn, pub, *, start, end):
    verify_coverage_chain(conn, version=pub.version)
    row = conn.execute("SELECT basis,through,payload,payload_sha256 FROM sentinel_action_coverage "
                       "WHERE publication_version=%s", (pub.version,)).fetchone()
    if row is None:
        if pub.evidence.get('action_history'):
            raise ValueError("RETAINED_ACTION_COVERAGE_MISSING")
        return None
    if (digest(row[2]) != row[3] or pub.evidence.get("action_history") != row[3]
            or str(row[0]) != row[2]["basis"] or str(row[1]) != row[2]["through"]):
        raise ValueError("RETAINED_ACTION_COVERAGE_CORRUPT")
    if (start < row[0] or end < start
            or str(end) > calendar.next_session(str(row[1]))):
        from sentinel.execution.feed_inputs import ExecutionInputsRefused
        raise ExecutionInputsRefused("ROLLING_ACTION_HISTORY_UNAVAILABLE")
    return row[2]


def _material(conn, refs, pub):
    from sentinel.execution.feed_actions import snapshot_lookup
    lo, hi = refs.manifest.window.start, refs.manifest.window.end
    lookup = snapshot_lookup(conn, refs=refs, pub=pub, start=lo, end=hi)
    material = defaultdict(lambda: dict(scalar=[], unsupported=[], unresolved=[],
                                        sources=[], bars=[], predecessors=[], dispositions=[], defensive=None))
    for name, events in (("scalar", lookup.scalar_events), ("unsupported", lookup.unsupported_events),
                         ("unresolved", lookup.unresolved_events)):
        for event in events:
            material[str(event.session)][name].append(event.to_dict())
    for source, payload, _ in refs.actions:
        day = calendar.session_on_or_after(payload["date"])
        if str(lo) < day <= str(hi) and payload["action"].lower() not in {"listed", "relation"}:
            material[day]["sources"].append(dict(payload, source_row_id=source))
    # Store only action/dividend coordinates and their actual predecessors.
    for day, item in material.items():
        symbols = sorted({p["ticker"] for p in item["sources"]}
                         | {p["ticker"] for k in ("scalar", "unsupported", "unresolved") for p in item[k]})
        identities = {e['security_id'] for k in ('scalar', 'unsupported', 'unresolved') for e in item[k]}
        identities.update(refs.resolver.resolve(symbol, day) for symbol in symbols if symbol != 'BIL')
        item['identity_rows'] = [row for row in refs.tickers if row['permaticker'] in identities]
        item['identity_aliases'] = [row for row in refs.projection.alias_rows if row['permaticker'] in identities]
        identity_symbols = set(symbols) | {row['ticker'] for row in item['identity_rows'] + item['identity_aliases']}
        item['identity_actions'] = [dict(payload, source_row_id=source) for source, payload, _ in refs.actions
            if payload['ticker'] in identity_symbols and payload['action'].lower() in {'tickerchangeto', 'tickerchangefrom', 'listed', 'delisted'}]
        item['identity_policy'] = refs.projection.applied_alias_rejections
        rows = conn.execute(
            "SELECT security_id,ticker,close_signal,close_unadjusted,dividend_per_share,split_ratio "
            "FROM sentinel_snapshot_bars WHERE candidate_id=%s AND session=%s AND ticker=ANY(%s) "
            "ORDER BY security_id", (refs.candidate_id, day, symbols)).fetchall()
        item["bars"] = [list(row) for row in rows]
        for sid, *_ in rows:
            prior = conn.execute("SELECT session,close_signal,close_unadjusted FROM sentinel_snapshot_bars "
                "WHERE candidate_id=%s AND security_id=%s AND session<%s ORDER BY session DESC LIMIT 1",
                (refs.candidate_id, sid, day)).fetchone()
            if prior:
                item["predecessors"].append([sid, str(prior[0]), *prior[1:]])
        pair = conn.execute("SELECT session,bil_close_signal,bil_close_unadjusted "
            "FROM sentinel_snapshot_benchmarks WHERE candidate_id=%s AND session<=%s "
            "ORDER BY session DESC LIMIT 2", (refs.candidate_id, day)).fetchall()
        item["defensive"] = [[str(r[0]), *r[1:]] for r in reversed(pair)]
    validation_sha = conn.execute("SELECT validation_sha256 FROM sentinel_snapshot_validations "
                                  "WHERE candidate_id=%s", (refs.candidate_id,)).fetchone()[0]
    validation = rolling_store.load_evidence(conn, validation_sha)
    for value in validation["split_dispositions"]:
        if value["session"] in material:
            material[value["session"]]["dispositions"].append(value)
    return dict(material)


def append(conn, *, candidate, version, previous):
    """Caller owns the corpus lock and publication transaction. Never commits."""
    from types import SimpleNamespace
    from sentinel.core.rolling_inputs import SnapshotReferences
    from sentinel.feed import store
    store._assert_corpus_locked(conn)
    manifest = rolling_store.manifest(conn, candidate)
    refs = SnapshotReferences(conn, candidate_id=candidate, snapshot_id=manifest.snapshot_id)
    pub = SimpleNamespace(version=version, run_id=None, window_end=str(manifest.window.end))
    prior = (conn.execute("SELECT basis,through FROM sentinel_action_coverage WHERE publication_version=%s",
                         (previous.version,)).fetchone() if previous else None)
    basis = prior[0] if prior else manifest.window.start
    if prior and manifest.window.start > prior[1]:
        raise ValueError("RETAINED_ACTION_COVERAGE_GAP")
    old = records(conn, version=version - 1, start=basis, end=manifest.window.end)
    new = _material(conn, refs, pub)
    current_sources = defaultdict(list)
    for source, payload, _ in refs.actions:
        if payload["action"].lower() not in {"listed", "relation"}:
            current_sources[calendar.session_on_or_after(payload["date"])].append(dict(payload, source_row_id=source))
    corrections, correction_evidence, added = [], {}, {}
    for day in sorted(set(old) | set(new) | {d for d in current_sources if str(basis) < d <= str(prior[1] if prior else basis)}):
        existing, observed = old.get(day), new.get(day)
        historical = prior is not None and day <= str(prior[1])
        sources = sorted(current_sources.get(day, []), key=lambda p: p["source_row_id"])
        prior_sources = sorted((existing or {}).get("sources", []), key=lambda p: p["source_row_id"])
        events = [e for item in (existing, observed) if item for k in ("scalar", "unsupported", "unresolved") for e in item[k]]
        symbols = {p['ticker'] for p in sources + prior_sources + events}
        changed = {symbol for symbol in symbols if historical and (
            [p for p in sources if p['ticker'] == symbol] != [p for p in prior_sources if p['ticker'] == symbol]
            or (str(manifest.window.start) < day <= str(manifest.window.end)
                and _economics(observed, symbol) != _economics(existing, symbol)))}
        if changed:
            correction_evidence[day] = dict(sources=sources, observed=observed,
                                           snapshot_id=manifest.snapshot_id)
            identities = {(e["security_id"], e["ticker"]) for e in events if e['ticker'] in changed}
            identities.update(("SENTINEL:BIL" if p["ticker"] == "BIL" else refs.resolver.resolve(p["ticker"], day),
                               p["ticker"]) for p in sources + prior_sources if p['ticker'] in changed)
            for sid, symbol in sorted(identities, key=str):
                corrections.append(dict(security_id=sid, ticker=symbol, session=day, action="historycorrection",
                    value=None, contraticker=None, source_row_id=digest(sources),
                    reason="RETAINED_ACTION_MEANING_CHANGED", evidence_kind="retained_action_correction",
                    publication_version=version))
        if existing is None and observed is not None and not historical:
            payload = dict(observed, snapshot_id=manifest.snapshot_id,
                           reference_sha256=manifest.reference_sha256,
                           source_evidence_sha256=manifest.source_evidence_sha256,
                           publication_version=version)
            conn.execute("INSERT INTO sentinel_action_history VALUES (%s,%s,%s,%s::jsonb)",
                         (day, version, digest(payload), canonical_json(payload)))
            added[day] = digest(payload)
    payload = dict(schema=SCHEMA, basis=str(basis), through=str(manifest.window.end),
                   candidate_id=candidate, corrections=corrections,
                   correction_evidence=correction_evidence, added=added)
    sha = digest(payload)
    conn.execute("INSERT INTO sentinel_action_coverage VALUES (%s,%s,%s,%s,%s::jsonb)",
                 (version, basis, manifest.window.end, sha, canonical_json(payload)))
    return sha


def lookup(conn, pub, *, start, end):
    from sentinel.execution.reconcile import CorpusActionLookup
    covered = coverage(conn, pub, start=start, end=end)
    if covered is None:
        return None
    values = records(conn, version=pub.version, start=start, end=end)
    buckets = {k: tuple(_event(e) for p in values.values() for e in p[k])
               for k in ("scalar", "unsupported", "unresolved")}
    corrections = tuple(_event(e) for e in covered["corrections"] if str(start) < e["session"] <= str(end))
    events = defaultdict(list)
    for e in buckets["scalar"]:
        events[e.security_id].append((e.session, e.canonical_multiplier))
    return CorpusActionLookup(start=start, events={k: tuple(v) for k, v in events.items()},
        scalar_events=buckets["scalar"], unsupported_events=buckets["unsupported"],
        unresolved_events=buckets["unresolved"] + corrections)
