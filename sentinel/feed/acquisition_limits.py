"""Reviewed complete-export envelope; never truncate source evidence."""
from __future__ import annotations

import io
import struct

from sentinel.feed import sharadar

ZIP_BYTES = 64 * 1024 * 1024
CSV_BYTES = 256 * 1024 * 1024
ROWS = 1_000_000
CELLS = 8_000_000
COLUMNS = 64
RECORD_CHARS = 1024 * 1024
DIRECTORY_BYTES = 1024 * 1024
ZIP_ENTRIES = 32
CACHE_BYTES = 512 * 1024 * 1024
CACHE_FILES = 64
CHUNK_BYTES = 64 * 1024


class AcquisitionResourceExceeded(sharadar.SharadarRequestError):
    """Deterministic refusal, not a pending export or transient retry."""


def check(boundary: str, observed: int, maximum: int) -> None:
    if observed > maximum:
        raise AcquisitionResourceExceeded(
            f"SOURCE_RESOURCE_LIMIT: {boundary} exceeds limit={maximum}; observed={observed}")


def check_zip_directory(blob: bytes) -> None:
    """Bound central-directory allocation before ZipFile creates entry objects."""
    check("ZIP_BYTES", len(blob), ZIP_BYTES)
    # Standard EOCD has a 22-byte header and at most a 65535-byte comment.
    offset = blob.rfind(b"PK\x05\x06", max(0, len(blob) - 65557))
    if offset < 0 or offset + 22 > len(blob):
        raise ValueError("missing ZIP end directory")
    _, disk, start_disk, local_count, count, size, start, comment = struct.unpack_from(
        "<4s4H2LH", blob, offset)
    if (disk or start_disk or local_count != count or count == 65535
            or size == 0xffffffff or start == 0xffffffff
            or offset + 22 + comment != len(blob)
            or start + size != offset):
        raise ValueError("unsupported ZIP directory layout")
    check("ZIP_ENTRIES", count, ZIP_ENTRIES)
    check("DIRECTORY_BYTES", size, DIRECTORY_BYTES)


class ExpandedReader(io.RawIOBase):
    """Bound actual decompressor output as well as the directory's declaration."""

    def __init__(self, raw):
        self.raw = raw
        self.total = 0

    def readable(self):
        return True

    def readinto(self, buffer):
        data = self.raw.read(min(len(buffer), CHUNK_BYTES, CSV_BYTES - self.total + 1))
        self.total += len(data)
        check("CSV_BYTES", self.total, CSV_BYTES)
        buffer[:len(data)] = data
        return len(data)


class RecordLines:
    """csv.reader requests physical lines; count all lines of a quoted record."""

    def __init__(self, text):
        self.text = text
        self.total = 0

    def __iter__(self):
        return self

    def __next__(self):
        line = self.text.readline(RECORD_CHARS - self.total + 1)
        if not line:
            raise StopIteration
        self.total += len(line)
        check("RECORD_CHARS", self.total, RECORD_CHARS)
        return line
