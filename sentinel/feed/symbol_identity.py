"""Evidence-bound source aliases and effective-dated transport labels.

This projection never edits vendor rows or infers a permanent identity. See
docs/decisions/sentinel-source-recovery.md for the intentionally narrow join.
"""
from __future__ import annotations

from dataclasses import dataclass
import datetime as dt
import hashlib
import json
from typing import Iterable, Mapping

from sentinel.feed import action_source, calendar, universe

RENAME_TYPES = ("tickerchangeto", "tickerchangefrom")
SCHEMA = "sentinel.symbol-identity/1"


@dataclass(frozen=True)
class Rename:
    date: str
    old: str
    new: str
    source_ids: tuple[str, ...]


class SymbolProjection:
    def __init__(self, rows: Iterable[Mapping], actions: Iterable[Mapping], *, through: str):
        self.rows = tuple(dict(row) for row in rows)
        self.through = dt.date.fromisoformat(str(through)).isoformat()
        changes_from: dict[tuple[str, str, str], set[str]] = {}
        changes_to: dict[tuple[str, str, str], set[str]] = {}
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
            old, new = (ticker, contra) if kind == "tickerchangeto" else (contra, ticker)
            selected = changes_to if kind == "tickerchangeto" else changes_from
            selected.setdefault((day, old, new), set()).add(
                action_source.source_row_id(row))
        edges = []
        for (day, old, new), source_ids in changes_from.items():
            other = changes_to.get((day, old, new), set()) | changes_to.get((day, new, new), set())
            if old != new and other:
                edges.append(Rename(day, old, new, tuple(sorted(source_ids | other))))
        adjacency: dict[str, set[str]] = {}
        by_old: dict[str, list[Rename]] = {}
        for edge in edges:
            adjacency.setdefault(edge.old, set()).add(edge.new)
            adjacency.setdefault(edge.new, set()).add(edge.old)
            by_old.setdefault(edge.old, []).append(edge)
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
        remaining = set(adjacency)
        while remaining:
            pending, component = [min(remaining)], set()
            while pending:
                symbol = pending.pop()
                if symbol not in component:
                    component.add(symbol)
                    pending.extend(adjacency[symbol] - component)
            remaining -= component
            chain = sorted((edge for symbol in component for edge in by_old.get(symbol, ())),
                           key=lambda edge: (edge.date, edge.old, edge.new))
            claims = set().union(*(claim_index.get(symbol, set()) for symbol in component))
            to_claims = set().union(*(to_claim_index.get(symbol, set()) for symbol in component))
            permitted_to = {(edge.date, edge.old, edge.new) for edge in chain}
            permitted_to.update((edge.date, edge.new, edge.new) for edge in chain)
            # Every node has at most one predecessor/successor, and dates are
            # strictly increasing. Reuse, branches and cycles grant no alias.
            if (claims != {(edge.date, edge.old, edge.new) for edge in chain}
                    or not to_claims <= permitted_to
                    or len(chain) != len(component) - 1
                    or len({edge.old for edge in chain}) != len(chain)
                    or len({edge.new for edge in chain}) != len(chain)
                    or any(a.new != b.old or a.date >= b.date
                           for a, b in zip(chain, chain[1:]))):
                continue
            source = [row for symbol in component for row in anchors.get(symbol, ())]
            identities = {str(row.get("permaticker") or "").strip() for row in source}
            categories = {row.get("category") for row in source}
            if len(identities) != 1 or "" in identities or len(categories) != 1:
                continue
            if not all(row.get("firstpricedate") and row.get("lastpricedate") for row in source):
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
                    continue
            latest = chain[-1]
            if latest.new not in anchors:
                anchored = [edge for edge in chain if edge.old in anchors]
                predecessor_edge = anchored[-1] if anchored else latest
                prior = calendar.previous_sessions(predecessor_edge.date, 2)
                predecessor = [row for row in source if row.get("ticker") == predecessor_edge.old]
                if (len(prior) != 2 or not predecessor
                        or not all(universe._delisted_observation(row) is False
                                   for row in predecessor)
                        or last not in {prior[0], predecessor_edge.date, self.through}):
                    continue
                last = max(last, self.through)
            identity = next(iter(identities))
            # Never combine two disjoint rename chains anchored to one id.
            if identity in self.chains:
                self.alias_rows = [r for r in self.alias_rows if str(r["permaticker"]) != identity]
                self.chains[identity] = ()
                continue
            self.chains[identity] = tuple(chain)
            anchor = min(source, key=lambda row: str(row.get("ticker")))
            for symbol in sorted(component):
                self.alias_rows.append(dict(anchor, ticker=symbol,
                                            firstpricedate=first, lastpricedate=last))
        self.chains = {key: value for key, value in self.chains.items() if value}

    @property
    def evidence(self) -> dict:
        return {"schema": SCHEMA, "through": self.through,
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
