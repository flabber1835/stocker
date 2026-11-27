"""A writer's active independent orders share a one-way, in-memory stop."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass


@dataclass
class _Group:
    keys: frozenset[str]
    stopped: bool = False


_CURRENT: ContextVar[_Group | None] = ContextVar("sentinel_submission_group", default=None)


@contextmanager
def independent_dispatch_scope(commands):
    group = _Group(frozenset(command.client_key for command in commands))
    token = _CURRENT.set(group)
    try:
        yield
    finally:
        group.stopped = True
        _CURRENT.reset(token)


def member(key):
    group = _CURRENT.get()
    return group is not None and key in group.keys


def stopped(key):
    group = _CURRENT.get()
    return group is not None and key in group.keys and group.stopped


def stop(key):
    group = _CURRENT.get()
    if group is not None and key in group.keys:
        group.stopped = True
