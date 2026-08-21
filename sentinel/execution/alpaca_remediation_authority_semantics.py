"""Restore Sentinel's immediate emergency-authority semantics.

The first remediation pass attempted to linearize kill/revocation with broker
transport by blocking those emergency operations on the execution writer lock.
That is the wrong trade-off for Sentinel: ``engage_kill`` is explicitly an
immediate fencing operation and must succeed while execution holds its writer
lock.

There is no local database primitive that can simultaneously make an already
started network send atomic with an immediate, non-blocking kill committed by a
second process.  Sentinel instead has a durable side-effect boundary:

    PLANNED -> SEND_PENDING   (committed before transport)

A kill/revocation prevents every later authority check and every new command,
but does not claim to retract a request that already crossed that durable
boundary.  Such a request keeps the same deterministic client key and is
recovered through normal UNKNOWN/SEND_PENDING reconciliation.  This is stronger
than pretending a local DB commit can unsend bytes, and it preserves the actual
emergency-brake contract.
"""
from __future__ import annotations

_INSTALLED = False


def _closure_callable(function, *names):
    """Recover the pre-remediation function captured by the temporary wrapper."""
    closure = getattr(function, "__closure__", None) or ()
    freevars = getattr(getattr(function, "__code__", None), "co_freevars", ())
    cells = {name: cell.cell_contents for name, cell in zip(freevars, closure)}
    for name in names:
        candidate = cells.get(name)
        if callable(candidate):
            return candidate
    return None


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    from sentinel import authority
    from sentinel.automation import store as automation_store
    from sentinel.execution import alpaca

    # ``automation.store`` imports ``execution.journal`` and can therefore be
    # only partly initialized while the execution package installs overlays.
    # Its module tail calls this installer again after ``engage_kill`` exists.
    if not hasattr(automation_store, "engage_kill"):
        return

    if getattr(alpaca, "_IMMEDIATE_AUTHORITY_SEMANTICS_INSTALLED", False):
        _INSTALLED = True
        return

    original_kill = _closure_callable(
        automation_store.engage_kill, "original_engage_kill")
    if original_kill is None:
        raise RuntimeError(
            "cannot recover immediate engage_kill implementation from the "
            "temporary serialization wrapper")
    automation_store.engage_kill = original_kill

    for name in (
            "revoke_signed_certificate", "revoke_signed_key",
            "revoke_system_certificate"):
        wrapped = getattr(authority, name)
        original = _closure_callable(wrapped, "function")
        if original is None:
            raise RuntimeError(
                f"cannot recover immediate authority function {name} from "
                "the temporary serialization wrapper")
        setattr(authority, name, original)

    alpaca._IMMEDIATE_AUTHORITY_SEMANTICS_INSTALLED = True
    _INSTALLED = True


__all__ = ["install"]
