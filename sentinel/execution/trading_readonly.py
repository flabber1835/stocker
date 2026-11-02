"""URL-bound monitoring reads with fresh independent LIVE READ admission."""
from __future__ import annotations

import re
from uuid import UUID

from sentinel import binding, identity
from sentinel.authority import live_runtime, repository
from sentinel.authority.live import require_live_adapter_admission
from sentinel.authority.model import AuthorityRefused, RolloutMode
from sentinel.execution.alpaca import AlpacaCredentialsRefused, AlpacaExecutionBroker
from sentinel.trading_environment import TradingEndpoint, TradingEnvironment


class MonitoringReadRefused(AuthorityRefused):
    pass


def _uuid(value):
    try:
        return type(value) is str and str(UUID(value)) == value and UUID(value).int != 0
    except (ValueError, TypeError, AttributeError):
        return False


def _parameters(path, params):
    """Only the existing collectors' finite GET vocabulary reaches transport."""
    if type(path) is not str or params is not None and type(params) is not dict:
        raise MonitoringReadRefused("monitoring GET route or parameters refused")
    values = {} if params is None else dict(params)
    if path == "/v2/account":
        valid = not values
    elif path == "/v2/orders":
        valid = (set(values) == {"status", "limit", "nested"}
                 and values["status"] == "open" and values["nested"] is True
                 and type(values["limit"]) is int and 1 <= values["limit"] <= 500)
    elif path == "/v2/account/activities/FILL":
        valid = (set(values) in ({"order_id", "direction", "page_size"},
                                 {"order_id", "direction", "page_size", "page_token"})
                 and _uuid(values.get("order_id"))
                 and values.get("direction") in {"asc", "desc"}
                 and type(values.get("page_size")) is int and 1 <= values["page_size"] <= 100
                 and ("page_token" not in values or type(values["page_token"]) is str
                      and re.fullmatch(r"[A-Za-z0-9_.:-]{1,256}", values["page_token"]) is not None))
    else:
        valid = (path.startswith("/v2/orders/") and _uuid(path.removeprefix("/v2/orders/"))
                 and not values)
    if not valid:
        raise MonitoringReadRefused("monitoring GET route or parameters refused")
    return values


class _ReadTransport(AlpacaExecutionBroker):
    """Even the private adapter cannot dispatch a mutation."""

    def __init__(self, *, current, **kwargs):
        self._current = current
        admission, _verified = current()
        super().__init__(live_admission=admission, **kwargs)

    def _require_transport_authority(self, *, operation="READ", **_kwargs):
        if operation != "READ":
            raise MonitoringReadRefused("monitoring transport is GET-only")
        if TradingEndpoint.parse(self.base_url) != self._trading_endpoint:
            raise MonitoringReadRefused("LIVE monitoring origin changed after construction")
        # current() verifies the canonical admission while its fresh database
        # connection is open. Its context provider deliberately remains DB-bound;
        # reusing that provider after current() returns would reuse a closed DB.
        _admission, verified = self._current()
        return verified

    async def _get(self, path, params=None):
        values = _parameters(path, params)
        async with self._httpx.AsyncClient(timeout=15.0, follow_redirects=False) as client:
            first = self._require_transport_authority()
            response = await client.get(self.base_url + path, headers=self._headers(), params=values)
            if response.status_code in (401, 403):
                raise AlpacaCredentialsRefused("LIVE monitoring READ authority refused")
            response.raise_for_status()
            if len(response.content) > 8 * 1024 * 1024:
                raise MonitoringReadRefused("monitoring response exceeds byte bound")
            payload = response.json()
        last = self._require_transport_authority()
        if first.sha256 != last.sha256 or first.subject != last.subject:
            raise MonitoringReadRefused("LIVE monitoring authority changed during GET")
        if path == "/v2/account":
            account = self._account_identity(payload, broker=self.broker_namespace)
            if account.account_id != first.subject.account_id:
                raise MonitoringReadRefused("LIVE monitoring native account differs from binding")
        return payload


class TradingReadOnly:
    """Collector facade: no submit, cancel, close, or general transport methods."""

    __slots__ = ("__transport", "__endpoint", "__expected", "__config", "__factory")

    def __init__(self, *, config, connection_factory=None, http_provider=None):
        from sentinel.feed import store

        self.__endpoint = TradingEndpoint.parse(config.base_url)
        if self.__endpoint.environment is not TradingEnvironment.LIVE:
            raise MonitoringReadRefused("LIVE monitoring requires the exact LIVE origin")
        self.__config = config
        self.__factory = connection_factory or store.connect
        self.__expected = None
        self.__transport = _ReadTransport(current=self.__current,
            api_key=config.alpaca_key, secret_key=config.alpaca_secret,
            base_url=self.__endpoint.base_url, http_provider=http_provider)

    def __current(self):
        from sentinel.strategy import production_strategy

        conn = self.__factory(self.__config.database_url, connect_timeout=3, statement_timeout_ms=2000)
        try:
            owner = binding.require(conn)
            if not owner.is_owned or owner.broker != self.__endpoint.broker_namespace:
                raise MonitoringReadRefused("LIVE monitoring requires an owned alpaca-live binding")
            admission = live_runtime.load_live_adapter_admission(conn,
                base_url=self.__endpoint.base_url, runtime_identity=identity.rehearsal_identity(),
                strategy_identity=production_strategy()[1])
            verified = require_live_adapter_admission(admission,
                base_url=self.__endpoint.base_url, required_operation="READ")
            expected = (owner.deployment_id, owner.broker_account_id, owner.takeover_epoch)
            actual = (verified.subject.deployment_id, verified.subject.account_id,
                      verified.subject.takeover_epoch)
            if actual != expected:
                raise MonitoringReadRefused("LIVE monitoring certificate differs from current binding")
            rollout = repository.load_rollout_state(conn)
            if rollout.mode is RolloutMode.CONTROLLER and rollout.certificate_sha256 != verified.sha256:
                raise MonitoringReadRefused("LIVE monitoring rollout names another certificate")
            if self.__expected is None:
                self.__expected = verified.subject
            elif self.__expected != verified.subject:
                raise MonitoringReadRefused("LIVE monitoring durable subject changed")
            return admission, verified
        finally:
            conn.rollback()
            conn.close()

    def _require_config(self, config):
        if TradingEndpoint.parse(config.base_url) != self.__endpoint or config.database_url != self.__config.database_url:
            raise MonitoringReadRefused("LIVE monitoring reader belongs to another endpoint or database")

    async def identify_account(self):
        return await self.__transport.identify_account()

    async def account_snapshot(self):
        return await self.__transport.account_snapshot()

    async def _get(self, path, params=None):
        return await self.__transport._get(path, params)

    def _to_order(self, raw):
        return self.__transport._to_order(raw)


def live_monitoring_reader(config, reader=None):
    if reader is None:
        return TradingReadOnly(config=config)
    if type(reader) is not TradingReadOnly:
        raise MonitoringReadRefused("LIVE monitoring requires its authenticated GET-only facade")
    reader._require_config(config)
    return reader


def live_binding(conn, *, config):
    endpoint = TradingEndpoint.parse(config.base_url)
    owner = binding.load(conn)
    if (endpoint.environment is not TradingEnvironment.LIVE or owner is None
            or not owner.is_owned or owner.broker != endpoint.broker_namespace):
        raise MonitoringReadRefused("LIVE monitoring requires its exact owned alpaca-live binding")
    return owner.deployment_id, owner.broker, owner.broker_account_id, owner.takeover_epoch
