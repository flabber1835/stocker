"""Explicit caller-owned transaction port for additive persistence adapters."""
from __future__ import annotations

from typing import Protocol


class TransactionPort(Protocol):
    """Queries/cursors only. Commit, rollback and session disposal stay outside."""
    def execute(self, query, params=None): ...
    def cursor(self, *args, **kwargs): ...


class CallerTransaction:
    """A borrowed transaction cannot complete or dispose its owner's session."""
    __slots__ = ('_connection',)

    def __init__(self, connection):
        self._connection = connection

    def execute(self, query, params=None):
        return self._connection.execute(query,params)

    def cursor(self, *args, **kwargs):
        return self._connection.cursor(*args,**kwargs)


def borrow(connection) -> CallerTransaction:
    return connection if isinstance(connection,CallerTransaction) else CallerTransaction(connection)
