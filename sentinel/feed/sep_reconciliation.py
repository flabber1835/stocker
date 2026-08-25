"""Complete SEP reconciliation with causal source-update authority."""
from __future__ import annotations

import contextlib
import contextvars
import datetime as dt
import sys
import types

from sentinel.feed import sep_reconciliation_impl as _impl
from sentinel.feed.source_authority import CanonicalSourceFetch, SepUpdateEnvelope

for _name in dir(_impl):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_impl, _name)

_ORIGINAL_SOURCE_FINGERPRINT = _impl._source_fingerprint
_OBSERVATION_CEILING = contextvars.ContextVar(
    "sentinel_sep_reconciliation_observation_ceiling", default=None)


def _strict_ceiling(value) -> dt.date:
    if isinstance(value, dt.datetime):
        raise ValueError("SEP reconciliation observation ceiling must be a date")
    if isinstance(value, dt.date):
        return value
    text = str(value)
    parsed = dt.date.fromisoformat(text)
    if text != parsed.isoformat():
        raise ValueError("SEP reconciliation observation ceiling must use YYYY-MM-DD")
    return parsed


@contextlib.contextmanager
def _ceiling(value):
    token = _OBSERVATION_CEILING.set(_strict_ceiling(value))
    try:
        yield
    finally:
        _OBSERVATION_CEILING.reset(token)


def _guarded_source_fingerprint(conn, *, fetch, start: str, end: str):
    ceiling = _OBSERVATION_CEILING.get() or dt.date.today()
    guarded = CanonicalSourceFetch(
        fetch, sep_update_envelope=SepUpdateEnvelope.through(
            ceiling, context="complete SEP value/key reconciliation"))
    return _ORIGINAL_SOURCE_FINGERPRINT(
        conn, fetch=guarded, start=start, end=end)


_impl._source_fingerprint = _guarded_source_fingerprint
_source_fingerprint = _guarded_source_fingerprint


def reconcile_year(conn, *, fetch=_impl.sharadar.fetch_table,
                   year: int, start: str, end: str,
                   observation_ceiling=None):
    ceiling = dt.date.today() if observation_ceiling is None else observation_ceiling
    with _ceiling(ceiling):
        return _impl.reconcile_year(
            conn, fetch=fetch, year=year, start=start, end=end)


def reconcile_all(conn, *, fetch=_impl.sharadar.fetch_table, through: str):
    with _ceiling(through):
        return _impl.reconcile_all(conn, fetch=fetch, through=through)


def reconcile_next(conn, *, fetch=_impl.sharadar.fetch_table, through: str):
    with _ceiling(through):
        return _impl.reconcile_next(conn, fetch=fetch, through=through)


_FACADE_OWNED = frozenset({
    "_source_fingerprint", "reconcile_year", "reconcile_all", "reconcile_next",
})


class _SepReconciliationFacade(types.ModuleType):
    def __setattr__(self, name, value):
        if name not in _FACADE_OWNED and hasattr(_impl, name):
            setattr(_impl, name, value)
        super().__setattr__(name, value)


sys.modules[__name__].__class__ = _SepReconciliationFacade
__all__ = list(getattr(_impl, "__all__", ()))
