"""Evidence-bound source aliases and effective-dated transport labels.

This projection never edits vendor rows or infers a permanent identity. See
docs/decisions/sentinel-source-recovery.md for the intentionally narrow join.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import datetime as dt
import hashlib
import json
from typing import Iterable, Mapping

from sentinel.feed import action_source, calendar, universe, symbol_lineage

RENAME_TYPES = ("tickerchangeto", "tickerchangefrom")
SCHEMA = "sentinel.symbol-identity/2"
Claim = tuple[str, str, str]  # source date, primary ticker, contraticker


@dataclass(frozen=True)
class Rename:
    date: str
    old: str
    new: str
    source_ids: tuple[str, ...]


@dataclass
class _Pair:
    source_ids: set[str] = field(default_factory=set)
    from_claims: set[Claim] = field(default_factory=set)
    to_claims: set[Claim] = field(default_factory=set)


def _pair_claims(changes_from: dict[Claim, set[str]], changes_to: dict[Claim, set[str]]):
    """Pair source claims before interpreting their restated primary labels."""
    to_groups: dict[tuple[str, str], list[Claim]] = {}
    for claim in changes_to:
        to_groups.setdefault(claim[:2], []).append(claim)
    pairs: dict[tuple[str, str, str], _Pair] = {}

    def add(from_claim, to_claim):
        day, _, old = from_claim
        new = to_claim[2]
        if old == new:
            return
        pair = pairs.setdefault((day, old, new), _Pair())
        pair.from_claims.add(from_claim)
        pair.to_claims.add(to_claim)
        pair.source_ids.update(changes_from[from_claim] | changes_to[to_claim])

    for from_claim in changes_from:
        day, primary, old = from_claim
        # Sharadar can restate BOTH primary labels, including older events.
        # The contra fields carry the event's old/new symbols in this form.
        for to_claim in to_groups.get((day, primary), ()):
            add(from_claim, to_claim)
        # Also retain the reciprocal form: NEW/from/OLD + OLD/to/NEW.
        reciprocal = (day, old, primary)
        if reciprocal in changes_to:
            add(from_claim, reciprocal)
    return pairs


class SymbolProjection:
    def __init__(self, rows: Iterable[Mapping], actions: Iterable[Mapping], *, through: str):
        self.rows = tuple(dict(row) for row in rows)
        self.through = dt.date.fromisoformat(str(through)).isoformat()
        changes_from: dict[Claim, set[str]] = {}
        changes_to: dict[Claim, set[str]] = {}
        for row in actions:
            kind = str(row.get("action") or "").lower()
            if kind not in RENAME_TYPES:
                continue
            day = dt.date.fromisoformat(str(row.get("date"))).isoformat()
            if day > self.through:
                continue
            ticker = str(row.get("ticker") or "").strip().upper()
            contra = str(row.get("contraticker") or "").strip().upper()
            if not ticker or not contra or "N/A" in {ticker, contra}:
                continue
            selected = changes_to if kind == "tickerchangeto" else changes_from
            selected.setdefault((day, ticker, contra), set()).add(
                action_source.source_row_id(row))
        pairs = _pair_claims(changes_from, changes_to)
        edges = [Rename(day, old, new, tuple(sorted(pair.source_ids)))
                 for (day, old, new), pair in pairs.items()]
        claim_index: dict[str, set[tuple[str, str, str]]] = {}
        for claim in changes_from:
            for symbol in claim[1:]:
                claim_index.setdefault(symbol, set()).add(claim)
        to_claim_index: dict[str, set[tuple[str, str, str]]] = {}
        for claim in changes_to:
            for symbol in claim[1:]:
                to_claim_index.setdefault(symbol, set()).add(claim)
        anchors: dict[str, list[dict]] = {}
        for row in self.rows:
            if str(row.get("table") or "SEP").upper() == "SEP":
                anchors.setdefault(str(row.get("ticker") or "").upper(), []).append(row)
        self.chains: dict[str, tuple[Rename, ...]] = {}
        self.alias_rows: list[dict] = []
        self.rejections: list[dict] = []
        occurrences = symbol_lineage.Occurrences(edges, through=self.through)
        for chain in occurrences.paths():
            component = {symbol for edge in chain for symbol in (edge.old, edge.new)}
            context = sorted((row for symbol in component for row in anchors.get(symbol, ())),
                             key=lambda row: json.dumps(row, sort_keys=True, default=str))
            def refuse(reason):
                self.rejections.append({"reason_code": reason, "symbols": sorted(component),
                    "anchors": [{key: row.get(key) for key in (
                        "ticker", "permaticker", "category", "firstpricedate", "lastpricedate")}
                        for row in context],
                    "source_ids": sorted({sid for edge in chain for sid in edge.source_ids})})
            # Every node has at most one predecessor/successor, and dates are
            # strictly increasing within this occurrence. Branches and cycles
            # grant no alias; separate dated occurrences may reuse a spelling.
            if (len(chain) != len(component) - 1
                    or len({edge.old for edge in chain}) != len(chain)
                    or len({edge.new for edge in chain}) != len(chain)
                    or any(a.new != b.old or a.date >= b.date
                           for a, b in zip(chain, chain[1:]))):
                refuse("RENAME_PATH_AMBIGUOUS")
                continue
            windows = occurrences.windows(chain)
            claims = {claim for symbol in component for claim in claim_index.get(symbol, ())
                      if symbol_lineage.touches(claim, windows, chain[-1].new)}
            to_claims = {claim for symbol in component for claim in to_claim_index.get(symbol, ())
                         if symbol_lineage.touches(claim, windows, chain[-1].new)}
            chain_pairs = [pairs[(edge.date, edge.old, edge.new)] for edge in chain]
            # Do not discard an unpaired or conflicting older source claim to
            # salvage a more recent pair from the same identity component.
            if (claims != set().union(*(pair.from_claims for pair in chain_pairs))
                    or to_claims != set().union(*(pair.to_claims for pair in chain_pairs))):
                refuse("RENAME_CLAIMS_INCOMPLETE_OR_COMPETING")
                continue
            successors = {edge.new: index for index, edge in enumerate(chain)}
            # A restated primary must be this event's successor or a later one
            # in the same proven chain, never an unrelated or earlier label.
            if any(successors.get(claim[1], -1) < index
                   for index, pair in enumerate(chain_pairs) for claim in pair.from_claims):
                refuse("RENAME_PRIMARY_OUTSIDE_PATH")
                continue
            source = [row for row in context
                      if occurrences.anchor_applies(row, windows[str(row["ticker"]).upper()])]
            identities = {str(row.get("permaticker") or "").strip() for row in source}
            categories = {row.get("category") for row in source}
            if len(identities) != 1 or "" in identities or len(categories) != 1:
                refuse("RENAME_ANCHOR_IDENTITY_OR_CATEGORY_AMBIGUOUS")
                continue
            if not all(row.get("firstpricedate") and row.get("lastpricedate") for row in source):
                refuse("RENAME_ANCHOR_INTERVAL_MISSING")
                continue
            first = min(str(row["firstpricedate"]) for row in source)
            last = max(str(row["lastpricedate"]) for row in source)
            if first > chain[-1].date or last < chain[0].date:
                # Permit exactly the active predecessor -> next-session rename
                # seam, never an arbitrary gap in a stale listing interval.
                prior = calendar.previous_sessions(chain[0].date, 2)
                if (len(prior) != 2 or prior[-1] != chain[0].date
                        or last != prior[0] or first > last
                        or not all(universe._delisted_observation(row) is False
                                   for row in source)):
                    refuse("RENAME_ANCHOR_INTERVAL_UNSUPPORTED")
                    continue
            latest = chain[-1]
            if latest.new not in anchors:
                anchored = [edge for edge in chain if edge.old in anchors]
                predecessor_edge = anchored[-1] if anchored else latest
                prior = calendar.previous_sessions(latest.date, 2)
                predecessor = [row for row in source if row.get("ticker") == predecessor_edge.old]
                if (len(prior) != 2 or not predecessor
                        or not all(universe._delisted_observation(row) is False
                                   for row in predecessor)
                        or last not in {prior[0], latest.date, self.through}):
                    refuse("RENAME_ACTIVE_PREDECESSOR_UNPROVEN")
                    continue
                last = max(last, self.through)
            identity = next(iter(identities))
            # Never combine two disjoint rename chains anchored to one id.
            if identity in self.chains:
                self.alias_rows = [r for r in self.alias_rows if str(r["permaticker"]) != identity]
                self.chains[identity] = ()
                refuse("RENAME_IDENTITY_HAS_DISJOINT_PATHS")
                continue
            self.chains[identity] = tuple(chain)
            anchor = min(source, key=lambda row: str(row.get("ticker")))
            for symbol in sorted(component):
                start, end = occurrences.alias_interval(
                    symbol, windows[symbol], first, last,
                    rows=anchors.get(symbol, ()), identity=identity)
                if start <= end:
                    self.alias_rows.append(dict(anchor, ticker=symbol,
                                                firstpricedate=start, lastpricedate=end))
        self.chains = {key: value for key, value in self.chains.items() if value}

    def explain(self, *, symbols=(), identities=()):
        wanted, keys = set(symbols), set(identities)
        selected = [item for item in self.rejections
                    if wanted.intersection(item["symbols"]) or any(
                        str(row.get("permaticker")) in keys for row in item["anchors"])]
        return {"schema": SCHEMA, "rejections_total": len(selected),
                "rejections": [dict(item, symbols=item["symbols"][:16],
                                    anchors=item["anchors"][:8], source_ids=item["source_ids"][:16])
                               for item in selected[:8]],
                "sha256": hashlib.sha256(json.dumps(selected, sort_keys=True,
                                                     default=str).encode()).hexdigest()}

    @property
    def evidence(self) -> dict:
        return {"schema": SCHEMA, "through": self.through,
                "aliases": [{key: row[key] for key in (
                    "permaticker", "ticker", "firstpricedate", "lastpricedate")}
                    for row in sorted(self.alias_rows, key=lambda r: (str(r["permaticker"]), r["ticker"]))],
                "renames": [{"permaticker": sid, "date": edge.date,
                             "old": edge.old, "new": edge.new,
                             "source_ids": list(edge.source_ids)}
                            for sid, chain in sorted(self.chains.items()) for edge in chain]}

    def digest(self, tickers_digest: str) -> str:
        if not self.chains:
            return tickers_digest
        return hashlib.sha256(json.dumps(
            {"tickers": tickers_digest, **self.evidence},
            sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def resolver(self) -> universe.IdentityResolver:
        return _SymbolResolver(self)


class _SymbolResolver(universe.IdentityResolver):
    def __init__(self, projection: SymbolProjection):
        super().__init__(universe.listings_from_rows((*projection.rows, *projection.alias_rows)))
        self.projection = projection

    def ticker_for_security(self, security_id: str, session: str):
        chain = self.projection.chains.get(str(security_id))
        if not chain:
            return super().ticker_for_security(security_id, session)
        label = chain[0].old
        for edge in chain:
            if edge.date <= session:
                label = edge.new
        return label if self.resolve(label, session) == str(security_id) else None


__all__ = ["RENAME_TYPES", "SCHEMA", "SymbolProjection"]


def stable_rename_rows(fetch, *, through: str) -> list[dict]:
    """A small identity-only preflight, never publication permission."""
    from sentinel.feed import authority, sharadar
    params = {"action": ",".join(RENAME_TYPES), "date.gte": "1900-01-01", "date.lte": through}
    first = list(fetch(sharadar.ACTIONS, params))
    second = list(fetch(sharadar.ACTIONS, params))
    authority.require_stable(sharadar.ACTIONS, authority.observe_actions(first),
                             authority.observe_actions(second))
    return second


def require_published_history(conn, rows, *, before: str) -> None:
    """Daily replay cannot acquire rename authority outside its fetched window."""
    from sentinel.feed import actions
    end = (dt.date.fromisoformat(before) - dt.timedelta(days=1)).isoformat()
    published = actions.active_rows(conn, start="1900-01-01", end=end,
                                    action_types=RENAME_TYPES)

    def claims(source):
        return {(str(row["date"]), str(row["action"]), str(row["ticker"]),
                 str(row.get("contraticker") or "")) for row in source
                if row.get("action") in RENAME_TYPES and str(row["date"]) < before}

    if claims(rows) != claims(published):
        raise universe.HistoricalIdentityMutation(
            "historical ACTIONS rename claims changed before the daily window; "
            "a complete retained source replay is required")
