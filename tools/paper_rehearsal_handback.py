"""Attended return of an authorized paper rehearsal; never broker mutation.

Retires only a terminal, never-sent production plan after native flatness and
test cash flow are proved. The canonical book and old plan economics survive.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from fractions import Fraction
import json
import os
from pathlib import Path
import re

from pydantic import BaseModel, ConfigDict, Field
from sentinel import binding
from sentinel.automation import store as automation_store
from sentinel.execution import journal
from sentinel.execution.numeric import exact_decimal
from sentinel.feed import publication, store
from sentinel.feed.rolling_contract import digest
from tools.live_paper_rehearsal import AttendedRun, Refused

SCHEMA = 'sentinel.attended-paper-handback/1'
TOLERANCE = Fraction(1)  # Existing paper cash explanation tolerance.


class Request(BaseModel):
    model_config = ConfigDict(extra='forbid',frozen=True)
    expected_plan_id: str = Field(pattern=r'^sentinel-[0-9a-f]{64}$')
    account_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    since: datetime
    starting_cash: Decimal = Field(gt=0,allow_inf_nan=False)
    approved_client_keys: tuple[str,...]
    actor: str = Field(min_length=1,max_length=200)
    reason: str = Field(min_length=1,max_length=1000)


def qualify_orders(orders, approved_keys):
    """Positive native terminal evidence; returns exact signed fill cash flow."""
    if (not isinstance(orders,list) or not orders or len(orders)>=500
            or len(set(approved_keys))!=len(approved_keys)
            or any(not re.fullmatch(r'sntl-[0-9a-f]{20}',key) for key in approved_keys)):
        raise Refused('handback requires a bounded unique approved test-key set')
    seen, ids, shares, cash = set(),set(),{},Fraction(0)
    for order in orders:
        if not isinstance(order,dict): raise Refused('native test order is unreadable')
        key, native_id, asset = order.get('client_order_id'),order.get('id'),order.get('asset_id')
        if (key not in approved_keys or key in seen or not native_id or native_id in ids
                or not asset or not order.get('symbol')
                or order.get('status') not in {'filled','canceled','cancelled','expired','rejected'}
                or order.get('side') not in {'buy','sell'}):
            raise Refused('foreign, duplicate or nonterminal native test order')
        seen.add(key); ids.add(native_id)
        try:
            quantity, filled = Decimal(order['qty']),Decimal(order['filled_qty'])
            if (not quantity.is_finite() or quantity<=0 or quantity!=quantity.to_integral_value()
                    or not filled.is_finite() or not 0<=filled<=quantity
                    or filled!=filled.to_integral_value()
                    or (order['status']=='filled' and filled!=quantity)):
                raise ValueError('invalid whole shares')
            price = Decimal(order['filled_avg_price']) if filled else Decimal(0)
            if not price.is_finite() or (filled and price<=0): raise ValueError('invalid fill price')
        except (ArithmeticError,KeyError,TypeError,ValueError) as exc:
            raise Refused('native test fill is malformed') from exc
        sign = 1 if order['side']=='buy' else -1
        shares[asset] = shares.get(asset,Fraction(0))+sign*Fraction(filled)
        cash -= sign*Fraction(filled)*Fraction(price)
    if seen!=set(approved_keys) or any(shares.values()):
        raise Refused('test keys are incomplete or native test shares do not net to zero')
    return cash


def explain_cash(*, plan_cash, starting_cash, current_cash, native_cash_flow):
    if abs(Fraction(plan_cash)-Fraction(starting_cash))>TOLERANCE:
        raise Refused('starting test cash is unexplained by the unsent production plan')
    expected = Fraction(starting_cash)+native_cash_flow
    if abs(Fraction(current_cash)-expected)>TOLERANCE:
        raise Refused('current cash is unexplained by native test fills')
    return exact_decimal(expected)


def require_local(conn, request):
    control = automation_store.load_control(conn)
    if control.enabled or not control.kill_switch_engaged:
        raise Refused('production must be disabled and killed for handback')
    active = conn.execute('SELECT EXISTS(SELECT 1 FROM sentinel_automation_lease WHERE holder_id IS NOT NULL AND expires_at>clock_timestamp())').fetchone()[0]
    counts = conn.execute('SELECT (SELECT count(*) FROM sentinel_commands),(SELECT count(*) FROM sentinel_fills)').fetchone()
    if active or counts!=(0,0): raise Refused('handback requires no active lease or production trading history')
    plan = journal.latest_plan(conn)
    if plan is None or plan.plan_id!=request.expected_plan_id:
        raise Refused('the exact unsent handback plan is no longer current')
    bound = binding.require(conn)
    if bound.broker!='alpaca': raise Refused('handback is Alpaca paper only')
    if (plan.deployment_id,plan.broker,plan.broker_account_id,plan.takeover_epoch) != (
            bound.deployment_id,bound.broker,bound.broker_account_id,bound.takeover_epoch):
        raise Refused('handback plan belongs to another account incarnation')
    terminal = conn.execute("SELECT EXISTS(SELECT 1 FROM sentinel_automation_cycles WHERE plan_id=%s AND state IN ('SUPERSEDED','BLOCKED','MISSED_STATE_ONLY'))",(plan.plan_id,)).fetchone()[0]
    if not terminal: raise Refused('the old production cycle is not terminal')
    return plan


async def handback(args):
    if not args.confirm_retire_unsent_plan:
        raise Refused('explicit attended unsent-plan retirement confirmation is required')
    request = Request.model_validate_json(args.request.read_bytes())
    if request.since.utcoffset() is None or request.since>datetime.now(timezone.utc):
        raise Refused('handback requires an actual aware test interval')
    owner = AttendedRun(output=args.output,account_sha256=request.account_sha256,maximum=Decimal(5000))
    owner.acquire_owner();owner.production_fenced()
    with store.connect(os.environ['REHEARSAL_PRODUCTION_DATABASE_URL']) as conn:
        plan = require_local(conn,request)
    account = await owner.read('/v2/account')
    positions = await owner.read('/v2/positions')
    working = await owner.read('/v2/orders',{'status':'open','limit':500})
    orders = await owner.read('/v2/orders',{'status':'all','after':request.since.isoformat(),'limit':500,'direction':'asc'})
    final = await owner.read('/v2/account')
    account_id = final.get('account_number') or final.get('id')
    import hashlib
    if (positions or working or hashlib.sha256(str(account_id).encode()).hexdigest()!=request.account_sha256
            or str(account_id)!=plan.broker_account_id or account.get('id')!=final.get('id')
            or Decimal(account['cash'])!=Decimal(final['cash'])
            or Decimal(final['cash'])!=Decimal(final['equity'])
            or abs(Decimal(final['buying_power'])-Decimal(final['cash']))>Decimal(1)
            or Decimal(final['multiplier'])!=1 or final.get('status')!='ACTIVE'
            or any(final.get(k) is not False for k in ('trading_blocked','account_blocked','trade_suspended_by_user'))):
        raise Refused('native account is not stable, flat, cash-only and bound')
    flow = qualify_orders(orders,request.approved_client_keys)
    expected = explain_cash(plan_cash=plan.account_cash,starting_cash=request.starting_cash,
        current_cash=Decimal(final['cash']),native_cash_flow=flow)
    value = dict(schema=SCHEMA,authority_effect='RETIRE_UNSENT_PLAN_ONLY',actor=request.actor,reason=request.reason,
        plan_id=plan.plan_id,plan_fingerprint=plan.fingerprint(),shadow_snapshot_hash=plan.shadow_snapshot_hash,
        deployment_id=plan.deployment_id,broker_account_id=plan.broker_account_id,takeover_epoch=plan.takeover_epoch,
        since=request.since.isoformat(),starting_cash=str(request.starting_cash),native_fill_cash_flow=str(exact_decimal(flow)),
        expected_cash=str(expected),observed_cash=str(final['cash']),orders_sha256=digest(orders),
        native_order_count=len(orders),positions=0,working_orders=0,observed_at=datetime.now(timezone.utc).isoformat())
    signature = publication._receipt_hmac({'purpose':SCHEMA,'receipt':value})
    receipt = dict(value,receipt_hmac=signature)
    receipt_sha = digest(receipt)
    owner.production_fenced()
    with store.connect(os.environ['REHEARSAL_PRODUCTION_DATABASE_URL']) as conn, journal.writer_lock(conn):
        current = require_local(conn,request)
        if current.fingerprint()!=plan.fingerprint(): raise Refused('plan changed during native handback evidence')
        conn.execute('INSERT INTO sentinel_processed_sessions(cursor_name,session,state) VALUES(%s,%s,%s::jsonb)',
            ('attended-paper-handback:v1:'+receipt_sha,plan.decision_session,json.dumps(receipt,sort_keys=True)))
        journal.supersede_plan(conn,plan.plan_id,'attended-handback-'+receipt_sha)
    (args.output/'handback-receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
    (args.output/'native-orders-private.json').write_text(json.dumps(orders,indent=2)+'\n')
    print(json.dumps(dict(result='UNSENT_PLAN_RETIRED',receipt_sha256=receipt_sha,positions=0,working_orders=0,
        account_cash=final['cash'],native_order_count=len(orders),book_preserved=True)),flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--confirm-retire-unsent-plan',action='store_true')
    asyncio.run(handback(parser.parse_args()))


if __name__=='__main__': main()
