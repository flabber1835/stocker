"""Dated occurrences of rename labels; no permanent identity is inferred here."""
from __future__ import annotations

import bisect
import datetime as dt


def adjacent_day(day, delta):
    return (dt.date.fromisoformat(day) + dt.timedelta(days=delta)).isoformat()


class Occurrences:
    def __init__(self, edges, *, through):
        self.through = through
        self.departures, self.arrivals = {}, {}
        for edge in edges:
            self.departures.setdefault(edge.old, []).append(edge)
            self.arrivals.setdefault(edge.new, []).append(edge)
        for index in (self.departures, self.arrivals):
            for rows in index.values():
                rows.sort(key=lambda e: (e.date, e.old, e.new))

    def paths(self):
        edges = {edge for rows in self.departures.values() for edge in rows}
        links = {edge: set() for edge in edges}

        def join(left, right):
            links[left].add(right)
            links[right].add(left)

        for edge in edges:
            # A ticker's next arrival starts a different occurrence. Never
            # connect across that arrival merely because the spelling matches.
            arrivals = [e.date for e in self.arrivals.get(edge.new, ())]
            next_i = bisect.bisect_right(arrivals, edge.date)
            boundary = arrivals[next_i] if next_i < len(arrivals) else None
            departures = self.departures.get(edge.new, ())
            dates = [e.date for e in departures]
            start = bisect.bisect_left(dates, edge.date)
            if start < len(dates) and (boundary is None or dates[start] < boundary):
                for following in departures[start:bisect.bisect_right(dates, dates[start])]:
                    join(edge, following)
            # Competing pairs on one date are one ambiguous occurrence.
            for competing in self.departures[edge.old]:
                if competing.date == edge.date:
                    join(edge, competing)
            for competing in self.arrivals[edge.new]:
                if competing.date == edge.date:
                    join(edge, competing)
        remaining = set(edges)
        while remaining:
            pending = [min(remaining, key=lambda e: (e.date, e.old, e.new))]
            component = set()
            while pending:
                edge = pending.pop()
                if edge not in component:
                    component.add(edge)
                    pending.extend(links[edge] - component)
            remaining -= component
            yield sorted(component, key=lambda e: (e.date, e.old, e.new))

    def windows(self, chain):
        previous = [e.date for e in self.departures[chain[0].old]
                    if e.date < chain[0].date]
        first = adjacent_day(max(previous), 1) if previous else "0001-01-01"
        result = {chain[0].old: (first, chain[0].date)}
        for index, edge in enumerate(chain):
            end = chain[index + 1].date if index + 1 < len(chain) else self.through
            result[edge.new] = (edge.date, end)
        return result

    def alias_interval(self, symbol, window, first, last, *, rows, identity):
        lo, hi = window
        # A later reuse ends this alias permanently; an old business cannot
        # reclaim it when the newer listing ends. Likewise do not back-project
        # a later business over a previous occurrence.
        for event in (*self.arrivals.get(symbol, ()), *self.departures.get(symbol, ())):
            if event.date > hi:
                last = min(last, adjacent_day(event.date, -1))
            elif event.date < lo:
                first = max(first, adjacent_day(event.date, 1))
        for row in rows:
            if str(row.get("permaticker")) == identity:
                continue
            start, end = row.get("firstpricedate"), row.get("lastpricedate")
            if start and str(start) > hi:
                last = min(last, adjacent_day(str(start), -1))
            elif end and str(end) < lo:
                first = max(first, adjacent_day(str(end), 1))
        return first, last

    def anchor_applies(self, row, window):
        if overlaps(row, window):
            return True
        first, last = row.get("firstpricedate"), row.get("lastpricedate")
        lo, hi = window
        if first and str(first) > hi:
            return False  # This occurrence explicitly departed before listing.
        # A pre-existing successor spelling is not proof of a separate older
        # business unless a prior departure actually bounds that occurrence.
        return not (last and str(last) < lo and any(
            e.date < lo for e in self.departures.get(str(row["ticker"]).upper(), ())))


def overlaps(row, window):
    first, last = row.get("firstpricedate"), row.get("lastpricedate")
    lo, hi = window
    # Missing bounds cannot prove that a competing listing is unrelated.
    return not ((first and str(first) > hi) or (last and str(last) < lo))


def touches(claim, windows, terminal):
    day, primary, contra = claim
    if primary == terminal:
        return True  # Restated primary binds even a very old unpaired claim.
    return any(symbol in windows and windows[symbol][0] <= day <= windows[symbol][1]
               for symbol in (primary, contra))
