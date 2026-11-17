"""Bounded encoding for immutable daily checkpoint input archives."""
from __future__ import annotations

from base64 import b64decode, b64encode
import bz2
import hashlib
import hmac
import json
import re

from sentinel.feed.rolling_contract import canonical_json


SCHEMA = "sentinel.rolling-daily-input/bzip2-1"
MAX_PAYLOAD_BYTES = 128 * 1024 * 1024
MAX_COMPRESSED_BYTES = 32 * 1024 * 1024
_HASH = re.compile(r"[0-9a-f]{64}")


def encode(value: dict) -> dict:
    raw = canonical_json(value).encode("ascii")
    if len(raw) > MAX_PAYLOAD_BYTES:
        raise ValueError("daily input exceeds uncompressed archive limit")
    compressed = bz2.compress(raw, compresslevel=1)
    if len(compressed) > MAX_COMPRESSED_BYTES:
        raise ValueError("daily input exceeds compressed archive limit")
    return {"schema": SCHEMA, "sha256": hashlib.sha256(raw).hexdigest(),
            "content": b64encode(compressed).decode("ascii")}


def decode(archive: dict, *, expected_sha256: str) -> dict:
    if (not isinstance(archive, dict) or set(archive) != {"schema", "sha256", "content"}
            or archive["schema"] != SCHEMA or not isinstance(expected_sha256, str)
            or not _HASH.fullmatch(expected_sha256) or archive["sha256"] != expected_sha256):
        raise ValueError("daily input archive identity changed")
    content = archive["content"]
    if not isinstance(content, str) or len(content) > 4 * ((MAX_COMPRESSED_BYTES + 2) // 3):
        raise ValueError("daily input compressed archive size changed")
    compressed = b64decode(content, validate=True)
    if len(compressed) > MAX_COMPRESSED_BYTES:
        raise ValueError("daily input compressed archive size changed")
    stream = bz2.BZ2Decompressor()
    try:
        raw = stream.decompress(compressed, MAX_PAYLOAD_BYTES + 1)
    except OSError as exc:
        raise ValueError("daily input archive compression changed") from exc
    if (len(raw) > MAX_PAYLOAD_BYTES or not stream.eof or stream.unused_data
            or not hmac.compare_digest(hashlib.sha256(raw).hexdigest(), expected_sha256)):
        raise ValueError("daily input archive stream changed")
    try:
        value = json.loads(raw)
        if isinstance(value, dict) and canonical_json(value).encode("ascii") == raw:
            return value
    except (ValueError, RecursionError) as exc:
        raise ValueError("daily input archive JSON changed") from exc
    raise ValueError("daily input archive JSON changed")
