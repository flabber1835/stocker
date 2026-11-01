"""Route authenticated late ordinary dividends without changing share history.

This is an execution view, not a replacement action compiler or a payment
certificate. Original archive rows and scalar interpretations remain intact.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
import re
from typing import Literal

from pydantic import Field

from sentinel.feed.rolling_contract import Contract, Digest, digest

SCHEMA = 'sentinel.cash-correction-classification/1'
_MATERIAL_KEYS = frozenset({'scalar', 'unsupported', 'unresolved', 'sources', 'bars',
    'predecessors', 'dispositions', 'defensive', 'identity_rows', 'identity_aliases',
    'identity_actions', 'identity_policy'})
_ORIGINAL_KEYS = _MATERIAL_KEYS | {'snapshot_id', 'reference_sha256',
    'source_evidence_sha256', 'publication_version'}
_SOURCE_KEYS = frozenset({'date', 'action', 'ticker', 'name', 'value',
    'contraticker', 'contraname', 'source_row_id'})
_MARKER_KEYS = frozenset({'security_id', 'ticker', 'session', 'action', 'value',
    'contraticker', 'source_row_id', 'reason', 'evidence_kind', 'publication_version'})


class CashOnlyAdditionProof(Contract):
    schema_id: Literal['sentinel.cash-correction-classification/1'] = Field(default=SCHEMA, alias='schema')
    classification: Literal['CASH_ONLY_ADDITION'] = 'CASH_ONLY_ADDITION'
    publication_version: int = Field(gt=0)
    original_publication_version: int = Field(gt=0)
    correction_publication_version: int = Field(gt=0)
    security_id: str = Field(min_length=1)
    ticker: str = Field(min_length=1)
    session: str
    per_share: Decimal = Field(gt=0, allow_inf_nan=False)
    marker_sha256: Digest
    original_record_sha256: Digest
    coverage_sha256: Digest
    original_coverage_sha256: Digest
    correction_coverage_sha256: Digest
    correction_evidence_sha256: Digest
    publication_receipt_sha256: Digest
    original_receipt_sha256: Digest
    correction_receipt_sha256: Digest
    broker_payment_claimed: Literal[False] = False
    economic_equivalence_claimed: Literal[False] = False


class _NotCashAddition(ValueError):
    pass


def _require(value):
    if not value:
        raise _NotCashAddition('not a proved ordinary cash addition')


def _positive(value):
    _require(not isinstance(value, bool))
    result = Decimal(str(value))
    _require(result.is_finite() and result > 0)
    return result


def _matches(item, sid, ticker):
    _require(isinstance(item, dict))
    return (item.get('security_id') == sid or item.get('permaticker') == sid
            or str(item.get('ticker') or '').upper() == ticker
            or str(item.get('contraticker') or '').upper() == ticker)


@dataclass(frozen=True)
class CashAddition:
    proof: CashOnlyAdditionProof
    source: dict
    bar: tuple
    predecessor: tuple
    identity: dict


def classify(marker, original, correction, *, publication_version, coverage_sha256,
             original_coverage_sha256, correction_coverage_sha256,
             publication_receipt_sha256, original_receipt_sha256,
             correction_receipt_sha256):
    """Pure, narrow classification after callers authenticate the parent links.

    Unknown/mixed/changed-old economics give no classification. Corruption of
    authenticated storage is handled by the live reader, not swallowed here.
    """
    try:
        from sentinel.feed import calendar
        from sentinel.feed.corporate_action_authority import resolve_dividends
        from sentinel.feed.source_authority.corporate_action_data import (
            CASH_ADJUDICATION_AUTHORITIES, DISPUTED_CASH_EVENTS)
        from sentinel.feed.universe import IdentityResolver, listings_from_rows
        from stock_strategy_shared.wealth_core.sharadar_domains import raw_dividend_per_share

        _require(isinstance(marker, dict) and set(marker) == _MARKER_KEYS)
        sid, ticker, session = marker['security_id'], marker['ticker'], marker['session']
        _require(isinstance(sid, str) and sid and isinstance(ticker, str)
                 and ticker == ticker.strip().upper() and ticker and ticker != 'BIL'
                 and sid != 'SENTINEL:BIL' and date.fromisoformat(session).isoformat() == session)
        _require(marker['action'] == 'historycorrection' and marker['value'] is None
                 and marker['contraticker'] is None and marker['reason'] == 'RETAINED_ACTION_MEANING_CHANGED'
                 and marker['evidence_kind'] == 'retained_action_correction'
                 and type(marker['publication_version']) is int)
        _require(isinstance(original, dict) and set(original) == _ORIGINAL_KEYS
                 and isinstance(correction, dict) and set(correction) == {'sources', 'observed', 'snapshot_id'})
        observed = correction['observed']
        _require(isinstance(observed, dict) and set(observed) == _MATERIAL_KEYS)
        _require(all(isinstance(original[key], list) and isinstance(observed[key], list)
                     for key in _MATERIAL_KEYS))
        _require(not original['identity_policy'] and not observed['identity_policy'])
        _require(type(original['publication_version']) is int
                 and 0 < original['publication_version'] < marker['publication_version'] <= publication_version)
        _require(digest(correction['sources']) == marker['source_row_id']
                 and isinstance(correction['sources'], list)
                 and sorted(correction['sources'], key=digest) == sorted(observed['sources'], key=digest))
        # A covered sparse absence is not permission to replace an old cash or
        # structural event, identity, or old material bar for this security.
        for key in ('sources', 'scalar', 'unsupported', 'unresolved', 'identity_rows',
                    'identity_aliases', 'identity_actions', 'dispositions'):
            _require(not any(_matches(item, sid, ticker) for item in original[key]))
        _require(not any(row[0] == sid or (len(row) > 1 and row[1] == ticker)
                         for row in original['bars']))
        _require(not any(row[0] == sid for row in original['predecessors']))
        for key in ('scalar', 'unsupported', 'unresolved', 'identity_aliases',
                    'identity_actions', 'identity_policy', 'dispositions'):
            _require(not any(_matches(item, sid, ticker) for item in observed[key]))
        sources = [item for item in observed['sources'] if _matches(item, sid, ticker)]
        _require(len(sources) == 1 and set(sources[0]) == _SOURCE_KEYS)
        source = sources[0]
        _require(source['ticker'] == ticker and source['action'] == 'dividend'
                 and source['contraticker'] is None and source['contraname'] is None
                 and calendar.session_on_or_after(source['date']) == session)
        _require(isinstance(source['source_row_id'], str)
                 and re.fullmatch('[0-9a-f]{64}', source['source_row_id']) is not None)
        _positive(source['value'])
        identities = [row for row in observed['identity_rows'] if _matches(row, sid, ticker)]
        _require(len(identities) == 1 and identities[0].get('permaticker') == sid
                 and identities[0].get('ticker') == ticker
                 and IdentityResolver(listings_from_rows(identities)).resolve(ticker, session) == sid)
        bars = [row for row in observed['bars'] if row[0] == sid or row[1] == ticker]
        _require(len(bars) == 1 and len(bars[0]) == 6 and bars[0][0] == sid and bars[0][1] == ticker)
        bar = bars[0]
        signal, raw, per_share = map(_positive, bar[2:5])
        _require(Decimal(str(bar[5])) == 1)
        predecessors = [row for row in observed['predecessors'] if row[0] == sid]
        _require(len(predecessors) == 1 and len(predecessors[0]) == 4
                 and predecessors[0][1] == calendar.previous_sessions(session, 2)[0])
        _positive(predecessors[0][2]); _positive(predecessors[0][3])
        resolution = resolve_dividends([source], [session], disputed_events=tuple(
            item for item in DISPUTED_CASH_EVENTS if item['ticker'] == ticker),
            authorities=tuple(item for item in CASH_ADJUDICATION_AUTHORITIES if item['ticker'] == ticker))
        canonical = Decimal(str(raw_dividend_per_share(signal, raw, resolution.dividends[(ticker, session)])))
        _require(canonical.is_finite() and canonical > 0 and canonical == per_share)
        proof = CashOnlyAdditionProof(publication_version=publication_version,
            original_publication_version=original['publication_version'],
            correction_publication_version=marker['publication_version'], security_id=sid,
            ticker=ticker, session=session, per_share=per_share, marker_sha256=digest(marker),
            original_record_sha256=digest(original), coverage_sha256=coverage_sha256,
            original_coverage_sha256=original_coverage_sha256,
            correction_coverage_sha256=correction_coverage_sha256,
            correction_evidence_sha256=digest(correction), publication_receipt_sha256=publication_receipt_sha256,
            original_receipt_sha256=original_receipt_sha256, correction_receipt_sha256=correction_receipt_sha256)
        return CashAddition(proof, deepcopy(source), tuple(bar), tuple(predecessors[0]), deepcopy(identities[0]))
    except (KeyError, TypeError, ValueError, InvalidOperation, IndexError, ArithmeticError):
        return None


@dataclass(frozen=True)
class CashCorrectionView:
    additions: tuple[CashAddition, ...] = ()

    @property
    def cash_correction_classifications(self):
        return [item.proof.model_dump(mode='json', by_alias=True) for item in self.additions]

    def material(self, session, original):
        selected = [item for item in self.additions if item.proof.session == str(session)]
        if not selected:
            return original
        value = deepcopy(original)
        for item in selected:
            value['sources'].append(deepcopy(item.source))
            value['bars'].append(list(item.bar))
            value['predecessors'].append(list(item.predecessor))
            value['identity_rows'].append(deepcopy(item.identity))
        value['cash_correction_classifications'] = [item.proof.model_dump(mode='json', by_alias=True) for item in selected]
        return value


class ClassifiedActions:
    def __init__(self, original, view):
        self._original, self._view = original, view
        self._markers = frozenset(item.proof.marker_sha256 for item in view.additions)

    def __call__(self, *args, **kwargs):
        return self._original(*args, **kwargs)

    def __getattr__(self, name):
        value = getattr(self._original, name)
        return tuple(item for item in value if not self._classified(item)) if name == 'unresolved_events' else value

    @property
    def cash_correction_classifications(self):
        return self._view.cash_correction_classifications

    def _classified(self, event):
        return (getattr(event, 'action', None) == 'historycorrection'
                and callable(getattr(event, 'to_dict', None)) and digest(event.to_dict()) in self._markers)

    def material_events_for(self, **kwargs):
        return tuple(item for item in self._original.material_events_for(**kwargs) if not self._classified(item))


def load(conn, pub, *, start, end, covered=None, records=None):
    """Read and authenticate live held evidence; exported flags are never authority."""
    from sentinel.execution import feed_inputs
    from sentinel.feed import action_history, publication

    if not feed_inputs.is_rolling(pub):
        return CashCorrectionView()
    if covered is None:
        covered = action_history.coverage(conn, pub, start=start, end=end)
    if covered is None:
        return CashCorrectionView()
    markers = [item for item in covered.get('corrections', ())
               if isinstance(item, dict) and str(start) < str(item.get('session', '')) <= str(end)]
    if not markers:
        return CashCorrectionView()
    current = feed_inputs.require_current(conn)
    if current.version != pub.version or current.evidence != pub.evidence:
        raise ValueError('CASH_CORRECTION_PUBLICATION_CHANGED')
    publication._verify_receipt_chain(conn, through_version=pub.version)
    policy = conn.execute('SELECT required_after_version FROM sentinel_publication_validation_policy').fetchall()
    if len(policy) != 1:
        raise ValueError('CASH_CORRECTION_PUBLICATION_POLICY_CHANGED')
    boundary = int(policy[0][0])
    cache = {}

    def parent(version):
        if version not in cache:
            row = conn.execute('SELECT c.payload,c.payload_sha256,p.evidence,r.receipt_sha256 '
                'FROM sentinel_action_coverage c JOIN sentinel_corpus_publications p ON p.version=c.publication_version '
                'LEFT JOIN sentinel_publication_validation_receipts r ON r.publication_version=p.version '
                'WHERE c.publication_version=%s', (version,)).fetchone()
            if (row is None or version <= boundary or digest(row[0]) != row[1]
                    or row[2].get('action_history') != row[1] or not row[3]
                    or row[2].get('publication_validation', {}).get('receipt_sha256') != row[3]):
                raise ValueError('CASH_CORRECTION_PARENT_AUTHORITY_UNAVAILABLE')
            cache[version] = row
        return cache[version]

    live = parent(pub.version)
    if digest(covered) != live[1] or live[1] != pub.evidence.get('action_history'):
        raise ValueError('CASH_CORRECTION_HELD_COVERAGE_CHANGED')
    if records is None:
        records = action_history.records(conn, version=pub.version, start=start, end=end)
    scopes = [(item.get('security_id'), item.get('ticker'), item.get('session')) for item in markers]
    additions = []
    for marker, scope in zip(markers, scopes):
        original = records.get(marker.get('session'))
        correction = covered.get('correction_evidence', {}).get(marker.get('session'))
        if not isinstance(original, dict) or not isinstance(correction, dict) or scopes.count(scope) != 1:
            continue
        old_version, origin_version = original.get('publication_version'), marker.get('publication_version')
        if type(old_version) is not int or type(origin_version) is not int:
            continue
        old, origin = parent(old_version), parent(origin_version)
        session = marker['session']
        if (old[0].get('added', {}).get(session) != digest(original)
                or marker not in origin[0].get('corrections', ())
                or origin[0].get('correction_evidence', {}).get(session) != correction
                or not str(old[0]['basis']) < session <= str(old[0]['through'])):
            raise ValueError('CASH_CORRECTION_ORIGINAL_LINK_CHANGED')
        addition = classify(marker, original, correction, publication_version=pub.version,
            coverage_sha256=live[1], original_coverage_sha256=old[1], correction_coverage_sha256=origin[1],
            publication_receipt_sha256=live[3], original_receipt_sha256=old[3], correction_receipt_sha256=origin[3])
        if addition is not None:
            additions.append(addition)
    return CashCorrectionView(tuple(additions))


def action_view(conn, actions, *, start, end):
    """Wrap only an affected lookup; ordinary scalar and unsupported paths are unchanged."""
    if not any(getattr(item, 'action', None) == 'historycorrection'
               for item in getattr(actions, 'unresolved_events', ())):
        return actions
    from sentinel.execution import feed_inputs
    pub = feed_inputs.require_current(conn)
    view = load(conn, pub, start=start, end=end)
    return ClassifiedActions(actions, view) if view.additions else actions
