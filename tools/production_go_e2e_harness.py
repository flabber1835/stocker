#!/usr/bin/env python3
"""Exercise the canonical production GO lifecycle against deterministic externals.

This is deliberately a process/composition harness.  The success lane invokes
``bash scripts/sentinel-go-validate.sh`` exactly once and lets that entry point
own locking, bootstrap, Docker/Compose/PostgreSQL, local-full certification,
feed recovery, readiness, promotion, panel recreation and handoff.  Only the
Alpaca SIP and OpenFIGI HTTP boundaries are replaced with a deterministic
server; SHADOW is the production-supported broker-free target.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ENTRYPOINT = ("bash", "scripts/sentinel-go-validate.sh")
SUCCESS = "[GO] GO lifecycle completed successfully"
PHASE_RE = re.compile(r"^=== (.+) ===$", re.MULTILINE)
HANDOFF = ROOT / "artifacts" / "sentinel" / "deployment" / "validated-artifact-handoff.json"
POINTER = ROOT / "artifacts" / "sentinel" / "runtime-selection.json"
VALIDATED_RUNTIME_POINTER = (
    ROOT / "artifacts" / "sentinel" / "deployment" / "validated-runtime.env"
)

REQUIRED_PHASES = (
    "HOST COMPATIBILITY",
    "ACQUIRE SINGLE GO LIFECYCLE LOCK",
    "DEPLOYMENT SECRETS BOOTSTRAP",
    "HOST GO IDENTITY PREFLIGHT",
    "RUNTIME SELECTION PREFLIGHT",
    "PAPER ACCOUNT PREFLIGHT - GET ONLY",
    "CERTIFICATION + FINANCIAL READINESS",
    "PROMOTE EXACT CERTIFIED RUNTIME",
    "POST-VALIDATION HANDOFF",
)

_FIXTURE_READY = False
SEEDED_PUBLICATION: dict | None = None
_SOURCE_SETTINGS: dict[str, str] = {}
SOURCE_REQUESTS: list[dict[str, str]] = []


class HarnessFailure(RuntimeError):
    pass


def _git_head() -> str:
    out = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if out.returncode != 0 or re.fullmatch(r"[0-9a-f]{40}", out.stdout.strip()) is None:
        raise HarnessFailure("exact git HEAD is unavailable")
    return out.stdout.strip()


def _latest_closed_session() -> dt.date:
    from sentinel.feed import calendar
    return dt.date.fromisoformat(calendar.latest_closed_session())


@contextlib.contextmanager
def _source_server(*, profile=None, end=None, bind=None):
    from tools.acquisition_resources import fixtures
    SOURCE_REQUESTS.clear()
    profile = profile or fixtures.Profile(name="go", securities=600, tickers=625, actions=4)
    handler = fixtures.handler(profile, end=end or _latest_closed_session().isoformat(), requests=SOURCE_REQUESTS)
    server = ThreadingHTTPServer((bind or _docker_host_gateway(), 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _docker_host_gateway() -> str:
    completed = subprocess.run(
        ["docker", "network", "inspect", "bridge", "--format",
         "{{(index .IPAM.Config 0).Gateway}}"],
        cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        check=False,
    )
    value = completed.stdout.strip()
    if completed.returncode != 0 or not value:
        raise HarnessFailure("Docker host gateway is unavailable")
    return value


def _write_env(path: Path, *, port: int, backup_dir: Path) -> None:
    gateway = _docker_host_gateway()
    _SOURCE_SETTINGS.clear()
    _SOURCE_SETTINGS['address'] = f"http://{gateway}:{port}"
    lines = [
        "SENTINEL_POSTGRES_PASSWORD=e2e-postgres-password-363",
        "SENTINEL_PUBLICATION_RECEIPT_KEY=e2e-publication-receipt-key-363-0123456789abcdef",
        "ALPACA_API_KEY=fixture-data-id",
        "ALPACA_SECRET_KEY=fixture-data-secret",
        "OPENFIGI_API_KEY=fixture-mapping",
        "ALPACA_BASE_URL=https://paper-api.alpaca.markets",
        f"SENTINEL_BACKUP_DIR={backup_dir}",
        "SENTINEL_BACKUP_DURABLE_TARGET_ATTESTED=1",
        "SENTINEL_SHADOW_OBSERVATION_ENABLED=0",
        "SENTINEL_SHADOW_STARTING_CASH=50000",
        "SENTINEL_MAX_CYCLES=1",
        "SENTINEL_POLL_SECONDS=1",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


@contextlib.contextmanager
def _temporary_environment_file(*, port: int, backup_dir: Path):
    path = ROOT / ".env"
    old = path.read_bytes() if path.exists() else None
    _write_env(path, port=port, backup_dir=backup_dir)
    try:
        yield
    finally:
        if old is None:
            path.unlink(missing_ok=True)
        else:
            path.write_bytes(old)


def _run_host(argv: list[str], *, env: dict[str, str] | None = None,
              timeout: int = 900) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        argv, cwd=ROOT, env=env, text=True, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, timeout=timeout, check=False,
    )
    if completed.returncode != 0:
        raise HarnessFailure(
            f"fixture command failed rc={completed.returncode} argv={argv}:\n"
            f"{(completed.stdout or '')[-5000:]}"
        )
    return completed


def _initialize_backup_target(backup: Path) -> None:
    for name in ("wal", "base"):
        child = backup / name
        child.mkdir(parents=True, exist_ok=True)
        child.chmod(0o777)
    completed = _run_host(
        ["bash", "scripts/sentinel-compose.sh", "--initialize-backup"],
        timeout=180,
    )
    if "initialized_backup_target:" not in (completed.stdout or ""):
        raise HarnessFailure("canonical backup target initialization produced no evidence")


def _compose_service_container_id(service: str, *, env: dict[str, str]) -> str:
    completed = _run_host(
        ["bash", "scripts/sentinel-compose.sh", "--run", "ps", "-q", service],
        env=env, timeout=60,
    )
    values = [line.strip() for line in (completed.stdout or "").splitlines() if line.strip()]
    if len(values) != 1 or re.fullmatch(r"[0-9a-f]{12,64}", values[0]) is None:
        raise HarnessFailure(f"Compose service {service} has no unique container identity")
    return values[0]


def fixture_docker_arguments(argv, address):
    """Supply the HTTP fixture only to the canonical preparation process."""
    result = list(argv)
    if ('compose' not in result or 'run' not in result or '-c' not in result
            or 'SENTINEL_GO_PREPARATION=' not in result[-1]):
        return result
    if result[-3:-1] != ['sentinel', '-c'] or '--entrypoint' not in result:
        raise HarnessFailure('unexpected preparation child command')
    adapter = (ROOT / 'tools/acquisition_resources/fixture_transport.py').read_text(encoding='utf-8')
    result[-1] = adapter + '\ninstall_fixture(' + repr(address) + ')\n' + result[-1]
    return result


@contextlib.contextmanager
def _fixture_cli(env):
    """Every other Docker invocation, including image certification, is unchanged."""
    real = shutil.which('docker', path=env.get('PATH'))
    if not real or not _SOURCE_SETTINGS.get('address'):
        raise HarnessFailure('isolated data fixture is unavailable')
    with tempfile.TemporaryDirectory(prefix='sentinel-go-fixture-bin-') as directory:
        wrapper = Path(directory) / 'docker'
        wrapper.write_text(f"#!{sys.executable}\nimport os, sys\n"
            f"sys.path.insert(0, {str(ROOT)!r})\n"
            "from tools.production_go_e2e_harness import fixture_docker_arguments\n"
            f"args = fixture_docker_arguments(sys.argv[1:], {_SOURCE_SETTINGS['address']!r})\n"
            f"os.execv({real!r}, [{real!r}, *args])\n", encoding='utf-8')
        wrapper.chmod(0o755)
        # The host GO also observes the optional PAPER gate on SHADOW. Confine
        # those HTTPS attempts to the private server, which rejects all tunnels.
        proxy = _SOURCE_SETTINGS['address']
        yield {**env, 'PATH': directory + os.pathsep + env.get('PATH', ''),
               'https_proxy': proxy, 'HTTPS_PROXY': proxy,
               'no_proxy': 'localhost,127.0.0.1', 'NO_PROXY': 'localhost,127.0.0.1'}


def _bootstrap_financial_fixture() -> None:
    """Establish a backed, empty database before the canonical cold GO."""
    global _FIXTURE_READY, SEEDED_PUBLICATION
    if _FIXTURE_READY:
        return

    commit = _git_head()
    runtime_ref = f"sentinel-go-runtime:{commit}"
    env = dict(os.environ)
    env["SENTINEL_RUNTIME_IMAGE_REF"] = runtime_ref
    env["NO_COLOR"] = "1"

    # A previous GO run can leave an immutable selector that correctly overrides
    # shell state.  This fresh E2E database must start from the exact tested
    # image we build below; the canonical GO success path will publish its own
    # validated selector later.
    VALIDATED_RUNTIME_POINTER.unlink(missing_ok=True)

    _run_host([
        "docker", "build", "--network", "host", "--build-arg",
        "SOURCE_GIT_SHA=" + commit, "-t", runtime_ref,
        "-f", "Dockerfile.sentinel", ".",
    ], env=env, timeout=1800)
    print("E2E fixture: exact runtime built", flush=True)
    _run_host([
        "bash", "scripts/sentinel-compose.sh", "--run",
        "up", "-d", "--wait", "sentinel-postgres",
    ], env=env, timeout=300)

    # Feed mutation is allowed only when the real backup runtime can prove a
    # restore horizon, so establish that horizon before any schema/feed write.
    _run_host(["bash", "scripts/sentinel-base-backup.sh"], env=env, timeout=900)
    print("E2E fixture: real PostgreSQL backup horizon established", flush=True)

    schema_code = (
        "import os; "
        "from sentinel import operational_schema, schema; "
        "from sentinel.feed import store; "
        "c=store.connect(os.environ['SENTINEL_DATABASE_URL']); "
        "schema.ensure_schema(c); store.migrate_schema(c); operational_schema.install_quiescent(c); c.close()"
    )
    schema_url = (
        "postgresql://sentinel:e2e-postgres-password-363@127.0.0.1:5432/sentinel"
    )
    from scripts import sentinel_env
    fixture_env = sentinel_env.merge(sentinel_env.load(ROOT / ".env", required=True), env)
    postgres_container = _compose_service_container_id("sentinel-postgres", env=env)
    _run_host([
        "docker", "run", "--rm", "--network", f"container:{postgres_container}",
        "--entrypoint", "python", "-e", f"SENTINEL_DATABASE_URL={schema_url}",
        "-e", "SENTINEL_PUBLICATION_RECEIPT_KEY", runtime_ref, "-c", schema_code,
    ], env=fixture_env, timeout=300)

    # Phase C owns acquisition, candidate construction and first publication.
    # Refuse a stale fixture volume rather than certifying an already warm head.
    result = _run_host([
        "docker", "run", "--rm", "--network", f"container:{postgres_container}",
        "--entrypoint", "python", "-e", f"SENTINEL_DATABASE_URL={schema_url}",
        runtime_ref, "-c", "import os; from sentinel.feed import store; "
        "c=store.connect(os.environ['SENTINEL_DATABASE_URL']); "
        "print(c.execute('SELECT count(*) FROM sentinel_corpus_publications').fetchone()[0]); c.close()"
    ], env=env, timeout=120)
    if result.stdout.strip() != '0':
        raise HarnessFailure('canonical cold qualification requires an empty publication history')
    SEEDED_PUBLICATION = {"version": 0, "visible_frontier": None}
    _FIXTURE_READY = True


def _publication_identity(*, env=None) -> dict:
    from scripts import sentinel_env

    code = """
import json, os
from sentinel.core.decision import publication_fingerprint
from sentinel.feed import rolling_go_inputs, store
c = store.connect(os.environ['SENTINEL_DATABASE_URL'])
try:
    with c.cursor() as cur:
        cur.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
    with rolling_go_inputs.pinned(c) as held:
        print(json.dumps({
            'publication_fingerprint': publication_fingerprint(held),
            'visible_frontier': (held.window_end if rolling_go_inputs.is_rolling(held)
                                 else store.latest_visible_session(c)),
            'version': held.version,
        }, sort_keys=True))
finally:
    c.rollback(); c.close()
"""
    env = sentinel_env.merge(
        sentinel_env.load(ROOT / ".env", required=True),
        os.environ if env is None else env)
    postgres_container = _compose_service_container_id("sentinel-postgres", env=env)
    # Observe through the same isolated database connection used during fixture
    # setup. Operational Compose intentionally forbids entrypoint overrides.
    database_url = (
        "postgresql://sentinel:e2e-postgres-password-363@127.0.0.1:5432/sentinel"
    )
    result = _run_host([
        "docker", "run", "--rm", "--network", f"container:{postgres_container}",
        "--entrypoint", "python", "-e", f"SENTINEL_DATABASE_URL={database_url}",
        "-e", "SENTINEL_PUBLICATION_RECEIPT_KEY",
        f"sentinel-go-runtime:{_git_head()}", "-c", code,
    ], env=env, timeout=120)
    value = json.loads(result.stdout)
    if (not isinstance(value, dict) or type(value.get("version")) is not int
            or value["version"] < 1):
        raise HarnessFailure("fixture publication identity is unavailable")
    return value


def _clean_runtime() -> None:
    global _FIXTURE_READY, SEEDED_PUBLICATION
    _FIXTURE_READY = False
    SEEDED_PUBLICATION = None
    _run_host(
        ["bash", "scripts/sentinel-compose.sh", "--run", "down"],
        timeout=300,
    )


def _invoke(*, target: str = "SHADOW", extra_env: dict[str, str] | None = None,
            timeout: int = 19800, prepare_fixture: bool = True) -> subprocess.CompletedProcess[str]:
    from types import SimpleNamespace
    from scripts import sentinel_go_observability as observability
    if prepare_fixture:
        _bootstrap_financial_fixture()
    env = dict(os.environ)
    env.update(extra_env or {})
    env["NO_COLOR"] = "1"
    argv = [*ENTRYPOINT, "--local-full-certification", "--target", target]
    # GO already sanitizes its operator output. Retain it and stream the same
    # transcript so long real certification/preparation runs remain diagnosable.
    with _fixture_cli(env) as fixture_env:
        result = observability._streaming_run(
            SimpleNamespace(_safe_int_env=lambda *_args: timeout),
            SimpleNamespace(MAX_BOUNDED_INGEST_MS=timeout * 1000),
            argv, cwd=ROOT, env=fixture_env, raw_stream=True)
    return subprocess.CompletedProcess(
        argv, result.returncode, stdout=result.stdout + "\n" + result.stderr,
        stderr="")


def _phase_names(output: str) -> list[str]:
    return PHASE_RE.findall(output)


def _load_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise HarnessFailure(f"required evidence is unavailable: {path}") from exc
    if not isinstance(value, dict):
        raise HarnessFailure(f"required evidence is not an object: {path}")
    return value


def require_provider_requests(evidence):
    expected = {('GET', '/v2/assets'), ('GET', '/v2/stocks/bars'),
                ('GET', '/v1/corporate-actions'), ('POST', '/v3/mapping')}
    if {(row['method'], row['endpoint']) for row in evidence} != expected:
        raise HarnessFailure('incomplete or unexpected market-data provider traffic')


def _success_evidence(completed: subprocess.CompletedProcess[str], commit: str) -> dict:
    phases = _phase_names(completed.stdout)
    missing = [phase for phase in REQUIRED_PHASES if phase not in phases]
    if completed.returncode != 0 or SUCCESS not in completed.stdout or missing:
        tail = completed.stdout[-5000:]
        raise HarnessFailure(
            f"canonical GO failed rc={completed.returncode} missing_phases={missing}:\n{tail}")
    require_provider_requests(SOURCE_REQUESTS)
    handoff = _load_json(HANDOFF)
    if handoff.get("git_commit") != commit:
        raise HarnessFailure("handoff is not bound to tested HEAD")
    if handoff.get("mode") != "LOCAL_FULL_CERTIFICATION":
        raise HarnessFailure("handoff is not the local-full certified runtime")
    if handoff.get("software_certification") != "LOCAL_FULL_VERIFIED":
        raise HarnessFailure("handoff does not prove software certification")
    if handoff.get("authority") != "EVIDENCE_ONLY_NOT_BROKER_AUTHORITY":
        raise HarnessFailure("handoff authority changed")
    return {
        "returncode": completed.returncode,
        "phases": phases,
        "runtime_identity": handoff.get("runtime_local_image_id"),
        "test_lens_identity": handoff.get("test_lens_local_image_id"),
        "target": "SHADOW",
        "publication_and_readiness": "CERTIFICATION + FINANCIAL READINESS",
        "promotion": "PROMOTE EXACT CERTIFIED RUNTIME",
        "panel": "verified_recreated_promoted_runtime",
        "handoff": handoff,
    }


def _sensitivity_case(name: str, *, port: int, backup_dir: Path) -> dict:
    if name == "host-compatibility":
        completed = _invoke(
            extra_env={"SENTINEL_HOST_PYTHON": "/definitely/missing/python"},
            timeout=60, prepare_fixture=False)
        expected = "HOST COMPATIBILITY"
    elif name == "account-preflight":
        completed = _invoke(target="DUAL_RUN_OBSERVATION", extra_env={"ALPACA_API_KEY": "", "ALPACA_SECRET_KEY": ""},
                            timeout=300, prepare_fixture=False)
        expected = "PAPER ACCOUNT PREFLIGHT - GET ONLY"
    else:
        raise HarnessFailure(f"unknown sensitivity case {name}")
    phases = _phase_names(completed.stdout)
    if completed.returncode == 0 or expected not in phases:
        raise HarnessFailure(
            f"sensitivity {name} did not refuse at/after {expected}; rc={completed.returncode}")
    return {
        "name": name,
        "status": "EXPECTED_REFUSAL",
        "returncode": completed.returncode,
        "expected_phase": expected,
        "observed_phases": phases,
    }


def run(*, output: Path, sensitivity: bool) -> dict:
    commit = _git_head()
    output.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="sentinel-go-e2e-"))
    backup = work / "backup"
    backup.mkdir(parents=True)
    result: dict = {
        "schema": "sentinel.production-go-e2e/2",
        "git_commit": commit,
        "canonical_entrypoint": list(ENTRYPOINT),
        "success": None,
        "sensitivity": [],
        "all_pass": False,
    }
    try:
        with _source_server() as port, _temporary_environment_file(port=port, backup_dir=backup):
            _initialize_backup_target(backup)
            _clean_runtime()
            completed = _invoke()
            (output.parent / "canonical-go.log").write_text(completed.stdout, encoding="utf-8")
            result["success"] = _success_evidence(completed, commit)

            if sensitivity:
                # Cheap early-stage cases prove the harness is stage-sensitive.
                result["sensitivity"].append(
                    _sensitivity_case("host-compatibility", port=port, backup_dir=backup))
                result["sensitivity"].append(
                    _sensitivity_case("account-preflight", port=port, backup_dir=backup))

            _clean_runtime()

        result["all_pass"] = True
        output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return result
    except Exception as exc:
        result["failure"] = {"type": type(exc).__name__, "detail": str(exc)[-5000:]}
        output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        raise
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sensitivity", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = run(output=args.output, sensitivity=args.sensitivity)
    except (HarnessFailure, OSError, subprocess.SubprocessError) as exc:
        print(f"REFUSED: production GO E2E harness failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({
        "schema": result["schema"],
        "git_commit": result["git_commit"],
        "sensitivity_cases": len(result["sensitivity"]),
        "all_pass": result["all_pass"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
