"""Disk-backed complete Sharadar ACTIONS source generations.

The complete ACTIONS export currently contains hundreds of thousands of rows.
Keeping the decoded CSV, a canonical identity map, the published baseline, and
the final observation list in Python at the same time made correctness depend on
a multi-gigabyte heap.  This module moves source-row identity, exact-repeat
collapse, and generation comparison to a temporary SQLite relation.

SQLite is only scratch authority: publication still lives in PostgreSQL.  The
scratch database is deleted when the snapshot closes and can always be rebuilt
from the complete vendor export.
"""
from __future__ import annotations

import csv
from contextlib import closing
import datetime as dt
import io
import json
from pathlib import Path
import sqlite3
import tempfile
from typing import Iterable, Iterator, Mapping, Sequence
import zipfile

from sentinel.feed import action_source


class ActionSnapshotError(RuntimeError):
    """The complete ACTIONS export cannot define one canonical generation."""


_CURRENT_DDL = """
CREATE TABLE current_rows (
    source_row_id  TEXT NOT NULL,
    source_payload TEXT NOT NULL,
    ticker         TEXT NOT NULL,
    session        TEXT NOT NULL,
    action         TEXT NOT NULL,
    name           TEXT,
    value          TEXT,
    contraticker   TEXT,
    contraname     TEXT,
    PRIMARY KEY (source_row_id, source_payload)
)
"""

_PRIOR_DDL = """
CREATE TABLE prior_rows (
    source_row_id  TEXT PRIMARY KEY,
    source_payload TEXT NOT NULL,
    ticker         TEXT NOT NULL,
    session        TEXT NOT NULL,
    action         TEXT NOT NULL,
    name           TEXT,
    value          TEXT,
    contraticker   TEXT,
    contraname     TEXT
)
"""

_INSERT_CURRENT = """
INSERT OR IGNORE INTO current_rows
 (source_row_id,source_payload,ticker,session,action,name,value,
  contraticker,contraname)
VALUES (?,?,?,?,?,?,?,?,?)
"""

_INSERT_PRIOR = """
INSERT INTO prior_rows
 (source_row_id,source_payload,ticker,session,action,name,value,
  contraticker,contraname)
VALUES (?,?,?,?,?,?,?,?,?)
ON CONFLICT(source_row_id) DO UPDATE SET
 source_payload=excluded.source_payload,
 ticker=excluded.ticker,
 session=excluded.session,
 action=excluded.action,
 name=excluded.name,
 value=excluded.value,
 contraticker=excluded.contraticker,
 contraname=excluded.contraname
"""


class ActionSnapshot(Sequence[dict]):
    """Replayable, bounded-memory complete ACTIONS generation.

    ``source_rows`` counts received CSV rows. ``len(snapshot)`` counts distinct
    canonical seven-column source rows. Exact semantic repeats collapse under
    the explicit source-row rule; every distinct sibling sharing an economic
    ``(ticker,date,action)`` key remains present.
    """

    def __init__(self) -> None:
        self._directory = tempfile.TemporaryDirectory(
            prefix="sentinel-actions-snapshot-")
        self.path = Path(self._directory.name) / "actions.sqlite3"
        self.source_rows = 0
        self.exact_repeat_rows = 0
        self._distinct_rows = 0
        self._closed = False
        with closing(self._connect()) as conn:
            conn.executescript(_CURRENT_DDL + ";" + _PRIOR_DDL + ";")

    @classmethod
    def from_rows(cls, rows: Iterable[Mapping], *, batch_size: int = 5_000
                  ) -> "ActionSnapshot":
        snapshot = cls()
        try:
            snapshot._load_current(rows, batch_size=batch_size)
            return snapshot
        except BaseException:
            snapshot.close()
            raise

    @classmethod
    def from_zip_bytes(
        cls,
        blob: bytes,
        *,
        required_columns: Iterable[str] = action_source.SOURCE_FIELDS,
        batch_size: int = 5_000,
    ) -> "ActionSnapshot":
        """Incrementally decode a one-CSV ZIP directly into external spill."""
        snapshot = cls()
        try:
            try:
                archive = zipfile.ZipFile(io.BytesIO(blob))
            except (zipfile.BadZipFile, OSError) as exc:
                raise ActionSnapshotError(
                    "complete ACTIONS export is not a readable ZIP archive") from exc
            with archive:
                members = [item for item in archive.infolist() if not item.is_dir()]
                if len(members) != 1 or not members[0].filename.lower().endswith(".csv"):
                    raise ActionSnapshotError(
                        "complete ACTIONS export must contain exactly one CSV file")
                with archive.open(members[0], "r") as raw:
                    text = io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")
                    reader = csv.DictReader(text)
                    fields = list(reader.fieldnames or ())
                    if (len(fields) != len(set(fields))
                            or any(not str(field).strip() for field in fields)):
                        raise ActionSnapshotError(
                            "complete ACTIONS export has invalid/duplicate columns")
                    missing = sorted(set(required_columns) - set(fields))
                    if missing:
                        raise ActionSnapshotError(
                            "complete ACTIONS export lacks required column(s): "
                            + ", ".join(missing))

                    def rows() -> Iterator[dict]:
                        for row in reader:
                            if None in row:
                                raise ActionSnapshotError(
                                    "complete ACTIONS export row is wider than its header")
                            yield {
                                key: (None if value == "" else value)
                                for key, value in row.items()
                            }

                    snapshot._load_current(rows(), batch_size=batch_size)
            return snapshot
        except BaseException:
            snapshot.close()
            raise

    @classmethod
    def from_zip_path(
        cls,
        path: str | Path,
        *,
        required_columns: Iterable[str] = action_source.SOURCE_FIELDS,
        batch_size: int = 5_000,
    ) -> "ActionSnapshot":
        """Measurement/operator helper that avoids retaining compressed bytes."""
        snapshot = cls()
        try:
            try:
                archive = zipfile.ZipFile(str(path))
            except (zipfile.BadZipFile, OSError) as exc:
                raise ActionSnapshotError(
                    "complete ACTIONS export is not a readable ZIP archive") from exc
            with archive:
                members = [item for item in archive.infolist() if not item.is_dir()]
                if len(members) != 1 or not members[0].filename.lower().endswith(".csv"):
                    raise ActionSnapshotError(
                        "complete ACTIONS export must contain exactly one CSV file")
                with archive.open(members[0], "r") as raw:
                    text = io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")
                    reader = csv.DictReader(text)
                    fields = list(reader.fieldnames or ())
                    if (len(fields) != len(set(fields))
                            or any(not str(field).strip() for field in fields)):
                        raise ActionSnapshotError(
                            "complete ACTIONS export has invalid/duplicate columns")
                    missing = sorted(set(required_columns) - set(fields))
                    if missing:
                        raise ActionSnapshotError(
                            "complete ACTIONS export lacks required column(s): "
                            + ", ".join(missing))

                    def rows() -> Iterator[dict]:
                        for row in reader:
                            if None in row:
                                raise ActionSnapshotError(
                                    "complete ACTIONS export row is wider than its header")
                            yield {
                                key: (None if value == "" else value)
                                for key, value in row.items()
                            }

                    snapshot._load_current(rows(), batch_size=batch_size)
            return snapshot
        except BaseException:
            snapshot.close()
            raise

    def _connect(self) -> sqlite3.Connection:
        if self._closed:
            raise ActionSnapshotError("ACTIONS scratch snapshot is closed")
        conn = sqlite3.connect(str(self.path))
        conn.execute("PRAGMA journal_mode=OFF")
        conn.execute("PRAGMA synchronous=OFF")
        conn.execute("PRAGMA temp_store=FILE")
        return conn

    @staticmethod
    def _strict_source_row(row: Mapping) -> tuple[str, str, tuple]:
        payload = action_source.canonical_payload(row)
        ticker = str(payload.get("ticker") or "").strip()
        action = str(payload.get("action") or "").strip()
        session = str(payload.get("date") or "").strip()
        if not ticker or not action or not session:
            raise ActionSnapshotError(
                "complete ACTIONS row lacks ticker, date, or action")
        try:
            parsed = dt.date.fromisoformat(session)
        except ValueError as exc:
            raise ActionSnapshotError(
                f"complete ACTIONS row has invalid date {session!r}") from exc
        if parsed.isoformat() != session:
            raise ActionSnapshotError(
                f"complete ACTIONS row date is not canonical ISO: {session!r}")
        payload_text = action_source.payload_bytes(payload).decode("utf-8")
        identity = action_source.source_row_id(payload)
        return identity, payload_text, (
            identity, payload_text, ticker, session, action,
            payload.get("name"), payload.get("value"),
            payload.get("contraticker"), payload.get("contraname"),
        )

    def _load_current(self, rows: Iterable[Mapping], *, batch_size: int) -> None:
        if batch_size < 1:
            raise ValueError("ACTIONS snapshot batch_size must be positive")
        pending: list[tuple] = []
        with closing(self._connect()) as conn:
            for row in rows:
                _identity, _payload, item = self._strict_source_row(row)
                self.source_rows += 1
                pending.append(item)
                if len(pending) >= batch_size:
                    conn.executemany(_INSERT_CURRENT, pending)
                    conn.commit()
                    pending.clear()
            if pending:
                conn.executemany(_INSERT_CURRENT, pending)
                conn.commit()
                pending.clear()
            collision = conn.execute(
                "SELECT source_row_id,COUNT(*) FROM current_rows"
                " GROUP BY source_row_id HAVING COUNT(*)>1 LIMIT 1"
            ).fetchone()
            if collision is not None:
                raise ActionSnapshotError(
                    "ACTIONS source-row identity collision for "
                    f"{collision[0]}")
            conn.execute(
                "CREATE UNIQUE INDEX current_rows_source_id"
                " ON current_rows(source_row_id)")
            self._distinct_rows = int(conn.execute(
                "SELECT COUNT(*) FROM current_rows").fetchone()[0])
            self.exact_repeat_rows = self.source_rows - self._distinct_rows

    @staticmethod
    def _prior_tuple(row: Mapping) -> tuple:
        identity = str(row.get("source_row_id") or "")
        if not identity:
            raise ActionSnapshotError(
                "published ACTIONS baseline row lacks source_row_id")
        raw_payload = row.get("source_payload")
        if isinstance(raw_payload, Mapping):
            payload_text = json.dumps(
                raw_payload, sort_keys=True, separators=(",", ":"),
                ensure_ascii=False, default=str)
        elif raw_payload not in (None, ""):
            try:
                parsed = json.loads(str(raw_payload))
            except (TypeError, ValueError) as exc:
                raise ActionSnapshotError(
                    f"published ACTIONS row {identity} has invalid source payload") from exc
            payload_text = json.dumps(
                parsed, sort_keys=True, separators=(",", ":"),
                ensure_ascii=False, default=str)
        else:
            payload_text = action_source.payload_bytes(
                action_source.canonical_payload(row)).decode("utf-8")
        ticker = str(row.get("ticker") or "").strip()
        session = str(row.get("date") or row.get("session") or "").strip()
        action = str(row.get("action") or "").strip()
        if not ticker or not session or not action:
            raise ActionSnapshotError(
                f"published ACTIONS baseline row {identity} lacks event fields")
        return (
            identity, payload_text, ticker, session, action, row.get("name"),
            row.get("value"), row.get("contraticker"), row.get("contraname"),
        )

    def load_prior_rows(self, rows: Iterable[Mapping], *, batch_size: int = 5_000
                        ) -> int:
        """Stream the published baseline into the same external comparison DB."""
        if batch_size < 1:
            raise ValueError("ACTIONS prior batch_size must be positive")
        pending: list[tuple] = []
        count = 0
        with closing(self._connect()) as conn:
            conn.execute("DELETE FROM prior_rows")
            for row in rows:
                pending.append(self._prior_tuple(row))
                count += 1
                if len(pending) >= batch_size:
                    conn.executemany(_INSERT_PRIOR, pending)
                    conn.commit()
                    pending.clear()
            if pending:
                conn.executemany(_INSERT_PRIOR, pending)
                conn.commit()
            recorded = int(conn.execute(
                "SELECT COUNT(*) FROM prior_rows").fetchone()[0])
        if recorded != count:
            raise ActionSnapshotError(
                "published ACTIONS baseline contains duplicate source identities")
        return recorded

    @property
    def prior_rows(self) -> int:
        with closing(self._connect()) as conn:
            return int(conn.execute(
                "SELECT COUNT(*) FROM prior_rows").fetchone()[0])

    def identity_delta_count(self) -> int:
        with closing(self._connect()) as conn:
            return int(conn.execute(
                "SELECT COUNT(*) FROM ("
                " SELECT c.source_row_id FROM current_rows c"
                " LEFT JOIN prior_rows p USING(source_row_id)"
                " WHERE p.source_row_id IS NULL"
                " UNION ALL"
                " SELECT p.source_row_id FROM prior_rows p"
                " LEFT JOIN current_rows c USING(source_row_id)"
                " WHERE c.source_row_id IS NULL) delta"
            ).fetchone()[0])

    def changed_dates(self, actions: Iterable[str]) -> list[str]:
        names = sorted({str(value).strip().lower() for value in actions
                        if str(value).strip()})
        if not names:
            return []
        placeholders = ",".join("?" for _ in names)
        sql = (
            "WITH changed(session,action) AS ("
            " SELECT c.session,c.action FROM current_rows c"
            " LEFT JOIN prior_rows p USING(source_row_id)"
            " WHERE p.source_row_id IS NULL"
            " UNION ALL"
            " SELECT p.session,p.action FROM prior_rows p"
            " LEFT JOIN current_rows c USING(source_row_id)"
            " WHERE c.source_row_id IS NULL)"
            " SELECT DISTINCT session FROM changed"
            f" WHERE LOWER(action) IN ({placeholders}) ORDER BY session")
        with closing(self._connect()) as conn:
            return [str(row[0]) for row in conn.execute(sql, names)]

    @staticmethod
    def _dict(row: tuple) -> dict:
        return {
            "ticker": row[0], "date": row[1], "action": row[2],
            "name": row[3], "value": row[4], "contraticker": row[5],
            "contraname": row[6],
        }

    def _iter_table(self, table: str) -> Iterator[dict]:
        if table not in {"current_rows", "prior_rows"}:
            raise ValueError("unknown ACTIONS scratch relation")
        conn = self._connect()
        try:
            cursor = conn.execute(
                f"SELECT ticker,session,action,name,value,contraticker,contraname"
                f" FROM {table} ORDER BY source_row_id")
            while True:
                batch = cursor.fetchmany(2_000)
                if not batch:
                    return
                for row in batch:
                    yield self._dict(row)
        finally:
            conn.close()

    def __iter__(self) -> Iterator[dict]:
        return self._iter_table("current_rows")

    def iter_prior(self) -> Iterator[dict]:
        return self._iter_table("prior_rows")

    def __len__(self) -> int:
        return self._distinct_rows

    def __getitem__(self, index):
        if isinstance(index, slice):
            start, stop, step = index.indices(len(self))
            return [self[item] for item in range(start, stop, step)]
        item = int(index)
        if item < 0:
            item += len(self)
        if item < 0 or item >= len(self):
            raise IndexError(index)
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT ticker,session,action,name,value,contraticker,contraname"
                " FROM current_rows ORDER BY source_row_id LIMIT 1 OFFSET ?",
                (item,)).fetchone()
        if row is None:
            raise IndexError(index)
        return self._dict(row)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._directory.cleanup()

    def __enter__(self) -> "ActionSnapshot":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.close()
        return False

    def __del__(self):  # pragma: no cover - best-effort crash/test cleanup
        try:
            self.close()
        except Exception:
            pass


__all__ = ["ActionSnapshot", "ActionSnapshotError"]
