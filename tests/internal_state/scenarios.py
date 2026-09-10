"""Named compound failures and deterministic, causally valid generated traces."""
from __future__ import annotations

import random

from .contract import Action, Trace


def actions(*names):
    return tuple(Action(kind=value) if isinstance(value, str) else Action(kind=value[0], value=value[1])
                 for value in names)


BASE = ("daily", "daily", "daily")
COMMON = ("production_daily", "production_kernel", "production_plan", "canonical_state",
          "populated_wealth_core", "populated_witness", "persisted_ldrc", "kernel_differential")


def catalogue():
    definitions = {
        "populated_lifecycle": ((*BASE, "execute", "fill", "reconcile", "restart", "execute"),
            ("production_executor", "broker_fills", "connection_restart")),
        "submit_process_death": ((*BASE, "kill_submit", "fill", "restart", "reconcile", "execute"),
            ("sigkill_after_acceptance", "durable_commands", "broker_fills")),
        "submit_response_loss": ((*BASE, "timeout_submit", "fill", "restart", "reconcile", "execute"),
            ("response_loss_after_acceptance", "broker_fills")),
        "partial_cancel_fill_race": ((*BASE, "execute", "cancel_race", "restart", "execute"),
            ("partial_fill_cancel_race", "broker_fills")),
        "external_cash_isolation": ((*BASE, "execute", "fill", "reconcile", ("cash", 1200),
            ("cash", -500), "restart"), ("cash_deduplication", "broker_fills")),
        "startup_failure_after_plan": ((*BASE, "env_bad", "env_repair", "restart", "execute", "fill", "reconcile"),
            ("malformed_startup_refusal", "broker_fills")),
        "interrupted_publication": ((*BASE, "data_bad", "daily", "data_repair", "daily", "restart"),
            ("interrupted_publication", "connection_restart")),
        "backup_loss_after_plan": ((*BASE, "media_loss", "media_repair", "execute", "fill", "reconcile"),
            ("backup_authority_refusal", "broker_fills")),
        "wal_corruption_after_plan": ((*BASE, "wal_corrupt", "wal_repair", "restart", "execute", "fill", "reconcile"),
            ("same_size_wal_corruption_refused", "broker_fills")),
        "stale_populated_restore": ((*BASE, "checkpoint", "execute", "fill", "reconcile", "restore", "restart", "reconcile", "execute"),
            ("populated_physical_backup", "stale_physical_restore", "restore_increases_fenced", "broker_fills")),
        "valid_json_state_corruption": ((*BASE, "corrupt_state", "restart", "execute", "fill", "reconcile"),
            ("valid_json_corruption_refused", "broker_fills")),
        "competing_execution_workers": ((*BASE, "compete", "execute", "fill", "reconcile"),
            ("competing_writer", "broker_fills")),
        "interrupted_multi_session_catchup": ((*BASE, "kill_catchup", "restart", "execute", "fill", "reconcile"),
            ("sigkill_between_catchup_sessions", "broker_fills")),
        "stress_and_recovery": ((*BASE, ("market_shock", -2200), *("daily",) * 3,
            "restart", ("market_shock", 3000), *("daily",) * 8, "execute", "fill", "reconcile"),
            ("market_regime_change", "controller_reduced_exposure", "broker_fills")),
    }
    return tuple(Trace(name=name, profile=profile, actions=actions(*steps), required=COMMON + coverage)
                 for name, (steps, coverage) in definitions.items() for profile in ("paper", "live_cash"))


def generated(seed, *, blocks=6):
    rng = random.Random(seed)
    steps = list(BASE)
    choices = (
        ("execute", ("fill", -1), "reconcile", "execute", "restart", "daily"),
        ("env_bad", "env_repair", "restart"),
        ("data_bad", "daily", "data_repair", "daily"),
        ("media_loss", "media_repair", "restart"),
        ("wal_corrupt", "wal_repair", "restart"),
        ("corrupt_state", "restart"),
        ("compete", "restart"),
        (("market_shock", -1500), "daily", ("market_shock", 2000), "daily"),
    )
    for _ in range(blocks):
        steps.extend(rng.choice(choices))
    return Trace(name=f"generated_{seed:08d}", seed=seed,
        profile="paper" if seed % 2 == 0 else "live_cash", actions=actions(*steps), required=COMMON)
