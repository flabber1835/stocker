"""What a certified run RAN AS. Deterministic, self-describing, hashable.

A rehearsal result is only evidence if someone can reproduce it, and by the time
Sentinel places corporate actions through an exchange calendar, "the same code
and the same corpus" no longer identifies the computation. The calendar decides
what the next valid session is; that placement decides which session a dividend
or a split lands on; that lands cash and shares in the book. The calendar
implementation is therefore part of the strategy's data contract, and so is the
interpreter that runs it and the base image that carries both.

So this module records everything that can change the answer:

```text
interpreter        python version, and whether it is the CERTIFIED one
base image         the pinned digest the image was built FROM
packages           exact installed versions of every pinned dependency, with
                   any DRIFT from sentinel/requirements.txt named
calendar           exchange name + library version
source             sentinel/ and the Wealth Core package, hashed separately —
                   they are certified against different things and move at
                   different times
corpus             vendor tables and the normalised corpus, hashed over the
                   INTERVAL being certified, not over whatever happens to be
                   loaded
```

## Two hashes, deliberately

`identity_hash` covers the ENVIRONMENT and the SOURCE — everything that is true
before a corpus exists. `corpus_hash` covers the data. They are separate because
they answer different questions: a rehearsal that differs with the same
`identity_hash` and a different `corpus_hash` was fed different data, which is a
finding; the same corpus under a different `identity_hash` is a different
machine, which is a different finding.

## RECORDED, NOT ASSERTED

Nothing here raises because the interpreter is not 3.12.13. This code has to run
in a developer's checkout, and an identity record that cannot be produced
outside the certified image is useless exactly when you want to compare the two.
`certified` is a FIELD; refusing on it is a decision for the caller that is
about to produce certification evidence, not for the module that describes the
environment.

## The corpus hash is a full scan, and is meant to be

It reads every bar in the interval and digests it in order. That is O(n) over
the window and it is the only thing that actually detects a silently corrected
row — a row count and a date span do not change when a vendor restates a price
in place, which is the exact failure the Stocker factor cache shipped for months
(`bt_data_version` exists because of it). Scope it to the interval you are
certifying, not to the whole history.
"""
from __future__ import annotations

import hashlib
import json
import platform
import re
import sys
from pathlib import Path
from typing import Iterable, Optional

#: The base image `Dockerfile.sentinel` pins by digest, and the interpreter that
#: digest carries. Recorded here so a running container can say whether it IS
#: the certified environment rather than only what it happens to be.
CERTIFIED_BASE_DIGEST = (
    "sha256:229a2c5bfa27522db7815ea81f9bed70af17ccb9de9fc7ad142b1877b5830d36")
CERTIFIED_PYTHON = "3.12.13"

_REQUIREMENTS = Path(__file__).resolve().parent / "requirements.txt"
_SENTINEL_PKG = Path(__file__).resolve().parent
_WEALTH_CORE_PKG = (Path(__file__).resolve().parents[1] / "shared"
                    / "stock_strategy_shared" / "wealth_core")

#: `psycopg[binary]==3.3.4` -> ("psycopg", "3.3.4"). The extra is part of what
#: is installed, not part of the distribution name that reports its version.
_PIN = re.compile(r"^\s*([A-Za-z0-9_.\-]+)\s*(?:\[[^\]]*\])?\s*==\s*([^\s#]+)")


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def pinned_requirements(path: Path = _REQUIREMENTS) -> dict[str, str]:
    """The exact pins, as declared. Comments and blank lines ignored."""
    out: dict[str, str] = {}
    if not path.exists():                       # pragma: no cover - packaging
        return out
    for line in path.read_text().splitlines():
        m = _PIN.match(line)
        if m:
            out[m.group(1).lower().replace("_", "-")] = m.group(2)
    return out


def installed_versions(names: Iterable[str]) -> dict[str, Optional[str]]:
    """What is actually importable, by distribution name. None when absent."""
    import importlib.metadata as md                       # noqa: PLC0415

    out: dict[str, Optional[str]] = {}
    for n in names:
        try:
            out[n] = md.version(n)
        except Exception:                                  # noqa: BLE001
            out[n] = None
    return out


def pin_drift() -> dict[str, dict]:
    """Where the environment disagrees with the pin file.

    The whole point of pinning is defeated by a pin nobody checks: an image
    built before a pin changed, or a developer's venv resolving something else,
    both produce results that look certified. Named per package rather than
    reduced to a boolean, because "which one moved" is the entire question.
    """
    pinned = pinned_requirements()
    have = installed_versions(pinned)
    return {k: {"pinned": v, "installed": have.get(k)}
            for k, v in pinned.items() if have.get(k) != v}


def source_hash(root: Path) -> dict:
    """A deterministic digest of a Python package tree.

    Sorted relative POSIX paths, each hashed with its content, so the digest
    does not depend on filesystem order, absolute location, or the caches and
    bytecode that a test run leaves behind.
    """
    if not root.exists():                        # pragma: no cover - packaging
        return {"root": root.name, "files": 0, "hash": None}
    files = sorted(p for p in root.rglob("*.py")
                   if "__pycache__" not in p.parts)
    h = hashlib.sha256()
    for p in files:
        h.update(p.relative_to(root).as_posix().encode())
        h.update(b"\0")
        h.update(_sha(p.read_bytes()).encode())
        h.update(b"\n")
    return {"root": root.name, "files": len(files), "hash": h.hexdigest()}


def environment() -> dict:
    """Everything true before a corpus exists."""
    from sentinel.feed import calendar as cal                # noqa: PLC0415

    py = platform.python_version()
    drift = pin_drift()
    try:
        calendar_version = cal.calendar_version()
    except Exception as exc:                                  # noqa: BLE001
        calendar_version = f"unavailable: {exc}"
    return {
        "python": py,
        "python_certified": py == CERTIFIED_PYTHON,
        "python_implementation": platform.python_implementation(),
        "base_image_digest_pinned": CERTIFIED_BASE_DIGEST,
        "calendar_exchange": cal.EXCHANGE,
        "calendar_version": calendar_version,
        "packages": installed_versions(pinned_requirements()),
        "pin_drift": drift,
        "pins_match": not drift,
        "sentinel_source": source_hash(_SENTINEL_PKG),
        "wealth_core_source": source_hash(_WEALTH_CORE_PKG),
        # TRUE only when the interpreter and every pin are the certified ones.
        # The base digest cannot be verified from inside the container — it is
        # what the image was built FROM, and nothing in a running process can
        # attest to that — so this is a necessary condition, never a sufficient
        # one. The build is what makes it sufficient.
        "certified": (py == CERTIFIED_PYTHON) and not drift,
    }


def _digest_query(conn, sql: str, params: tuple) -> dict:
    """Row count and an ORDER-DEPENDENT digest of a result set.

    The count alone is the trap: a vendor restating a price in place leaves it
    completely unchanged. Only reading the values detects that, which is why
    this scans rather than samples.
    """
    h = hashlib.sha256()
    n = 0
    with conn.cursor() as cur:
        cur.execute(sql, params)
        for row in cur:
            n += 1
            h.update(repr(tuple(row)).encode())
            h.update(b"\n")
    return {"rows": n, "hash": h.hexdigest() if n else None}


def corpus(conn, *, start: str, end: str) -> dict:
    """Identity of the data over [start, end] — the interval being certified.

    THREE digests, not one. The vendor tables and the normalised corpus are
    hashed separately because they fail differently: the same ACTIONS producing
    a different `sentinel_bars` means the NORMALISER changed (which is exactly
    what review #4 did), while different ACTIONS means the vendor did. One
    combined hash would say only that something moved.
    """
    bars = _digest_query(
        conn,
        "SELECT session, security_id, ticker, close_signal, close_unadjusted,"
        " open_unadjusted, volume, split_ratio, dividend_per_share"
        " FROM sentinel_bars WHERE session BETWEEN %s AND %s"
        " ORDER BY session, security_id", (start, end))
    actions = _digest_query(
        conn,
        "SELECT session, ticker, action, value, contraticker"
        " FROM sentinel_actions WHERE session BETWEEN %s AND %s"
        " ORDER BY session, ticker, action", (start, end))
    universe = _digest_query(
        conn,
        "SELECT permaticker, ticker, category, related_tickers,"
        " first_price_date, last_price_date, is_delisted, snapshot_date"
        " FROM sentinel_universe"
        " ORDER BY permaticker, ticker, snapshot_date", ())
    with conn.cursor() as cur:
        cur.execute("SELECT MIN(session), MAX(session),"
                    " COUNT(DISTINCT session), COUNT(DISTINCT security_id)"
                    " FROM sentinel_bars WHERE session BETWEEN %s AND %s",
                    (start, end))
        lo, hi, sessions, securities = cur.fetchone()
    out = {
        "window": {"start": start, "end": end},
        "first_session": str(lo) if lo else None,
        "last_session": str(hi) if hi else None,
        "sessions": sessions,
        "securities": securities,
        "normalised_bars": bars,
        "vendor_actions": actions,
        "vendor_universe": universe,
    }
    out["corpus_hash"] = _sha(json.dumps(
        {k: out[k] for k in ("normalised_bars", "vendor_actions",
                             "vendor_universe")},
        sort_keys=True).encode())
    return out


def rehearsal_identity(conn=None, *, start: Optional[str] = None,
                       end: Optional[str] = None) -> dict:
    """The whole record. `conn` omitted describes the environment alone."""
    env = environment()
    rec = {"environment": env,
           "identity_hash": _sha(json.dumps(env, sort_keys=True).encode())}
    if conn is not None and start and end:
        rec["corpus"] = corpus(conn, start=start, end=end)
    return rec


__all__ = ["CERTIFIED_BASE_DIGEST", "CERTIFIED_PYTHON", "corpus",
           "environment", "installed_versions", "pin_drift",
           "pinned_requirements", "rehearsal_identity", "source_hash"]
