from __future__ import annotations

from datetime import date, timedelta


def business_sessions(start: date, count: int) -> list[date]:
    sessions: list[date] = []
    cursor = start
    while len(sessions) < count:
        if cursor.weekday() < 5:
            sessions.append(cursor)
        cursor += timedelta(days=1)
    return sessions
