"""Durable execution-only evidence shared by PAPER funding and plan fulfillment."""
from datetime import datetime, timedelta

from sentinel.execution import protected_funding
from sentinel.execution.identity import is_sentinel_key
from sentinel.execution.numeric import decimal_text
from sentinel.execution.target_reprojection import TargetProjectionRefused

PREFIX = protected_funding.PREFIX + protected_funding.DOLLAR_RESERVATION_BRANCH + "v1:"


def current_working_receipt(diagnostic, *, plan_id, observation_id, now):
    keys = diagnostic.get("working_order_keys")
    if (not observation_id or str(diagnostic.get("observation_id")) != observation_id
            or diagnostic.get("plan_id") != plan_id or diagnostic.get("clean") is not True
            or not isinstance(keys, list) or not 0 < len(keys) <= 100
            or not all(isinstance(k, str) and is_sentinel_key(k) for k in keys)
            or len(set(keys)) != len(keys)):
        return False
    try:
        observed = datetime.fromisoformat(diagnostic["observed_at"])
        return timedelta(0) <= now - observed <= timedelta(seconds=60)
    except (KeyError, TypeError, ValueError):
        return False


def read(conn, plan_id):
    row = conn.execute(
        "SELECT a.session,a.state,h.session,h.state FROM sentinel_processed_sessions a "
        "LEFT JOIN sentinel_processed_sessions h ON h.cursor_name=%s || (a.state->>'sha256') "
        "WHERE a.cursor_name=%s", (PREFIX + "history:", PREFIX + plan_id)).fetchone()
    if row is None:
        return None
    if row[0] != row[2] or not isinstance(row[3], dict):
        raise TargetProjectionRefused("dollar reservation lost its durable funding evidence")
    body = row[3]
    if (row[1] != {"sha256": protected_funding._sha(body)} or body.get("plan_id") != plan_id
            or body.get("session") != row[0].isoformat()):
        raise TargetProjectionRefused("invalid immutable dollar reservation identity")
    return body


def store(conn, *, plan, body):
    digest = protected_funding._sha(body)
    key = PREFIX + "history:" + digest
    conn.execute("INSERT INTO sentinel_processed_sessions(cursor_name,session,state) VALUES (%s,%s,%s::jsonb)"
                 " ON CONFLICT(cursor_name) DO NOTHING",
                 (key, plan.effective_session, protected_funding._canonical(body)))
    conn.execute("INSERT INTO sentinel_processed_sessions(cursor_name,session,state) VALUES(%s,%s,%s::jsonb)"
                 " ON CONFLICT(cursor_name) DO UPDATE SET state=EXCLUDED.state,updated_at=NOW()",
                 (PREFIX + plan.plan_id, plan.effective_session, protected_funding._canonical({"sha256": digest})))
    if read(conn, plan.plan_id) != body:
        raise TargetProjectionRefused("dollar reservation conflicts with its original funding evidence")


def completed_partial_sweep(conn, *, command, projection, deployment):
    """The first filled staged BIL consumed its single opening purchase opportunity."""
    basis = read(conn, projection.plan_id)
    if basis is None or not basis["sales"]:
        return False
    if (basis["deployment"] != deployment.to_dict() or basis["projection"] != projection.fingerprint()
            or basis["plan"] != projection.plan_fingerprint
            or basis["session"] != projection.through_session.isoformat()
            or set(basis["members"]) != {command.client_key}
            or basis["members"][command.client_key] != {
                "security_id": command.security_id, "symbol": command.instrument.symbol,
                "broker_id": command.instrument.broker_id, "notional": decimal_text(command.notional)}):
        raise TargetProjectionRefused("partial BIL fulfillment differs from its reserved order")
    return True
