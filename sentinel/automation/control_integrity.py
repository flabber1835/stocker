"""Immutable-lineage validation for the automation control singleton."""
from __future__ import annotations

import json
from typing import Any, Mapping

from sentinel.automation.model import (
    AutomationControl,
    AutomationRefused,
    ControlBinding,
)


def _detail(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        value = json.loads(value)
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise AutomationRefused(
            "automation control event detail is not a JSON object")
    return dict(value)


def validate_control_lineage(
        conn, control: AutomationControl) -> AutomationControl:
    """Replay immutable control events and require exact authority agreement.

    Generation 1 is schema genesis: disabled, kill engaged, no binding. Every
    later generation must have exactly one event. Liveness verdict/check fields
    are intentionally excluded because they are same-generation observations,
    not authority transitions.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT seq,generation,action,detail"
            " FROM sentinel_automation_events ORDER BY generation,seq")
        rows = list(cur.fetchall())

    enabled = False
    kill_engaged = True
    binding: ControlBinding | None = None
    generation = 1

    for _seq, raw_generation, raw_action, raw_detail in rows:
        event_generation = int(raw_generation)
        if event_generation != generation + 1:
            raise AutomationRefused(
                "automation control event generations are not contiguous "
                "from genesis")
        action = str(raw_action)
        detail = _detail(raw_detail)

        if action == "ACTIVATED":
            if enabled:
                raise AutomationRefused(
                    "automation control history activates an enabled service")
            try:
                binding = ControlBinding.model_validate(detail)
            except Exception as exc:
                raise AutomationRefused(
                    "automation activation event has malformed binding authority") \
                    from exc
            enabled = True
            kill_engaged = True
        elif action == "DEACTIVATED":
            if not enabled:
                raise AutomationRefused(
                    "automation control history deactivates a disabled service")
            enabled = False
            kill_engaged = True
        elif action == "KILL_RELEASED":
            if not enabled or not kill_engaged or binding is None:
                raise AutomationRefused(
                    "automation control history releases an unavailable kill switch")
            try:
                released = ControlBinding.model_validate(detail)
            except Exception as exc:
                raise AutomationRefused(
                    "kill-release event has malformed binding authority") from exc
            if released != binding:
                raise AutomationRefused(
                    "kill-release binding disagrees with activation authority")
            kill_engaged = False
        elif action == "KILL_ENGAGED":
            if not enabled or kill_engaged:
                raise AutomationRefused(
                    "automation control history contains an invalid kill engagement")
            kill_engaged = True
        else:
            raise AutomationRefused(
                f"automation control history contains unknown action {action!r}")
        generation = event_generation

    if generation != control.generation:
        raise AutomationRefused(
            "automation control generation disagrees with immutable history")
    if enabled != control.enabled:
        raise AutomationRefused(
            "automation control enabled state disagrees with immutable history")
    if kill_engaged != control.kill_switch_engaged:
        raise AutomationRefused(
            "automation control kill state disagrees with immutable history")
    try:
        actual_binding = control.binding
    except Exception as exc:
        raise AutomationRefused(
            "automation control singleton carries malformed binding authority") from exc
    if actual_binding != binding:
        raise AutomationRefused(
            "automation control binding disagrees with immutable history")
    return control


__all__ = ["validate_control_lineage"]
