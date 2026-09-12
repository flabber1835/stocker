#!/usr/bin/env python3
"""Authority and host helpers for the true production GO E2E."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import re
import socket
import subprocess
import time
from typing import Iterable, Mapping

IMAGE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
HEX40 = re.compile(r"^[0-9a-f]{40}$")
TARGET = "DUAL_RUN_OBSERVATION"
ALPACA_HOST = "paper-api.alpaca.markets"

LIFECYCLE_MARKERS = (
    "=== HOST COMPATIBILITY ===",
    "=== ACQUIRE SINGLE GO LIFECYCLE LOCK ===",
    "[GO] GO lifecycle lock held",
    "=== DEPLOYMENT SECRETS BOOTSTRAP ===",
    "=== HOST GO IDENTITY PREFLIGHT ===",
    "=== RUNTIME SELECTION PREFLIGHT ===",
    "=== PAPER ACCOUNT PREFLIGHT - GET ONLY ===",
    "=== READ-ONLY SHARADAR PREFLIGHT ===",
    "=== CERTIFICATION + FINANCIAL READINESS ===",
    "software certification mode: LOCAL_FULL",
    "=== PROMOTE EXACT CERTIFIED RUNTIME ===",
    "runtime promotion: BOUND - requested DUAL_RUN_OBSERVATION GO",
    "=== POST-VALIDATION HANDOFF ===",
    "post-validation: panel recreated and verified on the one validated runtime",
    "[GO] GO lifecycle completed successfully",
)


class E2ERefused(RuntimeError):
    pass


def run(argv: Iterable[str], *, cwd: Path, env: Mapping[str, str] | None = None,
        check: bool = True, capture: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(
        [str(item) for item in argv], cwd=str(cwd),
        env=dict(env) if env is not None else None, text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None, check=False)
    if check and result.returncode != 0:
        detail = ((result.stdout or "") + "\n" + (result.stderr or ""))[-6000:]
        raise E2ERefused(
            f"command failed ({result.returncode}): {' '.join(map(str, argv))}\n{detail}")
    return result


def git(cwd: Path, *args: str) -> str:
    return (run(["git", *args], cwd=cwd).stdout or "").strip()


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("0.0.0.0", 0))
        return int(sock.getsockname()[1])


def current_source_final_target(cwd: Path, env: Mapping[str, str]) -> str:
    code = r'''
from datetime import datetime, timezone
from sentinel.feed import calendar
from sentinel.shadow_runtime import publication_not_before
now = datetime.now(timezone.utc)
target = calendar.latest_closed_session(now)
while now < publication_not_before(target):
    previous = calendar.previous_sessions(target, 2)
    if len(previous) != 2 or previous[-1] != target:
        raise RuntimeError("source-final predecessor is unavailable")
    target = previous[0]
print(target)
'''
    result = run([env.get("SENTINEL_HOST_PYTHON", "python"), "-c", code],
                 cwd=cwd, env=env)
    return (result.stdout or "").strip()


def validate_lifecycle_transcript(text: str) -> None:
    cursor = 0
    for marker in LIFECYCLE_MARKERS:
        found = text.find(marker, cursor)
        if found < 0:
            raise E2ERefused(f"production GO lifecycle marker missing: {marker}")
        cursor = found + len(marker)


def digest_image(cwd: Path, ref: str) -> str:
    value = (run(["docker", "image", "inspect", "--format", "{{.Id}}", ref],
                 cwd=cwd).stdout or "").strip()
    if IMAGE_ID.fullmatch(value) is None:
        raise E2ERefused(f"invalid image id for {ref}: {value!r}")
    return value


def validate_authority_payloads(*, handoff: Mapping[str, object],
                                ordinary: Mapping[str, object], pointer: str,
                                commit: str) -> tuple[str, str]:
    runtime_id = str(handoff.get("runtime_local_image_id") or "")
    test_id = str(handoff.get("test_lens_local_image_id") or "")
    if handoff.get("schema") != "sentinel.validated-artifact-handoff/3":
        raise E2ERefused("handoff schema mismatch")
    if handoff.get("mode") != "LOCAL_FULL_CERTIFICATION":
        raise E2ERefused("handoff mode mismatch")
    if handoff.get("git_commit") != commit:
        raise E2ERefused("handoff commit mismatch")
    if IMAGE_ID.fullmatch(runtime_id) is None or IMAGE_ID.fullmatch(test_id) is None:
        raise E2ERefused("handoff image identity missing")
    if ordinary.get("git_commit") != commit:
        raise E2ERefused("certification binding commit mismatch")
    if ordinary.get("ordinary_runtime_image_digest") != runtime_id:
        raise E2ERefused("certification/promotion runtime identity mismatch")
    if pointer != f"SENTINEL_RUNTIME_IMAGE_REF={runtime_id}":
        raise E2ERefused("runtime pointer does not name certified runtime")
    return runtime_id, test_id


def verify_final_authority(*, work: Path, commit: str, expected_target: str) -> dict:
    handoff_path = work / "artifacts/sentinel/deployment/validated-artifact-handoff.json"
    pointer_path = work / "artifacts/sentinel/deployment/validated-runtime.env"
    ordinary_path = work / "artifacts/sentinel/go-validation/stable-certification-ordinary-runtime.json"
    handoff = json.loads(handoff_path.read_text(encoding="utf-8"))
    ordinary = json.loads(ordinary_path.read_text(encoding="utf-8"))
    pointer = pointer_path.read_text(encoding="ascii").strip()
    runtime_id, test_id = validate_authority_payloads(
        handoff=handoff, ordinary=ordinary, pointer=pointer, commit=commit)
    if digest_image(work, f"sentinel-go-runtime:{commit}") != runtime_id:
        raise E2ERefused("local runtime tag moved after certification")
    if digest_image(work, f"sentinel-go-test:{commit}") != test_id:
        raise E2ERefused("local test lens moved after certification")
    panel = (run(["bash", "scripts/sentinel-compose.sh", "--run", "ps", "-q",
                  "sentinel-panel"], cwd=work).stdout or "").strip()
    if not panel or "\n" in panel:
        raise E2ERefused("promoted panel container is not uniquely running")
    panel_image = (run(["docker", "container", "inspect", "--format", "{{.Image}}",
                        panel], cwd=work).stdout or "").strip()
    if panel_image != runtime_id:
        raise E2ERefused("panel does not use certified/promoted runtime")
    row = (run([
        "bash", "scripts/sentinel-compose.sh", "--run", "exec", "-T",
        "sentinel-postgres", "psql", "-U", "sentinel", "-d", "sentinel",
        "-AtX", "-v", "ON_ERROR_STOP=1", "-c",
        "SELECT p.version::text || '|' || COALESCE(p.run_id::text,'') || '|' || "
        "p.window_end::text || '|' || "
        "(SELECT MAX(b.session)::text FROM sentinel_bars b "
        " WHERE EXISTS (SELECT 1 FROM sentinel_corpus_publications p2 "
        "               WHERE p2.run_id=b.last_written_run_id)) "
        "FROM sentinel_corpus_publications p ORDER BY p.version DESC LIMIT 1;",
    ], cwd=work).stdout or "").strip()
    parts = row.split("|")
    if len(parts) != 4 or parts[2] != expected_target or parts[3] != expected_target:
        raise E2ERefused(
            f"publication/frontier mismatch: {row!r}, expected {expected_target}")
    return {
        "git_commit": commit, "requested_target": TARGET,
        "source_final_frontier": expected_target, "runtime_image_id": runtime_id,
        "test_lens_image_id": test_id, "panel_image_id": panel_image,
        "publication_version": int(parts[0]), "publication_run_id": parts[1],
        "publication_window_end": parts[2], "visible_frontier": parts[3],
    }


def fixture_value(label: str) -> str:
    return hashlib.sha256(f"issue-363-go-e2e:{label}".encode()).hexdigest()


def write_env(path: Path, *, backup: Path, ndl_base: str) -> dict[str, str]:
    values = {
        "SENTINEL_POSTGRES_PASSWORD": fixture_value("postgres"),
        "SENTINEL_PUBLICATION_RECEIPT_KEY": fixture_value("receipt"),
        "SHARADAR_API_KEY": fixture_value("sharadar"),
        "NDL_BASE_URL": ndl_base,
        "SHARADAR_ALLOW_INSECURE_BASE_URL": "1",
        "ALPACA_API_KEY": "e2e-key",
        "ALPACA_SECRET_KEY": "e2e-" + "secret",
        "ALPACA_BASE_URL": f"https://{ALPACA_HOST}",
        "SENTINEL_PAPER_ACCOUNT_ID": "E2E-PAPER-ACCOUNT",
        "SENTINEL_AUTOMATION_ALERT_WEBHOOK_URL": "https://alerts.invalid/sentinel-e2e",
        "SENTINEL_BACKUP_DIR": str(backup),
        "SENTINEL_BACKUP_DURABLE_TARGET_ATTESTED": "1",
        "SENTINEL_GO_TARGET": TARGET,
    }
    path.write_text("".join(f"{key}={value}\n" for key, value in values.items()),
                    encoding="utf-8")
    path.chmod(0o600)
    return values


def wait_postgres(work: Path, env: Mapping[str, str], timeout: int = 120) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        ids = (run(["bash", "scripts/sentinel-compose.sh", "--run", "ps", "-q",
                    "sentinel-postgres"], cwd=work, env=env,
                   check=False).stdout or "").strip()
        if ids and "\n" not in ids:
            state = (run([
                "docker", "inspect", "--format",
                "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}",
                ids], cwd=work, env=env, check=False).stdout or "").strip()
            if state == "healthy":
                return
        time.sleep(1)
    raise E2ERefused("PostgreSQL did not become healthy")


def openssl_alpaca_certificate(root: Path, cwd: Path) -> tuple[Path, Path, Path]:
    ca_key, ca_crt = root / "ca.key", root / "ca.crt"
    server_key, server_csr, server_crt = root / "alpaca.key", root / "alpaca.csr", root / "alpaca.crt"
    ext = root / "alpaca.ext"
    ext.write_text(
        "subjectAltName=DNS:paper-api.alpaca.markets\n"
        "basicConstraints=CA:FALSE\nkeyUsage=digitalSignature,keyEncipherment\n"
        "extendedKeyUsage=serverAuth\n", encoding="ascii")
    run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
         "-keyout", str(ca_key), "-out", str(ca_crt), "-days", "2",
         "-subj", "/CN=Sentinel GO E2E CA"], cwd=cwd)
    run(["openssl", "req", "-newkey", "rsa:2048", "-nodes",
         "-keyout", str(server_key), "-out", str(server_csr),
         "-subj", f"/CN={ALPACA_HOST}"], cwd=cwd)
    run(["openssl", "x509", "-req", "-in", str(server_csr), "-CA", str(ca_crt),
         "-CAkey", str(ca_key), "-CAcreateserial", "-out", str(server_crt),
         "-days", "2", "-sha256", "-extfile", str(ext)], cwd=cwd)
    return ca_crt, server_crt, server_key


@contextmanager
def hosts_mapping(cwd: Path):
    marker = "# sentinel-production-go-e2e"
    line = f"127.0.0.1 {ALPACA_HOST} {marker}"
    run(["sudo", "sh", "-c", f"printf '%s\\n' '{line}' >> /etc/hosts"], cwd=cwd)
    try:
        yield
    finally:
        cleanup = (
            "from pathlib import Path\n"
            "p=Path('/etc/hosts')\n"
            f"m={marker!r}\n"
            "p.write_text(''.join(x for x in p.read_text().splitlines(True) if m not in x))\n")
        run(["sudo", "python3", "-c", cleanup], cwd=cwd, check=False)


def parse_env_for_cleanup(path: Path) -> dict[str, str]:
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    return values
