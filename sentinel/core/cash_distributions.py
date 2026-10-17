"""Point-in-time shadow cash reconciliation; no clock, database or broker."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from bisect import bisect_right
from collections import defaultdict
from datetime import date
from math import isfinite
from typing import Literal
from pydantic import Field
from sentinel.feed.rolling_contract import Contract, Digest, digest
from stock_strategy_shared.wealth_core.ledger import EventType, Ledger

LEGACY_POLICY = 'FORWARD_CASH_DISTRIBUTIONS_V1'
POLICY = 'FORWARD_CASH_DISTRIBUTIONS_V2'
SCHEMA = 'sentinel.forward-cash-distributions/1'


class Observation(Contract):
    security_id: str = Field(min_length=1)
    ticker: str = Field(min_length=1)
    ex_date: str
    per_share: Decimal = Field(ge=0, allow_inf_nan=False)
    source_sha256: Digest


class Inputs(Contract):
    schema_id: Literal['sentinel.forward-cash-distributions/1'] = Field(default=SCHEMA, alias='schema')
    prior_state_sha256: Digest
    publication_version: int = Field(gt=0)
    session: str
    observations: list[Observation]
    pending: list[dict] = Field(default_factory=list)
    source_observations: list[dict] = Field(default_factory=list)
    legacy_floors: list[Observation] = Field(default_factory=list)


class OwnershipIndex:
    def __init__(self, ledger):
        self.first_session = None
        changes = defaultdict(lambda: defaultdict(Decimal))
        self.accrued = defaultdict(Decimal)
        for event in ledger.events:
            if self.first_session is None or event.session < self.first_session:
                self.first_session = event.session
            if event.event_type is EventType.DIVIDEND_ACCRUED:
                self.accrued[(event.security_id, event.detail.get('entitlement_date', event.session))] += Decimal(str(event.detail['amount']))
            if event.event_type is EventType.CONVERSION:
                detail = event.detail
                try:
                    source = Decimal(str(detail['shares_in']))
                    delivered = Decimal(str(detail['shares_delivered']))
                    successor = detail['delivered_security_id']
                    if (not source.is_finite() or not delivered.is_finite()
                            or source < 0 or delivered < 0 or not isinstance(successor, str) or not successor):
                        raise ValueError
                except (KeyError, InvalidOperation, ValueError) as exc:
                    raise ValueError('CASH_CONVERSION_OWNERSHIP_INCOMPLETE') from exc
                changes[event.security_id][(event.session, 1)] -= source
                changes[successor][(event.session, 1)] += delivered
            else:
                opening = event.event_type in (EventType.SPLIT, EventType.SPINOFF_RECEIPT,
                                               EventType.SPINOFF_LIQUIDATION)
                changes[event.security_id][(event.session, 0 if opening else 1)] += Decimal(str(event.shares_delta))
        self.histories = {}
        for security_id, daily in changes.items():
            keys, quantities, shares = [], [], Decimal(0)
            for key, delta in sorted(daily.items()):
                shares += delta
                keys.append(key)
                quantities.append(shares)
            self.histories[security_id] = keys, quantities

    def entitlement(self, *, security_id, ex_date):
        if self.first_session is None or ex_date < self.first_session:
            return None
        keys, quantities = self.histories.get(security_id, ((), ()))
        index = bisect_right(keys, (ex_date, 0)) - 1
        shares = quantities[index] if index >= 0 else Decimal(0)
        if shares < 0:
            raise ValueError('CASH_ENTITLEMENT_OWNERSHIP_INCOHERENT')
        return shares


def entitlement(ledger, *, security_id, ex_date):
    return OwnershipIndex(ledger).entitlement(security_id=security_id, ex_date=ex_date)


def apply(inputs, *, prior, published, state, ledger, lag):
    value = Inputs.model_validate(inputs)
    if (value.prior_state_sha256 != prior.state_hash
            or value.publication_version != published.data_version
            or value.session != published.session
            or prior.last_processed_session is None):
        raise ValueError('CASH_DISTRIBUTION_INPUT_BINDING_CHANGED')
    keys, audit = set(), []
    historical = Ledger.from_dict(prior.ledger)
    ownership = OwnershipIndex(historical)
    for observation in value.observations:
        key = (observation.security_id, observation.ex_date)
        if (key in keys or date.fromisoformat(observation.ex_date).isoformat() != observation.ex_date
                or observation.ex_date > prior.last_processed_session):
            raise ValueError('CASH_DISTRIBUTION_KEYS_INVALID')
        keys.add(key)
        owned = ownership.entitlement(security_id=key[0], ex_date=key[1])
        accrued = ownership.accrued[key]
        target = None if owned is None else owned * observation.per_share
        delta = None if target is None else target - accrued
        if delta is not None:
            future_cash = (Decimal(str(state.cash))
                + sum((Decimal(str(r['amount'])) for r in ledger.receivables), Decimal(0))
                + max(delta, Decimal(0)))
            if not all(isfinite(float(amount)) for amount in (target, delta, future_cash)):
                delta = None
        # The existing canonical shadow ledger serializes modeled amounts as
        # floats. Representation dust is not a second dividend entitlement.
        if delta is not None and abs(delta) <= Decimal('0.000000001'):
            delta = Decimal(0)
        status = ('ENTITLEMENT_PENDING' if target is None else
                  'CASH_AMOUNT_PENDING' if delta is None else
                  'CORRECTION_PENDING' if delta < 0 else
                  'ZERO_ENTITLEMENT' if target == 0 else
                  'ALREADY_RECOGNIZED' if delta == 0 else 'ACCRUED_FORWARD')
        detail = {'policy': POLICY, 'entitlement_date': key[1],
                  'per_share': str(observation.per_share),
                  'entitled_shares': None if owned is None else str(owned),
                  'recognized_before': str(accrued), 'target': None if target is None else str(target),
                  'status': status, 'source_sha256': observation.source_sha256}
        if delta is not None and delta < 0:
            payable = [r for r in ledger.receivables if r['security_id'] == key[0]
                       and r['accrued_session'] == key[1]]
            unearned = -delta
            unsettled = sum((Decimal(str(r['amount'])) for r in payable), Decimal(0))
            cancelled = min(unearned, unsettled)
            debit = unearned - cancelled
            if Decimal(str(state.cash)) >= debit:
                left = cancelled
                for receipt in sorted(payable, key=lambda r: (r['accrued_session'], r['due_in'])):
                    reduction = min(left, Decimal(str(receipt['amount'])))
                    receipt['amount'] = float(Decimal(str(receipt['amount'])) - reduction)
                    left -= reduction
                ledger.receivables = [r for r in ledger.receivables if r['amount'] > 0]
                detail['status'] = 'CORRECTED_FORWARD'
                ledger.post(session=published.session, event_type=EventType.DIVIDEND_ACCRUED,
                    security_id=key[0], ticker=observation.ticker, cash_before=state.cash,
                    reason='DIVIDEND_ENTITLEMENT_CORRECTED', detail={**detail, 'amount': float(delta),
                        'receivable_cancelled': str(cancelled), 'cash_debit': str(debit)})
                if debit:
                    correction = ledger.post(session=published.session, event_type=EventType.DIVIDEND_PAID,
                        security_id=key[0], ticker=observation.ticker, cash_before=state.cash,
                        cash_delta=-float(debit), reason='DIVIDEND_CASH_CORRECTED',
                        detail={**detail, 'amount': -float(debit), 'accrued_session': published.session})
                    state.cash = correction.cash_after
        audit.append({'security_id': key[0], 'ticker': observation.ticker, **detail})
        if delta is not None and delta > 0:
            amount = float(delta)
            ledger.receivables.append({'security_id': key[0], 'ticker': observation.ticker,
                'amount': amount, 'accrued_session': key[1], 'due_in': int(lag)})
            ledger.post(session=published.session, event_type=EventType.DIVIDEND_ACCRUED,
                security_id=key[0], ticker=observation.ticker, cash_before=state.cash,
                reason='LATE_DIVIDEND_ACCRUED', detail={**detail, 'amount': amount, 'due_in': int(lag)})
    return {'policy': POLICY, 'input_sha256': digest(inputs),
            'observations': audit, 'pending': value.pending,
            'source_observations': value.source_observations,
            'legacy_floors': [row.model_dump(mode='json') for row in value.legacy_floors]}


def observations(previous, current, *, cursor, pending=None, retained=None, knowledge=None, floors=None):
    """Latest explicit ex-date totals; an absent row alone cancels nothing."""
    def totals(refs):
        result = {}
        for _, payload, _ in refs.actions:
            if payload['action'].lower() != 'dividend' or payload['date'] > cursor:
                continue
            try:
                amount = Decimal(str(payload['value']))
                if not amount.is_finite() or amount <= 0 or not isfinite(float(amount)) or float(amount) <= 0:
                    raise ValueError
            except (InvalidOperation, ValueError, OverflowError):
                if pending is not None:
                    pending.append({'ticker': payload['ticker'], 'ex_date': payload['date'],
                        'reason': 'CASH_DISTRIBUTION_TERMS_PENDING', 'source_sha256': digest(payload)})
                continue
            sid = refs.resolver.resolve(payload['ticker'], payload['date'])
            if sid is None:
                if pending is not None:
                    pending.append({'ticker': payload['ticker'], 'ex_date': payload['date'],
                                    'reason': 'CASH_DISTRIBUTION_IDENTITY_UNRESOLVED'})
                continue
            key = (sid, payload['date'])
            before = result.get(key, (payload['ticker'], Decimal(0), []))
            result[key] = (payload['ticker'], before[1] + amount, before[2] + [payload])
        return result
    retained = retained or {}
    latest = {(row['security_id'], row['entitlement_date']):
              (row.get('ticker', ''), Decimal(row['per_share']), [row])
              for row in retained.get('observations', [])}
    latest.update({**totals(previous), **totals(current)})
    legacy = {(row['security_id'], row['ex_date']):
              (row['ticker'], Decimal(row['per_share']), row['source_sha256'])
              for row in retained.get('legacy_floors', [])}
    if not getattr(previous, 'cash_observations', []):
        for key, (ticker, amount, rows) in totals(previous).items():
            legacy.setdefault(key, (ticker, amount, digest(rows)))
    # A native event outside retained price coverage is still knowledge. Its
    # dated identity must be provable before it can create shadow money.
    native = {item['id']: (None, item) for item in retained.get('source_observations', [])}
    blocked = set()
    for refs in (previous, current):
        for item in getattr(refs, 'cash_observations', []):
            if item['date'] <= cursor:
                prior = native.get(item['id'])
                if prior and (prior[1]['ticker'], prior[1]['date']) != (item['ticker'], item['date']):
                    if pending is not None:
                        pending.append({'id': item['id'], 'reason': 'CASH_DISTRIBUTION_IDENTITY_CHANGED'})
                    blocked.add((item['ticker'], item['date']))
                    continue
                sid = prior[1].get('security_id') if prior else None
                native[item['id']] = (refs, {**item, **({'security_id': sid} if sid else {})})
    grouped = {}
    captured = []
    for _, (refs, item) in sorted(native.items()):
        sid = item.get('security_id') or (refs or current).resolver.resolve(item['ticker'], item['date'])
        captured.append({**item, **({'security_id': sid} if sid else {})})
        if sid is None:
            if pending is not None:
                pending.append({'id': item['id'], 'ticker': item['ticker'], 'ex_date': item['date'],
                                'reason': 'CASH_DISTRIBUTION_IDENTITY_UNRESOLVED'})
            continue
        key = (sid, item['date'])
        before = grouped.get(key, (item['ticker'], Decimal(0), []))
        grouped[key] = (item['ticker'], before[1] + Decimal(item['rate']), before[2] + [item])
    latest = {key: row for key, row in latest.items() if (row[0], key[1]) not in blocked}
    # Native identities preserve omitted payments across window expiry. Legacy
    # aggregate knowledge likewise survives absence without cancelling money.
    latest.update(grouped)
    for key, (ticker, amount, sha) in legacy.items():
        if key in grouped and grouped[key][1] < amount:
            latest[key] = (ticker, amount, [{'legacy_source_sha256': sha}])
            if pending is not None:
                pending.append({'security_id': key[0], 'ex_date': key[1],
                                'reason': 'CASH_DISTRIBUTION_NATIVE_COMPONENTS_UNKNOWN'})
    if knowledge is not None:
        knowledge.extend(captured)
    if floors is not None:
        floors.extend(Observation(security_id=sid, ticker=ticker, ex_date=day,
            per_share=amount, source_sha256=sha) for (sid, day), (ticker, amount, sha) in sorted(legacy.items()))
    return [Observation(security_id=sid, ticker=ticker, ex_date=day,
                        per_share=amount, source_sha256=digest({'actions': rows,
                            'native': [item for item in getattr(current, 'cash_observations', [])
                                       if item['ticker'] == ticker and item['date'] == day]}))
            for (sid, day), (ticker, amount, rows) in sorted(latest.items())]
