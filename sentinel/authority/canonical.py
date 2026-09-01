"""Deterministic JSON, hashing, and encoding primitives."""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
import unicodedata
from typing import Mapping

from .model import AuthorityRefused, MAX_CERTIFICATE_BYTES


def canonical_json_bytes(value) -> bytes:
    """Return the one signed JSON encoding and reject ambiguous value types."""
    _validate_json_value(value, label="canonical JSON")
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False).encode("ascii")


def canonical_sha256(value) -> str:
    return _sha256(canonical_json_bytes(value))
def key_id_for_public_key(public_key: bytes) -> str:
    if not isinstance(public_key, bytes) or len(public_key) != 32:
        raise AuthorityRefused("Ed25519 public keys must be exactly 32 bytes")
    return "ed25519-sha256:" + _sha256(public_key)


def _validate_json_value(value, *, label: str) -> None:
    if value is None or isinstance(value, (str, bool)):
        if isinstance(value, str) and unicodedata.normalize("NFC", value) != value:
            raise AuthorityRefused(f"{label} contains a non-NFC string")
        return
    if type(value) is int:
        return
    if isinstance(value, float):
        raise AuthorityRefused(f"{label} contains a floating-point number")
    if isinstance(value, list):
        for item in value:
            _validate_json_value(item, label=label)
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise AuthorityRefused(f"{label} contains a non-string key")
            if unicodedata.normalize("NFC", key) != key:
                raise AuthorityRefused(f"{label} contains a non-NFC key")
            _validate_json_value(item, label=label)
        return
    raise AuthorityRefused(
        f"{label} contains unsupported {type(value).__name__} value")


def _parse_canonical_json(payload: bytes, *, label: str) -> Mapping:
    if not isinstance(payload, bytes):
        raise TypeError(f"{label} bytes must be bytes")
    if not payload or len(payload) > MAX_CERTIFICATE_BYTES:
        raise AuthorityRefused(
            f"{label} size must be between 1 and {MAX_CERTIFICATE_BYTES} bytes")
    try:
        value = json.loads(
            payload.decode("utf-8"), object_pairs_hook=_unique_object,
            parse_constant=_nonfinite_constant,
            parse_float=lambda _value: (_ for _ in ()).throw(
                AuthorityRefused(f"{label} contains a floating-point number")))
    except AuthorityRefused:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise AuthorityRefused(f"{label} is not valid UTF-8 JSON") from exc
    value = _mapping(value, label=label)
    _validate_json_value(value, label=label)
    if canonical_json_bytes(value) != payload:
        raise AuthorityRefused(f"{label} bytes are not canonical JSON")
    return value
def _b64url_decode(value, *, label: str, length: int) -> bytes:
    if not isinstance(value, str) or not value or "=" in value:
        raise AuthorityRefused(f"{label} must be unpadded base64url")
    if re.fullmatch(r"[A-Za-z0-9_-]+", value) is None:
        raise AuthorityRefused(f"{label} must be unpadded base64url")
    try:
        decoded = base64.urlsafe_b64decode(
            value + "=" * ((4 - len(value) % 4) % 4))
    except (ValueError, binascii.Error) as exc:
        raise AuthorityRefused(f"{label} is malformed base64url") from exc
    canonical = base64.urlsafe_b64encode(decoded).rstrip(b"=").decode("ascii")
    if canonical != value or len(decoded) != length:
        raise AuthorityRefused(
            f"{label} is noncanonical or not exactly {length} bytes")
    return decoded


def _b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")
def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _mapping(value, *, label: str) -> Mapping:
    if not isinstance(value, Mapping):
        raise AuthorityRefused(f"{label} must be a JSON object")
    return value


def _unique_object(pairs) -> dict:
    """Reject JSON whose meaning depends on a parser's duplicate-key rule."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise AuthorityRefused(
                f"system-certificate manifest repeats JSON key {key!r}")
        result[key] = value
    return result


def _nonfinite_constant(value: str):
    raise AuthorityRefused(
        f"system-certificate manifest contains non-finite number {value}")


def _parse_manifest(payload: bytes) -> Mapping:
    try:
        value = json.loads(
            payload.decode("utf-8"), object_pairs_hook=_unique_object,
            parse_constant=_nonfinite_constant)
    except AuthorityRefused:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuthorityRefused(
            "the system-certificate manifest is not valid UTF-8 JSON") from exc
    return _mapping(value, label="system-certificate manifest")
