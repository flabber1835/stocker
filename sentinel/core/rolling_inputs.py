"""Snapshot-native input material. No publication, shadow or trading authority."""
from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
from datetime import date

from stock_strategy_shared.wealth_core.feed import SecurityMeta, VendorBar

from sentinel.core.loader import CorpusWindow
from sentinel.core.spinoffs import map_distributions
from sentinel.core.session import FeedAnchor
from sentinel.core.terminal import SPINOFF_ACTIONS, map_terminal_rows
from sentinel.feed import (
    action_source, calendar, rolling_store, source_aliases, symbol_identity, tickers_authority,
)
from sentinel.feed.rolling_builder import NORMALIZATION_VERSION
from sentinel.feed.rolling_contract import CanonicalBenchmark
from sentinel.feed.requirements import PREFERRED_SESSIONS
from sentinel.feed.universe import listings_from_rows, parse_related_tickers


class RollingInputsRefused(RuntimeError):
    pass


@dataclass(frozen=True)
class ColdStartInputs:
    """Prospective warmup + one decision, deliberately without data_version.

    The operational caller must admit a real publication and a fresh durable
    state before constructing PublishedSession or persisting the canonical result.
    """

    snapshot_id: str
    reference_sha256: str
    session: str
    warmup: CorpusWindow
    bars: tuple[VendorBar, ...]
    meta: dict[str, SecurityMeta]
    sectors: dict[str, str | None]
    benchmarks: tuple[CanonicalBenchmark, ...]
    terminal_events: tuple
    spinoff_distributions: tuple
    feed_anchors: dict[str, FeedAnchor] = dataclass_field(default_factory=dict)


def fresh_anchors(bars, meta, known):
    """Only for proven inactive/fresh series, never retained economic state."""
    return {bar.security_id: FeedAnchor(bar.security_id, bar.ticker,
                meta[bar.security_id].issuer_key()[0] or f"S:{bar.security_id}", 1.0)
            for bar in bars if bar.security_id not in known}


class SnapshotReferences:
    def __init__(self, conn, *, candidate_id: str, snapshot_id: str):
        self.conn = conn
        self.candidate_id = candidate_id
        self.manifest = rolling_store.manifest(conn, candidate_id)
        if self.manifest.snapshot_id != snapshot_id:
            raise RollingInputsRefused("SNAPSHOT_ID_MISMATCH")
        if (self.manifest.normalization_version != NORMALIZATION_VERSION
                or self.manifest.calendar_version != calendar.calendar_version()):
            raise RollingInputsRefused("UNSUPPORTED_SNAPSHOT_SEMANTICS")
        reference = rolling_store.load_evidence(conn, self.manifest.reference_sha256)
        if (set(reference) != {"schema", "tickers", "actions"}
                or reference["schema"] != "sentinel.rolling-sharadar-references/1"
                or not isinstance(reference["tickers"], list)
                or not isinstance(reference["actions"], list)):
            raise RollingInputsRefused("UNSUPPORTED_REFERENCE_BUNDLE")
        with conn.cursor() as cur:
            cur.execute("SELECT validation_sha256 FROM sentinel_snapshot_validations "
                        "WHERE candidate_id=%s", (candidate_id,))
            row = cur.fetchone()
        validation = rolling_store.load_evidence(conn, row[0]) if row else {}
        if (validation.get("schema") != "sentinel.rolling-comparison-validation/1"
                or validation.get("scope") != "COMPARISON_ONLY"
                or validation.get("snapshot_id") != snapshot_id
                or not isinstance(validation.get("alias_rejections"), dict)):
            raise RollingInputsRefused("UNBOUND_REFERENCE_VALIDATION")
        self.tickers = tickers_authority.validate(reference["tickers"])
        self.actions = action_source.distinct_rows(reference["actions"])
        for _, payload, _ in self.actions:
            day = str(payload["date"])
            if (date.fromisoformat(day).isoformat() != day
                    or not "1900-01-01" <= day <= str(self.manifest.window.end)):
                raise RollingInputsRefused("ACTION_OUTSIDE_REFERENCE_INTERVAL")
        self.projection = symbol_identity.SymbolProjection(
            self.tickers, [payload for _, payload, _ in self.actions],
            through=str(self.manifest.window.end),
            alias_rejections=validation["alias_rejections"])
        source_aliases.require_current(self.projection, validation["alias_rejections"])
        self.resolver = self.projection.resolver()
        self.listings = {}
        for listing in listings_from_rows((*self.projection.rows, *self.projection.alias_rows)):
            self.listings.setdefault(listing.permaticker, []).append(listing)

    def current_metadata(self, *, session=None):
        """Observed reference metadata; never a historical decision timeline."""
        grouped = {}
        for row in self.tickers:
            grouped.setdefault(row["permaticker"], []).append(row)
        meta, sectors = {}, {}
        for sid, rows in sorted(grouped.items()):
            def unique(field, transform=lambda value: value):
                values = {transform(row[field]) for row in rows if row.get(field) is not None}
                if len(values) > 1:
                    raise RollingInputsRefused("CONFLICTING_REFERENCE_METADATA: " + sid + ":" + field)
                return next(iter(values)) if values else None

            category = unique("category")
            related = unique("relatedtickers", parse_related_tickers)
            sectors[sid] = unique("sector")
            session = str(session or self.manifest.window.end)
            active = {listing.ticker for listing in self.listings[sid] if listing.covers(session)}
            if sid in self.projection.chains:
                ticker = self.resolver.ticker_for_security(sid, session)
            else:
                ticker = next(iter(active)) if len(active) == 1 else None
                if ticker and self.resolver.resolve(ticker, session) != sid:
                    ticker = None
            # A terminated security still needs metadata for its terminal stream;
            # choose a stable retained label, never use it as identity authority.
            if ticker is None:
                if active:
                    raise RollingInputsRefused("AMBIGUOUS_REFERENCE_SYMBOL: " + sid)
                dated = [row for row in rows if not row.get("firstpricedate")
                         or row["firstpricedate"] <= session]
                ticker = sorted(dated or rows, key=lambda row: (
                    row.get("lastpricedate") or "", row["ticker"]))[-1]["ticker"]
            first = min((row["firstpricedate"] for row in rows if row.get("firstpricedate")), default=None)
            meta[sid] = SecurityMeta(security_id=sid, ticker=ticker, category=category,
                                     permaticker=sid, related_tickers=related or (), first_session=first)
        return meta, sectors

    def terminals(self, *, start: str, end: str):
        lo, hi = calendar.action_date_window(start, end)
        rows = [(source, p["ticker"], p["date"], p["action"], p["value"],
                 p["contraticker"], p["contraname"]) for source, p, _ in self.actions
                if lo <= p["date"] <= hi]
        result = map_terminal_rows(
            sorted(rows, key=lambda row: (row[2], row[1], row[3], row[0])),
            start=start, end=end, resolve_with_reason=self.resolver.resolve_with_reason)
        if (result.unresolved or not result.conservation_holds()
                or not result.normalized_stream_holds()):
            raise RollingInputsRefused("UNRESOLVED_SNAPSHOT_TERMINALS")
        return result

    def distributions(self, *, session: str):
        lo, hi = calendar.action_date_window(session, session)
        rows = [(p["date"], p["ticker"], p["contraticker"], source, p["value"])
                for source, p, _ in self.actions if lo <= p["date"] <= hi
                and str(p["action"]).lower() in SPINOFF_ACTIONS]
        return map_distributions(sorted(rows, key=lambda row: (row[0], row[3])), session=session,
                                 resolve_with_reason=self.resolver.resolve_with_reason)


def _snapshot_context(conn, candidate_id, snapshot_id):
    refs = SnapshotReferences(conn, candidate_id=candidate_id, snapshot_id=snapshot_id)
    rolling_store.verify_content(conn, candidate_id)
    session = str(refs.manifest.window.end)
    axis = calendar.previous_sessions(session, PREFERRED_SESSIONS + 1)
    warm = axis[:-1]
    if len(warm) != PREFERRED_SESSIONS or not set(axis).issubset(map(str, refs.manifest.window.sessions)):
        raise RollingInputsRefused("COLD_START_WINDOW_UNAVAILABLE")
    meta, sectors = refs.current_metadata()
    return refs, session, axis, warm, meta, sectors


def _mapped_bars(conn, candidate_id, refs, meta, first):
    for row in rolling_store.read_bars(conn, candidate_id):
        day = str(row.session)
        if day < first:
            continue
        if (row.security_id not in meta
                or refs.resolver.resolve(row.ticker, day) != row.security_id):
            raise RollingInputsRefused("SNAPSHOT_BAR_REFERENCE_MISMATCH")
        yield VendorBar(
            session=day, security_id=row.security_id, ticker=row.ticker,
            raw_close=row.close_unadjusted, raw_open=row.open_unadjusted,
            volume=row.volume, split_ratio=row.split_ratio,
            dividend_per_share=row.dividend_per_share,
            tradeable=bool(row.close_unadjusted and row.volume), signal_close=row.close_signal)


def _benchmarks(conn, candidate_id, session):
    benchmark_axis = calendar.previous_sessions(session, 254)
    benchmarks = tuple(row for row in rolling_store.read_benchmarks(conn, candidate_id)
                       if str(row.session) >= benchmark_axis[0])
    if [str(row.session) for row in benchmarks] != benchmark_axis:
        raise RollingInputsRefused("COLD_START_BENCHMARK_GAP")
    return benchmarks


def cold_start_inputs(conn, *, candidate_id: str, snapshot_id: str) -> ColdStartInputs:
    """Materialize verified strategy inputs; compact status uses readiness_inputs."""
    refs, session, axis, warm, meta, sectors = _snapshot_context(conn, candidate_id, snapshot_id)
    by_session = {}
    for bar in _mapped_bars(conn, candidate_id, refs, meta, warm[0]):
        by_session.setdefault(bar.session, []).append(bar)
    if sorted(by_session) != axis:
        raise RollingInputsRefused("COLD_START_PRICE_GAP")
    known = {bar.security_id for day in warm for bar in by_session[day]}
    benchmarks = _benchmarks(conn, candidate_id, session)
    window = CorpusWindow(warm, {day: by_session[day] for day in warm}, meta)
    window.median5_spy_closes = {str(row.session): row.spy_total_return for row in benchmarks
                                if str(row.session) in warm}
    terminals = refs.terminals(start=warm[0], end=session)
    window.median5_terminals = {}
    for event in terminals.events:
        window.median5_terminals.setdefault(event.session, set()).add(event.security_id)
    return ColdStartInputs(
        snapshot_id, refs.manifest.reference_sha256, session, window,
        tuple(by_session[session]), meta, sectors, benchmarks,
        tuple(event for event in terminals.events if event.session == session),
        refs.distributions(session=session), fresh_anchors(by_session[session], meta, known))


READINESS_DOMAINS = ("signal_close", "raw_close", "raw_open", "volume")


@dataclass
class ReadinessInputs:
    """Read-only counts, never a strategy input or persisted authority."""
    session: str
    warmup_sessions: list[str]
    benchmarks: tuple[CanonicalBenchmark, ...]
    related_issuers: bool
    counts: dict[str, int] = dataclass_field(default_factory=dict)
    frontier_positive: dict[str, int] = dataclass_field(
        default_factory=lambda: dict.fromkeys(READINESS_DOMAINS, 0))
    warmup_positive: dict[str, int] = dataclass_field(
        default_factory=lambda: dict.fromkeys(READINESS_DOMAINS, 0))

    def observe(self, bar):
        self.counts[bar.session] = self.counts.get(bar.session, 0) + 1
        positive = self.frontier_positive if bar.session == self.session else self.warmup_positive
        for name in READINESS_DOMAINS:
            value = getattr(bar, name)
            positive[name] += value is not None and value > 0


def summarize_readiness(material):
    summary = ReadinessInputs(material.session, material.warmup.sessions,
                              material.benchmarks, any(m.related_tickers for m in material.meta.values()))
    for day in material.warmup.sessions:
        for bar in material.warmup.bars_by_session[day]:
            summary.observe(bar)
    for bar in material.bars:
        summary.observe(bar)
    return summary


def readiness_inputs(conn, *, candidate_id: str, snapshot_id: str) -> ReadinessInputs:
    refs, session, axis, warm, meta, _sectors = _snapshot_context(conn, candidate_id, snapshot_id)
    summary = ReadinessInputs(session, warm, _benchmarks(conn, candidate_id, session),
                              any(m.related_tickers for m in meta.values()))
    for bar in _mapped_bars(conn, candidate_id, refs, meta, warm[0]):
        summary.observe(bar)
    if sorted(summary.counts) != axis:
        raise RollingInputsRefused("COLD_START_PRICE_GAP")
    # Counts are insufficient evidence for dated action/reference closure.
    refs.terminals(start=warm[0], end=session)
    refs.distributions(session=session)
    return summary
