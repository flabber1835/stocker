"""A writer's active independent orders share a one-way, in-memory stop."""
import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Callable

from sentinel.execution.commands import Command


@dataclass
class _PaperSale:
    command: Command
    promote: Callable[[], None]
    task: asyncio.Task
    attempted: bool = False
    committed: bool = False


@dataclass
class _Group:
    keys: frozenset[str]
    paper_seller: object | None = None
    sales: dict[str, _PaperSale] = field(default_factory=dict)
    stopped: bool = False
    before_transport: set[str] = field(default_factory=set)


_CURRENT: ContextVar[_Group | None] = ContextVar("sentinel_submission_group", default=None)


@contextmanager
def independent_dispatch_scope(commands, *, paper_seller=None):
    group = _Group(frozenset(command.client_key for command in commands), paper_seller)
    token = _CURRENT.set(group)
    try:
        yield
    finally:
        group.stopped = True
        _CURRENT.reset(token)


def member(key):
    group = _CURRENT.get()
    return group is not None and key in group.keys


def owner(key):
    group = _CURRENT.get()
    return group if group is not None and key in group.keys and not group.stopped else None


def sale_group():
    group = _CURRENT.get()
    return group if group is not None and group.paper_seller is not None else None


def stage_sale(broker, command, promote):
    group = sale_group()
    if group is None:
        return None
    if (group.stopped or group.paper_seller is not broker or command.client_key not in group.keys
            or command.client_key in group.sales):
        raise ValueError("sale differs from its original independent dispatch")
    sale = _PaperSale(command, promote, asyncio.current_task())
    group.sales[command.client_key] = sale
    return sale


def checkpointed(key):
    group = _CURRENT.get()
    if group is not None and key in group.keys:
        group.before_transport.add(key)


def entering_transport(key):
    group = _CURRENT.get()
    if group is not None:
        group.before_transport.discard(key)


def known_unsent(key):
    group = _CURRENT.get()
    return group is not None and key in group.before_transport


def stopped(key):
    group = _CURRENT.get()
    return group is not None and key in group.keys and group.stopped


def stop(key):
    group = _CURRENT.get()
    if group is not None and key in group.keys:
        group.stopped = True
