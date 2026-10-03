"""Retained Alpaca/Nasdaq inputs for GO and daily rolling candidates."""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sentinel.feed import calendar, progress, rolling_jobs as jobs
from sentinel.feed.acquisition_parts import Parts
from sentinel.feed.alpaca_nasdaq import DIRECTORY_URLS, parse_directory, select_assets
from sentinel.feed.alpaca_observation import (
    action_participants, action_symbols, cash_dividend, paired_month,
    structural_action_date,
)
from sentinel.feed.alpaca_transport import (
    ACTION_URL, ASSETS, BAR_URL, AlpacaTransportRefused, Client,
)
from sentinel.feed.operational_source import _months
from sentinel.feed.rolling_contract import digest

SOURCE = "sentinel.alpaca-nasdaq-operational-source/1"
_NY = ZoneInfo("America/New_York")


def _bounds(first: str, last: str):
    start = datetime.fromisoformat(first + "T00:00:00").replace(tzinfo=_NY)
    # Daily bars are labelled at New York midnight; end is inclusive. Asking
    # for day-end reaches unavailable recent SIP data during source-final runs.
    end = datetime.fromisoformat(last + "T00:00:00").replace(tzinfo=_NY)
    return start.isoformat(), end.isoformat()


def _groups(values, size=400):
    ordered = sorted(values)
    for offset in range(0, len(ordered), size):
        yield ordered[offset:offset + size]


def _merged(pages, *, symbols):
    result = {}
    proofs = []
    for bars, proof in pages:
        proofs.append(proof)
        for symbol, records in bars.items():
            if symbol not in symbols or not isinstance(records, list):
                raise AlpacaTransportRefused("unexpected symbol in Alpaca bars")
            result.setdefault(symbol, []).extend(records)
    return result, proofs


class AlpacaSource:
    provider = "ALPACA_NASDAQ"

    def __init__(self, window, conn, lease, *, client=None, verify_during_coverage=False):
        self.window, self.conn, self.lease = window, conn, lease
        self.client = client or Client()
        self.parts = Parts(conn, lease)
        self.verify_during_coverage = verify_during_coverage
        self.price_manifests = {}
        self.evidence = []
        self.selected = []
        self.action_affected = frozenset()
        self.reset_after = {}
        self.action_evidence = {}
        self.dividends = []
        self.pair_absent = set()
        self.sfp = []
        self.tickers = []
        self.actions = []
        self.months = []

    def preflight(self):
        if str(self.window.end) > calendar.latest_closed_session():
            raise AlpacaTransportRefused("Alpaca GO target is not a closed XNYS session")
        self.months = list(_months(str(self.window.start), str(self.window.end)))

    def _part(self, component, generation, acquire, checkpoint):
        with self.parts.unit():
            retained = self.parts.get(component, generation,
                                      defer_prices=self.verify_during_coverage
                                      and component.startswith("SEP."))
            if retained is None:
                progress.emit("source_download", "started", table=component.split(".")[0],
                              reason="ACQUIRE_MISSING_PART", job_id=self.lease.job_id)
                payload, prices, evidence, rows = acquire()
                retained = self.parts.put(component, generation, payload=payload,
                                          prices=prices, evidence=evidence, rows=rows)
                reason = "PART_COMMITTED"
            else:
                reason = "RETAINED_PART_REUSED"
            manifest, payload = retained
            if component.startswith("SEP.") and self.verify_during_coverage:
                self.price_manifests[digest(manifest)] = manifest
            self.evidence.append({"component": component,
                                  "content_sha256": manifest["content_sha256"],
                                  "rows": manifest["rows"],
                                  "evidence": manifest["evidence"]})
            checkpoint(component, generation, manifest["content_sha256"],
                       manifest["rows"], 0)
            progress.emit("source_replay", "completed", table=component.split(".")[0],
                          reason=reason, rows=manifest["rows"], job_id=self.lease.job_id)
            return payload

    def _references(self):
        assets, asset_proof = self.client.get(ASSETS, {"status": "active", "asset_class": "us_equity"})
        if not isinstance(assets, list) or not assets:
            raise AlpacaTransportRefused("Alpaca asset inventory is absent")
        listed_text, listed_proof = self.client.get(DIRECTORY_URLS[0], text=True)
        other_text, other_proof = self.client.get(DIRECTORY_URLS[1], text=True)
        listed = parse_directory(listed_text, name="nasdaqlisted")
        other = parse_directory(other_text, name="otherlisted")
        selected, selection = select_assets(assets, listed, other)
        payload = {"selected": selected, "selection": selection,
                   "assets": assets, "nasdaqlisted": listed, "otherlisted": other}
        proof = {"assets": asset_proof, "nasdaqlisted": listed_proof,
                 "otherlisted": other_proof}
        return payload, None, proof, len(selected)

    def _action_rows(self):
        start = (self.window.start - timedelta(days=365)).isoformat()
        end = str(self.window.end)
        params = {"start": start, "end": end, "limit": 1000,
                  "data_quality": "all", "sort": "asc"}
        seen, proofs = {}, []
        affected = set()
        reset_after = {}
        dividends = []
        by_type = Counter()
        selected = {row["ticker"] for row in self.selected}
        axis = {str(day) for day in self.window.sessions}
        for page, proof in self.client.pages(ACTION_URL, params, key="corporate_actions"):
            proofs.append(proof)
            action_symbols([page], start=start, end=end)
            for kind, records in page.items():
                for record in records:
                    identity = digest({"type": kind, "record": record})
                    before = seen.get(record["id"])
                    if before is not None and before != identity:
                        raise AlpacaTransportRefused("corporate action changed across pages")
                    if before is None:
                        seen[record["id"]] = identity
                        by_type[kind] += 1
                        involved = action_participants(record) & selected
                        if not involved:
                            continue
                        if kind == "cash_dividends":
                            try:
                                event = cash_dividend(record, axis=axis)
                            except AlpacaTransportRefused:
                                affected.update(involved)
                                continue
                            if event is not None:
                                dividends.append(event)
                        else:
                            economic_date = structural_action_date(kind, record)
                            if economic_date is None or economic_date > str(self.window.end):
                                affected.update(involved)
                            elif economic_date >= str(self.window.start):
                                for symbol in involved:
                                    reset_after[symbol] = max(
                                        economic_date, reset_after.get(symbol, ""))
        dividends = sorted((item for item in dividends
                            if item["ticker"] not in affected),
                           key=lambda item: (item["date"], item["ticker"], item["id"]))
        summary = {"actions": len(seen), "by_type": dict(sorted(by_type.items())),
                   "affected_selected_symbols": len(affected),
                   "post_event_reset_symbols": len(reset_after),
                   "cash_dividend_rows": len(dividends)}
        return {"affected": sorted(affected), "reset_after": reset_after,
                "dividends": dividends,
                "summary": summary}, None, \
            {"pages": proofs}, len(seen)

    def _bars(self, symbols, first, last, adjustment):
        start, end = _bounds(first, last)
        result, proofs = {}, []
        for group in _groups(symbols):
            params = {"symbols": ",".join(group), "timeframe": "1Day",
                      "start": start, "end": end, "limit": 10000,
                      "feed": "sip", "adjustment": adjustment,
                      "asof": str(self.window.end), "sort": "asc"}
            bars, evidence = _merged(self.client.pages(BAR_URL, params, key="bars"),
                                     symbols=set(group))
            proofs.extend(evidence)
            result.update(bars)
            jobs.heartbeat(self.conn, self.lease, lease_seconds=600)
        return result, proofs

    def _benchmark_rows(self):
        first, last = str(self.window.start), str(self.window.end)
        symbols, sessions = {"SPY", "BIL"}, {str(day) for day in self.window.sessions}
        raw, raw_proofs = self._bars(symbols, first, last, "raw")
        adjusted, adjusted_proofs = self._bars(symbols, first, last, "all")
        paired, absent = paired_month(raw, adjusted, symbols=symbols, sessions=sessions)
        if absent or {(row["ticker"], row["date"]) for row in paired} != {
                (symbol, day) for symbol in symbols for day in sessions}:
            raise AlpacaTransportRefused("SPY/BIL lack exact paired daily coverage")
        rows = [{"date": row["date"], "ticker": row["ticker"],
                 "open": row["open"], "close": row["close"],
                 "closeunadj": row["closeunadj"], "closeadj": row["adjusted_close"]}
                for row in paired]
        return rows, None, {"raw": raw_proofs, "all": adjusted_proofs}, len(rows)

    def references(self, checkpoint):
        base = {"provider": self.provider, "target": str(self.window.end)}
        refs = self._part("TICKERS", {**base, "component": "assets-and-directories"},
                          self._references, checkpoint)
        self.selected = refs["selected"]
        actions = self._part("ACTIONS", {**base, "component": "actions",
                                          "start": (self.window.start - timedelta(days=365)).isoformat()},
                             self._action_rows, checkpoint)
        self.action_affected = frozenset(actions["affected"])
        self.reset_after = actions["reset_after"]
        self.action_evidence = actions["summary"]
        self.dividends = actions["dividends"]
        self.sfp = self._part("SFP", {**base, "component": "benchmarks",
                                      "window": self.window.model_dump(mode="json")},
                              self._benchmark_rows, checkpoint)

    def acquire_prices(self, checkpoint, pulse):
        safe_symbols = {row["ticker"] for row in self.selected} - self.action_affected
        if not safe_symbols:
            raise AlpacaTransportRefused("no candidate securities remain after action quarantine")
        for number, (lo, hi) in enumerate(self.months, 1):
            component = f"SEP.{lo}.{hi}"
            generation = {"provider": self.provider, "component": component,
                          "selection_sha256": digest(self.selected),
                          "actions_sha256": digest({"affected": sorted(self.action_affected),
                                                    "reset_after": self.reset_after}),
                          "asof": str(self.window.end)}
            def acquire():
                raw, raw_proofs = self._bars(safe_symbols, lo, hi, "raw")
                adjusted, adjusted_proofs = self._bars(safe_symbols, lo, hi, "split")
                sessions = {str(day) for day in self.window.sessions if lo <= str(day) <= hi}
                rows, absent = paired_month(raw, adjusted, symbols=safe_symbols,
                                            sessions=sessions)
                return {"pair_absent": [list(key) for key in sorted(absent)]}, rows, \
                    {"raw": raw_proofs, "split": adjusted_proofs}, len(rows)
            payload = self._part(component, generation, acquire, checkpoint)
            self.pair_absent.update(tuple(key) for key in payload["pair_absent"])
            progress.emit("source_replay", "working", table="SEP", part=number,
                          parts=len(self.months), job_id=self.lease.job_id)
            pulse()

    def corroborate(self):
        # Reobserve current admission metadata and actions after the long price
        # acquisition. A changed provider view cannot certify this candidate.
        newer, *_ = self._references()
        if newer["selected"] != self.selected:
            raise AlpacaTransportRefused("Alpaca/Nasdaq current universe changed during GO")
        actions, *_ = self._action_rows()
        if (frozenset(actions["affected"]) != self.action_affected
                or actions["reset_after"] != self.reset_after
                or actions["dividends"] != self.dividends):
            raise AlpacaTransportRefused("Alpaca action participants changed during GO")

    def reference_payload(self):
        admitted = {row["ticker"]: row["firstpricedate"] for row in self.tickers}
        actions = [{"date": day, "action": "dividend",
                    "ticker": symbol, "name": None,
                    "value": rate, "contraticker": None,
                    "contraname": None}
                   for (symbol, day), rate in sorted(self.dividend_totals(admitted).items())]
        return {"schema": "sentinel.rolling-alpaca-nasdaq-references/1",
                "tickers": self.tickers, "actions": actions}

    def dividend_totals(self, admitted):
        totals = {}
        for event in self.dividends:
            if event["ticker"] in admitted and event["date"] >= admitted[event["ticker"]]:
                key = (event["ticker"], event["date"])
                totals[key] = totals.get(key, Decimal(0)) + Decimal(event["rate"])
        return {key: format(value.normalize(), "f") for key, value in totals.items()}

    def source_payload(self):
        return {"schema": SOURCE, "provider": self.provider,
                "selected_count": len(self.selected),
                "admitted_count": len(self.tickers),
                "components": self.evidence, "sfp_sha256": digest(self.sfp),
                "selection_sha256": digest(self.selected),
                "action_quarantine": self.action_evidence,
                "post_event_reset_sha256": digest(self.reset_after),
                "dividends_sha256": digest(self.dividends)}
