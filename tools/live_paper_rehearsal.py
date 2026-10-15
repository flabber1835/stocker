"""Attended, owner-authorized paper API rehearsal; never a production route.

Uses Sentinel's actual adapter and command recovery. The one limit-order probe
is provider testing only: production's market-order contract is unchanged.
Requires production automation to remain disabled and killed at every mutation.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
from decimal import Decimal
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import time
import threading
from urllib.parse import urlsplit
import uuid

import httpx

from sentinel.execution.alpaca import AlpacaExecutionBroker
from sentinel.execution.commands import Command
from sentinel.execution.contract import Side
from sentinel.execution.identity import CommandIdentity, DeploymentIdentity
from sentinel.execution import recovery
from sentinel.execution.states import CommandState
from sentinel.feed import store

PAPER = 'https://paper-api.alpaca.markets'


class Refused(RuntimeError):
    pass


def decimal(value):
    result = Decimal(str(value))
    if not result.is_finite():
        raise Refused('nonfinite provider number')
    return result


class Ledger:
    def __init__(self, root, *, resume=False):
        root.mkdir(parents=True, exist_ok=resume)
        self.path = root/'events.jsonl'
        self.root = root
        self.lock = threading.Lock()

    def record(self, event, **evidence):
        value = dict(at=datetime.now(timezone.utc).isoformat(), event=event, **evidence)
        with self.lock:
            with self.path.open('a') as stream:
                stream.write(json.dumps(value, sort_keys=True, default=str)+'\n')
                stream.flush()
                os.fsync(stream.fileno())
            print(json.dumps(value, default=str), flush=True)


class AttendedRun:
    def __init__(self, *, output, account_sha256, maximum, resume=False):
        if not maximum.is_finite() or not Decimal(0) < maximum <= Decimal(5000):
            raise Refused('approved maximum is USD5000')
        if re.fullmatch('[0-9a-f]{64}', account_sha256) is None:
            raise Refused('expected bound paper account digest is required')
        self.maximum = maximum
        self.account_sha256 = account_sha256
        self.run_id = uuid.uuid4().hex
        self.ledger = Ledger(output,resume=resume)
        self.keys = set()
        self.ids = set()
        self.asset_id = None
        self.owner_connection = None
        self.allowed_symbols = {'SPY'}
        self.asset_symbols = {}
        self.quantities = {}
        self.allow_batch = False
        self.crash_after_accept = False
        self.drop_ack = False
        self.dropped = False
        self.started = datetime.now(timezone.utc)
        self.buy_window_open = False
        self.last_request = 0.0
        self.pacing_lock = asyncio.Lock()
        self.headers = {'APCA-API-KEY-ID':os.environ['ALPACA_API_KEY'],
                        'APCA-API-SECRET-KEY':os.environ['ALPACA_SECRET_KEY']}
        self.lock = (output.parent/('paper-account-'+account_sha256+'.lock')).open('a')
        fcntl.flock(self.lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    async def pace(self):
        async with self.pacing_lock:
            delay=0.4-(time.monotonic()-self.last_request)
            if delay>0:
                await asyncio.sleep(delay)
            self.last_request=time.monotonic()

    def production_fenced(self):
        if self.owner_connection is None:
            raise Refused('exclusive attended account owner is required')
        # A lost session also loses the exclusive test-owner lock. Never
        # silently reconnect and continue a previously authorized send.
        inherited=os.getpid()!=getattr(self,'owner_process_id',os.getpid())
        if not inherited:
            self.owner_connection.execute('SELECT 1')
        c = store.connect(os.environ['REHEARSAL_PRODUCTION_DATABASE_URL'],
                          connect_timeout=3, statement_timeout_ms=3000)
        try:
            c.execute('BEGIN TRANSACTION READ ONLY')
            if inherited:
                key=self.owner_key & ((1<<64)-1)
                present=c.execute("SELECT EXISTS(SELECT 1 FROM pg_locks l JOIN pg_stat_activity a ON a.pid=l.pid "
                    "WHERE l.pid=%s AND a.backend_start=%s AND l.locktype='advisory' AND l.granted "
                    "AND l.mode='ExclusiveLock' AND l.objsubid=1 AND l.classid::bigint=%s AND l.objid::bigint=%s "
                    "AND l.database=(SELECT oid FROM pg_database WHERE datname=current_database()))",
                    (self.owner_backend_pid,self.owner_backend_start,key>>32,key & ((1<<32)-1))).fetchone()[0]
                if not present:raise Refused('parent attended account owner was lost')
            row = c.execute('SELECT a.enabled,a.kill_switch_engaged,b.broker,b.broker_account_id '
                'FROM sentinel_automation_control a CROSS JOIN sentinel_account_binding b '
                'WHERE a.id=1').fetchall()
            if (len(row)!=1 or row[0][:3]!=(False,True,'alpaca') or
                    hashlib.sha256(row[0][3].encode()).hexdigest()!=self.account_sha256):
                raise Refused('production must be disabled, killed and bound to approved paper account')
        finally:
            c.rollback()
            c.close()

    def acquire_owner(self):
        key=int.from_bytes(hashlib.sha256(('sentinel.attended.paper:'+self.account_sha256).encode()).digest()[:8],
                           byteorder='big',signed=True)
        self.owner_connection=store.connect(os.environ['REHEARSAL_PRODUCTION_DATABASE_URL'],
                                            connect_timeout=3,statement_timeout_ms=3000)
        if not self.owner_connection.execute('SELECT pg_try_advisory_lock(%s)',(key,)).fetchone()[0]:
            self.owner_connection.close()
            self.owner_connection=None
            raise Refused('another attended test owns this paper account')
        self.owner_process_id=os.getpid()
        self.owner_key=key
        self.owner_backend_pid,self.owner_backend_start=self.owner_connection.execute(
            'SELECT pid,backend_start FROM pg_stat_activity WHERE pid=pg_backend_pid()').fetchone()
        self.owner_connection.commit()

    async def read(self, path, params=None):
        await self.pace()
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(PAPER+path, headers=self.headers, params=params)
            response.raise_for_status()
            return response.json(parse_float=Decimal)

    async def snapshot(self):
        account, positions, orders, clock = await asyncio.gather(
            self.read('/v2/account'), self.read('/v2/positions'),
            self.read('/v2/orders',{'status':'open','limit':500}),self.read('/v2/clock'))
        identity = account.get('account_number') or account.get('id')
        if hashlib.sha256(str(identity).encode()).hexdigest()!=self.account_sha256:
            raise Refused('provider account differs from approved bound account')
        if (account.get('status')!='ACTIVE' or decimal(account['multiplier'])!=1 or
                any(account.get(k) for k in ('trading_blocked','account_blocked','trade_suspended_by_user'))):
            raise Refused('paper account is not active, cash-only and unblocked')
        if not clock.get('is_open'):
            raise Refused('rehearsal permits actual regular-session trading only')
        close=datetime.fromisoformat(clock['next_close'].replace('Z','+00:00'))
        self.buy_window_open=(close-datetime.now(timezone.utc)).total_seconds()>600
        if any(o.get('client_order_id') not in self.keys for o in orders):
            raise Refused('unattributed working order; no new test mutation permitted')
        if any(p['symbol'] not in self.allowed_symbols or decimal(p['qty'])<0 for p in positions):
            raise Refused('unexpected or short position; no new test mutation permitted')
        exposure = sum((abs(decimal(p['market_value'])) for p in positions),Decimal(0))
        return account, positions, orders, exposure

    async def quote(self, symbol='SPY'):
        if symbol not in self.allowed_symbols:
            raise Refused('quote outside approved test instruments')
        await self.pace()
        async with httpx.AsyncClient(timeout=15) as client:
            response=await client.get('https://data.alpaca.markets/v2/stocks/'+symbol+'/quotes/latest',
                                      headers=self.headers,params={'feed':'iex'})
            response.raise_for_status()
            q=response.json(parse_float=Decimal)['quote']
        bid,ask=decimal(q['bp']),decimal(q['ap'])
        stamp=datetime.fromisoformat(q['t'].replace('Z','+00:00'))
        age=(datetime.now(timezone.utc)-stamp).total_seconds()
        if not (0 <= age <= 30 and 0 < bid <= ask):
            raise Refused(f'fresh positive noncrossed test quote unavailable: {symbol}, age={age:.1f}s')
        return bid,ask

    async def authorize(self, method, url, body):
        target=urlsplit(str(url))
        if target.scheme!='https' or target.netloc!='paper-api.alpaca.markets':
            raise Refused('test mutation destination must be Alpaca PAPER')
        self.production_fenced()
        if method=='DELETE':
            if target.path.removeprefix('/v2/orders/') not in self.ids:
                raise Refused('may cancel only this run\'s known order IDs')
            await self.snapshot()
            return
        if method!='POST' or target.path!='/v2/orders':
            raise Refused('unsupported test mutation')
        account,positions,orders,exposure=await self.snapshot()
        symbols={**self.asset_symbols, 'SPY':'SPY'}
        if self.asset_id: symbols[self.asset_id]='SPY'
        symbol=symbols.get(body.get('symbol'))
        if (symbol not in self.allowed_symbols
                or body.get('client_order_id') not in self.keys):
            raise Refused('unattributed test instrument/command')
        qty=decimal(body['qty'])
        if (body.get('type') not in {'market','limit'} or body.get('order_class','simple')!='simple'
                or set(body)-{'symbol','qty','side','type','time_in_force','client_order_id',
                              'extended_hours','order_class','limit_price'}):
            raise Refused('unsupported test order shape')
        expected=self.quantities.get(body.get('client_order_id'),Decimal(1))
        if (qty!=expected or qty<=0 or qty!=qty.to_integral_value()
                or body.get('time_in_force')!='day' or body.get('extended_hours') is not False):
            raise Refused('rehearsal only permits approved whole-share quantities, DAY, regular hours')
        if orders and not self.allow_batch:
            raise Refused('settle or cancel working test orders before another submit')
        held=sum((decimal(p['qty']) for p in positions if p['symbol']==symbol),Decimal(0))
        if body.get('side')=='sell':
            if held<qty:
                raise Refused('test sell cannot create a short')
        elif body.get('side')=='buy':
            if not self.buy_window_open:
                raise Refused('new test purchases stop ten minutes before the actual close')
            _,ask=await self.quote() if symbol=='SPY' else await self.quote(symbol)
            reserve=(decimal(body['limit_price']) if body.get('type')=='limit' else ask*Decimal('1.25'))*qty
            working=Decimal(0)
            for order in orders:
                if order['side']=='buy':
                    _,price=await self.quote(order['symbol'])
                    working+=(decimal(order['qty'])-decimal(order['filled_qty']))*price*Decimal('1.25')
            if reserve<=0 or exposure+working+reserve>self.maximum or working+reserve>decimal(account['cash']):
                raise Refused('test buy exceeds approved exposure/cash envelope')
        else:
            raise Refused('unrecognized test side')

    def provider(self):
        run=self
        class CheckedClient(httpx.AsyncClient):
            async def request(self, method, url, **kwargs):
                method=method.upper()
                if method not in {'GET','POST','DELETE'}:
                    raise Refused('unsupported HTTP method')
                target=urlsplit(str(url))
                if target.scheme!='https' or target.netloc!='paper-api.alpaca.markets':
                    raise Refused('adapter may access only Alpaca PAPER')
                body=kwargs.get('json') or {}
                if method!='GET':
                    await run.authorize(method,url,body)
                await run.pace()
                if method!='GET':
                    run.ledger.record('transport_start',method=method,path=target.path,
                                      client_key=body.get('client_order_id'))
                response=await super().request(method,url,**kwargs)
                if method!='GET':
                    data=response.json() if response.content else {}
                    if method=='POST' and response.status_code in (200,201):
                        run.ids.add(data['id'])
                    run.ledger.record('provider_mutation',method=method,path=target.path,
                        status=response.status_code,client_key=body.get('client_order_id'),
                        order={k:data.get(k) for k in ('id','symbol','side','qty','status','filled_qty','filled_avg_price')})
                    crash_marker=run.ledger.root/'accepted-crash-injected.json'
                    if (method=='POST' and response.status_code in (200,201)
                            and run.crash_after_accept and not crash_marker.exists()):
                        with crash_marker.open('x') as stream:
                            json.dump({'client_key':body['client_order_id'],'at':datetime.now(timezone.utc).isoformat()},stream)
                            stream.flush();os.fsync(stream.fileno())
                        run.ledger.record('injected_process_death_before_journal_ack',client_key=body['client_order_id'])
                        os._exit(75)
                    if method=='POST' and response.status_code in (200,201) and run.drop_ack:
                        run.drop_ack=False
                        run.dropped=True
                        run.ledger.record('injected_acknowledgement_loss',client_key=body['client_order_id'])
                        raise httpx.ReadTimeout('attended rehearsal discarded accepted acknowledgement')
                return response
        return type('CheckedHttp',(),{'AsyncClient':CheckedClient})

    def command(self, instrument, scenario, side):
        cmd=Command(identity=CommandIdentity(
            DeploymentIdentity('paper-rehearsal-'+self.run_id,'alpaca',self.account_id,1),
            scenario,instrument.security_id),instrument=instrument,side=side,quantity=Decimal(1))
        self.keys.add(cmd.client_key)
        return cmd

    async def settle(self, broker, cmd):
        deadline=time.monotonic()+60
        while time.monotonic()<deadline:
            # Ordinary current observation plus positive, identity-bound exact
            # lookup proves this run's individual command. Do not advertise the
            # adapter's deliberately disabled restore-grade history capability.
            observed=await broker.observe()
            if not observed.is_complete:
                self.ledger.record('observation_incomplete',completeness=observed.completeness.value)
                await asyncio.sleep(2)
                continue
            if recovery.needs_resolution(cmd):
                cmd=await recovery.resolve_indeterminate(broker,cmd,observed)
            else:
                exact=await broker.find_by_client_key(cmd.client_key)
                if exact.order is not None:
                    # Use the same positive-identity validation as UNKNOWN
                    # recovery before applying terminal evidence.
                    recovery._assert_order_matches_command(cmd,exact.order,where='attended exact lookup')
                    cmd=cmd.transition(exact.order.state,broker_order_id=exact.order.broker_order_id,
                        filled_quantity=exact.order.filled_quantity,
                        filled_average_price=exact.order.filled_average_price)
            cmd=recovery.apply_observation(cmd,observed)
            self.ledger.record('command_observed',key=cmd.client_key,state=cmd.state.value,
                filled_quantity=str(cmd.filled_quantity),price=str(cmd.filled_average_price))
            if cmd.state in {CommandState.FILLED,CommandState.CANCELLED,CommandState.REJECTED}:
                return cmd
            await asyncio.sleep(1)
        raise Refused('test order did not reach terminal state; preserve identity and resolve before new submits')

    async def market(self, broker, instrument, scenario, side, *, lose_ack=False):
        cmd=recovery.prepare_send(self.command(instrument,scenario,side))
        self.ledger.record('durable_send_pending',key=cmd.client_key,scenario=scenario,side=side.value)
        self.drop_ack=lose_ack
        cmd=await recovery.dispatch(broker,cmd)
        self.ledger.record('submit_outcome',key=cmd.client_key,state=cmd.state.value,detail=cmd.detail)
        if lose_ack and (not self.dropped or cmd.state is not CommandState.UNKNOWN):
            raise Refused('accepted acknowledgement loss was not exercised')
        cmd=await self.settle(broker,cmd)
        if cmd.state is not CommandState.FILLED or cmd.filled_quantity!=1:
            raise Refused('market test did not fill exactly one share')
        return cmd

    async def run(self):
        self.acquire_owner()
        self.production_fenced()
        account,positions,orders,_=await self.snapshot()
        if positions or orders:
            raise Refused('attended test must start with a flat account and no orders')
        self.account_id=str(account.get('account_number') or account['id'])
        broker=AlpacaExecutionBroker(api_key=os.environ['ALPACA_API_KEY'],
            secret_key=os.environ['ALPACA_SECRET_KEY'],base_url=PAPER,http_provider=self.provider)
        instrument=await broker.resolve_instrument(security_id='SPY',symbol='SPY')
        self.asset_id=instrument.broker_id
        self.ledger.record('started',account_sha256=self.account_sha256,maximum_open_usd=str(self.maximum),
                           run_id=self.run_id,production_fenced=True)
        try:
            buy=await self.market(broker,instrument,'market-buy',Side.BUY)
            self.ledger.record('scenario_pass',scenario='market_buy_and_terminal_fill')
            await self.market(broker,instrument,'market-sell',Side.SELL)
            self.ledger.record('scenario_pass',scenario='market_sell_and_terminal_fill')
            bid,_=await self.quote()
            limit=(bid*Decimal('0.80')).quantize(Decimal('0.01'))
            probe=self.command(instrument,'resting-limit-cancel',Side.BUY)
            body={'symbol':'SPY','qty':'1','side':'buy','type':'limit','time_in_force':'day',
                  'limit_price':str(limit),'client_order_id':probe.client_key,'extended_hours':False}
            self.ledger.record('durable_limit_probe',key=probe.client_key,body=body)
            async with self.provider().AsyncClient(timeout=20) as client:
                response=await client.post(PAPER+'/v2/orders',headers=self.headers,json=body)
                response.raise_for_status()
                order=response.json()
            cancel=await broker.cancel(order['id'])
            self.ledger.record('cancel_outcome',order_id=order['id'],state=cancel.state.value)
            deadline=time.monotonic()+45
            while time.monotonic()<deadline:
                found=await self.read('/v2/orders/'+order['id'])
                if found['status'] in {'canceled','expired','filled','rejected'}:
                    break
                await asyncio.sleep(1)
            if found['status']!='canceled' or decimal(found['filled_qty'])!=0:
                raise Refused('resting cancellation was not confirmed without a fill')
            self.ledger.record('scenario_pass',scenario='resting_limit_cancel_confirmed',order_id=order['id'])
            await self.market(broker,instrument,'accepted-ack-lost',Side.BUY,lose_ack=True)
            self.ledger.record('scenario_pass',scenario='accepted_unknown_exact_key_recovery')
            await self.market(broker,instrument,'recovered-position-sell',Side.SELL)
            self.ledger.record('scenario_pass',scenario='recovered_position_closed')
        finally:
            self.drop_ack=False
            # Only this run's attributable effects can be cleaned up. Unknown
            # foreign activity refuses rather than issuing a blanket liquidation.
            _,positions,orders,_=await self.snapshot()
            for order in orders:
                await broker.cancel(order['id'])
            if orders:
                await asyncio.sleep(2)
            _,positions,orders,_=await self.snapshot()
            if orders:
                raise Refused('test working orders remain; no cleanup sale permitted')
            if positions:
                qty=sum((decimal(p['qty']) for p in positions),Decimal(0))
                if qty!=1:
                    raise Refused('unexpected remaining quantity; preserve evidence for attended recovery')
                await self.market(broker,instrument,'cleanup-sell',Side.SELL)
        account,positions,orders,_=await self.snapshot()
        if positions or orders:
            raise Refused('test finished with unsettled effects')
        self.ledger.record('provider_rehearsal_complete',positions=0,working_orders=0,
            ending_cash=str(account['cash']),ending_equity=str(account['equity']),
            full_system_qualification='STILL_REQUIRED')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--account-sha256',required=True)
    parser.add_argument('--maximum-open-usd',type=Decimal,required=True)
    parser.add_argument('--confirm-owner-authorized-current-paper-account',action='store_true',required=True)
    args=parser.parse_args()
    asyncio.run(AttendedRun(output=args.output,account_sha256=args.account_sha256,
                           maximum=args.maximum_open_usd).run())


if __name__=='__main__':
    main()
