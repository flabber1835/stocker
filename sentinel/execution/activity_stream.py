"""Finite Activity-SSE framing and exact reference uniqueness during discovery."""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing, ExitStack


class UniqueReferences:
    """Retain small histories in memory, spill a larger stream to a private temporary DB."""

    memory_limit = 8192

    def __init__(self):
        self._memory = set()
        self._spill = None
        self._resources = ExitStack()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._resources.close()

    def add(self, ref):
        if self._spill is None:
            if ref in self._memory:
                return False
            if len(self._memory) < self.memory_limit:
                self._memory.add(ref)
                return True
            # Empty filename selects a private temporary database, deleted on close.
            self._spill = self._resources.enter_context(closing(sqlite3.connect("")))
            self._spill.execute("PRAGMA cache_size=-1024")
            self._spill.execute("CREATE TABLE refs (id TEXT PRIMARY KEY) WITHOUT ROWID")
            self._spill.executemany("INSERT INTO refs VALUES (?)", ((r,) for r in self._memory))
            self._memory.clear()
        return self._spill.execute("INSERT OR IGNORE INTO refs VALUES (?)", (ref,)).rowcount == 1


async def events(lines, *, malformed):
    """Yield a single validated JSON envelope per SSE frame, including the final frame."""
    data = []
    async for raw in lines:
        line = raw.rstrip("\r")
        if line.startswith(":"):
            if "dropped" in line.lower() or "internal server error" in line.lower():
                raise malformed("Activity SSE reported message loss/server failure; history is not complete")
        elif line.startswith("data:"):
            data.append(line[5:].lstrip())
        elif line.startswith(("event:", "id:", "retry:")):
            continue
        elif line:
            raise malformed(f"Activity SSE contained unknown line {line!r}")
        elif data:
            yield _decode(data, malformed)
            data.clear()
    if data:
        yield _decode(data, malformed)


def _decode(data, malformed):
    try:
        event = json.loads("\n".join(data))
    except ValueError as exc:
        raise malformed("Activity SSE contained malformed JSON") from exc
    if not isinstance(event, dict):
        raise malformed("Activity SSE data event must be a JSON object")
    return event
