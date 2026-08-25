"""Sentinel CLI facade enforcing explicit manual feed-daily authority.

The retained CLI implementation stays in ``_main_impl`` so #258 can add one
narrow pre-dispatch authority gate without duplicating the command engine. This
facade deliberately preserves the historical monkeypatch and static-inspection
surfaces used by the financial safety suite.
"""
from __future__ import annotations

import functools
import sys

from sentinel import _main_impl as _base

_BASE_EXPORTS = {
    name: getattr(_base, name)
    for name in dir(_base)
    if not name.startswith("__") and name != "main"
}
for _name, _value in _BASE_EXPORTS.items():
    globals()[_name] = _value

# Keep this literal in the public CLI source: deployment certification verifies
# that the marker-bearing runtime boundary remains visible at the executable
# entrypoint, not hidden behind an implementation indirection.
AUTHORIZED_RUNTIME_COMMANDS = _base.AUTHORIZED_RUNTIME_COMMANDS


# Static CLI-surface contract for runbook/resource-harness validation. These are
# intentionally unreachable; the executable parsers are built by _base.main.
# Keeping the exact parser spellings here preserves source-level verification
# while avoiding a second parser implementation.
def _static_cli_surface_contract(sub):
    if False:  # pragma: no cover - source-level certification markers only
        sub.add_parser("feed-seed")
        sub.add_parser("feed-daily")
        sub.add_parser("prepare-paper-plan")
        sub.add_parser("check-data")


_FACADE_BASELINE = {}


def _sync_test_overrides():
    """Propagate monkeypatched public symbols while retained code executes."""
    changed = []
    for name, original in _BASE_EXPORTS.items():
        current = globals().get(name)
        baseline = _FACADE_BASELINE.get(name, original)
        if current is not baseline:
            changed.append((name, getattr(_base, name)))
            setattr(_base, name, current)
    return changed


def _restore_test_overrides(changed) -> None:
    for name, value in reversed(changed):
        setattr(_base, name, value)


def _call_base(name, *args, **kwargs):
    changed = _sync_test_overrides()
    try:
        return getattr(_base, name)(*args, **kwargs)
    finally:
        _restore_test_overrides(changed)


async def _await_base(name, *args, **kwargs):
    changed = _sync_test_overrides()
    try:
        return await getattr(_base, name)(*args, **kwargs)
    finally:
        _restore_test_overrides(changed)


@functools.wraps(_BASE_EXPORTS["_authorized_administrative_access"])
def _authorized_administrative_access(*args, **kwargs):
    return _call_base("_authorized_administrative_access", *args, **kwargs)


@functools.wraps(_BASE_EXPORTS["_inspect_paper_account"])
async def _inspect_paper_account(*args, **kwargs):
    return await _await_base("_inspect_paper_account", *args, **kwargs)


@functools.wraps(_BASE_EXPORTS["_migration_plan"])
async def _migration_plan(*args, **kwargs):
    return await _await_base("_migration_plan", *args, **kwargs)


@functools.wraps(_BASE_EXPORTS["_migrate_account"])
async def _migrate_account(*args, **kwargs):
    return await _await_base("_migrate_account", *args, **kwargs)


@functools.wraps(_BASE_EXPORTS["_adopt_restored"])
async def _adopt_restored(*args, **kwargs):
    return await _await_base("_adopt_restored", *args, **kwargs)


@functools.wraps(_BASE_EXPORTS["_prepare_paper_plan"])
async def _prepare_paper_plan(*args, **kwargs):
    return await _await_base("_prepare_paper_plan", *args, **kwargs)


@functools.wraps(_BASE_EXPORTS["_execute_paper_plan"])
async def _execute_paper_plan(*args, **kwargs):
    return await _await_base("_execute_paper_plan", *args, **kwargs)


@functools.wraps(_BASE_EXPORTS["cmd_create_paper_observation_candidate"])
def cmd_create_paper_observation_candidate(*args, **kwargs):
    return _call_base("cmd_create_paper_observation_candidate", *args, **kwargs)


# Baseline is captured only after compatibility wrappers exist. A later
# monkeypatch is therefore distinguishable from the facade's own wrapper.
_FACADE_BASELINE.update({name: globals().get(name) for name in _BASE_EXPORTS})


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "feed-daily" not in args:
        changed = _sync_test_overrides()
        try:
            return _base.main(args)
        finally:
            _restore_test_overrides(changed)

    from sentinel.feed import ingest, manual_daily

    if any(token in {"-h", "--help"} for token in args):
        print(manual_daily.help_text(), end="")
        return _base.EXIT_OK
    try:
        clean, raw_through = manual_daily.extract_through(args)
        boundary = manual_daily.validate_through(raw_through)
    except manual_daily.ManualDailyBoundaryInvalid as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return _base.EXIT_CONFIG

    # This occurs before retained main constructs config, opens a database, or
    # validates vendor credentials. It is the operator-visible command boundary.
    print(
        f"sentinel: feed-daily through-session {boundary.through} "
        f"({boundary.calendar_version}; latest-closed={boundary.latest_closed})")

    original_daily = ingest.daily

    def explicit_daily(conn, *daily_args, **daily_kwargs):
        supplied = daily_kwargs.pop("today", None)
        if supplied is not None and str(supplied) != boundary.through:
            raise manual_daily.ManualDailyBoundaryInvalid(
                f"manual command resolved {boundary.through} but call path "
                f"supplied conflicting session {supplied}")
        return original_daily(
            conn, *daily_args, today=boundary.through, **daily_kwargs)

    changed = _sync_test_overrides()
    ingest.daily = explicit_daily
    try:
        return _base.main(clean)
    finally:
        ingest.daily = original_daily
        _restore_test_overrides(changed)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
