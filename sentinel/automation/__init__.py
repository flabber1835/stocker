"""Disabled-by-default durable orchestration for Sentinel paper trading.

Importing this package performs no database, clock, network, or broker action.
"""
from functools import wraps

from sentinel.automation.model import (
    AckState,
    AlertRecord,
    AlertState,
    AutomationConfig,
    AutomationControl,
    AutomationRefused,
    CallbackDeadlineExceeded,
    CancellationAuthority,
    ControlBinding,
    CycleContext,
    CycleRecord,
    CycleSpec,
    CycleState,
    DataIntegrityFailure,
    DispatchResult,
    ExecuteDisposition,
    ExecuteResult,
    ImmutableAlertChanged,
    ImmutableCycleChanged,
    InvalidCycleTransition,
    HumanInterventionRequired,
    LeaderPermit,
    MissingAutomationState,
    NonRetryableCallbackRefused,
    PermanentOperationalRefusal,
    PrepareResult,
    RefreshResult,
    SessionSchedule,
    SoftwareDefect,
    SupervisorIntegrityFailure,
    StaleLeaderRefused,
    TickAction,
    TickResult,
    TransientInfrastructureFailure,
)


def _install_control_lineage_guards() -> None:
    """Put immutable control reconstruction on every authority-bearing read."""
    from sentinel.automation import store as _store
    from sentinel.automation.control_integrity import validate_control_lineage

    if getattr(_store, "_CONTROL_LINEAGE_GUARDED", False):
        return

    original_load = _store.load_control
    original_heartbeat = _store.heartbeat_lease
    original_require_leader = _store.require_leader

    @wraps(original_load)
    def load_control(conn, *, for_update: bool = False):
        control = original_load(conn, for_update=for_update)
        return validate_control_lineage(conn, control)

    @wraps(original_heartbeat)
    def heartbeat_lease(conn, *args, **kwargs):
        load_control(conn)
        return original_heartbeat(conn, *args, **kwargs)

    @wraps(original_require_leader)
    def require_leader(conn, *args, **kwargs):
        load_control(conn)
        return original_require_leader(conn, *args, **kwargs)

    # acquire_lease() resolves its module-global load_control at call time, so
    # replacing that one name also guards lease acquisition and every store
    # writer that reloads the singleton before returning authority.
    _store.load_control = load_control
    _store.heartbeat_lease = heartbeat_lease
    _store.require_leader = require_leader
    _store._CONTROL_LINEAGE_GUARDED = True


_install_control_lineage_guards()


__all__ = [
    "AckState", "AlertRecord", "AlertState", "AutomationConfig",
    "AutomationControl", "AutomationRefused", "CallbackDeadlineExceeded",
    "CancellationAuthority",
    "ControlBinding",
    "CycleContext", "CycleRecord", "CycleSpec", "CycleState",
    "DataIntegrityFailure",
    "DispatchResult", "ExecuteDisposition", "ExecuteResult",
    "ImmutableAlertChanged", "ImmutableCycleChanged",
    "HumanInterventionRequired", "InvalidCycleTransition", "LeaderPermit",
    "MissingAutomationState", "NonRetryableCallbackRefused",
    "PermanentOperationalRefusal", "PrepareResult", "RefreshResult",
    "SessionSchedule", "SoftwareDefect", "SupervisorIntegrityFailure",
    "StaleLeaderRefused", "TickAction",
    "TickResult", "TransientInfrastructureFailure",
]
