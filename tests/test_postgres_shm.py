"""Both Postgres services must raise /dev/shm above Docker's default.

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


def parse_size(v) -> int:
    s = str(v).strip().lower()
    for suffix, mult in (("gb", 1024 ** 3), ("g", 1024 ** 3),
                         ("mb", 1024 ** 2), ("m", 1024 ** 2),
                         ("kb", 1024), ("k", 1024), ("b", 1)):
        if s.endswith(suffix):
            return int(float(s[: -len(suffix)]) * mult)
    return int(float(s))


def postgres_services():
    out = []
    for f in ("docker-compose.yml", "docker-compose.backtest.yml"):
        doc = yaml.safe_load((ROOT / f).read_text())
        for name, svc in (doc.get("services") or {}).items():
            if str(svc.get("image", "")).startswith("postgres"):
                out.append((f, name, svc))
    return out


def test_there_are_postgres_services_to_check():
    """Guards the parametrisation below: if the image name changes, every test
    would silently pass on an empty list."""
    assert postgres_services()


@pytest.mark.parametrize("f,name,svc", postgres_services())
def test_shm_size_is_raised_above_the_docker_default(f, name, svc):
    assert "shm_size" in svc, (
        f"{f}:{name} has no shm_size, so it gets Docker's 64MB default. A "
        f"parallel query then fails with 'No space left on device', which "
        f"reads like a full disk and is not one.")
    assert parse_size(svc["shm_size"]) > DOCKER_DEFAULT_SHM, (
        f"{f}:{name} sets shm_size at or below the 64MB default, which is the "
        f"value that caused the failure")


def test_the_backtest_corpus_gets_the_larger_allowance():
    """bt-postgres holds the 35M-row price corpus every backtest scans; the
    live tables are far smaller."""
    sizes = {name: parse_size(svc["shm_size"])
             for _, name, svc in postgres_services()}
    assert sizes["bt-postgres"] >= sizes["postgres"]
