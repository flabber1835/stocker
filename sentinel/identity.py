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
import os
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

#: The database image the corpus lives in, pinned the same way. Leaving the
#: server as a mutable tag while pinning tzdata to the day is inconsistent: a
#: Postgres minor upgrade can change collation, planner behaviour and float
#: text output, and the corpus digests are computed by reading rows back out
#: of it.
CERTIFIED_POSTGRES_DIGEST = (
    "sha256:95206741a5b214807675e14165369d05b93a9cf692223b616d07cca227e74b0b")
CERTIFIED_POSTGRES_VERSION = "16.14"

_REQUIREMENTS = Path(__file__).resolve().parent / "requirements.txt"

#: The COMPLETE resolved closure, produced from a real build by
#: `scripts/sentinel-lock.sh` and committed. Absent until the first Python
#: 3.12.13 build exists — see the file's own header for the bootstrap.
_LOCK = Path(__file__).resolve().parent / "requirements.lock"


#: Where `Dockerfile.sentinel` leaves the requirement files it installed from.
#: Baked into the IMAGE, so it describes the build rather than the host.
_IMAGE_REQ_DIR = Path("/tmp/req")


def _image_lock_sha256() -> Optional[str]:
    """SHA-256 of the lock file INSIDE the image, or None if it has none.

    This is the difference between "a lock exists somewhere" and "this image
    was built from a lock". `--verify-only` does not rebuild, so without it an
    unlocked image passes the moment a lock appears in the checkout — which
    proves the operator ran the generator, not that anything consumed it.
    """
    p = _IMAGE_REQ_DIR / "requirements.lock"
    try:
        return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None
    except Exception:                                        # noqa: BLE001
        return None


def _imported_package_root(module_name: str) -> Optional[Path]:
    """Where Python ACTUALLY imported a package from.

    NOT a path assembled from `__file__` and a guess about the repository
    layout. The previous version computed Wealth Core as
    `sentinel/../shared/stock_strategy_shared/wealth_core`, which is true in a
    checkout and FALSE in the runtime image: there `sentinel/` is at `/app` and
    `shared/` was pip-installed into site-packages, so nothing exists at that
    path. `source_hash` then reported `files: 0, hash: None` — and `certified`
    did not look at it, so an image with NO Wealth Core identity at all
    returned PASS.

    Importing to find out is the only thing that cannot be wrong about this:
    the answer is the code that would run.
    """
    import importlib                                       # noqa: PLC0415

    try:
        mod = importlib.import_module(module_name)
    except Exception:                                       # noqa: BLE001
        return None
    f = getattr(mod, "__file__", None)
    if f:
        return Path(f).resolve().parent
    paths = list(getattr(mod, "__path__", []) or [])        # namespace package
    return Path(paths[0]).resolve() if paths else None

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


def installed_distributions() -> list[list[str]]:
    """EVERY installed distribution and its version, sorted. Not just the pins.

    `requirements.txt` pins the DIRECT dependencies. pip is still free to
    resolve everything underneath them, so two images could carry the same
    `pinned_requirements` — the same declared versions, the same source, the
    same interpreter — and different transitive closures, and nothing in the
    record would separate them. `pin_drift()` cannot see that by construction:
    it only compares what the pin file names.

    So the record fingerprints the CLOSURE. This does not make a build
    reproducible on its own — `sentinel/requirements.lock` is what does that —
    but it makes two differing closures produce different `identity_hash`
    values, which is the property a certification actually needs: results from
    two different environments can never be mistaken for results from one.
    """
    import importlib.metadata as md                          # noqa: PLC0415

    seen: dict[str, str] = {}
    for dist in md.distributions():
        try:
            name = (dist.metadata["Name"] or "").lower().replace("_", "-")
            version = dist.version or ""
        except Exception:                                    # noqa: BLE001
            continue
        if name:
            # A duplicate name means two installs of one distribution are
            # visible. Recording BOTH versions is the honest answer; silently
            # keeping one would hide a broken environment.
            seen[name] = version if name not in seen \
                else f"{seen[name]}|{version}"
    return [[k, seen[k]] for k in sorted(seen)]


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


def source_hash(root: Optional[Path]) -> dict:
    """A deterministic digest of a Python package tree.

    Sorted relative POSIX paths, each hashed with its content, so the digest
    does not depend on filesystem order, absolute location, or the caches and
    bytecode that a test run leaves behind.
    """
    if root is None or not root.exists():
        return {"root": None if root is None else root.name,
                "path": None if root is None else str(root),
                "files": 0, "hash": None}
    files = sorted(p for p in root.rglob("*.py")
                   if "__pycache__" not in p.parts)
    h = hashlib.sha256()
    for p in files:
        h.update(p.relative_to(root).as_posix().encode())
        h.update(b"\0")
        h.update(_sha(p.read_bytes()).encode())
        h.update(b"\n")
    return {"root": root.name, "path": str(root), "files": len(files),
            "hash": h.hexdigest()}


def environment() -> dict:
    """Everything true before a corpus exists."""
    from sentinel.feed import calendar as cal                # noqa: PLC0415

    py = platform.python_version()
    drift = pin_drift()
    try:
        calendar_version = cal.calendar_version()
    except Exception as exc:                                  # noqa: BLE001
        calendar_version = f"unavailable: {exc}"

    dists = installed_distributions()
    sentinel_src = source_hash(_imported_package_root("sentinel"))
    wc_src = source_hash(_imported_package_root(
        "stock_strategy_shared.wealth_core"))
    # A MISSING source hash is a failure, not a blank field. The whole point of
    # the record is to name the code that produced a result; "we could not find
    # Wealth Core" and "here is Wealth Core's hash" must not both read as
    # certified. This is the condition that was absent, and it is exactly the
    # condition the old repo-relative path violated inside the image.
    sources_known = bool(sentinel_src["hash"] and sentinel_src["files"]
                         and wc_src["hash"] and wc_src["files"])
    return {
        "python": py,
        "python_certified": py == CERTIFIED_PYTHON,
        "python_implementation": platform.python_implementation(),
        "base_image_digest_pinned": CERTIFIED_BASE_DIGEST,
        "postgres_image_digest_pinned": CERTIFIED_POSTGRES_DIGEST,
        "calendar_exchange": cal.EXCHANGE,
        "calendar_version": calendar_version,
        "packages": installed_versions(pinned_requirements()),
        "pin_drift": drift,
        "pins_match": not drift,
        # THE WHOLE CLOSURE, not only the direct pins. Two images with
        # identical declared versions and different transitive resolutions must
        # not be able to share an identity_hash — which they could, because
        # `pin_drift` compares only what the pin file names.
        "distributions_count": len(dists),
        "distributions_hash": _sha(json.dumps(dists, sort_keys=True).encode()),
        "distributions": dists,
        # THE LOCK THE IMAGE WAS BUILT FROM, not the one lying in a checkout.
        #
        # `--verify-only` does not rebuild, so an OLD UNLOCKED image could pass
        # a "is there a lock?" check simply because a lock file appeared on the
        # host afterwards — proving the operator ran the generator, not that
        # anything was built from its output. The Dockerfile copies the lock to
        # /tmp/req; hashing THAT is the only claim about the image itself, and
        # the harness requires it to equal the checkout's.
        "lock_present": _LOCK.exists(),
        "image_lock_sha256": _image_lock_sha256(),
        "sentinel_source": sentinel_src,
        "wealth_core_source": wc_src,
        "sources_known": sources_known,
        # TRUE only when the interpreter is the certified one, every pin is
        # satisfied, and BOTH source trees were actually located. The base
        # digest cannot be verified from inside the container — it is what the
        # image was built FROM, and nothing in a running process can attest to
        # that — so this is a necessary condition, never a sufficient one. The
        # build is what makes it sufficient.
        "certified": (py == CERTIFIED_PYTHON) and not drift and sources_known,
    }


def _digest_query(conn, sql: str, params: tuple) -> dict:
    """Row count and an ORDER-DEPENDENT digest of a result set.

    The count alone is the trap: a vendor restating a price in place leaves it
    completely unchanged. Only reading the values detects that, which is why
    this scans rather than samples.
    """
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return _digest_rows(cur)


def _digest_rows(rows) -> dict:
    """Digest already-ordered rows, including derived calendar fields."""
    h = hashlib.sha256()
    n = 0
    for row in rows:
        n += 1
        h.update(repr(tuple(row)).encode())
        h.update(b"\n")
    return {"rows": n, "hash": h.hexdigest() if n else None}


def _corpus_pinned(conn, *, start: str, end: str, publication_record) -> dict:
    """Identity of the data over [start, end] — the interval being certified.

    THREE digests, not one. The vendor tables and the normalised corpus are
    hashed separately because they fail differently: the same ACTIONS producing
    a different `sentinel_bars` means the NORMALISER changed (which is exactly
    what review #4 did), while different ACTIONS means the vendor did. One
    combined hash would say only that something moved.
    """
    from sentinel.feed import calendar
    from sentinel.feed.publication import effective_split_ratio, visible_predicate

    bars = _digest_query(
        conn,
        "SELECT session, security_id, ticker, close_signal, close_unadjusted,"
        " open_unadjusted, volume,"
        f" {effective_split_ratio('b')}, dividend_per_share"
        " FROM sentinel_bars b WHERE session BETWEEN %s AND %s"
        f" AND {visible_predicate('b')}"
        " ORDER BY session, security_id", (start, end))
    raw_start, raw_end = calendar.action_date_window(start, end)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT session, ticker, action, value, contraticker"
            " FROM sentinel_actions a WHERE session BETWEEN %s AND %s"
            f" AND {visible_predicate('a')}"
            " ORDER BY session, ticker, action", (raw_start, raw_end))
        action_rows = []
        for raw_session, ticker, action, value, contraticker in cur:
            effective = calendar.session_on_or_after(str(raw_session))
            if start <= effective <= end:
                # Preserve both dates.  The raw value proves what the vendor
                # supplied; the effective value proves where Sentinel applied
                # it under the pinned XNYS calendar contract.
                action_rows.append((str(raw_session), effective, ticker,
                                    action, value, contraticker))
    actions = _digest_rows(action_rows)
    universe = _digest_query(
        conn,
        "SELECT permaticker, ticker, category, related_tickers,"
        " first_price_date, last_price_date, is_delisted, snapshot_date"
        " FROM sentinel_universe u"
        f" WHERE {visible_predicate('u')}"
        " ORDER BY permaticker, ticker, snapshot_date", ())
    from sentinel.feed.store import published_spy_total_return

    spy = _digest_rows(published_spy_total_return(conn, start, end))
    repairs = _digest_query(
        conn,
        "SELECT rr.security_id, rr.session, rr.prior_split_ratio,"
        " rr.split_ratio, rp.version"
        " FROM sentinel_bar_split_repairs rr"
        " JOIN sentinel_corpus_publications rp"
        "   ON rp.run_id = rr.last_written_run_id"
        " WHERE rr.session BETWEEN %s AND %s"
        " ORDER BY rr.session, rr.security_id, rp.version", (start, end))
    # THE REFUSALS ARE PART OF THE CORPUS'S IDENTITY. Without them two seeds
    # with identical accepted bars and completely different dropped evidence
    # digest the same, and the claim "this interval is complete" rests on
    # exactly the rows that were left out of the hash proving it.
    rejections = _digest_query(
        conn,
        "SELECT session, ticker, reason, close_unadjusted, volume"
        " FROM sentinel_ingest_rejections WHERE session BETWEEN %s AND %s"
        " ORDER BY session, ticker, reason", (start, end))
    # Hash the evidence disposition NAMED BY THIS PUBLICATION, not every
    # historical or unpublished observation. Otherwise a failed corrective
    # ingest changes the hash of a corpus whose active evidence did not move,
    # and stale + current split dispositions are combined in one identity.
    from sentinel.feed.anomalies import active_rows as active_anomalies

    anomaly_rows = active_anomalies(conn, start=start, end=end)
    anomalies = _digest_rows(
        (row["session"], row["ticker"], row["kind"], row["detail"])
        for row in anomaly_rows)
    # TRUNCATION IS PART OF THE EVIDENCE STATE. A corpus whose refusal evidence
    # was capped is not the same corpus as one whose was complete, even when
    # every stored row is identical — the second can be certified and the first
    # cannot. Leaving it out of the hash would let those two digest the same.
    # Overlap, not containment, to match how the audit reads it.
    truncation = _digest_query(
        conn,
        "SELECT window_start, window_end, chunk, retained, truncated"
        " FROM sentinel_rejection_truncation"
        " WHERE window_start <= %s AND window_end >= %s"
        " ORDER BY window_start, chunk", (end, start))
    with conn.cursor() as cur:
        cur.execute("SELECT MIN(session), MAX(session),"
                    " COUNT(DISTINCT session), COUNT(DISTINCT security_id)"
                    " FROM sentinel_bars b WHERE session BETWEEN %s AND %s"
                    f" AND {visible_predicate('b')}",
                    (start, end))
        lo, hi, sessions, securities = cur.fetchone()
        cur.execute("SHOW server_version")
        server_version = str(cur.fetchone()[0])
    out = {
        "window": {"start": start, "end": end},
        "data_version": publication_record.version,
        "publication": publication_record.to_dict(),
        "postgres_server_version": server_version,
        "postgres_certified": server_version.split()[0].startswith(
            CERTIFIED_POSTGRES_VERSION),
        "first_session": str(lo) if lo else None,
        "last_session": str(hi) if hi else None,
        "sessions": sessions,
        "securities": securities,
        "normalised_bars": bars,
        "vendor_actions": actions,
        "vendor_universe": universe,
        "spy_total_return": spy,
        "applied_repairs": repairs,
        "refusals": rejections,
        "anomalies": anomalies,
        "refusal_truncation": truncation,
    }
    out["corpus_hash"] = _sha(json.dumps(
        {k: out[k] for k in ("data_version", "normalised_bars",
                             "vendor_actions", "vendor_universe",
                             "spy_total_return", "applied_repairs", "refusals",
                             "anomalies", "refusal_truncation")},
        sort_keys=True).encode())
    return out


def corpus(conn, *, start: str, end: str) -> dict:
    """Hash one coherent published snapshot, named by its held data version."""
    from sentinel.feed import publication
    from sentinel.feed.sharadar import validate_date_range

    start, end = validate_date_range(start, end)
    with publication.pinned(conn) as pinned:
        publication.assert_coherent(conn)
        return _corpus_pinned(
            conn, start=start, end=end, publication_record=pinned)


def rehearsal_identity(conn=None, *, start: Optional[str] = None,
                       end: Optional[str] = None) -> dict:
    """The whole record. `conn` omitted describes the environment alone."""
    env = environment()
    rec = {"environment": env,
           "identity_hash": _sha(json.dumps(env, sort_keys=True).encode()),
           # These are deployment facts, not computational-environment inputs.
           # Keeping them outside ``identity_hash`` lets the certification image
           # record its environment before a registry digest exists, while the
           # installed runtime must still independently present the exact
           # commit and image digests signed later by the offline decision.
           "deployment_artifacts": {
               "schema": "sentinel.runtime-artifacts/1",
               "git_commit": os.environ.get("SENTINEL_GIT_COMMIT", "").strip(),
               "runtime_image_digest": os.environ.get(
                   "SENTINEL_RUNTIME_IMAGE_DIGEST", "").strip(),
               "test_image_digest": os.environ.get(
                   "SENTINEL_TEST_IMAGE_DIGEST", "").strip(),
           }}
    if conn is not None and start and end:
        rec["corpus"] = corpus(conn, start=start, end=end)
    return rec


__all__ = ["CERTIFIED_BASE_DIGEST", "CERTIFIED_POSTGRES_DIGEST",
           "CERTIFIED_POSTGRES_VERSION", "CERTIFIED_PYTHON", "corpus",
           "environment", "installed_versions", "pin_drift",
           "pinned_requirements", "rehearsal_identity", "source_hash"]
