"""Retained Alpaca/OpenFIGI inputs for GO and daily rolling candidates."""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from sentinel.feed import calendar, progress, rolling_jobs as jobs
from sentinel.feed.acquisition_parts import Parts
from sentinel.feed import openfigi
from sentinel.feed.alpaca_observation import (
    action_participants, action_symbols, cash_dividend, paired_month,
    structural_action_date, stock_split, bar_page_rows, admissible_history,
)
from sentinel.feed.alpaca_transport import (
    ACTION_URL, ASSETS, BAR_URL, AlpacaTransportRefused, Client,
)
from sentinel.feed.operational_source import _months
from sentinel.feed.rolling_contract import digest

SOURCE = "sentinel.alpaca-openfigi-operational-source/1"
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


def _today():
    return datetime.now(timezone.utc).date()


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
    provider = "ALPACA_OPENFIGI"

    def __init__(self, window, conn, lease, *, client=None, classifier=None, verify_during_coverage=False):
        self.window, self.conn, self.lease = window, conn, lease
        self.client = client or Client()
        self.classifier = classifier or openfigi.Client()
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
        self.splits = []
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

    def _inventory(self):
        assets, asset_proof = self.client.get(ASSETS, {"status": "active", "asset_class": "us_equity"})
        if not isinstance(assets, list) or not assets:
            raise AlpacaTransportRefused("Alpaca asset inventory is absent")
        values = openfigi.inventory(assets)
        return {"assets": values}, None, asset_proof, len(values)

    def _prior_classifications(self):
        from sentinel.feed import operational_snapshot
        current = operational_snapshot._current(self.conn)
        if current is None:
            return {}
        binding = operational_snapshot._bound(self.conn, current)
        row = self.conn.execute('SELECT part_id FROM sentinel_acquisition_bindings '
            'WHERE job_id=%s AND component=%s', (binding['job_id'], 'TICKERS')).fetchone()
        if row is None:
            return {}
        retained = self.parts._manifest(row[0])
        if retained is None or retained[0]['generation'].get('provider') != self.provider:
            return {}
        return retained[1].get('classifications', {})

    def _classified_references(self, base, checkpoint):
        captured = self._part('TICKERS.ASSETS', {**base, 'component': 'assets'},
                              self._inventory, checkpoint)
        self.assets = captured['assets']
        plan = self._part('TICKERS.PLAN', {**base, 'component':'classification-plan',
            'assets_sha256':digest(self.assets)}, self._classification_plan, checkpoint)
        observations, missing = dict(plan['observations']), plan['missing']
        size = plan['batch_size']
        for number, offset in enumerate(range(0, len(missing), size), 1):
            group = missing[offset:offset+size]
            def acquire(group=group):
                responses, proof = self.classifier.mapping(group)
                observed = datetime.fromisoformat(proof['observed_at']).astimezone(timezone.utc).date()
                values = {digest(asset): {'response': response, 'observed_day': str(observed)}
                          for asset, response in zip(group, responses, strict=True)}
                for asset, response in zip(group, responses, strict=True):
                    openfigi.classify(asset, response)
                return values, None, proof, len(group)
            values = self._part('TICKERS.FIGI.'+str(number),
                {**base, 'component': 'figi', 'assets_sha256': digest(group)}, acquire, checkpoint)
            observations.update(values)
            progress.emit('source_classification', 'working', rows=len(observations),
                          total=len(self.assets), job_id=self.lease.job_id)
        selected, selection = openfigi.select_assets(self.assets, observations)
        payload = {'selected': selected, 'selection': selection,
                   'assets': self.assets, 'classifications': observations}
        return self._part('TICKERS', {**base, 'component': 'assets-and-openfigi'},
            lambda: (payload, None, {'policy': openfigi.POLICY}, len(selected)), checkpoint)

    def _classification_plan(self):
        prior = self._prior_classifications()
        today = _today()
        observations, missing = {}, []
        for asset in self.assets:
            key = digest(asset)
            cached = prior.get(key)
            if cached:
                item, reason = openfigi.classify(asset, cached['response'])
                age = (today - date.fromisoformat(cached['observed_day'])).days
                if 0 <= age < (7 if item is not None or reason == 'non_ordinary_equity' else 1):
                    observations[key] = cached
                    continue
            missing.append(asset)
        return {'observations':observations, 'missing':missing,
                'batch_size':self.classifier.batch_size}, None, {'policy':openfigi.POLICY}, len(self.assets)

    def _action_rows(self):
        start = (self.window.start - timedelta(days=365)).isoformat()
        end = str(self.window.end)
        params = {"start": start, "end": end, "limit": 1000,
                  "data_quality": "all", "sort": "asc"}
        seen, proofs = {}, []
        affected = set()
        reset_after = {}
        dividends = []
        splits = {}
        by_type = Counter()
        selected = {row["ticker"] for row in self.selected} | {'BIL'}
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
                                if kind in ('forward_splits', 'reverse_splits'):
                                    try:
                                        event = stock_split(kind, record, axis=axis)
                                        key = (event['ticker'], event['date'])
                                        old = splits.get(key)
                                        if old is not None and old['ratio'] != event['ratio']:
                                            raise AlpacaTransportRefused('conflicting split terms')
                                        splits[key] = event
                                        continue
                                    except AlpacaTransportRefused:
                                        # No split inference: reset only an unowned candidate.
                                        pass
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
                "splits": sorted(splits.values(), key=lambda item:(item['date'],item['ticker'])),
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
        if 'BIL' in self.action_affected or 'BIL' in self.reset_after:
            raise AlpacaTransportRefused('BIL structural action terms are unavailable')
        split, split_proofs = self._bars({'BIL'}, first, last, 'split')
        split_bars = bar_page_rows(split, symbols={'BIL'}, sessions=sessions)
        paired_bil, absent_bil = paired_month({'BIL':raw.get('BIL',[])}, split,
                                            symbols={'BIL'}, sessions=sessions)
        bil_history, _ = admissible_history(paired_bil, axis=list(map(str,self.window.sessions)),
            symbols={'BIL'}, action_affected=frozenset(), pair_absent=absent_bil,
            split_terms=self.split_terms())
        if bil_history != {'BIL':first}:
            raise AlpacaTransportRefused('BIL split-only/raw prices lack corroborated coverage')
        paired, absent = paired_month(raw, adjusted, symbols=symbols, sessions=sessions)
        if absent or {(row["ticker"], row["date"]) for row in paired} != {
                (symbol, day) for symbol in symbols for day in sessions}:
            raise AlpacaTransportRefused("SPY/BIL lack exact paired daily coverage")
        rows = [{"date": row["date"], "ticker": row["ticker"],
                 "open": split_bars[('BIL',row['date'])]['open'] if row['ticker']=='BIL' else row['open'],
                 "close": split_bars[('BIL',row['date'])]['close'] if row['ticker']=='BIL' else row['close'],
                 "closeunadj": row["closeunadj"], "closeadj": row["adjusted_close"]}
                for row in paired]
        return rows, None, {"raw": raw_proofs, "all": adjusted_proofs, 'bil_split':split_proofs}, len(rows)

    def references(self, checkpoint):
        base = {"provider": self.provider, "target": str(self.window.end)}
        refs = self._classified_references(base, checkpoint)
        self.selected = refs["selected"]
        actions = self._part("ACTIONS", {**base, "component": "actions",
                                          "start": (self.window.start - timedelta(days=365)).isoformat()},
                             self._action_rows, checkpoint)
        self.action_affected = frozenset(actions["affected"])
        self.reset_after = actions["reset_after"]
        self.action_evidence = actions["summary"]
        self.dividends = actions["dividends"]
        self.splits = actions["splits"]
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
                                                    "reset_after": self.reset_after,
                                                    "splits": self.splits}),
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
        newer, *_ = self._inventory()
        if newer["assets"] != self.assets:
            raise AlpacaTransportRefused("Alpaca/OpenFIGI current universe changed during GO")
        actions, *_ = self._action_rows()
        if (frozenset(actions["affected"]) != self.action_affected
                or actions["reset_after"] != self.reset_after
                or actions["dividends"] != self.dividends
                or actions['splits'] != self.splits):
            raise AlpacaTransportRefused("Alpaca action participants changed during GO")

    def reference_payload(self):
        admitted = {row["ticker"]: row["firstpricedate"] for row in self.tickers}
        admitted['BIL'] = str(self.window.start)
        actions = [{"date": day, "action": "dividend",
                    "ticker": symbol, "name": None,
                    "value": rate, "contraticker": None,
                    "contraname": None}
                   for (symbol, day), rate in sorted(self.dividend_totals(admitted).items())]
        actions.extend({'date':event['date'], 'action':'split', 'ticker':event['ticker'],
            'name':None, 'value':event['ratio'], 'contraticker':None, 'contraname':None}
            for event in self.splits if event['ticker'] in admitted
            and event['date'] >= admitted[event['ticker']])
        return {"schema": "sentinel.rolling-alpaca-openfigi-references/1",
                "tickers": self.tickers, "actions": actions}

    def split_terms(self):
        return {(event['ticker'],event['date']):event['ratio'] for event in self.splits}

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
