"""Independent cash collector during concurrent durable and native order transitions."""
import asyncio
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D
from types import SimpleNamespace

import pytest

from sentinel import binding, local_paper
from sentinel.config import SentinelConfig
from sentinel.execution import account_status, journal, observed_dollar_hold
from sentinel.execution.alpaca import AlpacaExecutionBroker
from sentinel.execution.market_buy_policy import FRACTIONAL_MODE
from sentinel.execution.states import CommandState as S
from sentinel.feed import calendar
from sentinel.panel import model, sources
from tests.sentinel.test_market_buy_policy import MARKET_ENV
from tests.sentinel.test_market_reservations import DEPLOY, book, command, database, enroll, pg, subject, transition
from tests.sentinel.test_order_terms_schema import _compiled


@pytest.mark.parametrize("fault", ["", "partial", "missing-filled", "foreign", "duplicate", "larger-gap", "partial-wrong",
                                   "unknown", "replaced", "wrong-symbol", "blocked", "moving", "damaged-journal"])
def test_native_hold_during_funded_dispatch(database, subject, monkeypatch, fault):
    for key, value in {**MARKET_ENV, local_paper.MODE_ENV: local_paper.MODE, local_paper.ACCOUNT_ENV: "PATEST",
                       "SENTINEL_PAPER_BUY_POLICY": FRACTIONAL_MODE, "ALPACA_BASE_URL":"https://paper-api.alpaca.markets"}.items():
        monkeypatch.setenv(key, value)
    deployment = binding.bind(database, deployment_id=DEPLOY.deployment_id, broker="alpaca", broker_account_id="PATEST").identity
    plan = replace(subject["plan"], broker_account_id=deployment.broker_account_id)
    plan = replace(plan, plan_id="sentinel-" + plan.fingerprint())
    journal.adopt_current_plan(database, plan)
    subject["projection"].plan_id = plan.plan_id
    subject["projection"].plan_fingerprint = plan.fingerprint()
    subject.update(plan=plan, deployment=deployment)
    now = calendar.session_window(plan.effective_session)[0] + timedelta(minutes=3)
    from tests.sentinel import test_market_reservations
    monkeypatch.setattr(test_market_reservations, "DEPLOY", deployment)
    first, working, pending = (command(plan, symbol, amount="20") for symbol in ("FIRST", "OPEN", "LATER"))
    with journal.writer_lock(database, recovery_only=True):
        enroll(database, (first, working, pending), subject,
               replace(book(), account_identity=replace(book().account_identity, account_id="PATEST")))
        for c in (first, working, pending):
            sent = transition(database, c, S.SEND_PENDING)
            if c is not pending:
                transition(database, sent, S.ACKNOWLEDGED, broker_order_id="id-"+c.security_id)
        database.commit()

    class Clocked:
        def __getattr__(self, name):
            return getattr(database, name)
        def execute(self, sql, *args):
            if sql == "SELECT clock_timestamp()":
                return SimpleNamespace(fetchone=lambda: (now,))
            return database.execute(sql, *args)

    def row(c, state, quantity, price):
        return dict(id="id-"+c.security_id, client_order_id=c.client_key, asset_id=c.instrument.broker_id,
            symbol=c.instrument.symbol, side="buy", qty=None, notional="20", filled_qty=quantity,
            filled_avg_price=price, status=state, submitted_at=now.isoformat(), type="market",
            order_class="simple", time_in_force="day", extended_hours=False)
    native_open = [row(working, "new", "0", None)]
    native_closed = [row(first, "filled", "2", "10")]
    if fault == "missing-filled":
        native_closed.clear()
    if fault == "foreign":
        native_open[0]["client_order_id"] = "foreign"
    if fault == "duplicate":
        native_open.append(native_open[0].copy())
    if fault == "replaced":
        native_open[0]["replaced_by"] = "another-order-id"
    if fault == "wrong-symbol":
        native_open[0]["symbol"] = "ALIEN"
    if fault in {"partial", "partial-wrong"}:
        native_open[0].update(status="partially_filled", filled_qty="0.5", filled_avg_price="10")
    if fault == "unknown":
        transition(database, replace(pending,state=S.SEND_PENDING), S.UNKNOWN)
        database.commit()
    payload = dict(id="11111111-1111-4111-8111-111111111111", account_number="PATEST", currency="USD",
        equity="100", cash="80", buying_power="65" if fault == "partial" else "60",
        status="ACTIVE", multiplier="1", trading_blocked=fault=="blocked",
        account_blocked=False, trade_suspended_by_user=False)
    if fault == "larger-gap":
        payload["buying_power"] = "58.99"
    reader = AlpacaExecutionBroker(api_key="fixture", secret_key="fixture", base_url="https://paper-api.alpaca.markets")
    requests = []
    async def get(path, params=None):
        assert database.info.transaction_status.name == "IDLE"
        requests.append((path, params))
        if path == "/v2/account":
            n = sum(path == "/v2/account" for path, _ in requests)
            return {**payload, "buying_power": "57" if fault=="moving" and n % 2 == 0 else payload["buying_power"]}
        assert path == "/v2/orders" and params["limit"] == 500
        return native_open if params["status"] == "open" else native_closed
    monkeypatch.setattr(reader, "_get", get)
    assert asyncio.run(account_status.collect(Clocked(), reader=reader, config=SentinelConfig.from_env({})))
    recorded = sources._latest_account_evidence(database)
    bound = account_status._bound(database)
    receipt = recorded["flags"].get(account_status.RESERVATION_FLAG)
    if fault == "damaged-journal":
        database.execute("UPDATE sentinel_commands SET broker_order_id='another' WHERE client_key=%s",(working.client_key,))
    def verify(at):
        return observed_dollar_hold.verify(database, bound, receipt, recorded["cash"],
                                          recorded["buying_power"], recorded["observed_at"], at)
    proof = verify(now)
    if fault not in ("", "partial"):
        assert proof is None
        assert model.alpaca_account_row(available=True,expected_account_id="PATEST",**recorded).status == model.FAIL
        return
    assert proof["reserved_cash"] == ("15" if fault == "partial" else "20") and proof["terms"] == "MARKET/DAY"
    assert [params["status"] for path,params in requests if path=="/v2/orders"] == ["open","closed"]
    def evaluate(*_args, **_kwargs):
        return {"plan_id":plan.plan_id}
    monkeypatch.setattr(sources, "_latest_automation_cycle", evaluate)
    monkeypatch.setenv("SENTINEL_GIT_COMMIT", "a" * 40)
    monkeypatch.setenv("SENTINEL_RUNTIME_IMAGE_DIGEST", "sha256:" + "b" * 64)
    monkeypatch.setattr(local_paper, "require_runtime", lambda *_: None)
    rows, errors = sources._operator_evidence_rows(database.info.dsn, now=now, observation_clock=lambda: now)
    account_row = next(row for row in rows if row.key=="alpaca_account")
    assert not any(e.startswith("operator account:") for e in errors), errors
    assert account_row.status == model.OK and "freshly matched native MARKET/DAY" in account_row.detail, account_row.detail
    with journal.writer_lock(database, recovery_only=True):
        for c in (first, working):
            transition(database, replace(c,state=S.ACKNOWLEDGED,broker_order_id="id-"+c.security_id),
                       S.FILLED, filled_quantity=D(2), filled_average_price=D(10))
        database.commit()
    assert verify(now + timedelta(seconds=3)) == proof
    assert verify(now + timedelta(seconds=91)) is None
    assert journal.load_commands(database, deployment, client_keys=(pending.client_key,))[0].state is S.SEND_PENDING


def test_terminal_native_evidence_falsifier(database, subject, monkeypatch):
    monkeypatch.setattr(observed_dollar_hold, "capture", _compiled(observed_dollar_hold.capture,
        'if ({o.client_key for o in terminal} != missing or len(terminal) != len(missing)',
        'if (False'))
    with pytest.raises(AssertionError):
        test_native_hold_during_funded_dispatch(database, subject, monkeypatch, "missing-filled")
