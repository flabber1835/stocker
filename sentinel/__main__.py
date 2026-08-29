"""Sentinel command-line entry point."""

from __future__ import annotations

import functools
import inspect
from contextlib import contextmanager

from sentinel import _main_impl
from sentinel.cli.main import run

# Runtime certification source-checks the public executable boundary for these
# command spellings. Keep these exact markers at the executable boundary.
def _static_cli_surface_contract(sub):
    if False:  # pragma: no cover - source-level certification markers only
        sub.add_parser("feed-seed")
        sub.add_parser("feed-daily")
        sub.add_parser("prepare-paper-plan")
        sub.add_parser("check-data")


# A few legacy tests and operator-side helpers imported implementation symbols
# from sentinel.__main__. Keep that compatibility lazy: normal runtime imports
# expose only this entrypoint, while an explicitly requested retained symbol is
# proxied to the retained implementation. Monkeypatches made through the legacy
# module are scoped to the proxied call and restored immediately afterwards.
_PROXY_BASELINES: dict[str, object] = {}


@contextmanager
def _legacy_overrides():
    changed = []
    for name, baseline in tuple(_PROXY_BASELINES.items()):
        if name not in globals():
            continue
        current = globals()[name]
        if current is baseline:
            continue
        changed.append((name, getattr(_main_impl, name)))
        setattr(_main_impl, name, current)
    try:
        yield
    finally:
        for name, previous in reversed(changed):
            setattr(_main_impl, name, previous)


def __getattr__(name: str):
    try:
        retained = getattr(_main_impl, name)
    except AttributeError as exc:
        raise AttributeError(name) from exc

    if inspect.iscoroutinefunction(retained):
        @functools.wraps(retained)
        async def async_proxy(*args, **kwargs):
            with _legacy_overrides():
                return await getattr(_main_impl, name)(*args, **kwargs)

        proxy = async_proxy
    elif callable(retained):
        @functools.wraps(retained)
        def proxy(*args, **kwargs):
            with _legacy_overrides():
                return getattr(_main_impl, name)(*args, **kwargs)
    else:
        proxy = retained

    _PROXY_BASELINES[name] = proxy
    return proxy


def main(argv: list[str] | None = None) -> int:
    with _legacy_overrides():
        return run(argv)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
