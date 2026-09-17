"""Versioned market inputs for execution; never strategy or broker authority."""
from __future__ import annotations

from contextlib import contextmanager, ExitStack
from decimal import Decimal

from sentinel.feed import calendar, publication, operational_snapshot as snapshots
from sentinel.feed import rolling_go_inputs, rolling_store, store, readiness as legacy_readiness


class ExecutionInputsRefused(publication.CorpusIncoherent):
    pass


def is_rolling(pub):
    return rolling_go_inputs.is_rolling(pub)


def current(conn):
    try:
        return publication.current(conn)
    except publication.CorpusIncoherent as exc:
        if str(exc) != "ROLLING_SNAPSHOT_REQUIRES_VERSIONED_READER":
            raise
    pub = snapshots._current(conn)
    snapshots._bound(conn, pub)
    return pub


def require_current(conn):
    # Dispatch only the authenticated publication's explicit reader-version
    # refusal. Integrity, receipt and all other legacy failures remain failures.
    try:
        return publication.require_current(conn)
    except publication.CorpusIncoherent as exc:
        if str(exc) != "ROLLING_SNAPSHOT_REQUIRES_VERSIONED_READER":
            raise
    pub = snapshots._current(conn)
    snapshots._bound(conn, pub)
    return pub


@contextmanager
def pinned(conn, *, commit=True):
    with ExitStack() as stack:
        snapshot_reader = False
        try:
            pub = stack.enter_context(publication.pinned(conn, commit=commit))
        except publication.CorpusIncoherent as exc:
            if str(exc) != "ROLLING_SNAPSHOT_REQUIRES_VERSIONED_READER":
                raise
            snapshot_reader = True
        if snapshot_reader:
            pub, _ = stack.enter_context(snapshots.pinned(conn, commit=commit))
        yield pub


def frontier(conn, pub=None):
    pub = current(conn) if pub is None else pub
    return pub.window_end if is_rolling(pub) else store.latest_visible_session(conn)


def coherent(conn):
    pub = require_current(conn)
    if is_rolling(pub):
        snapshots._bound(conn, pub)
        if publication.chain_gaps(conn):
            raise ExecutionInputsRefused("ROLLING_PUBLICATION_CHAIN_GAP")
        return
    publication.assert_operationally_coherent(conn)


def readiness(conn, *, today):
    pub = require_current(conn)
    if is_rolling(pub):
        from datetime import datetime
        return rolling_go_inputs.validate(conn, pub, now=datetime.fromisoformat(today))[2]
    return legacy_readiness.check_readiness(conn, today=today)


def references(conn, pub):
    from sentinel.core.rolling_inputs import SnapshotReferences
    binding = snapshots._bound(conn, pub)
    rolling_store.verify_content(conn, binding["candidate_id"])
    return SnapshotReferences(conn, candidate_id=binding["candidate_id"], snapshot_id=binding["snapshot_id"])


def require_shadow_mode(pub, dual_mode):
    if is_rolling(pub) and not dual_mode:
        raise ExecutionInputsRefused("ROLLING_PAPER_REQUIRES_VERIFIED_SHADOW")


def marks(conn, pub, *, session, security_ids, tickers):
    refs = references(conn, pub)
    if str(session) != pub.window_end:
        raise ExecutionInputsRefused("ROLLING_MARKS_REQUIRE_CURRENT_DECISION")
    marks, symbols = {}, dict(tickers)
    with conn.cursor() as cur:
        cur.execute("SELECT security_id,ticker,close_unadjusted FROM sentinel_snapshot_bars "
                    "WHERE candidate_id=%s AND session=%s AND security_id=ANY(%s)",
                    (refs.candidate_id, session, list(security_ids)))
        for sid, ticker, close in cur.fetchall():
            if refs.resolver.resolve(str(ticker), str(session)) != str(sid):
                raise ExecutionInputsRefused("ROLLING_MARK_IDENTITY_CHANGED")
            marks[str(sid)] = Decimal(str(close))
            symbols[str(sid)] = str(ticker)
        cur.execute("SELECT bil_close_unadjusted FROM sentinel_snapshot_benchmarks "
                    "WHERE candidate_id=%s AND session=%s", (refs.candidate_id, session))
        row = cur.fetchone()
    if row is None or set(security_ids) - set(marks):
        raise ExecutionInputsRefused("ROLLING_EXECUTION_MARKS_MISSING")
    marks["SENTINEL:BIL"] = Decimal(str(row[0]))
    symbols["SENTINEL:BIL"] = "BIL"
    return marks, symbols


def resolver(conn, pub, *, session):
    from sentinel.feed import symbol_identity, source_aliases
    refs = references(conn, pub)
    requested = str(session)
    end = str(refs.manifest.window.end)
    if requested > end and requested != calendar.next_session(end):
        raise ExecutionInputsRefused("ROLLING_IDENTITY_BEYOND_NEXT_SESSION")
    rows = [dict(row) for row in refs.tickers]
    if requested > end:
        by_identity = {}
        for row in refs.tickers:
            by_identity.setdefault(row["permaticker"], []).append(row)
        for row in rows:
            competing = any(other["ticker"] != row["ticker"]
                and (not other.get("firstpricedate") or other["firstpricedate"] <= requested)
                and (not other.get("lastpricedate") or other["lastpricedate"] >= requested)
                for other in by_identity[row["permaticker"]])
            if row.get("isdelisted") == "N" and row.get("lastpricedate") == end and not competing:
                row["lastpricedate"] = requested
    validation_row = conn.execute("SELECT validation_sha256 FROM sentinel_snapshot_validations "
                                  "WHERE candidate_id=%s", (refs.candidate_id,)).fetchone()
    validation = rolling_store.load_evidence(conn, validation_row[0])
    projection = symbol_identity.SymbolProjection(rows, [p for _, p, _ in refs.actions],
        through=requested, alias_rejections=validation["alias_rejections"])
    source_aliases.require_current(projection, validation["alias_rejections"])
    future = projection.resolver()

    def resolve(symbol, as_of=None):
        effective = str(as_of or requested)
        if str(symbol).upper() == "BIL":
            return "SENTINEL:BIL"
        if effective > end and effective != requested:
            return None
        authority = future if effective == requested else refs.resolver
        return authority.resolve(str(symbol), effective)
    return resolve


def metadata(conn):
    pub = current(conn)
    if is_rolling(pub):
        return references(conn, pub).current_metadata()[0]
    from sentinel.core.loader import load_meta
    return load_meta(conn)
