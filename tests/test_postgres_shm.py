"""PostgreSQL server services must raise /dev/shm above Docker's default.

THE FAILURE THIS PREVENTS. Docker gives a container 64MB of /dev/shm, and
PostgreSQL allocates the per-worker segments a PARALLEL query needs there. On a
35M-row table any parallel plan wants more, and the error is

    could not resize shared memory segment "/PostgreSQL.3229497642"
    to 67128672 bytes: No space left on device

which reads like a full disk and is not one — 67128672 bytes is 64MiB, the
default, and the number is the tell. It cost a long detour through query plans
and index checks before anything pointed at shared memory.

A latent default is worth a test precisely because it works fine on small
tables: nothing surfaces it until the corpus is large, by which time the symptom
looks like something else entirely.
"""
from __future__ import annotations

import pathlib

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]

# Docker's default, in bytes. A container at or below this is unconfigured.
DOCKER_DEFAULT_SHM = 64 * 1024 * 1024
POSTGRES_DATA_DIR = "/var/lib/postgresql/data"


def parse_size(v) -> int:
    s = str(v).strip().lower()
    for suffix, mult in (("gb", 1024 ** 3), ("g", 1024 ** 3),
                         ("mb", 1024 ** 2), ("m", 1024 ** 2),
                         ("kb", 1024), ("k", 1024), ("b", 1)):
        if s.endswith(suffix):
            return int(float(s[: -len(suffix)]) * mult)
    return int(float(s))


def _runs_postgres_server(svc) -> bool:
    """Identify an actual PostgreSQL server, not any use of its image.

    Compose may legitimately reuse the pinned postgres image as a narrow shell
    utility. Such a helper never starts PostgreSQL and therefore has no server
    shared-memory requirement. Server-mode services are identified by the
    server health probe or the canonical PostgreSQL data mount.
    """
    if not str(svc.get("image", "")).startswith("postgres"):
        return False

    healthcheck = svc.get("healthcheck") or {}
    health_test = healthcheck.get("test") or []
    if isinstance(health_test, str):
        health_text = health_test
    else:
        health_text = " ".join(str(part) for part in health_test)
    if "pg_isready" in health_text:
        return True

    for volume in svc.get("volumes") or []:
        if isinstance(volume, str):
            if POSTGRES_DATA_DIR in volume:
                return True
        elif isinstance(volume, dict) and volume.get("target") == POSTGRES_DATA_DIR:
            return True
    return False


def postgres_server_services():
    """EVERY PostgreSQL server service in EVERY compose file, discovered.

    This used to name `docker-compose.yml` and `docker-compose.backtest.yml`
    literally. Both were deleted with the Stocker runtime, so the guard stopped
    collecting — and `sentinel-postgres`, which now holds the corpus those two
    files' databases used to, was created with no `shm_size` at all. The
    invariant did not lapse because anyone decided it should; it lapsed because
    it was pinned to filenames rather than to the property.

    Discovery is intentionally about server behaviour, not image provenance:
    a networkless permissions helper may use the same pinned postgres image
    without ever starting a database server.
    """
    out = []
    for f in sorted(ROOT.glob("docker-compose*.yml")):
        doc = yaml.safe_load(f.read_text()) or {}
        for name, svc in (doc.get("services") or {}).items():
            if _runs_postgres_server(svc):
                out.append((f.name, name, svc))
    return out


def test_there_are_postgres_servers_to_check():
    """Guard against an accidentally empty discovery set."""
    assert postgres_server_services()


@pytest.mark.parametrize("f,name,svc", postgres_server_services())
def test_shm_size_is_raised_above_the_docker_default(f, name, svc):
    assert "shm_size" in svc, (
        f"{f}:{name} has no shm_size, so it gets Docker's 64MB default. A "
        f"parallel query then fails with 'No space left on device', which "
        f"reads like a full disk and is not one.")
    assert parse_size(svc["shm_size"]) > DOCKER_DEFAULT_SHM, (
        f"{f}:{name} sets shm_size at or below the 64MB default, which is the "
        f"value that caused the failure")


def test_non_server_postgres_image_helpers_are_not_treated_as_databases():
    """A shell helper sharing the image must not inherit database-only policy."""
    helpers = []
    for f in sorted(ROOT.glob("docker-compose*.yml")):
        doc = yaml.safe_load(f.read_text()) or {}
        for name, svc in (doc.get("services") or {}).items():
            if (str(svc.get("image", "")).startswith("postgres")
                    and not _runs_postgres_server(svc)):
                helpers.append((f.name, name, svc))
    assert helpers, "fixture no longer exercises a non-server postgres-image helper"
    assert all("shm_size" not in svc for _, _, svc in helpers)


def test_the_corpus_database_gets_at_least_the_allowance_that_was_needed():
    """1gb, the value bt-postgres was raised to when the failure was diagnosed.

    `sentinel-postgres` inherited that role — it holds the Sharadar corpus every
    window load scans — so it inherits the number. Asserted absolutely rather
    than relatively: the old form compared bt-postgres against the live stack,
    and with one database left there is nothing to compare against, so the
    relative form would pass on any value at all.
    """
    sizes = {name: parse_size(svc["shm_size"])
             for _, name, svc in postgres_server_services()}
    assert sizes.get("sentinel-postgres", 0) >= 1024 ** 3, (
        "sentinel-postgres holds the corpus; 1gb is the measured requirement, "
        "not a guess")
