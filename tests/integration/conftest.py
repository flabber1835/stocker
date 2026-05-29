"""
Integration test tier — runs real SQL against a real, fully-migrated Postgres.

Why this exists
---------------
The per-service unit tests mock the database (e.g. `patch.object(mod, "engine", ...)`),
so they execute *Python logic* but never the actual SQL. That let two production
bugs ship green:

  - vetter held-tickers query selected `id` instead of `run_id`
    → asyncpg: "operator does not exist: uuid = integer"
  - penalty-box query bound `date.today().isoformat()` (str) to a DATE column
    → asyncpg: "'str' object has no attribute 'toordinal'"

Both only fail when the query hits a real Postgres with the real schema. This
tier closes that gap: a session-scoped ephemeral Postgres is created, the actual
alembic migrations are applied to `head`, and tests run the real queries through
an async SQLAlchemy + asyncpg engine — exactly the production stack.

Setup strategy (in priority order)
-----------------------------------
1. If `STOCKER_TEST_DSN` is set, use that existing database (CI may provide one).
2. Otherwise spin up a throwaway local Postgres cluster via initdb/pg_ctl.

If neither a DSN nor the Postgres binaries are available, every test in this
tier is skipped with a clear reason (so `pytest` stays green on bare runners).
"""
from __future__ import annotations

import glob
import os
import shutil
import socket
import subprocess
import tempfile
import time

import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


# ── binary / port helpers ─────────────────────────────────────────────────────

def _find_pg_bin(name: str) -> str | None:
    candidates = [shutil.which(name)]
    candidates += sorted(glob.glob(f"/usr/lib/postgresql/*/bin/{name}"), reverse=True)
    candidates += sorted(glob.glob(f"/usr/pgsql-*/bin/{name}"), reverse=True)
    for c in candidates:
        if c and os.path.exists(c):
            return c
    return None


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=120, **kw)


def _as_pg_user(cmd: list[str]) -> list[str]:
    """Postgres refuses to run as root. When we are root, wrap the command so it
    runs as the `postgres` system user; otherwise run it directly."""
    if os.geteuid() == 0:
        runuser = shutil.which("runuser") or "/usr/sbin/runuser"
        return [runuser, "-u", "postgres", "--", *cmd]
    return cmd


# ── ephemeral cluster lifecycle ───────────────────────────────────────────────

def _pick_cluster_base() -> str | None:
    """When running as root, the cluster dir must live somewhere the `postgres`
    system user can traverse — the default TMPDIR is often root-only (mode 700).
    Prefer the postgres home; otherwise create a world-traversable base in /tmp.
    """
    if os.geteuid() != 0:
        return None  # mkdtemp default is fine for non-root
    import pwd
    try:
        home = pwd.getpwnam("postgres").pw_dir
        if home and os.path.isdir(home) and os.access(home, os.W_OK):
            return home
    except KeyError:
        pass
    base = "/tmp/stocker_pg_clusters"
    os.makedirs(base, exist_ok=True)
    os.chmod(base, 0o711)  # traversable by other users (postgres) but not listable
    return base


class _EphemeralPostgres:
    def __init__(self) -> None:
        self.datadir = tempfile.mkdtemp(prefix="stocker_pg_", dir=_pick_cluster_base())
        self.port = _free_port()
        self.user = "postgres" if os.geteuid() == 0 else (os.environ.get("USER") or "postgres")
        self.dbname = "stocker_test"
        self._started = False

    @property
    def sync_dsn(self) -> str:
        return f"postgresql://{self.user}@127.0.0.1:{self.port}/{self.dbname}"

    @property
    def async_dsn(self) -> str:
        return f"postgresql+asyncpg://{self.user}@127.0.0.1:{self.port}/{self.dbname}"

    def start(self) -> None:
        initdb = _find_pg_bin("initdb")
        pg_ctl = _find_pg_bin("pg_ctl")
        createdb = _find_pg_bin("createdb")
        if not (initdb and pg_ctl and createdb):
            raise RuntimeError("Postgres binaries (initdb/pg_ctl/createdb) not found")

        # The data dir must be owned by the user the server runs as.
        if os.geteuid() == 0:
            shutil.chown(self.datadir, user="postgres", group="postgres")

        r = _run(_as_pg_user([initdb, "-D", self.datadir, "-U", self.user,
                              "-A", "trust", "--encoding=UTF8"]))
        if r.returncode != 0:
            raise RuntimeError(f"initdb failed: {r.stderr or r.stdout}")

        logfile = os.path.join(self.datadir, "server.log")
        opts = f"-p {self.port} -h 127.0.0.1 -k {self.datadir}"
        r = _run(_as_pg_user([pg_ctl, "-D", self.datadir, "-o", opts,
                              "-l", logfile, "-w", "-t", "30", "start"]))
        if r.returncode != 0:
            tail = ""
            try:
                with open(logfile) as fh:
                    tail = fh.read()[-2000:]
            except OSError:
                pass
            raise RuntimeError(f"pg_ctl start failed: {r.stderr or r.stdout}\n{tail}")
        self._started = True

        # Wait for readiness then create the test database.
        pg_isready = _find_pg_bin("pg_isready")
        deadline = time.monotonic() + 30
        while pg_isready and time.monotonic() < deadline:
            if _run([pg_isready, "-h", "127.0.0.1", "-p", str(self.port)]).returncode == 0:
                break
            time.sleep(0.3)
        r = _run(_as_pg_user([createdb, "-h", "127.0.0.1", "-p", str(self.port),
                              "-U", self.user, self.dbname]))
        if r.returncode != 0:
            raise RuntimeError(f"createdb failed: {r.stderr or r.stdout}")

    def stop(self) -> None:
        if self._started:
            pg_ctl = _find_pg_bin("pg_ctl")
            if pg_ctl:
                _run(_as_pg_user([pg_ctl, "-D", self.datadir, "-m", "immediate", "stop"]))
        shutil.rmtree(self.datadir, ignore_errors=True)


def _alembic_upgrade(sync_dsn: str) -> None:
    """Apply all migrations to head against the test DB, mirroring db-migrator."""
    env = dict(os.environ)
    env["DATABASE_URL"] = sync_dsn
    r = subprocess.run(
        ["alembic", "-c", "alembic.ini", "upgrade", "head"],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=180,
    )
    if r.returncode != 0:
        raise RuntimeError(f"alembic upgrade failed:\n{r.stdout}\n{r.stderr}")


# ── session-scoped fixtures ───────────────────────────────────────────────────

@pytest.fixture(scope="session")
def migrated_dsn() -> str:
    """Return a sync DSN for a fully-migrated Postgres, or skip the tier."""
    external = os.environ.get("STOCKER_TEST_DSN")
    if external:
        sync = external.replace("postgresql+asyncpg://", "postgresql://")
        _alembic_upgrade(sync)
        yield sync
        return

    if not _find_pg_bin("initdb"):
        pytest.skip("no STOCKER_TEST_DSN and no local Postgres binaries available")

    if shutil.which("alembic") is None:
        try:
            import alembic  # noqa: F401
        except ImportError:
            pytest.skip("alembic not installed — cannot apply migrations")

    pg = _EphemeralPostgres()
    try:
        pg.start()
    except Exception as exc:  # noqa: BLE001
        pg.stop()
        pytest.skip(f"could not start ephemeral Postgres: {exc}")
    try:
        _alembic_upgrade(pg.sync_dsn)
        yield pg.sync_dsn
    finally:
        pg.stop()


@pytest.fixture(scope="session")
def async_dsn(migrated_dsn: str) -> str:
    """asyncpg DSN matching the production stack (services use +asyncpg)."""
    return migrated_dsn.replace("postgresql://", "postgresql+asyncpg://")
