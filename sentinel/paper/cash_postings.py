"""Account observations of qualified native PAPER cash postings."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from fractions import Fraction
import json

from sentinel.execution import broker_cash, journal
from sentinel.execution.numeric import decimal_text, exact_decimal
from sentinel.execution.states import CommandState

from .model import PaperActivationRefused
from .validation import _hash

PREFIX = broker_cash.PLAN_BASELINE_PREFIX + "posting-observation:"
# Bound the number of distinct partial sums that could still explain current cash.
MAX_POSTING_SUMS = 4096


def _remaining(amounts, gap):
    # A total has either a unique set of event IDs or multiple explanations
    # (None). Prune totals outside the bounds of all still-unread signed rows.
    lower = sum((min(value, 0) for value in amounts.values()), Fraction(0))
    upper = sum((max(value, 0) for value in amounts.values()), Fraction(0))
    reachable = {Fraction(0): ()}
    for key, amount in sorted(amounts.items()):
        lower -= min(amount, 0)
        upper -= max(amount, 0)
        following = {}
        for total, refs in reachable.items():
            for take in (False, True):
                candidate = total + amount if take else total
                if not candidate + lower <= gap <= candidate + upper:
                    continue
                if candidate in following or refs is None:
                    following[candidate] = None
                else:
                    following[candidate] = refs + (key,) if take else refs
        if len(following) > MAX_POSTING_SUMS:
            raise PaperActivationRefused("too many cash posting combinations to prove a unique observation")
        reachable = following
    if gap not in reachable:
        raise PaperActivationRefused("cash is unexplained by qualified native postings and exact fills")
    if reachable[gap] is None:
        raise PaperActivationRefused("cash posting attribution is ambiguous")
    return reachable[gap]


def read_posting_status(conn, *, plan_id, account_id):
    row = conn.execute("SELECT state FROM sentinel_processed_sessions WHERE cursor_name=%s",
                       (PREFIX + plan_id,)).fetchone()
    if row is None:
        return None
    body = dict(row[0])
    digest = body.pop("sha256", None)
    if (digest != _hash(body) or body.get("schema") != "sentinel.paper-cash-posting/1"
            or body.get("plan_id") != plan_id or body.get("broker") != "alpaca"
            or body.get("account_id") != account_id):
        raise PaperActivationRefused("cash posting observation has changed identity or contents")
    events = body["events"]
    reflected = body["reflected"]
    fills = body.get("fills")
    if (not isinstance(events, dict) or not isinstance(reflected, list) or not isinstance(fills, dict)
            or any(not isinstance(x, str) or len(x) != 64 or set(x) - set("0123456789abcdef")
                   for x in (*fills.keys(), *fills.values()))
            or Fraction(body["account_cash"]) < 0 or Fraction(body["buying_power"]) < 0
            or reflected != sorted(set(reflected)) or set(events).intersection(reflected)
            or not all(isinstance(k, str) and k for k in set(events).union(reflected))
            or Decimal(body["reserve"]) != -sum((Fraction(v) for v in events.values()
                                                 if Fraction(v) < 0), Fraction(0))
            or Fraction(body["expected_cash"]) - Fraction(body["account_cash"])
               != sum(map(Fraction, events.values()), Fraction(0))
            or datetime.fromisoformat(body["observed_at"]).utcoffset() is None):
        raise PaperActivationRefused("cash posting observation has inconsistent economics")
    return body


def _plan_fill_rows(conn, *, plan, deployment):
    from sentinel.execution.fill_integrity import load_exact_fill_rows

    commands = journal.load_commands(conn, deployment, plan_id=plan.plan_id)
    return commands, load_exact_fill_rows(conn, commands)


def _fill_witnesses(rows):
    witnesses = {}
    for (client_key, order_id), executions in rows.items():
        for key, quantity, price, posted in executions:
            if posted is None:
                continue
            digest = _hash([client_key, order_id, key, decimal_text(quantity), decimal_text(price), posted])
            witnesses[key] = (digest, Fraction(posted["amount"]))
    return witnesses


def verify_restored_postings(conn, *, baseline, activity, plan, has_observation):
    if not has_observation and not baseline.pending_postings:
        return
    if plan is None or activity is None or activity.posting_kinds is None:
        raise PaperActivationRefused("restored cash posting evidence has no plan or qualified native history")
    status = read_posting_status(conn, plan_id=plan.plan_id, account_id=plan.broker_account_id)
    if (status is None or status["plan_fingerprint"] != plan.fingerprint()
            or datetime.fromisoformat(status["observed_at"]) > activity.processed_through):
        raise PaperActivationRefused("restored cash posting observation is missing or mismatched")
    _verify_source(conn, baseline=baseline, plan=plan)
    rows = broker_cash._current_cash_ledger(conn, activity_state=activity)
    broker_cash._debit_fee_membership(baseline=baseline, activity_state=activity, rows=rows)
    fitted = set(status["events"]) | set(status["reflected"])
    kinds = dict(activity.posting_kinds)
    carry = set(baseline.pending_postings)
    prefix = f"{broker_cash.FLOW_PREFIX}{plan.broker}:{plan.broker_account_id}:"
    for ref in fitted:
        key = prefix + ref
        if (key not in rows or not _eligible(ref, rows[key], kinds)
                or key in dict(baseline.activity_membership) and key not in carry
                or ref in status["events"] and Fraction(status["events"][ref]) != rows[key][1]):
            raise PaperActivationRefused("restored cash posting reference or amount differs from the native ledger")
    if not carry <= {prefix + ref for ref in fitted}:
        raise PaperActivationRefused("restored cash posting observation omitted a carried event")
    from sentinel.execution.identity import DeploymentIdentity
    owner = DeploymentIdentity(plan.deployment_id, plan.broker, plan.broker_account_id, plan.takeover_epoch)
    _, fill_rows = _plan_fill_rows(conn, plan=plan, deployment=owner)
    fills = _fill_witnesses(fill_rows)
    if any(key not in fills or fills[key][0] != digest for key, digest in status["fills"].items()):
        raise PaperActivationRefused("restored posting observation lost an original signed fill")
    expected = (Fraction(plan.account_cash) + sum((fills[k][1] for k in status["fills"]), Fraction(0))
                + sum((rows[prefix + ref][1] for ref in fitted), Fraction(0)))
    if expected != Fraction(status["expected_cash"]):
        raise PaperActivationRefused("restored native cash posting and fill equation changed")


def carry_forward(conn, *, plan_id, account_id):
    status = read_posting_status(conn, plan_id=plan_id, account_id=account_id)
    if status is None or not status["events"]:
        return {}
    keys = tuple(sorted(broker_cash.broker_flow_id(broker="alpaca", account_id=account_id,
        activity_id=ref) for ref in status["events"]))
    return {"pending_postings": keys, "posting_source": (plan_id, _hash(status))}


def _verify_source(conn, *, baseline, plan):
    if baseline.pending_postings:
        prior_id, digest = baseline.posting_source
        account_id = plan.broker_account_id
        prior = read_posting_status(conn, plan_id=prior_id, account_id=account_id)
        link = conn.execute("SELECT superseded_by FROM sentinel_execution_plans WHERE plan_id=%s",
                            (prior_id,)).fetchone()
        if (link != (plan.plan_id,) or prior is None or _hash(prior) != digest
                or datetime.fromisoformat(prior["observed_at"]) != baseline.processed_through
                or Fraction(prior["account_cash"]) != plan.account_cash
                or set(baseline.pending_postings) != {broker_cash.broker_flow_id(
                    broker=plan.broker, account_id=account_id, activity_id=ref) for ref in prior["events"]}):
            raise PaperActivationRefused("carried cash postings differ from the predecessor account observation")


def _eligible(ref, row, kinds):
    _, amount, detail = row
    kind = kinds.get(ref)
    if kind == "CDIV" and amount > 0:
        activity_type = "DIV"
    elif kind == "FEE" and amount < 0:
        activity_type = "FEE"
    else:
        return False
    return detail == f"{broker_cash.DETAIL_PREFIX}class=INTERNAL;type={activity_type};id={ref}"


def _store(conn, *, plan, account, activity_state, expected, amounts, remaining, prior, fills):
    events = {k: decimal_text(exact_decimal(amounts[k])) for k in remaining}
    reserve = exact_decimal(-sum((amounts[k] for k in remaining if amounts[k] < 0), Fraction(0)))
    body = dict(schema="sentinel.paper-cash-posting/1", plan_id=plan.plan_id,
        plan_fingerprint=plan.fingerprint(), broker=plan.broker, account_id=plan.broker_account_id,
        observed_at=activity_state.processed_through.isoformat(),
        account_cash=decimal_text(account.cash), buying_power=decimal_text(account.buying_power),
        expected_cash=decimal_text(exact_decimal(expected)), events=events,
        reserve=decimal_text(reserve), reflected=sorted(amounts.keys() - events.keys()),
        fills={key: digest for key, (digest, _) in fills.items()})
    if prior and (datetime.fromisoformat(prior["observed_at"]) > activity_state.processed_through
                  or not set(prior["reflected"]) <= set(body["reflected"])
                  or not prior["fills"].items() <= body["fills"].items()):
        raise PaperActivationRefused("cash posting observation regressed")
    current = conn.execute("SELECT plan_id FROM sentinel_execution_plans WHERE plan_id=%s"
                           " AND superseded_by IS NULL FOR SHARE", (plan.plan_id,)).fetchone()
    if current is None:
        raise PaperActivationRefused("a superseded or missing plan cannot advance cash postings")
    payload = json.dumps(dict(body, sha256=_hash(body)), sort_keys=True)
    stored = conn.execute("INSERT INTO sentinel_processed_sessions(cursor_name,session,state)"
                 " VALUES (%s,%s,%s::jsonb) ON CONFLICT(cursor_name) DO UPDATE"
                 " SET state=EXCLUDED.state,updated_at=NOW()"
                 " WHERE sentinel_processed_sessions.state->>'sha256'=%s RETURNING cursor_name",
                 (PREFIX + plan.plan_id, plan.decision_session, payload, _hash(prior) if prior else None)).fetchone()
    if stored is None and read_posting_status(conn, plan_id=plan.plan_id, account_id=plan.broker_account_id) != body:
        raise PaperActivationRefused("cash posting observation changed concurrently")
    return reserve


def _posting_inputs(conn, *, plan, activity):
    baseline = broker_cash.load_plan_baseline(conn, plan_id=plan.plan_id)
    prior = read_posting_status(conn, plan_id=plan.plan_id, account_id=plan.broker_account_id)
    carried = baseline is not None and bool(baseline.pending_postings)
    if (baseline is None or baseline.activity_membership is None
            or activity is None or activity.posting_kinds is None):
        if carried or prior:
            raise PaperActivationRefused("retained cash postings require their native PAPER evidence")
        return None
    if not carried and not prior and baseline.last_activity_id == activity.last_activity_id:
        return None
    return baseline, prior


async def prepare(conn, *, broker, binding, plan, rec, account, activity, actions, clock):
    """Earn a repeatable account/book bracket before adopting or reusing a bridge."""
    from .cash import fractional_posting_reserve
    from .reconciliation_evidence import _settled_account_evidence_bracket
    if _posting_inputs(conn, plan=plan, activity=activity) is None:
        return rec, account, activity, None
    rec, account, activity, _, _ = await _settled_account_evidence_bracket(
        conn=conn, broker=broker, binding=binding, expected_account=binding.broker_account_id,
        deployment=binding.identity, initial_result=rec, actions=actions, dual_mode=True, clock=clock)
    reserve = fractional_posting_reserve(conn, plan=plan, deployment=binding.identity,
        account=account, observation=rec.observation, activity_state=activity)
    return rec, account, activity, reserve


def evaluate(conn, *, plan, deployment, account, observation, activity_state, candidate_key=None):
    """Return a debit reserve only when the current native posting evidence qualifies."""
    from sentinel.dual_plan_authority import require_current_buy_policy
    from sentinel.execution.market_buy_policy import MarketBuyPolicy
    from .cash import _plan_fill_cash

    policy = MarketBuyPolicy.from_env()
    if policy is None or not policy.fractional:
        return None
    inputs = _posting_inputs(conn, plan=plan, activity=activity_state)
    if inputs is None:
        return None
    baseline, prior = inputs
    carry = set(baseline.pending_postings)
    if (plan.broker != "alpaca" or plan.broker != deployment.broker
            or plan.broker_account_id != deployment.broker_account_id
            or plan.deployment_id != deployment.deployment_id or plan.takeover_epoch != deployment.takeover_epoch
            or baseline.broker != plan.broker or baseline.account_id != plan.broker_account_id
            or baseline.decision_session != plan.decision_session
            or baseline.account_id != activity_state.account_id
            or not deployment.matches_account(account.identity)
            or not baseline.activity_identity_authoritative):
        raise PaperActivationRefused("native posting account or plan identity changed")
    require_current_buy_policy(conn, plan=plan)
    _verify_source(conn, baseline=baseline, plan=plan)
    rows = broker_cash._current_cash_ledger(conn, activity_state=activity_state)
    # The fee membership reader also authenticates every original commitment,
    # boundary total and the native cursor, even when the suffix is not fee-only.
    broker_cash._debit_fee_membership(baseline=baseline, activity_state=activity_state, rows=rows)
    keys = (rows.keys() - dict(baseline.activity_membership).keys()) | carry
    kinds = dict(activity_state.posting_kinds)
    prefix = f"{broker_cash.FLOW_PREFIX}{plan.broker}:{plan.broker_account_id}:"
    amounts = {}
    for key in keys:
        ref = key.removeprefix(prefix)
        if not _eligible(ref, rows[key], kinds):
            if carry or prior:
                raise PaperActivationRefused("another native activity crossed a cash posting boundary")
            return None
        amounts[ref] = rows[key][1]
    if not amounts:
        if prior:
            raise PaperActivationRefused("cash posting evidence disappeared after observation")
        return None
    if (observation is None or not observation.is_complete
            or not deployment.matches_account(observation.account_identity)
            or any(order.is_working for order in observation.orders)
            or observation.observed_at > activity_state.processed_through
            or account.multiplier != 1 or account.buying_power is None
            or account.status.upper() != "ACTIVE" or account.account_blocked
            or account.trading_blocked or account.trade_suspended_by_user):
        raise PaperActivationRefused("cash postings require a current clean owned PAPER account")
    unresolved = journal.in_flight_commands(conn, deployment)
    if any(c.client_key != candidate_key or c.identity.plan_id != plan.plan_id
           or c.state != CommandState.SEND_PENDING for c in unresolved):
        raise PaperActivationRefused("cash posting admission found an unresolved order")
    commands, fill_rows = _plan_fill_rows(conn, plan=plan, deployment=deployment)
    expected = (_plan_fill_cash(conn, plan=plan, deployment=deployment, commands=commands, posted_rows=fill_rows)
                + Fraction(activity_state.balance_total) - Fraction(baseline.balance_total)
                + sum((rows[k][1] for k in carry), Fraction(0)))
    reflected = set(prior["reflected"]) if prior else set()
    if prior and (prior["plan_fingerprint"] != plan.fingerprint() or not reflected <= amounts.keys()
                  or any(ref not in amounts or amounts[ref] != Fraction(value)
                         for ref, value in prior["events"].items())):
        raise PaperActivationRefused("cash posting evidence changed after observation")
    remaining = _remaining({k: v for k, v in amounts.items() if k not in reflected},
                           expected - Fraction(account.cash))
    return _store(conn, plan=plan, account=account, activity_state=activity_state,
                  expected=expected, amounts=amounts, remaining=remaining, prior=prior, fills=_fill_witnesses(fill_rows))

