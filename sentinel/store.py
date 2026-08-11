"""Durable, append-only record of the ownership handover.

The ownership boundary is only as trustworthy as its persistence: if
`SENTINEL_OWNERSHIP_ESTABLISHED` can be lost, a restart re-enters legacy cleanup
against a Sentinel-owned book and liquidates it. So this module's contract is
narrow and its failure modes are loud.

```text
APPEND-ONLY     events are never rewritten. The log IS the history
DURABLE         each append is flushed and fsynced before it is acknowledged
CRASH-SAFE      a torn final line is tolerated on read, never on write
IRREVERSIBLE    no API removes SENTINEL_OWNERSHIP_ESTABLISHED. Undoing the
                migration is an administrative act against the file itself,
                which is the intended level of friction
```

JSONL rather than a table because Sentinel has no database yet and this state is
needed before one exists — the very first thing Sentinel does, on an account it
does not yet own. `OwnershipStore` is the seam; a Postgres implementation drops
in behind it when the Sentinel database lands, and nothing above it changes.

Stocker's `intent_proposals` earned the note that "append-only by application
convention" is a description of intent rather than a property. The same caveat
applies here and is worth stating rather than implying: nothing stops an
operator editing the file. What this module guarantees is that no CODE PATH
rewrites or truncates it.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Protocol

from sentinel.ownership import OwnershipState


@dataclass(frozen=True)
class OwnershipEvent:
    state: OwnershipState
    at: datetime
    detail: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(
            {
                "state": self.state.value,
                "at": self.at.astimezone(timezone.utc).isoformat(),
                "detail": self.detail,
            },
            sort_keys=True,
            separators=(",", ":"),
        )

    @staticmethod
    def from_obj(obj: dict[str, Any]) -> "OwnershipEvent":
        return OwnershipEvent(
            state=OwnershipState(obj["state"]),
            at=datetime.fromisoformat(obj["at"]),
            detail=obj.get("detail") or {},
        )


class OwnershipStore(Protocol):
    def append(self, event: OwnershipEvent) -> None: ...
    def events(self) -> list[OwnershipEvent]: ...


def current_state(store: OwnershipStore) -> OwnershipState:
    """The last state recorded, or UNINITIALIZED for an empty log."""
    events = store.events()
    return events[-1].state if events else OwnershipState.UNINITIALIZED


def ownership_established(store: OwnershipStore) -> bool:
    """Whether the irreversible migration event is ANYWHERE in the history.

    Deliberately not "is the current state at or past ownership". States advance
    and can in principle be re-recorded; the question here is whether the
    decision was ever taken, and a decision that was taken cannot become untaken
    by a later event. Searching the whole log is what makes this monotonic.
    """
    return any(
        e.state
        in (
            OwnershipState.SENTINEL_OWNERSHIP_ESTABLISHED,
            OwnershipState.WEALTH_CORE_BOOTSTRAP_ALLOWED,
        )
        for e in store.events()
    )


class InMemoryOwnershipStore:
    """For tests and dry runs. Loses everything on exit, which is the point:
    nothing that uses it can accidentally be believed across a restart."""

    def __init__(self, events: Iterable[OwnershipEvent] = ()) -> None:
        self._events: list[OwnershipEvent] = list(events)

    def append(self, event: OwnershipEvent) -> None:
        self._events.append(event)

    def events(self) -> list[OwnershipEvent]:
        return list(self._events)


class FileOwnershipStore:
    """JSONL on disk, one event per line, opened `a` and fsynced per append.

    `fsync` is not decoration. The failure this guards against is a host losing
    power between "Sentinel established ownership" and "the page cache was
    written back", after which the next start liquidates a live book. Paying a
    sync for a handful of lifetime events is the cheapest insurance here.
    """

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, event: OwnershipEvent) -> None:
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(event.to_json() + "\n")
            fh.flush()
            os.fsync(fh.fileno())

    def events(self) -> list[OwnershipEvent]:
        if not self.path.exists():
            return []
        out: list[OwnershipEvent] = []
        for lineno, line in enumerate(
            self.path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            line = line.strip()
            if not line:
                continue
            try:
                out.append(OwnershipEvent.from_obj(json.loads(line)))
            except (ValueError, KeyError) as exc:
                # A torn LAST line is a crash mid-append and is survivable: the
                # event it described never completed, so treating it as absent is
                # correct. A torn line anywhere EARLIER means the file was
                # rewritten or corrupted, and silently skipping it could drop the
                # ownership event — the one thing that must never be lost.
                if lineno == len(self.path.read_text(encoding="utf-8").splitlines()):
                    break
                raise ValueError(
                    f"{self.path}:{lineno} is unreadable and is not the final "
                    f"line, so it is corruption rather than a torn append. "
                    f"Refusing to continue: skipping it could discard the "
                    f"ownership record and re-arm legacy liquidation. ({exc})"
                ) from exc
        return out


class PostgresOwnershipStore:
    """The AUTHORITATIVE ownership log. Same Protocol, different durability.

    `FileOwnershipStore` was correct when Sentinel had no database and the
    ownership decision had to outlive the process before one existed. It now has
    one, and the file's remaining property is the dangerous one: losing it
    re-arms classification of a Sentinel-owned book as legacy, and it sits on a
    different volume from PostgreSQL, so a restore can recover the database and
    lose the file.

    The two write in the SAME transaction as the account binding when used
    through `sentinel.migration`, which is the point — a handover that recorded
    the events but not the binding, or the reverse, is the inconsistency the
    file could never rule out.

    Append-only by application convention. Nothing here rewrites a row; nothing
    at the DATABASE level prevents it. Stated rather than implied — Stocker's
    `intent_proposals` earned that note and the same caveat applies.
    """

    def __init__(self, conn) -> None:
        self.conn = conn

    def append(self, event: OwnershipEvent) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                "INSERT INTO sentinel_ownership_events (state, at, detail)"
                " VALUES (%s,%s,%s)",
                (event.state.value, event.at, json.dumps(event.detail,
                                                         sort_keys=True)))
        self.conn.commit()

    def events(self) -> list:
        with self.conn.cursor() as cur:
            cur.execute("SELECT state, at, detail FROM sentinel_ownership_events"
                        " ORDER BY seq")
            rows = cur.fetchall()
        out = []
        for state, at, detail in rows:
            payload = detail if isinstance(detail, dict) else json.loads(detail or "{}")
            out.append(OwnershipEvent(state=OwnershipState(state), at=at,
                                      detail=payload))
        return out


def mirror_to_file(store: OwnershipStore, path) -> int:
    """Copy the authoritative log out to JSONL as AUDIT evidence.

    One direction only, and never read back as authority. The file is convenient
    for an operator with a shell and no psql, and that is all it is now — the
    moment it can answer "has this account been migrated?" it can also answer it
    WRONGLY by being absent.
    """
    target = FileOwnershipStore(path)
    existing = len(target.events())
    events = store.events()
    for event in events[existing:]:
        target.append(event)
    return len(events) - existing


def record(store: OwnershipStore, state: OwnershipState, **detail: Any) -> OwnershipEvent:
    event = OwnershipEvent(state=state, at=datetime.now(timezone.utc), detail=detail)
    store.append(event)
    return event
