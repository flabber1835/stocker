"""Independent generated broker state for current callback-death qualification.

Native-shaped observations are simulation only. Business time is explicitly
synthetic; database leases and the callback supervisor retain their real clocks.
Only the owned callback can signal itself. No provider/network fallback exists.
"""
from __future__ import annotations

from contextlib import closing, contextmanager
from decimal import Decimal
import json
import multiprocessing
from multiprocessing.managers import BaseManager
import os
from pathlib import Path
import signal
import threading
import time
import uuid

from tools.opening_gateway_qualification import Response
from tests.support.current_workflow_transport import NativeWorkflowAlpaca


def kill_owned_callback(*, parent_pid: int) -> None:
    """The fault hook cannot target the test, provider or another process."""
    assert os.getpid() != parent_pid
    assert multiprocessing.current_process().name.startswith('sentinel-callback-')
    os.kill(os.getpid(), signal.SIGKILL)
    raise AssertionError('SIGKILL returned')  # pragma: no cover


class DurableWorkflowAlpaca(NativeWorkflowAlpaca):
    def __init__(self, *, state_path: Path, clock, **kwargs):
        super().__init__(**kwargs)
        self.state_path, self.clock = state_path, clock
        self.first_key = None
        self.faults = []
        self._lock = threading.RLock()
        self._persist()

    def _persist(self):
        material = {'schema': 'isolated.current-callback-provider/1',
                    'scope': 'PRIVATE_SIMULATION_SYNTHETIC_BUSINESS_CLOCK',
                    'provider_pid': os.getpid(), 'business_time': self.clock.now().isoformat(),
                    'first_key': self.first_key, 'faults': self.faults, 'state': self.state()}
        temporary = self.state_path.with_suffix('.pending')
        with temporary.open('w', encoding='utf-8', newline='\n') as stream:
            json.dump(material, stream, sort_keys=True, separators=(',', ':'), allow_nan=False)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self.state_path)
        directory = os.open(self.state_path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        return material

    def snapshot(self):
        with self._lock:
            return self._persist()

    def set_clock(self, instant):
        with self._lock:
            self.clock.instant = instant
            if self.started is None:
                self.started = time.monotonic()
            self._persist()

    def record_fault(self, point, callback_pid, client_key):
        with self._lock:
            assert point in {'ACCEPTED_PARTIAL_BEFORE_RESPONSE', 'BEFORE_FILLED_PERSISTENCE'}
            assert callback_pid != os.getpid()
            assert client_key == self.first_key
            self.faults.append({'point': point, 'callback_pid': callback_pid, 'client_key': client_key})
            self._persist()

    def _fill(self, order, amount):
        quantity, filled = Decimal(order['qty']), Decimal(order['filled_qty'])
        amount = Decimal(amount)
        assert order['side'] == 'buy' and 0 < amount <= quantity - filled
        price = Decimal(order['limit_price'])
        assert self.cash >= amount * price
        self.cash -= amount * price
        self.positions[order['asset_id']] = self.positions.get(order['asset_id'], Decimal(0)) + amount
        filled += amount
        stamp = self.clock.now().isoformat()
        order.update(filled_qty=str(filled), filled_avg_price=str(price), updated_at=stamp,
                     status='filled' if filled == quantity else 'partially_filled',
                     filled_at=stamp if filled == quantity else None)
        index = len(self.events) + 1
        self.events.append({
            'account_id': self.account_uuid, 'at': stamp, 'event_id': f'01OPENING{index:018d}',
            'ref_id': str(uuid.uuid5(uuid.NAMESPACE_URL, f'{order["id"]}:fill:{index}')),
            'status': 'executed', 'executed_at': stamp, 'settle_date': stamp[:10],
            'activity_type': 'TRD', 'activity_subtype': None, 'previous_id': None,
            'qty': str(amount), 'price': str(price), 'net_amount': str(-amount * price), 'currency': 'USD',
            'details': {'execution_type': 'fill', 'order_id': order['id'], 'asset_id': order['asset_id'],
                        'symbol': order['symbol'], 'side': 'buy', 'client_order_id': order['client_order_id']}})

    def complete_first(self):
        with self._lock:
            order = next(row for row in self.orders.values() if row['client_order_id'] == self.first_key)
            assert order['status'] == 'partially_filled'
            self._fill(order, Decimal(order['qty']) - Decimal(order['filled_qty']))
            self._persist()

    def get(self, url, params):
        path = self.path(url)
        if path == '/v2/account/activities/FILL':
            self.requests['GET ' + path] += 1
            order = self.orders[params['order_id']]
            events = [event for event in self.events if event['details']['order_id'] == order['id']]
            return Response([{
                'id': event['ref_id'], 'activity_type': 'FILL', 'account_id': self.account_uuid,
                'order_id': order['id'], 'asset_id': order['asset_id'], 'symbol': order['symbol'],
                'side': order['side'], 'qty': event['qty'], 'price': event['price'],
                'transaction_time': event['executed_at'], 'client_order_id': order['client_order_id'],
            } for event in events])
        result = super().get(url, params)
        if path == '/v2/account':
            remaining = sum(((Decimal(row['qty']) - Decimal(row['filled_qty'])) * Decimal(row['limit_price'])
                             for row in self.orders.values()
                             if row['side'] == 'buy' and row['status'] in {'new', 'partially_filled'}), Decimal(0))
            result.payload['buying_power'] = str(max(Decimal(0), self.cash - remaining))
        return result

    def request(self, method, url, parameters, callback_pid):
        with self._lock:
            kill = False
            if method == 'GET':
                result = self.get(url, parameters)
            else:
                assert method == 'POST'
                if self.first_key is None:
                    assert parameters['side'] == 'buy' and Decimal(parameters['qty']) >= 2
                    asset = self.by_id[parameters['symbol']]
                    original_price = asset['price']
                    # First accept a working protected order, then fill one
                    # whole share independently before its response is lost.
                    self.marketable_limit_fills = False
                    asset['price'] = Decimal(parameters['limit_price']) * 2
                    try:
                        result = super().post(url, parameters)
                    finally:
                        asset['price'] = original_price
                        self.marketable_limit_fills = True
                    self.first_key = parameters['client_order_id']
                    self._fill(result.payload, Decimal(1))
                    self.record_fault('ACCEPTED_PARTIAL_BEFORE_RESPONSE', callback_pid, self.first_key)
                    kill = True
                else:
                    result = super().post(url, parameters)
                self._persist()
            return {'payload': result.payload, 'text': result.text,
                    'status': result.status_code, 'kill_before_response': kill}


@contextmanager
def independent_provider(*, state_path, clock, **kwargs):
    """Fresh forked provider outlives both owned callback deaths."""
    class Manager(BaseManager):
        pass
    Manager.register('Provider', lambda: DurableWorkflowAlpaca(state_path=state_path, clock=clock, **kwargs),
                     exposed=('request', 'snapshot', 'set_clock', 'complete_first', 'record_fault'))
    manager = Manager(ctx=multiprocessing.get_context('fork'), shutdown_timeout=5)
    manager.start()
    try:
        yield manager.Provider(), manager._process.pid
    finally:
        manager.shutdown()


class ProxyTransport:
    """RPC only; the adapter sees the usual local HTTP response shape."""
    def __init__(self, provider, *, parent_pid):
        class Client:
            def __init__(self, **_kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return False

            async def get(self, url, headers=None, params=None):
                value = provider.request('GET', url, dict(params or {}), os.getpid())
                return Response(value['payload'], text=value['text'], status=value['status'])

            async def post(self, url, headers=None, json=None):
                value = provider.request('POST', url, dict(json or {}), os.getpid())
                if value['kill_before_response']:
                    kill_owned_callback(parent_pid=parent_pid)
                return Response(value['payload'], text=value['text'], status=value['status'])

            async def delete(self, *_args, **_kwargs):
                raise AssertionError('private callback fault campaign does not cancel orders')
        self.AsyncClient = Client


@contextmanager
def fenced_private_control(dsn, provider):
    """Always withdraw permission in this generated database, using a fresh owner."""
    from sentinel.automation import store as automation_store
    from sentinel.automation.model import StaleLeaderRefused
    from sentinel.feed import store
    owned = {'permit': None}
    try:
        yield owned
    except BaseException:
        try:
            print('PRIVATE_CALLBACK_FAILURE_EVIDENCE=' + json.dumps(provider.snapshot(),
                sort_keys=True, separators=(',', ':'), allow_nan=False), flush=True)
        except Exception as exc:
            print('PRIVATE_CALLBACK_EVIDENCE_UNAVAILABLE=' + type(exc).__name__, flush=True)
        raise
    finally:
        with closing(store.connect(dsn, connect_timeout=3, statement_timeout_ms=5000)) as fence:
            assert fence.info.dbname.startswith('operational_'), 'only a generated test database may be fenced'
            if owned['permit'] is not None:
                try:
                    automation_store.release_lease(fence, permit=owned['permit'])
                except StaleLeaderRefused:
                    # Expiry/fencing is not permission to recreate a lease.
                    fence.rollback()
            current = automation_store.load_control(fence)
            fence.rollback()
            if current.enabled:
                automation_store.deactivate(fence, actor='ISOLATED_QUALIFICATION',
                    reason='private callback fault campaign completed or refused')
            elif not current.kill_switch_engaged:
                automation_store.engage_kill(fence, actor='ISOLATED_QUALIFICATION',
                    reason='private callback fault campaign completed or refused')
            current = automation_store.load_control(fence)
            assert not current.enabled and current.kill_switch_engaged
            assert fence.execute('SELECT holder_id FROM sentinel_automation_lease WHERE id=1').fetchone() == (None,)
            fence.rollback()
            print('PRIVATE_CALLBACK_CONTROL_FENCED=true', flush=True)
