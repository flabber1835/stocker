"""Exact expected-state comparisons, independent of production reconstruction."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
from decimal import Decimal

from .model import Corpus


class StateMismatch(AssertionError):
    pass


def canonical(value):
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (dt.datetime, dt.date)):
        return value.isoformat()
    if isinstance(value, (int, float, Decimal)):
        if not math.isfinite(float(value)):
            raise StateMismatch("non-finite numeric corpus value")
        return format(Decimal(str(value)).normalize(), "f")
    if isinstance(value, dict):
        return {str(k): canonical(v) for k, v in sorted(value.items())}
    if isinstance(value, (tuple, list)):
        return [canonical(v) for v in value]
    return value


def canonical_bytes(value) -> bytes:
    return json.dumps(canonical(value), sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode()


def digest(value) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def corpus_digest(corpus: Corpus) -> str:
    return digest({field: sorted(canonical(getattr(corpus, field)), key=lambda r: json.dumps(r))
                   for field in Corpus.model_fields})


def compare(expected: Corpus, actual: Corpus) -> None:
    for field in Corpus.model_fields:
        want = sorted(canonical(getattr(expected, field)), key=lambda r: json.dumps(r))
        got = sorted(canonical(getattr(actual, field)), key=lambda r: json.dumps(r))
        if want != got:
            differing = next((i for i, pair in enumerate(zip(want, got))
                              if pair[0] != pair[1]), min(len(want), len(got)))
            raise StateMismatch(json.dumps({
                "field": field, "expected_rows": len(want), "actual_rows": len(got),
                "first_difference": differing,
                "expected": want[differing:differing + 2],
                "actual": got[differing:differing + 2],
            }, sort_keys=True))


def compare_readiness(*, expected: bool, actual: bool,
                      required_blockers: tuple[str, ...], failures: list[str]) -> None:
    if expected != actual or not set(required_blockers).issubset(failures):
        raise StateMismatch(f"readiness expected={expected}, actual={actual}, "
                            f"required={required_blockers}, failures={failures}")
