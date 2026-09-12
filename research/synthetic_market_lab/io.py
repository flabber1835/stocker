from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
from pathlib import Path
from typing import Iterable, Mapping, Sequence


def _cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, float):
        if value == 0.0:
            return "0"
        return format(value, ".12g")
    return str(value)


class DeterministicCSVGzipWriter:
    def __init__(self, path: Path, columns: Sequence[str]):
        self.path = path
        self.columns = tuple(columns)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._raw = path.open("wb")
        self._gz = gzip.GzipFile(filename="", mode="wb", fileobj=self._raw, mtime=0, compresslevel=3)
        self._text = io.TextIOWrapper(self._gz, encoding="utf-8", newline="")
        self._writer = csv.writer(self._text, lineterminator="\n")
        self._writer.writerow(self.columns)
        self.rows = 0

    def write(self, row: Mapping[str, object] | Sequence[object]) -> None:
        if isinstance(row, Mapping):
            values = [_cell(row.get(c)) for c in self.columns]
        else:
            values = [_cell(v) for v in row]
        self._writer.writerow(values)
        self.rows += 1

    def close(self) -> None:
        if self._text.closed:
            return
        self._text.flush()
        self._text.detach()
        self._gz.close()
        self._raw.close()

    def __enter__(self) -> "DeterministicCSVGzipWriter":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


def write_csv_gz(path: Path, columns: Sequence[str], rows: Iterable[Mapping[str, object] | Sequence[object]]) -> int:
    with DeterministicCSVGzipWriter(path, columns) as writer:
        for row in rows:
            writer.write(row)
        return writer.rows


def read_csv_gz(path: Path) -> list[dict[str, str]]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def canonical_json_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode("utf-8")


def write_canonical_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def file_record(path: Path) -> dict[str, object]:
    return {"sha256": sha256_file(path), "bytes": path.stat().st_size}
