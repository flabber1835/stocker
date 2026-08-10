"""Deterministic source-tree digests, usable from EITHER side of the retirement.

`sentinel/identity.py` computes these for the Sentinel image. bt-engine needs
the same digest, computed the same way, so that a rehearsal can be bound to the
engine source it actually ran — and neither may import the other. So the
mechanism lives here, in `shared/`, and both call it.

WHAT IT IS FOR. The certification manifest names the Wealth Core source that
Sentinel's image carries. The bt-engine run row records the Wealth Core source
the rehearsal IMPORTED. Comparing the two proves the numbers came from the
engine being certified. Inspecting a mutable `:latest` tag after the fact cannot
prove that: the tag may have been rebuilt between the run and the finalization,
and nothing about the resulting manifest would look wrong.

NOT under `wealth_core/`, deliberately — that package's tree is hashed as
`wealth_core_source` in every certification record and has been byte-identical
across five reviews. A helper that HASHES it must not be inside it, or every
change to the hashing would move the hash.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Optional


def package_source_hash(root: str | Path) -> Optional[str]:
    """Sorted relative POSIX paths, each hashed with its content.

    Independent of filesystem order, absolute location, and the caches a test
    run leaves behind. Byte-identical to `sentinel.identity.source_hash`'s
    digest — asserted by `tests/sentinel/test_runtime_is_the_artifact.py`, so
    the two cannot drift into producing different answers about one tree.
    """
    p = Path(root)
    if not p.exists():
        return None
    files = sorted(q for q in p.rglob("*.py") if "__pycache__" not in q.parts)
    h = hashlib.sha256()
    for q in files:
        h.update(q.relative_to(p).as_posix().encode())
        h.update(b"\0")
        h.update(hashlib.sha256(q.read_bytes()).hexdigest().encode())
        h.update(b"\n")
    return h.hexdigest()


def wealth_core_source_hash() -> Optional[str]:
    """The digest of the Wealth Core package AS IMPORTED.

    Resolved by import rather than by assembling a path: the same defect that
    made `sentinel.identity` report `files: 0, hash: None` inside the runtime
    image came from guessing a repository layout that does not exist there.
    """
    import stock_strategy_shared.wealth_core as wc

    f = getattr(wc, "__file__", None)
    if f:
        return package_source_hash(Path(f).resolve().parent)
    paths = list(getattr(wc, "__path__", []) or [])
    return package_source_hash(paths[0]) if paths else None


__all__ = ["package_source_hash", "wealth_core_source_hash"]
