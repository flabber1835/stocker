"""Explicit closed-session authority for the manual ``feed-daily`` command."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Sequence

from sentinel.feed import calendar

SCHEMA = "sentinel.manual-feed-through/1"


class ManualDailyBoundaryInvalid(ValueError):
    """A manual daily command did not name one closed XNYS session."""


@dataclass(frozen=True)
class ManualDailyBoundary:
    through: str
    latest_closed: str
    calendar_version: str
    schema: str = SCHEMA

    def to_dict(self) -> dict:
        return {
            "schema": self.schema,
            "through": self.through,
            "latest_closed": self.latest_closed,
            "calendar": self.calendar_version,
        }


def extract_through(argv: Sequence[str]) -> tuple[list[str], str]:
    """Remove exactly one ``--through`` option from a feed-daily argv.

    The old parser does not know this option; the authority facade extracts it
    before delegating all unrelated CLI behavior to the retained implementation.
    """
    clean: list[str] = []
    values: list[str] = []
    index = 0
    args = [str(item) for item in argv]
    while index < len(args):
        token = args[index]
        if token == "--through":
            if index + 1 >= len(args) or args[index + 1].startswith("--"):
                raise ManualDailyBoundaryInvalid(
                    "feed-daily requires `--through YYYY-MM-DD`")
            values.append(args[index + 1])
            index += 2
            continue
        if token.startswith("--through="):
            values.append(token.split("=", 1)[1])
            index += 1
            continue
        clean.append(token)
        index += 1
    if len(values) != 1 or not str(values[0]).strip():
        qualifier = "exactly one" if values else "a"
        raise ManualDailyBoundaryInvalid(
            f"feed-daily requires {qualifier} `--through YYYY-MM-DD`")
    return clean, values[0]


def validate_through(value, *, now_et=None) -> ManualDailyBoundary:
    """Resolve a strict ISO date to a real XNYS session whose close has passed."""
    text = str(value or "").strip()
    if len(text) != 10:
        raise ManualDailyBoundaryInvalid(
            f"--through must be canonical YYYY-MM-DD, got {text!r}")
    try:
        parsed = dt.date.fromisoformat(text)
    except ValueError as exc:
        raise ManualDailyBoundaryInvalid(
            f"--through must be a valid ISO calendar date, got {text!r}") from exc
    if parsed.isoformat() != text:
        raise ManualDailyBoundaryInvalid(
            f"--through must be canonical YYYY-MM-DD, got {text!r}")

    try:
        opened, closed = calendar.session_window(text)
        latest = calendar.latest_closed_session(now_et)
    except Exception as exc:  # one fail-closed CLI boundary for calendar faults
        if isinstance(exc, ManualDailyBoundaryInvalid):
            raise
        raise ManualDailyBoundaryInvalid(
            f"--through {text} is not a valid evaluable XNYS session: {exc}") from exc
    if text > latest:
        now_detail = ""
        if now_et is not None:
            now_detail = f" at {now_et.isoformat()}"
        raise ManualDailyBoundaryInvalid(
            f"--through {text} has not fully closed{now_detail}; latest closed "
            f"XNYS session is {latest} (candidate close {closed.isoformat()})")
    # ``session_window`` already proves exact XNYS membership. Keep both values
    # in scope so half-day/open-close schedule failures cannot be optimized away.
    if opened >= closed:                                      # pragma: no cover
        raise ManualDailyBoundaryInvalid(
            f"XNYS exposed an impossible session window for {text}")
    return ManualDailyBoundary(
        through=text,
        latest_closed=latest,
        calendar_version=calendar.calendar_version())


def help_text() -> str:
    return (
        "usage: sentinel feed-daily [-h] --through YYYY-MM-DD\n\n"
        "Fetch and publish through one explicit fully closed XNYS session.\n\n"
        "options:\n"
        "  -h, --help            show this help message and exit\n"
        "  --through YYYY-MM-DD  required closed XNYS session boundary\n")


__all__ = [
    "ManualDailyBoundary", "ManualDailyBoundaryInvalid", "SCHEMA",
    "extract_through", "help_text", "validate_through",
]
