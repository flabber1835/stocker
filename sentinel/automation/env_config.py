"""Shared environment parser for automation workers and their supervisors."""
from __future__ import annotations

import os
from types import MappingProxyType
from typing import Mapping

from sentinel.automation.model import AutomationConfig


AUTOMATION_CONFIG_ENV_BY_FIELD = MappingProxyType({
    "publication_timing_policy":
        "SENTINEL_AUTOMATION_PUBLICATION_TIMING_POLICY",
    "publication_delay_seconds":
        "SENTINEL_AUTOMATION_PUBLICATION_DELAY_SECONDS",
    "execution_delay_seconds":
        "SENTINEL_AUTOMATION_EXECUTION_DELAY_SECONDS",
    "paper_debug_window": "SENTINEL_PAPER_DEBUG_WINDOW",
    "lease_seconds": "SENTINEL_AUTOMATION_LEASE_SECONDS",
    "heartbeat_seconds": "SENTINEL_AUTOMATION_HEARTBEAT_SECONDS",
    "callback_deadline_seconds":
        "SENTINEL_AUTOMATION_CALLBACK_DEADLINE_SECONDS",
    "control_poll_seconds": "SENTINEL_AUTOMATION_CONTROL_POLL_SECONDS",
    "retry_base_seconds": "SENTINEL_AUTOMATION_RETRY_BASE_SECONDS",
    "retry_max_seconds": "SENTINEL_AUTOMATION_RETRY_MAX_SECONDS",
    "refresh_max_attempts": "SENTINEL_AUTOMATION_REFRESH_MAX_ATTEMPTS",
    "preflight_recover_max_attempts":
        "SENTINEL_AUTOMATION_PREFLIGHT_RECOVER_MAX_ATTEMPTS",
    "prepare_max_attempts": "SENTINEL_AUTOMATION_PREPARE_MAX_ATTEMPTS",
    "execute_max_attempts": "SENTINEL_AUTOMATION_EXECUTE_MAX_ATTEMPTS",
    "recover_max_attempts": "SENTINEL_AUTOMATION_RECOVER_MAX_ATTEMPTS",
    "alert_claim_seconds": "SENTINEL_AUTOMATION_ALERT_CLAIM_SECONDS",
    "alert_max_attempts": "SENTINEL_AUTOMATION_ALERT_MAX_ATTEMPTS",
})


def config_from_env(env: Mapping[str, str] | None = None) -> AutomationConfig:
    from sentinel.execution.market_buy_policy import MarketBuyPolicy

    source = os.environ if env is None else env
    values = {}
    market_policy = MarketBuyPolicy.from_env(source)
    if market_policy is not None:
        values["market_buy_policy_sha256"] = market_policy.fingerprint()
    for field, name in AUTOMATION_CONFIG_ENV_BY_FIELD.items():
        raw = str(source.get(name, "")).strip()
        if not raw:
            continue
        if field == "paper_debug_window":
            from sentinel.automation.model import PaperDebugWindow
            values[field] = PaperDebugWindow.from_env(source)
        else:
            values[field] = raw if field == "publication_timing_policy" else int(raw)
    return AutomationConfig(**values)
