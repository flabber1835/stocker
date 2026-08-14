"""Disabled-by-default durable orchestration for Sentinel paper trading.

Importing this package performs no database, clock, network, or broker action.
"""
from sentinel.automation.model import (
    AckState,
    AlertRecord,
    AlertState,
    AutomationConfig,
    AutomationControl,
    AutomationRefused,
    ControlBinding,
    CycleContext,
    CycleRecord,
    CycleSpec,
    CycleState,
    DispatchResult,
    ExecuteDisposition,
    ExecuteResult,
    ImmutableAlertChanged,
    ImmutableCycleChanged,
    InvalidCycleTransition,
    LeaderPermit,
    MissingAutomationState,
    NonRetryableCallbackRefused,
    PrepareResult,
    RefreshResult,
    SessionSchedule,
    StaleLeaderRefused,
    TickAction,
    TickResult,
)


__all__ = [
    "AckState", "AlertRecord", "AlertState", "AutomationConfig",
    "AutomationControl", "AutomationRefused", "ControlBinding",
    "CycleContext", "CycleRecord", "CycleSpec", "CycleState",
    "DispatchResult", "ExecuteDisposition", "ExecuteResult",
    "ImmutableAlertChanged", "ImmutableCycleChanged",
    "InvalidCycleTransition", "LeaderPermit", "MissingAutomationState",
    "NonRetryableCallbackRefused", "PrepareResult", "RefreshResult",
    "SessionSchedule",
    "StaleLeaderRefused", "TickAction", "TickResult",
]
