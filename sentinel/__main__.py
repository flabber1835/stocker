"""Sentinel CLI facade enforcing explicit manual feed-daily authority."""
from __future__ import annotations

import sys

from sentinel import _main_impl as _base

for _name in dir(_base):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_base, _name)

_EXPORTED_BASE_NAMES = tuple(
    name for name in dir(_base) if not name.startswith("__") and name != "main")


def _sync_test_overrides():
    """Propagate monkeypatched facade symbols while retained code executes."""
    changed = []
    for name in _EXPORTED_BASE_NAMES:
        current = globals().get(name)
        original = getattr(_base, name)
        if current is not original:
            changed.append((name, original))
            setattr(_base, name, current)
    return changed


def _restore_test_overrides(changed) -> None:
    for name, value in reversed(changed):
        setattr(_base, name, value)


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
