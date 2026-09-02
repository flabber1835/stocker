"""Unattended paper-automation command owners."""

from __future__ import annotations

import asyncio
import json
import sys

from sentinel.cli._shared import (
    EXIT_CONFIG, EXIT_NOT_ESTABLISHED, EXIT_OK,
    authorized_handler,
    require_authorized_runtime,
    paper_refusal_types as _paper_refusal_types,
    paper_refused as _paper_refused,
)
from sentinel.cli import authority as authority_cli
from sentinel.config import SentinelConfig

def _automation_authority(conn, config: SentinelConfig, automation_config):
    """Verify exact unattended authority without constructing a broker."""
    from sentinel import authority, binding as binding_mod
    from sentinel.execution.authority_gate import require_current_authority
    from sentinel.feed import publication

    binding = binding_mod.require(conn)
    rollout = authority.load_rollout_state(conn)
    runtime, strategy = authority_cli._current_system_identities()
    current = publication.require_current(conn)
    certificate = require_current_authority(
        conn, runtime_identity=runtime, strategy_identity=strategy,
        required_mode=rollout.mode, required_operation="AUTOMATION",
        paper_base_url=config.base_url,
        current_publication_version=current.version,
        automation_config_sha256=automation_config.fingerprint)
    return binding, rollout, certificate


def _automation_control_binding(binding, rollout, certificate,
                                automation_config):
    from sentinel.automation.model import ControlBinding

    return ControlBinding(
        deployment_id=binding.deployment_id, broker=binding.broker,
        broker_account_id=binding.broker_account_id,
        takeover_epoch=binding.takeover_epoch,
        certificate_sha256=certificate.certificate_sha256,
        rollout_mode=rollout.mode.value, rollout_version=rollout.version,
        config_sha256=automation_config.fingerprint)


def _automation_status(config: SentinelConfig, _args=None) -> int:
    from sentinel.automation.health import read_health
    from sentinel.feed import store as feed_store

    if not config.database_url:
        print("REFUSED: SENTINEL_DATABASE_URL is unset", file=sys.stderr)
        return EXIT_CONFIG
    conn = feed_store.connect(config.database_url)
    try:
        result = read_health(conn)
    except _paper_refusal_types() as exc:
        return _paper_refused(exc)
    finally:
        conn.close()
    print(json.dumps(result.model_dump(mode="json"), indent=2, default=str))
    return EXIT_OK if result.healthy else EXIT_NOT_ESTABLISHED


@authorized_handler("activate-paper-automation")
def _activate_paper_automation(config: SentinelConfig, args) -> int:
    refusal = require_authorized_runtime("activate-paper-automation")
    if refusal is not None:
        return refusal
    from sentinel import schema
    from sentinel.automation import store
    from sentinel.automation_runtime import config_from_env
    from sentinel.execution import journal
    from sentinel.feed import store as feed_store
    from sentinel.handover import assert_no_legacy_path

    if (not args.confirm_enable_unattended_alpaca_paper_automation
            or not args.confirm_old_writer_fenced):
        print(
            "REFUSED: --confirm-old-writer-fenced and "
            "--confirm-enable-unattended-alpaca-paper-automation are required",
            file=sys.stderr)
        return EXIT_CONFIG
    if not config.database_url:
        print("REFUSED: SENTINEL_DATABASE_URL is unset", file=sys.stderr)
        return EXIT_CONFIG
    conn = feed_store.connect(config.database_url)
    try:
        schema.ensure_schema(conn)
        automation_config = config_from_env()
        with journal.writer_lock(conn):
            assert_no_legacy_path(conn)
            binding, rollout, certificate = _automation_authority(
                conn, config, automation_config)
            if (binding.broker_account_id != args.confirm_paper_account
                    or binding.deployment_id != args.confirm_deployment_id
                    or certificate.certificate_sha256
                    != args.confirm_certificate_sha256):
                from sentinel.automation.model import AutomationRefused
                raise AutomationRefused(
                    "automation activation confirmations do not match durable "
                    "signed authority")
            control = store.activate(
                conn, binding=_automation_control_binding(
                    binding, rollout, certificate, automation_config),
                actor=args.actor, reason=args.reason)
    except _paper_refusal_types() as exc:
        return _paper_refused(exc)
    finally:
        conn.close()
    print(json.dumps({
        "automation_enabled": control.enabled,
        "kill_switch_engaged": control.kill_switch_engaged,
        "generation": control.generation,
        "broker_contacted": False,
        "operational_ready": False,
    }, indent=2))
    return EXIT_OK


@authorized_handler("release-paper-automation-kill-switch")
def _release_paper_automation_kill(config: SentinelConfig, args) -> int:
    refusal = require_authorized_runtime("release-paper-automation-kill-switch")
    if refusal is not None:
        return refusal
    from sentinel import schema
    from sentinel.automation import store
    from sentinel.automation_runtime import config_from_env
    from sentinel.execution import journal
    from sentinel.feed import store as feed_store

    if not args.confirm_release_unattended_paper_kill_switch:
        print("REFUSED: explicit unattended paper kill-switch release "
              "confirmation is required", file=sys.stderr)
        return EXIT_CONFIG
    if not config.database_url:
        print("REFUSED: SENTINEL_DATABASE_URL is unset", file=sys.stderr)
        return EXIT_CONFIG
    conn = feed_store.connect(config.database_url)
    try:
        schema.ensure_schema(conn)
        automation_config = config_from_env()
        with journal.writer_lock(conn):
            binding, rollout, certificate = _automation_authority(
                conn, config, automation_config)
            if (binding.broker_account_id != args.confirm_paper_account
                    or binding.deployment_id != args.confirm_deployment_id
                    or certificate.certificate_sha256
                    != args.confirm_certificate_sha256):
                from sentinel.automation.model import AutomationRefused
                raise AutomationRefused(
                    "kill release confirmations do not match durable authority")
            control = store.release_kill(
                conn, expected_binding=_automation_control_binding(
                    binding, rollout, certificate, automation_config),
                actor=args.actor, reason=args.reason)
    except _paper_refusal_types() as exc:
        return _paper_refused(exc)
    finally:
        conn.close()
    print(json.dumps({
        "automation_enabled": control.enabled,
        "kill_switch_engaged": control.kill_switch_engaged,
        "generation": control.generation,
        "broker_contacted": False,
    }, indent=2))
    return EXIT_OK


def _remove_automation_authority(
        config: SentinelConfig, args, *, kill: bool | None = None) -> int:
    from sentinel import schema
    from sentinel.automation import store
    from sentinel.feed import store as feed_store

    if not config.database_url:
        print("REFUSED: SENTINEL_DATABASE_URL is unset", file=sys.stderr)
        return EXIT_CONFIG
    if kill is None:
        kill = args.command == "engage-paper-automation-kill-switch"
    conn = feed_store.connect(config.database_url)
    try:
        if not kill:
            schema.require_runtime_schema(conn)
        # Emergency fencing must remain available while an executor owns the
        # shared writer advisory lock across slow broker I/O. These control
        # mutations serialize on their singleton row, bump the generation and
        # invalidate the lease; every guarded broker operation checks that
        # fresh state before transport.
        control = (store.engage_kill(
            conn, actor=args.actor, reason=args.reason)
            if kill else store.deactivate(
                conn, actor=args.actor, reason=args.reason))
    except _paper_refusal_types() as exc:
        return _paper_refused(exc)
    finally:
        conn.close()
    print(json.dumps({
        "automation_enabled": control.enabled,
        "kill_switch_engaged": control.kill_switch_engaged,
        "generation": control.generation,
        "broker_contacted": False,
    }, indent=2))
    return EXIT_OK


def _acknowledge_paper_alert(config: SentinelConfig, args) -> int:
    from sentinel import schema
    from sentinel.automation import outbox
    from sentinel.feed import store as feed_store

    if not config.database_url:
        print("REFUSED: SENTINEL_DATABASE_URL is unset", file=sys.stderr)
        return EXIT_CONFIG
    conn = feed_store.connect(config.database_url)
    try:
        schema.ensure_schema(conn)
        alert = outbox.acknowledge(
            conn, alert_id=args.alert_id, actor=args.actor,
            acknowledgement=args.acknowledgement)
    except _paper_refusal_types() as exc:
        return _paper_refused(exc)
    finally:
        conn.close()
    print(json.dumps(alert.model_dump(mode="json"), indent=2, default=str))
    return EXIT_OK


@authorized_handler("automation-run")
async def _automation_run(config: SentinelConfig, _args=None) -> int:
    """Run the persistent service; disabled/killed startup is broker-inert."""
    refusal = require_authorized_runtime("automation-run")
    if refusal is not None:
        return refusal
    import signal

    from sentinel import schema
    from sentinel.automation_runtime import ProductionAutomation, config_from_env
    from sentinel.feed import store as feed_store

    if not config.database_url:
        print("REFUSED: SENTINEL_DATABASE_URL is unset", file=sys.stderr)
        return EXIT_CONFIG
    conn = feed_store.connect(config.database_url)
    try:
        schema.require_runtime_schema(conn)
    finally:
        conn.close()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signame in ("SIGINT", "SIGTERM"):
        signum = getattr(signal, signame, None)
        if signum is not None:
            try:
                loop.add_signal_handler(signum, stop.set)
            except (NotImplementedError, RuntimeError):       # Windows/tests
                pass
    runtime = ProductionAutomation(
        sentinel_config=config, automation_config=config_from_env())
    try:
        await runtime.run(stop=stop)
    except _paper_refusal_types() as exc:
        return _paper_refused(exc)
    return EXIT_OK
