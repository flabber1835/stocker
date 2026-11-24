"""Retained Alpaca/OpenFIGI inputs for GO and daily rolling candidates."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import re
from time import perf_counter_ns
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import Field, ValidationError, model_validator

from sentinel.feed import calendar, progress, rolling_jobs as jobs
from sentinel.feed.acquisition_parts import Parts, SourceRevision
from sentinel.feed.alpaca_pending import AlpacaSourcePending
from sentinel.feed import openfigi
from sentinel.feed.alpaca_observation import (
    action_participants, action_symbols, cash_dividend, paired_month,
    structural_action_date, stock_split, bar_page_rows, admissible_history,
)
from sentinel.feed.alpaca_transport import (
    ACTION_URL, ASSETS, BAR_URL, AlpacaTransportRefused, Client, measure_requests,
)
from sentinel.feed.operational_source import _months
from sentinel.feed.rolling_contract import Contract, Digest, digest

SOURCE = "sentinel.alpaca-openfigi-operational-source/4"
REFERENCE = "sentinel.rolling-alpaca-openfigi-references/4"
IDENTITY_BREAK_POLICY = 'sentinel.alpaca-identity-break/1'
_NY = ZoneInfo("America/New_York")


class SplitBreakProof(Contract):
    kind: Literal['forward_splits', 'reverse_splits']
    record_id: str = Field(min_length=1, max_length=128)
    terms_sha256: Digest
    economic_session: date
    old_cusip: str = Field(pattern=r'^[A-Z0-9]{9}$')
    new_cusip: str = Field(pattern=r'^[A-Z0-9]{9}$')
    old_rate: str = Field(min_length=1, max_length=128)
    new_rate: str = Field(min_length=1, max_length=128)
    raw_record: dict

    @model_validator(mode='after')
    def bound_terms(self):
        record = self.raw_record
        if calendar.previous_sessions(self.economic_session, 1) != [self.economic_session.isoformat()]:
            raise ValueError('identity-break split date is not an XNYS session')
        if (not isinstance(record, dict) or record.get('id') != self.record_id
                or digest(record) != self.terms_sha256
                or record.get('old_cusip') != self.old_cusip
                or record.get('new_cusip') != self.new_cusip
                or self.old_cusip == self.new_cusip):
            raise ValueError('identity-break split source terms changed')
        event = stock_split(self.kind, record, axis={self.economic_session.isoformat()})
        try:
            old = Decimal(str(record['old_rate']))
            new = Decimal(str(record['new_rate']))
        except (KeyError, InvalidOperation, ValueError, TypeError):
            raise ValueError('identity-break split rates changed') from None
        if (self.old_rate != format(old.normalize(), 'f')
                or self.new_rate != format(new.normalize(), 'f')
                or event['date'] != self.economic_session.isoformat()):
            raise ValueError('identity-break split rates or date changed')
        return self


class IdentityBreak(Contract):
    ticker: str = Field(min_length=1, max_length=32)
    old_provider_asset_id: str = Field(min_length=1, max_length=128)
    new_provider_asset_id: str = Field(min_length=1, max_length=128)
    origin_snapshot_id: Digest
    origin_session: date
    first_affected_session: date
    floor_session: date
    split: SplitBreakProof | None

    @model_validator(mode='after')
    def valid_floor(self):
        if any(calendar.previous_sessions(day, 1) != [day.isoformat()]
               for day in (self.origin_session, self.first_affected_session,
                           self.floor_session)):
            raise ValueError('identity-break date is not an XNYS session')
        if (self.ticker != self.ticker.upper()
                or self.old_provider_asset_id == self.new_provider_asset_id
                or not self.origin_session < self.first_affected_session
                or self.floor_session < self.first_affected_session):
            raise ValueError('identity-break origin or floor is invalid')
        if self.split is None:
            if self.floor_session != self.first_affected_session:
                raise ValueError('unproven identity-break floor changed')
        elif (self.split.raw_record.get('symbol') != self.ticker
              or not self.origin_session < self.split.economic_session <= self.first_affected_session
              or self.floor_session != max(self.split.economic_session,
                                           self.first_affected_session)):
            raise ValueError('identity-break split does not establish the floor')
        return self


def source_breaks(source):
    """Validate additive /4 source evidence without changing old /4 rows."""
    if not isinstance(source, dict):
        raise AlpacaTransportRefused('published Alpaca identity breaks unavailable')
    has_policy = 'identity_break_policy' in source
    has_rows = 'identity_breaks' in source
    if not has_policy and not has_rows:
        return []
    if (source.get('schema') != SOURCE or source.get('provider') != 'ALPACA_OPENFIGI'
            or not has_policy or not has_rows
            or source['identity_break_policy'] != IDENTITY_BREAK_POLICY
            or not isinstance(source['identity_breaks'], list)):
        raise AlpacaTransportRefused('invalid Alpaca identity-break source policy')
    try:
        values = [IdentityBreak.model_validate(row) for row in source['identity_breaks']]
    except (ValidationError, ValueError, AlpacaTransportRefused) as exc:
        raise AlpacaTransportRefused('invalid Alpaca identity-break row') from exc
    if any(value.model_dump(mode='json') != row
           for value, row in zip(values, source['identity_breaks'])):
        raise AlpacaTransportRefused('noncanonical Alpaca identity-break row')
    if values != sorted(values, key=lambda value: (value.ticker, value.first_affected_session)):
        raise AlpacaTransportRefused('unordered Alpaca identity-break rows')
    latest = {}
    owners = {}
    proof_ids = set()
    for value in values:
        previous = latest.get(value.ticker)
        if (previous is not None
                and (value.first_affected_session <= previous.first_affected_session
                     or value.old_provider_asset_id != previous.new_provider_asset_id
                     or value.origin_session < previous.first_affected_session)):
            raise AlpacaTransportRefused('conflicting Alpaca identity-break chain')
        latest[value.ticker] = value
        if value.split is not None:
            if value.split.record_id in proof_ids:
                raise AlpacaTransportRefused('duplicate Alpaca identity-break split proof')
            proof_ids.add(value.split.record_id)
        for provider_id in (value.old_provider_asset_id, value.new_provider_asset_id):
            owner = owners.setdefault(provider_id, value.ticker)
            if owner != value.ticker:
                raise AlpacaTransportRefused('colliding Alpaca identity-break provider IDs')
    return values


def _break_events(symbol, origin_session, records):
    """Retain only actions that could describe the replaced listing."""
    from sentinel.feed import alpaca_identity

    return [(kind, record) for kind, record in records
            if symbol in alpaca_identity.action_sources(kind, record)
            and ((day := structural_action_date(kind, record)) is None
                 or day > origin_session)]


def _split_break_proof(symbol, origin_session, first_affected_session, records):
    """A split can bound a fresh series; it cannot bridge provider UUIDs."""
    relevant = _break_events(symbol, origin_session, records)
    if len(relevant) != 1 or relevant[0][0] not in ('forward_splits', 'reverse_splits'):
        return None
    kind, record = relevant[0]
    day = structural_action_date(kind, record)
    if day is None or not origin_session < day <= first_affected_session:
        return None
    old_cusip, new_cusip = record.get('old_cusip'), record.get('new_cusip')
    if (not isinstance(old_cusip, str) or not isinstance(new_cusip, str)
            or re.fullmatch(r'[A-Z0-9]{9}', old_cusip) is None
            or re.fullmatch(r'[A-Z0-9]{9}', new_cusip) is None
            or old_cusip == new_cusip):
        return None
    try:
        stock_split(kind, record, axis={day})
        old = Decimal(str(record['old_rate']))
        new = Decimal(str(record['new_rate']))
        value = SplitBreakProof(kind=kind, record_id=record['id'],
            terms_sha256=digest(record), economic_session=day,
            old_cusip=old_cusip, new_cusip=new_cusip,
            old_rate=format(old.normalize(), 'f'),
            new_rate=format(new.normalize(), 'f'), raw_record=record)
    except (AlpacaTransportRefused, ValidationError, KeyError, InvalidOperation,
            ValueError, TypeError):
        return None
    if value.raw_record.get('symbol') != symbol:
        return None
    return value.model_dump(mode='json')


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


def _unchanged_stock_merger_acquirer(record, current_assets, prior_assets):
    """Identify the receiving listing when the two economic roles are explicit."""
    acquirer = record.get('acquirer_symbol')
    acquiree = record.get('acquiree_symbol')
    if (not isinstance(acquirer, str) or not isinstance(acquiree, str)
            or acquirer == acquiree or action_participants(record) != {acquirer, acquiree}):
        return None
    cusips = (record.get('acquirer_cusip'), record.get('acquiree_cusip'))
    if (cusips[0] == cusips[1] or not all(isinstance(cusip, str)
            and re.fullmatch(r'[A-Z0-9]{9}', cusip) for cusip in cusips)):
        return None
    try:
        rates = tuple(Decimal(str(record[key])) for key in ('acquirer_rate', 'acquiree_rate'))
    except (KeyError, InvalidOperation):
        return None
    if not all(rate.is_finite() and rate > 0 for rate in rates):
        return None
    current = current_assets.get(acquirer)
    return acquirer if current and current == prior_assets.get(acquirer) else None


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
        self.pending_cash = []
        self.pair_absent = set()
        self.sfp = []
        self.tickers = []
        self.actions = []
        self.splits = []
        self.months = []
        self.identity_bindings = []
        self.merger_conversions = []
        self.identity_breaks = []
        self.previous_identity = None
        self.same_session_conversions = None
        self.same_session_breaks = None

    def preflight(self):
        if str(self.window.end) > calendar.latest_closed_session():
            raise AlpacaTransportRefused("Alpaca GO target is not a closed XNYS session")
        self.months = list(_months(str(self.window.start), str(self.window.end)))

    def _part(self, component, generation, acquire, checkpoint):
        details = {'table':component.split('.')[0]}
        if component.startswith('TICKERS.'):
            details['component'] = component
        elif component.startswith('SEP.'):
            _, lo, hi = component.split('.')
            details.update(date_from=lo,date_to=hi)
        details['job_id'] = self.lease.job_id
        with self.parts.unit():
            retained = self.parts.get(component, generation,
                                      defer_prices=self.verify_during_coverage
                                      and component.startswith("SEP."))
            if retained is None:
                progress.emit("source_download", "started", **details,
                              reason="ACQUIRE_MISSING_PART")
                started = perf_counter_ns()
                status, rows = 'failed', 0
                with measure_requests() as requests:
                    try:
                        payload, prices, evidence, rows = acquire()
                        status = 'completed'
                    finally:
                        progress.emit('alpaca_part_acquire', status, rows=rows,
                                      elapsed_ms=(perf_counter_ns() - started) // 1_000_000,
                                      **details, **requests.fields())
                with progress.phase('alpaca_part_persist', **details) as count:
                    retained = self.parts.put(component, generation, payload=payload,
                                              prices=prices, evidence=evidence, rows=rows)
                    count[0] = rows
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
            progress.emit("source_replay", "completed", **details,
                          reason=reason, rows=manifest["rows"])
            return payload

    def _inventory(self):
        assets, asset_proof = self.client.get(getattr(self.client, 'assets_url', ASSETS),
            {"status": "active", "asset_class": "us_equity"})
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
        return openfigi.reuse_classifications(self.assets,
            previous_assets=retained[1].get('assets', []),
            observations=retained[1].get('classifications', {}))

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
                          table='TICKERS',component='TICKERS.FIGI.'+str(number),
                          part=number,parts=(len(missing)+size-1)//size, job_id=self.lease.job_id)
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
        from sentinel.feed import alpaca_identity
        start = (self.window.start - timedelta(days=365)).isoformat()
        end = str(self.window.end)
        params = {"start": start, "end": end, "limit": 1000,
                  "data_quality": "all", "sort": "asc"}
        seen, proofs = {}, []
        affected = set()
        reset_after = {}
        dividends = []
        pending_cash = []
        splits = {}
        by_type = Counter()
        structural, resets = [], []
        current_assets = {row['ticker']: row.get('asset_id') for row in self.selected}
        selected = current_assets.keys() | {'BIL'}
        previous = self._previous_identity()
        prior_assets = {row['ticker']: row['asset_id'] for row in previous['previous_selected']} if previous else {}
        prior_breaks = previous.get('identity_breaks', []) if previous else []
        source_breaks({'schema': SOURCE, 'provider': self.provider,
                       'identity_break_policy': IDENTITY_BREAK_POLICY,
                       'identity_breaks': prior_breaks})
        same_session_breaks = getattr(self, 'same_session_breaks', None)
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
                        prior_acquiree = (kind == 'stock_mergers'
                                          and record.get('acquiree_symbol') in prior_assets)
                        if not involved and not prior_acquiree:
                            continue
                        if kind == "cash_dividends":
                            try:
                                event = cash_dividend(record, axis=axis, retain_historical=True)
                            except AlpacaTransportRefused as exc:
                                pending_cash.append({'id': record['id'], 'tickers': sorted(involved),
                                    'terms_sha256': digest(record), 'reason': str(exc)})
                                continue
                            if event is not None:
                                dividends.append(event)
                        else:
                            structural.append((kind, record))
                            involved = alpaca_identity.action_sources(kind, record) & selected
                            economic_date = structural_action_date(kind, record)
                            if kind == 'stock_mergers' and economic_date is not None:
                                acquirer = _unchanged_stock_merger_acquirer(record, current_assets, prior_assets)
                                if acquirer is not None:
                                    involved = involved - {acquirer}
                            if economic_date is None or economic_date > str(self.window.end):
                                affected.update(involved)
                            elif economic_date >= str(self.window.start):
                                if kind in ('forward_splits', 'reverse_splits'):
                                    try:
                                        event = stock_split(kind, record, axis=axis)
                                    except AlpacaTransportRefused:
                                        # No split inference: reset only an unowned candidate.
                                        pass
                                    else:
                                        key = (event['ticker'], event['date'])
                                        old = splits.get(key)
                                        if old is not None:
                                            if old['ratio'] != event['ratio']:
                                                raise AlpacaTransportRefused('conflicting split terms')
                                            ids = sorted({*old.get('source_ids', [old['id']]), event['id']})
                                            event.update(id=ids[0], source_ids=ids)
                                        splits[key] = event
                                        continue
                                for symbol in involved:
                                    resets.append((symbol, economic_date, record['id']))
        for row in [*prior_breaks, *(same_session_breaks or [])]:
            split = row['split']
            if split is None:
                continue
            observed = seen.get(split['record_id'])
            expected = digest({'type': split['kind'], 'record': split['raw_record']})
            if observed is not None and observed != expected:
                raise AlpacaTransportRefused('published identity-break split changed')
        identity_bindings = alpaca_identity.bind(selected=self.selected, records=structural,
            target_session=str(self.window.end),
            previous_selected=previous['previous_selected'],
            previous_bindings=previous['previous_bindings'],
            previous_session=previous['previous_session'],
            previous_snapshot_id=previous['previous_snapshot_id']) if previous is not None else []
        merger_conversions = alpaca_identity.merger_conversions(
            selected=self.selected, previous_identity=previous,
            bindings_raw=identity_bindings, records=structural,
            target_session=str(self.window.end))
        # A replaced provider UUID under the same symbol cannot inherit the
        # prior history without a complete dated identity or merger action.
        # The producer sees only source inventory, never controller selections.
        bound_symbols = {item['ticker'] for item in identity_bindings}
        converted_symbols = {item['old_symbol'] for item in merger_conversions}
        identity_breaks = list(prior_breaks)
        prior_break_by_symbol = {row['ticker']: row for row in prior_breaks}
        for symbol, row in prior_break_by_symbol.items():
            if symbol in prior_assets and prior_assets[symbol] != row['new_provider_asset_id']:
                raise AlpacaTransportRefused('published identity-break reference changed')
        prior_ids = {**prior_assets,
                     **{symbol: row['new_provider_asset_id']
                        for symbol, row in prior_break_by_symbol.items()}}
        for symbol, old_id in sorted(prior_ids.items()):
            new_id = current_assets.get(symbol)
            if new_id is None:
                continue
            old_break = prior_break_by_symbol.get(symbol)
            if new_id == old_id:
                if old_break is not None and old_break['split'] is None:
                    proof = _split_break_proof(symbol, old_break['origin_session'],
                        old_break['first_affected_session'], structural)
                    if proof is not None:
                        identity_breaks[identity_breaks.index(old_break)] = {
                            **old_break, 'split': proof,
                            'floor_session': max(proof['economic_session'],
                                                 old_break['first_affected_session'])}
                elif old_break is not None and old_break['split'] is not None:
                    # A later action response may omit an old event, but it may
                    # never rewrite or contradict the authenticated terms.
                    for kind, record in _break_events(symbol, old_break['origin_session'], structural):
                        day = structural_action_date(kind, record)
                        if day is None or day <= old_break['first_affected_session']:
                            proof = old_break['split']
                            if (kind != proof['kind'] or record.get('id') != proof['record_id']
                                    or digest(record) != proof['terms_sha256']):
                                raise AlpacaTransportRefused('published identity-break split changed')
                continue
            if symbol in bound_symbols or symbol in converted_symbols:
                if old_break is not None:
                    raise AlpacaSourcePending('ALPACA_IDENTITY_ACTION_PENDING', symbol=symbol)
                continue
            proof = _split_break_proof(symbol, previous['previous_session'],
                                       str(self.window.end), structural)
            identity_breaks.append(IdentityBreak(
                ticker=symbol, old_provider_asset_id=old_id,
                new_provider_asset_id=new_id,
                origin_snapshot_id=previous['previous_snapshot_id'],
                origin_session=previous['previous_session'],
                first_affected_session=str(self.window.end),
                floor_session=max(proof['economic_session'], str(self.window.end))
                    if proof is not None else str(self.window.end),
                split=proof).model_dump(mode='json'))
        if same_session_breaks is not None:
            generated = {(row['ticker'], row['first_affected_session']): row
                         for row in identity_breaks}
            for retained in same_session_breaks:
                key = (retained['ticker'], retained['first_affected_session'])
                observed = generated.get(key)
                if observed is None:
                    # The inventory may temporarily omit a quarantined listing.
                    identity_breaks.append(retained)
                    generated[key] = retained
                    continue
                if observed == retained:
                    continue
                if ({key: value for key, value in observed.items()
                     if key not in ('split', 'floor_session')}
                        != {key: value for key, value in retained.items()
                            if key not in ('split', 'floor_session')}
                        or retained['split'] is None or observed['split'] is not None):
                    raise AlpacaTransportRefused('same-session identity-break evidence changed')
                # A prior authenticated split remains evidence when the
                # provider no longer includes that action in a later page.
                for kind, record in _break_events(retained['ticker'],
                                                  retained['origin_session'], structural):
                    day = structural_action_date(kind, record)
                    if day is None or day <= retained['first_affected_session']:
                        proof = retained['split']
                        if (kind != proof['kind'] or record.get('id') != proof['record_id']
                                or digest(record) != proof['terms_sha256']):
                            raise AlpacaTransportRefused('same-session identity-break split changed')
                generated[key] = retained
                identity_breaks[identity_breaks.index(observed)] = retained
        identity_breaks.sort(key=lambda row: (row['ticker'], row['first_affected_session']))
        source_breaks({'schema': SOURCE, 'provider': self.provider,
                       'identity_break_policy': IDENTITY_BREAK_POLICY,
                       'identity_breaks': identity_breaks})
        if any(row['first_affected_session'] > str(self.window.end)
               or row['floor_session'] > str(self.window.end)
               for row in identity_breaks):
            raise AlpacaTransportRefused('identity-break floor is in the future')
        reserved_ids = {sid: row['ticker'] for row in identity_breaks
                        for sid in (row['old_provider_asset_id'],
                                    row['new_provider_asset_id'])}
        if any(reserved_ids.get(sid) not in (None, symbol)
               for symbol, sid in current_assets.items()):
            raise AlpacaTransportRefused('identity-break provider ID reused by another symbol')
        if same_session_breaks is not None:
            current_by_key = {(row['ticker'], row['first_affected_session']): row
                              for row in identity_breaks}
            if any(current_by_key.get((row['ticker'], row['first_affected_session'])) != row
                   for row in same_session_breaks):
                raise AlpacaTransportRefused('same-session identity-break evidence changed')
        old_conversions = getattr(self, 'same_session_conversions', None)
        if old_conversions is not None:
            alpaca_identity.conversions(old_conversions)
            previous_rows = {item['old_security_id']: item for item in old_conversions}
            current_rows = {item['old_security_id']: item for item in merger_conversions}
            if (any(current_rows.get(sid) != item for sid, item in previous_rows.items())
                    or len(current_rows) < len(previous_rows)):
                raise AlpacaTransportRefused('reobserved merger terms changed')
            if len(current_rows) == len(previous_rows):
                from sentinel.feed import rolling_jobs
                # Only a retained-book reconstruction may republish identical
                # source facts as after-open, state-only current information.
                lease = getattr(self, 'lease', None)
                reconstruction = (lease is not None and
                    rolling_jobs.status(self.conn, lease.job_id)['request']['cursor'] is not None)
                if not reconstruction:
                    raise AlpacaSourcePending('ALPACA_ACTION_REOBSERVATION_PENDING')
        exemptions = {item['event']['id'] for item in identity_bindings}
        current_mergers = {item['record_id']: item for item in merger_conversions}
        for symbol, day, event_id in resets:
            if event_id in exemptions:
                continue
            merger = current_mergers.get(event_id)
            if (merger is not None and symbol == merger['successor_symbol']
                    and symbol != merger['old_symbol']):
                # The recipient is a separate current listing; this record
                # terminates its acquiree, not its own price history.
                continue
            # A new same-symbol asset cannot inherit old history, but its
            # actual event-day bar starts the successor's fresh series.
            reset_day = previous['previous_session'] if merger is not None else day
            reset_after[symbol] = max(reset_day, reset_after.get(symbol, ''))
        for row in identity_breaks:
            symbol = row['ticker']
            if symbol not in current_assets:
                continue
            blocked_by_action = symbol in affected
            affected.discard(symbol)
            floor = (row['floor_session'] if row['split'] is not None and not blocked_by_action
                     else str(self.window.end))
            reset_after[symbol] = max(floor, reset_after.get(symbol, ''))
        dividends = sorted((item for item in dividends
                            if item["ticker"] not in affected),
                           key=lambda item: (item["date"], item["ticker"], item["id"]))
        summary = {"actions": len(seen), "by_type": dict(sorted(by_type.items())),
                   "affected_selected_symbols": len(affected),
                   "post_event_reset_symbols": len(reset_after),
                   "cash_dividend_rows": len(dividends),
                   "merger_conversion_rows": len(merger_conversions),
                   'identity_break_rows': len(identity_breaks)}
        return {"affected": sorted(affected), "reset_after": reset_after,
                'identity_bindings': identity_bindings,
                'merger_conversions': merger_conversions,
                'identity_breaks': identity_breaks,
                "dividends": dividends,
                'pending_cash': sorted(pending_cash, key=lambda item: item['id']),
                "splits": sorted(splits.values(), key=lambda item:(item['date'],item['ticker'])),
                "summary": summary}, None, \
            {"pages": proofs}, len(seen)

    def _previous_identity(self):
        """Use the preceding dated publication, including after a failed same-day GO."""
        if self.previous_identity is not None:
            return self.previous_identity
        from sentinel.feed import publication, operational_snapshot, rolling_store
        row = self.conn.execute('SELECT version,previous_version,run_id,window_start,window_end,evidence '
            'FROM sentinel_corpus_publications WHERE window_end <= %s '
            'ORDER BY window_end DESC,version DESC LIMIT 1', (str(self.window.end),)).fetchone()
        if row is None:
            return None
        if str(row[4]) == str(self.window.end):
            current_pub = publication.Publication(int(row[0]), row[1],
                str(row[2]) if row[2] else None, str(row[3]), str(row[4]), row[5])
            publication._validate_publication(self.conn, current_pub, allow_snapshot=True)
            current_manifest = rolling_store.manifest(self.conn, row[5]['rolling_snapshot']['candidate_id'])
            current_reference = rolling_store.load_evidence(self.conn, current_manifest.reference_sha256)
            if current_reference.get('schema') == REFERENCE:
                from sentinel.feed import alpaca_identity
                current_source = rolling_store.load_evidence(
                    self.conn, current_manifest.source_evidence_sha256)
                self.same_session_conversions = current_reference.get('merger_conversions')
                if (not isinstance(current_source, dict) or current_source.get('schema') != SOURCE or
                        current_source.get('merger_conversions_sha256') !=
                            digest(self.same_session_conversions)):
                    raise AlpacaTransportRefused('same-session merger source binding changed')
                alpaca_identity.conversions(self.same_session_conversions)
                self.same_session_breaks = [row.model_dump(mode='json')
                    for row in source_breaks(current_source)]
            row = self.conn.execute('SELECT version,previous_version,run_id,window_start,window_end,evidence '
                'FROM sentinel_corpus_publications WHERE window_end < %s '
                'ORDER BY window_end DESC,version DESC LIMIT 1', (str(self.window.end),)).fetchone()
            if row is None:
                return None
        pub = publication.Publication(int(row[0]), row[1], str(row[2]) if row[2] else None,
            str(row[3]), str(row[4]), row[5])
        publication._validate_publication(self.conn, pub, allow_snapshot=True)
        binding = operational_snapshot._bound(self.conn, pub)
        manifest = rolling_store.manifest(self.conn, binding['candidate_id'])
        if manifest.provider != self.provider:
            raise AlpacaTransportRefused('previous Alpaca identity provider mismatch')
        from sentinel.feed.alpaca_identity import published_assets
        reference = rolling_store.load_evidence(self.conn, manifest.reference_sha256)
        source = rolling_store.load_evidence(self.conn, manifest.source_evidence_sha256)
        selected = published_assets(reference, source)
        breaks = [value.model_dump(mode='json') for value in source_breaks(source)]
        if any(value['first_affected_session'] > pub.window_end
               or value['floor_session'] > pub.window_end for value in breaks):
            raise AlpacaTransportRefused('published identity-break floor is in the future')
        if (source.get('schema') == 'sentinel.alpaca-openfigi-operational-source/3'
                and reference.get('schema') == 'sentinel.rolling-alpaca-openfigi-references/3'):
            # This pre-policy source could already have assigned a replacement
            # UUID to historical same-symbol prices. Older /1 and /2 aggregates
            # retain their separate retirement and recovery contract.
            older = self.conn.execute(
                'SELECT version,previous_version,run_id,window_start,window_end,evidence '
                'FROM sentinel_corpus_publications WHERE window_end < %s '
                'ORDER BY window_end DESC,version DESC LIMIT 1',
                (pub.window_end,)).fetchone()
            if older is not None:
                older_pub = publication.Publication(int(older[0]), older[1],
                    str(older[2]) if older[2] else None, str(older[3]),
                    str(older[4]), older[5])
                publication._validate_publication(self.conn, older_pub, allow_snapshot=True)
                older_binding = operational_snapshot._bound(self.conn, older_pub)
                older_manifest = rolling_store.manifest(self.conn, older_binding['candidate_id'])
                if older_manifest.provider == self.provider:
                    older_reference = rolling_store.load_evidence(
                        self.conn, older_manifest.reference_sha256)
                    older_source = rolling_store.load_evidence(
                        self.conn, older_manifest.source_evidence_sha256)
                    older_assets = {item['ticker']: item['asset_id'] for item in
                                    published_assets(older_reference, older_source)}
                    from sentinel.feed import alpaca_identity
                    bound = {item.ticker: item for item in alpaca_identity.bindings(
                        reference.get('identity_bindings', []))}
                    converted = {item['old_symbol']: item for item in
                                 reference.get('merger_conversions', [])}
                    for item in selected:
                        symbol = item['ticker']
                        old_id = older_assets.get(symbol)
                        if old_id is None or item['asset_id'] == old_id:
                            continue
                        binding = bound.get(symbol)
                        conversion = converted.get(symbol)
                        proven_name = (binding is not None
                            and binding.prior_provider_asset_id == old_id
                            and binding.provider_asset_id == item['asset_id'])
                        proven_merger = (conversion is not None
                            and conversion['old_provider_asset_id'] == old_id
                            and conversion['successor_provider_asset_id'] == item['asset_id'])
                        if not proven_name and not proven_merger:
                            raise AlpacaSourcePending('ALPACA_IDENTITY_ACTION_PENDING',
                                                      symbol=symbol)
        latest = {value['ticker']: value for value in breaks}
        reserved_ids = {sid: value['ticker'] for value in breaks
                        for sid in (value['old_provider_asset_id'],
                                    value['new_provider_asset_id'])}
        if any(reserved_ids.get(row['asset_id']) not in (None, row['ticker'])
               for row in selected):
            raise AlpacaTransportRefused('published identity-break provider ID collision')
        for ticker in reference['tickers']:
            if reserved_ids.get(ticker['permaticker']) not in (None, ticker['ticker']):
                raise AlpacaTransportRefused('published identity-break provider ID collision')
            row = latest.get(ticker['ticker'])
            if row is None:
                continue
            if (row['split'] is None or ticker['permaticker'] != row['new_provider_asset_id']
                    or ticker['firstpricedate'] <= row['floor_session']):
                raise AlpacaTransportRefused('published identity-break price floor changed')
        self.previous_identity = dict(previous_selected=selected,
            previous_bindings=reference.get('identity_bindings', []),
            previous_session=pub.window_end, previous_snapshot_id=manifest.snapshot_id,
            identity_breaks=breaks)
        return self.previous_identity

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
        expected_bil = {('BIL', day) for day in sessions}
        observed_bil = {(row['ticker'], row['date']) for row in paired_bil}
        missing_bil = expected_bil - observed_bil
        if (missing_bil and last == calendar.latest_closed_session()
                and all(day == last for _symbol, day in missing_bil)):
            raise AlpacaSourcePending('ALPACA_BENCHMARK_CLOSE_PENDING', symbol='BIL')
        bil_history, _ = admissible_history(paired_bil, axis=list(map(str,self.window.sessions)),
            symbols={'BIL'}, action_affected=frozenset(), pair_absent=absent_bil,
            split_terms=self.split_terms())
        if bil_history != {'BIL':first}:
            raise AlpacaTransportRefused('BIL split-only/raw prices lack corroborated coverage')
        paired, absent = paired_month(raw, adjusted, symbols=symbols, sessions=sessions)
        expected = {(symbol, day) for symbol in symbols for day in sessions}
        observed = {(row['ticker'], row['date']) for row in paired}
        missing = expected - observed
        if (missing and last == calendar.latest_closed_session()
                and all(day == last for _symbol, day in missing)):
            raise AlpacaSourcePending('ALPACA_BENCHMARK_CLOSE_PENDING')
        if absent or observed != expected:
            raise AlpacaTransportRefused("SPY/BIL lack exact paired daily coverage")
        rows = [{"date": row["date"], "ticker": row["ticker"],
                 "open": split_bars[('BIL',row['date'])]['open'] if row['ticker']=='BIL' else row['open'],
                 "close": split_bars[('BIL',row['date'])]['close'] if row['ticker']=='BIL' else row['close'],
                 "closeunadj": row["closeunadj"], "closeadj": row["adjusted_close"]}
                for row in paired]
        return rows, None, {"raw": raw_proofs, "all": adjusted_proofs, 'bil_split':split_proofs}, len(rows)

    def references(self, checkpoint):
        base = {"provider": self.provider, "target": str(self.window.end), 'source_policy': SOURCE,
                'assets_endpoint': getattr(self.client, 'assets_url', ASSETS)}
        # A resumed acquisition with retained TICKERS but no ACTIONS needs
        # a fresh asset read. Backup and classification retries do not.
        retained = ({row[0] for row in self.conn.execute(
            'SELECT component FROM sentinel_acquisition_bindings '
            'WHERE job_id=%s AND component IN (%s,%s)',
            (self.lease.job_id, 'TICKERS', 'ACTIONS')).fetchall()}
            if self.lease.fence > 1 else set())
        recheck_action_wait = 'TICKERS' in retained and 'ACTIONS' not in retained
        refs = self._classified_references(base, checkpoint)
        self.selected = refs["selected"]
        if recheck_action_wait:
            # A prior action wait left TICKERS retained in this job. A new
            # inventory must either match or earn a fresh revision successor.
            newer, *_ = self._inventory()
            if ([openfigi.listing_identity(asset) for asset in newer['assets']]
                    != [openfigi.listing_identity(asset) for asset in self.assets]):
                raise SourceRevision('*', digest(self.assets), digest(newer['assets']))
        actions = self._part("ACTIONS", {**base, "component": "actions",
                                          'stock_merger_roles': 1,
                                          'split_identity': 3,
                                          'identity_break_policy': IDENTITY_BREAK_POLICY,
                                          'prior_identity_sha256': digest(self._previous_identity()),
                                          "start": (self.window.start - timedelta(days=365)).isoformat()},
                             self._action_rows, checkpoint)
        self.action_affected = frozenset(actions["affected"])
        self.reset_after = actions["reset_after"]
        self.action_evidence = actions["summary"]
        self.dividends = actions["dividends"]
        self.pending_cash = actions.get('pending_cash', [])
        self.splits = actions["splits"]
        self.identity_bindings = actions['identity_bindings']
        self.merger_conversions = actions['merger_conversions']
        self.identity_breaks = actions['identity_breaks']
        self.sfp = self._part("SFP", {**base, "component": "benchmarks",
                                      "window": self.window.model_dump(mode="json")},
                              self._benchmark_rows, checkpoint)

    def acquire_prices(self, checkpoint, pulse):
        from contextlib import nullcontext

        scope = self.client.pooled() if isinstance(self.client, Client) else nullcontext()
        with scope:
            self._acquire_prices(checkpoint, pulse)

    def _acquire_prices(self, checkpoint, pulse):
        safe_symbols = {row["ticker"] for row in self.selected} - self.action_affected
        if not safe_symbols:
            raise AlpacaTransportRefused("no candidate securities remain after action quarantine")
        for number, (lo, hi) in enumerate(self.months, 1):
            starts = defaultdict(set)
            for symbol in safe_symbols:
                floor = self.reset_after.get(symbol)
                if floor is not None and floor >= hi:
                    continue
                first = (calendar.next_session(floor)
                         if floor is not None and floor >= lo else lo)
                if first > hi:
                    continue
                starts[first].add(symbol)
            month_symbols = set().union(*starts.values()) if starts else set()
            component = f"SEP.{lo}.{hi}"
            generation = {"provider": self.provider, "component": component,
                          "selection_sha256": digest(self.selected),
                          "actions_sha256": digest({"affected": sorted(self.action_affected),
                                                    "reset_after": self.reset_after,
                                                    "splits": self.splits,
                                                    'identity_bindings': self.identity_bindings,
                                                    'merger_conversions': self.merger_conversions,
                                                    'identity_breaks': self.identity_breaks}),
                          "asof": str(self.window.end)}
            def acquire():
                raw, adjusted, raw_proofs, adjusted_proofs = {}, {}, [], []
                for first, symbols in sorted(starts.items()):
                    rows, proofs = self._bars(symbols, first, hi, "raw")
                    raw.update(rows); raw_proofs.extend(proofs)
                    rows, proofs = self._bars(symbols, first, hi, "split")
                    adjusted.update(rows); adjusted_proofs.extend(proofs)
                sessions = {str(day) for day in self.window.sessions if lo <= str(day) <= hi}
                with progress.phase('alpaca_price_pairing', job_id=self.lease.job_id,
                                    table='SEP', date_from=lo, date_to=hi) as count:
                    rows, absent = paired_month(raw, adjusted, symbols=month_symbols, sessions=sessions)
                    count[0] = len(rows)
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
        before_inventory = [openfigi.listing_identity(asset) for asset in self.assets]
        after_inventory = [openfigi.listing_identity(asset) for asset in newer['assets']]
        if after_inventory != before_inventory:
            raise SourceRevision("*", digest(self.assets), digest(newer["assets"]))
        try:
            actions, *_ = self._action_rows()
        except AlpacaSourcePending as exc:
            # ACTIONS was already persisted before the long price acquisition.
            # A same-job wait would replay that stale part on every retry.
            raise SourceRevision('ACTIONS', digest(self.merger_conversions),
                                 digest({'pending': exc.reason, 'symbol': exc.symbol})) from exc
        if (frozenset(actions["affected"]) != self.action_affected
                or actions["reset_after"] != self.reset_after
                or actions["dividends"] != self.dividends
                or actions['pending_cash'] != self.pending_cash
                or actions['splits'] != self.splits):
            before = {"affected": sorted(self.action_affected),
                      "reset_after": self.reset_after, "dividends": self.dividends,
                      'pending_cash': self.pending_cash,
                      "splits": self.splits}
            after = {key: actions[key] for key in before}
            raise SourceRevision("ACTIONS", digest(before), digest(after))
        if actions['identity_bindings'] != self.identity_bindings:
            raise SourceRevision('ACTIONS', digest(self.identity_bindings), digest(actions['identity_bindings']))
        if actions['merger_conversions'] != self.merger_conversions:
            raise SourceRevision('ACTIONS', digest(self.merger_conversions), digest(actions['merger_conversions']))
        if actions['identity_breaks'] != self.identity_breaks:
            raise SourceRevision('ACTIONS', digest(self.identity_breaks), digest(actions['identity_breaks']))

    def reference_payload(self):
        latest_breaks = {row['ticker']: row for row in getattr(self, 'identity_breaks', [])}
        reserved_ids = {sid: row['ticker'] for row in getattr(self, 'identity_breaks', [])
                        for sid in (row['old_provider_asset_id'],
                                    row['new_provider_asset_id'])}
        for row in self.tickers:
            if reserved_ids.get(row['permaticker']) not in (None, row['ticker']):
                raise AlpacaTransportRefused('identity-break reference provider ID collision')
            previous = latest_breaks.get(row['ticker'])
            if previous is not None and (previous['split'] is None
                    or row['permaticker'] != previous['new_provider_asset_id']
                    or row['firstpricedate'] <= previous['floor_session']):
                raise AlpacaTransportRefused('identity-break reference crossed price floor')
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
        return {"schema": REFERENCE,
                'identity_bindings': self.identity_bindings,
                'merger_conversions': self.merger_conversions,
                "tickers": self.tickers, "actions": actions,
                'cash_observations': self.dividends,
                'pending_cash': self.pending_cash}

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
        payload = {"schema": SOURCE, "provider": self.provider,
                "selected_count": len(self.selected),
                "admitted_count": len(self.tickers),
                "components": self.evidence, "sfp_sha256": digest(self.sfp),
                "selection_sha256": digest(self.selected),
                "action_quarantine": self.action_evidence,
                'identity_bindings_sha256': digest(self.identity_bindings),
                'merger_conversions_sha256': digest(self.merger_conversions),
                'identity_break_policy': IDENTITY_BREAK_POLICY,
                'identity_breaks': self.identity_breaks,
                "post_event_reset_sha256": digest(self.reset_after),
                "dividends_sha256": digest(self.dividends)}
        source_breaks(payload)
        return payload
