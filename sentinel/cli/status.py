"""Read-only status command owners."""

from __future__ import annotations

from dataclasses import replace
import json
import sys

from sentinel.cli._shared import EXIT_CONFIG, EXIT_NOT_ESTABLISHED, EXIT_OK
from sentinel.config import SentinelConfig
from sentinel.store import FileOwnershipStore

def cmd_status(config: SentinelConfig, _args=None) -> int:
    """Read-only. Deliberately does NOT require credentials — the moment you most
    want to inspect state is when something about the environment is wrong."""
    # THE DATABASE ANSWERS THIS, not the file. The binding became authoritative
    # in stage B and these readers did not move with it, so `status` could report
    # NOT owned while the runtime was correctly trading a bound account — which
    # is what an operator reads at 3am before deciding to rerun a migration.
    from sentinel import ownership_view

    view = ownership_view.read(config.database_url, config.state_dir)
    store = FileOwnershipStore(config.ownership_log)
    try:
        events = store.events()
    except Exception as exc:                                  # noqa: BLE001
        events = []
        view = replace(view, detail=view.detail
                       + f" (audit log unreadable: {exc})")
    authority_status = {
        "authority_mode": None,
        "historical_causality": None,
        "expires_at": None,
        "maximum_exposure": None,
        "lifecycle_current": False,
    }
    administrative_status = {
        "generation": 0,
        "highest_issuer_generation": 0,
        "active_certificate_sha256": None,
        "certificates": [],
    }
    if config.database_url:
        from sentinel.automation.health import read_health
        from sentinel.feed import store as feed_store

        conn = None
        try:
            conn = feed_store.connect(config.database_url)
            health = read_health(conn)
            authority_status = {
                "authority_mode": health.authority_mode,
                "historical_causality": health.historical_causality,
                "expires_at": (health.authority_expires_at.isoformat()
                               if health.authority_expires_at else None),
                "maximum_exposure": health.maximum_exposure,
                "lifecycle_current": bool(
                    health.authority_lifecycle_current),
            }
            from sentinel.administrative_authority import (
                administrative_authority_status,
            )
            administrative_status = administrative_authority_status(conn)
        except Exception as exc:                              # noqa: BLE001
            authority_status["error"] = f"{type(exc).__name__}: {exc}"
            administrative_status["error"] = (
                f"{type(exc).__name__}: {exc}")
        finally:
            if conn is not None:
                conn.close()
    print(json.dumps({
        "config": config.redacted(),
        **view.to_dict(),
        "paper_execution_authority": authority_status,
        "administrative_authority": administrative_status,
        # AUDIT ONLY, and labelled. Kept in the output because it is genuinely
        # useful during an incident; renamed so it can never be mistaken for the
        # answer above.
        "audit_log_events_detail": [
            {"state": e.state.value, "at": e.at.isoformat(), "detail": e.detail}
            for e in events
        ],
    }, indent=2))
    return EXIT_OK

def cmd_shadow_status(config: SentinelConfig, _args=None) -> int:
    """Verify and print only the broker-free performance chain."""
    from sentinel import schema, shadow_runtime
    from sentinel.automation_runtime import shadow_config_from_env
    from sentinel.feed import store as feed_store

    if not config.database_url:
        print("REFUSED: SENTINEL_DATABASE_URL is unset", file=sys.stderr)
        return EXIT_CONFIG
    try:
        _enabled, observation_id, starting_cash = shadow_config_from_env()
        conn = feed_store.connect(config.database_url)
        try:
            with conn.cursor() as cur:
                cur.execute("BEGIN TRANSACTION READ ONLY")
            schema.require_runtime_schema(conn)
            result = shadow_runtime.verified_shadow_status(
                conn, observation_id=observation_id,
                starting_cash=starting_cash)
        finally:
            conn.rollback()
            conn.close()
    except (ValueError, shadow_runtime.ShadowRuntimeRefused) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return EXIT_NOT_ESTABLISHED
    if result is None:
        print(json.dumps({
            "mode": "BROKER_FREE_SHADOW", "status": "NOT_STARTED",
            "broker_mutations_authorized": False,
        }, indent=2, sort_keys=True))
        return EXIT_NOT_ESTABLISHED
    print(json.dumps({
        "mode": "BROKER_FREE_SHADOW",
        "broker_mutations_authorized": False,
        **result.to_dict(),
    }, indent=2, sort_keys=True))
    return EXIT_OK


def cmd_shadow_run(_config: SentinelConfig | None, args) -> int:
    """Run the dedicated broker-free reviewed shadow service."""
    from sentinel import shadow_service

    forwarded = []
    if args.preflight:
        forwarded.append("--preflight")
    if args.once:
        forwarded.append("--once")
    return shadow_service.main(forwarded)
