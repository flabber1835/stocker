"""Authorized neutral trading commands; the configured URL selects mode."""
from __future__ import annotations

from datetime import datetime
import json
import os
import sys
from zoneinfo import ZoneInfo

from sentinel.cli._shared import (
    EXIT_CONFIG, EXIT_NOT_ESTABLISHED, EXIT_OK, authorized_handler,
    paper_refusal_types, paper_refused,
)
from sentinel.config import build_execution_broker
from sentinel.trading_environment import TradingEnvironment


def register_parser(sub):
    prepare = sub.add_parser("prepare-trading-plan", help="prepare from the URL-selected account; no orders")
    prepare.add_argument("--through", required=True)
    prepare.add_argument("--expect-account", required=True)
    sub.add_parser("current-trading-plan", help="inspect the URL-selected durable plan; no broker")
    execute = sub.add_parser("execute-trading-plan", help="execute confirmed plan; LIVE URL means real money")
    execute.add_argument("--confirm-account", required=True)
    execute.add_argument("--confirm-plan-id", required=True)
    execute.add_argument("--confirm-effective-session", required=True)
    execute.add_argument("--confirm-submit-trading-orders", action="store_true", required=True)
    recovery = sub.add_parser("recover-trading-account", help="read-only reconciliation of the URL-selected account")
    recovery.add_argument("--expect-account", required=True)
    enroll = sub.add_parser("enroll-live-issuer-policy", help="explicit LIVE issuer enrollment; empty account and engaged kill switch")
    enroll.add_argument("--confirm-account", required=True)
    enroll.add_argument("--confirm-deployment", required=True)
    enroll.add_argument("--confirm-real-money", action="store_true", required=True)
    bind = sub.add_parser("bind-empty-live-account", help="explicit signed LIVE empty-account provisioning; no orders")
    bind.add_argument("--confirm-live-account", required=True)
    bind.add_argument("--confirm-deployment", required=True)
    bind.add_argument("--confirm-empty-live-account", action="store_true", required=True)
    bind.add_argument("--confirm-real-money", action="store_true", required=True)
    bind.add_argument("--actor", required=True)
    bind.add_argument("--reason", required=True)
    for command in ("activate-live-automation", "release-live-automation-kill-switch"):
        activate = sub.add_parser(command, help="explicit signed LIVE automation authority; real money")
        activate.add_argument("--confirm-live-account", required=True)
        activate.add_argument("--confirm-deployment", required=True)
        activate.add_argument("--confirm-real-money", action="store_true", required=True)
        activate.add_argument("--actor", required=True)
        activate.add_argument("--reason", required=True)


def _connect(config):
    from sentinel import schema
    from sentinel.feed import store
    if not config.database_url:
        raise ValueError("SENTINEL_DATABASE_URL is unset")
    conn = store.connect(config.database_url)
    try:
        store.require_feed_schema(conn)
        schema.require_runtime_schema(conn)
    except BaseException:
        conn.close()
        raise
    return conn


def _shadow_kwargs(config):
    from sentinel.automation_runtime import shadow_config_from_env
    if (config.environment is TradingEnvironment.LIVE
            or os.environ.get("SENTINEL_REVIEWED_DEPLOYMENT_MODE", "").strip().lower() == "dual"):
        enabled, observation_id, starting_cash = shadow_config_from_env()
        if not enabled and config.environment is TradingEnvironment.PAPER:
            raise ValueError("authenticated canonical shadow configuration is required")
        return {"dual_shadow_observation_id": observation_id,
                "dual_shadow_starting_cash": starting_cash}
    return {}


def _broker(conn, config, session):
    from sentinel import identity, paper
    from sentinel.authority.live_runtime import load_live_adapter_admission
    from sentinel.strategy import production_strategy
    kwargs = {}
    if config.environment is TradingEnvironment.LIVE:
        kwargs["live_admission"] = load_live_adapter_admission(
            conn, base_url=config.base_url, runtime_identity=identity.rehearsal_identity(),
            strategy_identity=production_strategy()[1])
    return build_execution_broker(config,
        resolve_security_id=paper.build_security_resolver(conn, str(session)), **kwargs)


async def _operate(config, args, operation):
    from sentinel import trading
    from sentinel.feed import calendar
    conn = None
    try:
        conn = _connect(config)
        kwargs = _shadow_kwargs(config)
        if operation == "current":
            result = trading.current_trading_plan(conn, base_url=config.base_url, **kwargs)
        elif operation == "prepare":
            result = await trading.prepare_trading_plan(conn=conn,
                broker=_broker(conn, config, calendar.next_session(args.through)),
                base_url=config.base_url, through=args.through,
                expected_account=args.expect_account, **kwargs)
        elif operation == "execute":
            result = await trading.execute_trading_plan(conn=conn,
                broker=_broker(conn, config, args.confirm_effective_session),
                base_url=config.base_url, confirm_account=args.confirm_account,
                confirm_plan_id=args.confirm_plan_id,
                confirm_effective_session=args.confirm_effective_session,
                confirm_submit=args.confirm_submit_trading_orders, **kwargs)
        elif operation == "enroll":
            today = datetime.now(ZoneInfo(calendar.EXCHANGE_TZ)).date()
            result = await trading.enroll_live_issuer_policy(conn=conn,
                broker=_broker(conn, config, calendar.session_on_or_after(today)),
                base_url=config.base_url, confirm_account=args.confirm_account,
                confirm_deployment=args.confirm_deployment,
                confirm_real_money=args.confirm_real_money)
        else:
            today = datetime.now(ZoneInfo(calendar.EXCHANGE_TZ)).date()
            result = await trading.recover_trading_account(conn=conn,
                broker=_broker(conn, config, calendar.session_on_or_after(today)),
                base_url=config.base_url, expected_account=args.expect_account, **kwargs)
    except paper_refusal_types() as exc:
        return paper_refused(exc)
    finally:
        if conn is not None:
            conn.close()
    payload = result if isinstance(result, dict) else result.to_dict()
    print(json.dumps({"environment": config.environment.value, **payload}, indent=2, default=str))
    return EXIT_NOT_ESTABLISHED if getattr(result, "needs_attention", False) else EXIT_OK


@authorized_handler("prepare-trading-plan")
async def prepare(config, args):
    return await _operate(config, args, "prepare")


@authorized_handler("current-trading-plan")
async def current(config, args):
    return await _operate(config, args, "current")


@authorized_handler("execute-trading-plan")
async def execute(config, args):
    return await _operate(config, args, "execute")


@authorized_handler("recover-trading-account")
async def recover(config, args):
    return await _operate(config, args, "recover")


@authorized_handler("enroll-live-issuer-policy")
async def enroll_live_issuer(config, args):
    return await _operate(config, args, "enroll")


async def _live_admin(config, args, operation):
    from sentinel import identity
    from sentinel.authority import live_provisioning
    from sentinel.automation_runtime import config_from_env
    from sentinel.execution.native_readonly import ReadOnlyAlpacaClient
    from sentinel.strategy import production_strategy
    conn = None
    try:
        if config.environment is not TradingEnvironment.LIVE or args.confirm_real_money is not True:
            raise ValueError("explicit LIVE origin and real-money confirmation are required")
        conn = _connect(config)
        common = dict(base_url=config.base_url,
            runtime_identity=identity.rehearsal_identity(),
            strategy_identity=production_strategy()[1],
            automation_config_sha256=config_from_env().fingerprint)
        confirmations = dict(confirm_live_account=args.confirm_live_account,
            confirm_deployment=args.confirm_deployment, actor=args.actor, reason=args.reason)
        if operation == "bind":
            admission = live_provisioning.load_live_provisioning_admission(conn,
                deployment_id=args.confirm_deployment, expected_account=args.confirm_live_account, **common)
            if not config.alpaca_key or not config.alpaca_secret:
                raise ValueError("matching Alpaca LIVE credentials are required")
            client = ReadOnlyAlpacaClient(admission.context.subject,
                api_key=config.alpaca_key, secret_key=config.alpaca_secret)
            result = await live_provisioning.bind_empty_live_account(conn,
                client=client, admission=admission,
                confirm_empty_live_account=args.confirm_empty_live_account, **confirmations)
        else:
            function = live_provisioning.activate_live_automation if operation == "activate" else live_provisioning.release_live_kill
            result = function(conn, confirm_real_money=True, **common, **confirmations)
    except paper_refusal_types() as exc:
        return paper_refused(exc)
    finally:
        if conn is not None:
            conn.close()
    payload = result.to_dict() if hasattr(result, "to_dict") else result
    print(json.dumps(payload, indent=2, default=str))
    return EXIT_OK


@authorized_handler("bind-empty-live-account")
async def bind_empty_live(config, args):
    return await _live_admin(config, args, "bind")


@authorized_handler("activate-live-automation")
async def activate_live(config, args):
    return await _live_admin(config, args, "activate")


@authorized_handler("release-live-automation-kill-switch")
async def release_live(config, args):
    return await _live_admin(config, args, "release")
