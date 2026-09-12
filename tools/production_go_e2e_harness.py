#!/usr/bin/env python3
"""Exercise the canonical production GO lifecycle against deterministic externals.

This is deliberately a process/composition harness.  The success lane invokes
``bash scripts/sentinel-go-validate.sh`` exactly once and lets that entry point
own locking, bootstrap, Docker/Compose/PostgreSQL, local-full certification,
feed recovery, readiness, promotion, panel recreation and handoff.  Only the
Sharadar HTTP boundary is replaced with a deterministic Tables-compatible
server; SHADOW is the production-supported broker-free target.
"""
from __future__ import annotations

import argparse
import contextlib
import csv
import datetime as dt
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
from urllib.parse import parse_qs, urlparse
import zipfile

ROOT = Path(__file__).resolve().parents[1]
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
    "READ-ONLY SHARADAR PREFLIGHT",
    "CERTIFICATION + FINANCIAL READINESS",
    "PROMOTE EXACT CERTIFIED RUNTIME",
    "POST-VALIDATION HANDOFF",
)

TICKERS = (
    "SPY", "AAPL", "MSFT", "JPM", "XOM", "JNJ", "PG", "KO", "WMT", "CAT",
    "HD", "V", "MA", "PFE", "UNH", "CVX", "IBM", "GE", "DIS", "MMM",
)
SEP_COLUMNS = (
    "ticker", "date", "open", "high", "low", "close", "volume", "dividends",
    "closeunadj", "lastupdated",
)
SFP_COLUMNS = (
    "ticker", "date", "open", "high", "low", "close", "volume", "dividends",
    "closeadj", "closeunadj", "lastupdated",
)
ACTIONS_COLUMNS = (
    "date", "action", "ticker", "name", "value", "contraticker", "contraname",
)
TICKER_COLUMNS = (
    "table", "permaticker", "ticker", "name", "exchange", "isdelisted",
    "category", "cusips", "siccode", "sicsector", "sicindustry", "famasector",
    "famaindustry", "sector", "industry", "scalemarketcap", "scalerevenue",
    "relatedtickers", "currency", "location", "lastupdated", "firstadded",
    "firstpricedate", "lastpricedate", "firstquarter", "lastquarter",
    "secfilings", "companysite",
)

_FIXTURE_READY = False
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


def _session_days() -> tuple[dt.date, ...]:
    from sentinel.feed import calendar
    end = _latest_closed_session()
    start = end - dt.timedelta(days=560)
    return tuple(dt.date.fromisoformat(day) for day in calendar.sessions_in_range(start, end))


def _in_range(day: dt.date, query: dict[str, list[str]], key: str = "date") -> bool:
    lo = query.get(f"{key}.gte", [None])[0]
    hi = query.get(f"{key}.lte", [None])[0]
    eq = query.get(key, [None])[0]
    if eq and day.isoformat() != eq:
        return False
    if lo and day < dt.date.fromisoformat(lo[:10]):
        return False
    if hi and day > dt.date.fromisoformat(hi[:10]):
        return False
    return True


def _price_rows(query: dict[str, list[str]], *, sfp: bool = False) -> list[list[object]]:
    rows: list[list[object]] = []
    source_day = dt.datetime.now(dt.timezone.utc).date()
    ticker_filter = query.get("ticker", [None])[0]
    allowed = (
        {item.strip().upper() for item in ticker_filter.split(",") if item.strip()}
        if ticker_filter else None
    )
    tickers = ("SPY", "BIL") if sfp else TICKERS
    for ti, ticker in enumerate(tickers):
        if allowed is not None and ticker not in allowed:
            continue
        for di, day in enumerate(_session_days()):
            if not _in_range(day, query):
                continue
            if not _in_range(source_day, query, key="lastupdated"):
                continue
            base = 50.0 + ti * 7.0 + di * 0.03
            raw_open = round(base, 4)
            raw_close = round(base * 1.001, 4)
            common = [
                ticker, day.isoformat(), raw_open, round(base * 1.006, 4),
                round(base * 0.994, 4), raw_close, 2_000_000 + ti * 10_000,
                0.0,
            ]
            if sfp:
                rows.append(common + [raw_close, raw_close, source_day.isoformat()])
            else:
                rows.append(common + [raw_close, source_day.isoformat()])
    return rows


def _ticker_rows() -> list[list[object]]:
    source_day = dt.datetime.now(dt.timezone.utc).date().isoformat()
    result = []
    for i, ticker in enumerate(TICKERS, start=1):
        category = "ETF" if ticker == "SPY" else "Domestic Common Stock"
        result.append([
            "SEP", 100000 + i, ticker, f"{ticker} fixture security", "NYSE",
            "N", category, None, 3571, "Manufacturing", "Technology",
            "Business Equipment", "Computers", "Technology", "Software",
            "5 - Large", "5 - Large", None, "USD", "U.S.A.", source_day,
            "2000-01-03", "2000-01-03", None, "2000-03-31", None, None, None,
        ])
    return result


def _payload(table: str, query: dict[str, list[str]]) -> dict:
    if table == "SEP":
        columns, rows = SEP_COLUMNS, _price_rows(query)
    elif table == "SFP":
        columns, rows = SFP_COLUMNS, _price_rows(query, sfp=True)
    elif table == "ACTIONS":
        # Complete production seed acquisition requires a nonempty whole-table
        # ACTIONS witness. A relation is retained metadata with no cash/share
        # effect, and both paginated and exported observations carry it.
        day = _session_days()[0]
        columns = ACTIONS_COLUMNS
        rows = ([[day.isoformat(), "relation", "AAPL", "AAPL fixture security",
                  None, "MSFT", "MSFT fixture security"]]
                if _in_range(day, query) else [])
    elif table == "TICKERS":
        columns, rows = TICKER_COLUMNS, _ticker_rows()
    else:
        raise KeyError(table)
    return {
        "datatable": {
            "columns": [{"name": name, "type": "text"} for name in columns],
            "data": rows,
        },
        "meta": {"next_cursor_id": None},
    }


class _TablesHandler(BaseHTTPRequestHandler):
    fail_source = False
    downloads: dict[str, bytes] = {}
    refreshed_at = ""

    def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler API
        parsed = urlparse(self.path)
        table = Path(parsed.path).stem.upper()
        if self.fail_source:
            self.send_response(503)
            self.send_header("Retry-After", "0")
            self.end_headers()
            return
        query = parse_qs(parsed.query)
        try:
            if parsed.path.startswith("/exports/"):
                body = self.downloads[parsed.path]
                channel = "download"
                content_type = "application/zip"
            elif query.get("qopts.export") == ["true"]:
                page = _payload(table, query)["datatable"]
                content = io.StringIO(newline="")
                writer = csv.writer(content)
                writer.writerow(item["name"] for item in page["columns"])
                writer.writerows(page["data"])
                buffer = io.BytesIO()
                with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
                    info = zipfile.ZipInfo(f"{table}.csv", (2000, 1, 1, 0, 0, 0))
                    archive.writestr(info, content.getvalue())
                blob = buffer.getvalue()
                path = f"/exports/{table}-{hashlib.sha256(blob).hexdigest()}.zip"
                self.downloads[path] = blob
                body = json.dumps({"datatable_bulk_download": {
                    "file": {"status": "fresh", "link": f"http://{self.headers['Host']}{path}",
                             "data_snapshot_time": self.refreshed_at},
                    "datatable": {"last_refreshed_time": self.refreshed_at},
                }}).encode()
                channel = "export"
                content_type = "application/json"
            else:
                body = json.dumps(_payload(table, query)).encode()
                channel = "pages"
                content_type = "application/json"
        except (KeyError, ValueError):
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        SOURCE_REQUESTS.append({"table": table.split("-")[0], "channel": channel})
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format, *_args):
        return


@contextlib.contextmanager
def _source_server(*, fail_source: bool = False):
    SOURCE_REQUESTS.clear()
    handler = type("TablesHandler", (_TablesHandler,), {
        "fail_source": fail_source, "downloads": {},
        "refreshed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    })
    server = ThreadingHTTPServer(("0.0.0.0", 0), handler)
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
    _SOURCE_SETTINGS.update({
        "NDL_BASE_URL": f"http://{gateway}:{port}",
        "SHARADAR_ALLOW_INSECURE_BASE_URL": "1",
        "SHARADAR_FETCH_RETRIES": "1",
        "SHARADAR_FETCH_BACKOFF": "0",
    })
    lines = [
        "SENTINEL_POSTGRES_PASSWORD=e2e-postgres-password-363",
        "SENTINEL_PUBLICATION_RECEIPT_KEY=e2e-publication-receipt-key-363-0123456789abcdef",
        "SHARADAR_API_KEY=e2e-sharadar-key",
        *(f"{key}={value}" for key, value in _SOURCE_SETTINGS.items()),
        "ALPACA_API_KEY=",
        "ALPACA_SECRET_KEY=",
        "ALPACA_BASE_URL=https://paper-api.alpaca.markets",
        f"SENTINEL_BACKUP_DIR={backup_dir}",
        "SENTINEL_BACKUP_DURABLE_TARGET_ATTESTED=1",
        "SENTINEL_SHADOW_OBSERVATION_ENABLED=0",
        "SENTINEL_SHADOW_STARTING_CASH=100000",
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


def _require_local_source(model: dict, expected: dict[str, str]) -> None:
    service = model.get("services", {}).get("sentinel")
    if not isinstance(service, dict):
        raise HarnessFailure("resolved Compose model omits the CLI feed service")
    actual = service.get("environment", {})
    mismatched = [key for key, value in expected.items()
                  if str(actual.get(key, "")) != value]
    if not expected or mismatched:
        raise HarnessFailure(
            "resolved feed container does not select the local Sharadar fixture: "
            + ", ".join(mismatched))


def _bootstrap_financial_fixture() -> None:
    """Create the supported retained feed state required before production daily GO."""
    global _FIXTURE_READY
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

    # Resolve the exact production graph before any feed request. A dropped
    # setting must fail here, before the runtime can select its vendor default.
    resolved = _run_host([
        "bash", "scripts/sentinel-compose.sh", "--run", "--profile", "cli",
        "config", "--format", "json",
    ], env=env, timeout=60)
    _require_local_source(json.loads(resolved.stdout), _SOURCE_SETTINGS)
    print("E2E fixture: resolved feed container selects local Sharadar", flush=True)

    _run_host([
        "docker", "build", "--network", "host", "--build-arg",
        "SOURCE_GIT_SHA=" + commit, "-t", runtime_ref,
        "-f", "Dockerfile.sentinel", ".",
    ], env=env, timeout=1800)
    _run_host([
        "bash", "scripts/sentinel-compose.sh", "--run",
        "up", "-d", "--wait", "sentinel-postgres",
    ], env=env, timeout=300)

    # Feed mutation is allowed only when the real backup runtime can prove a
    # restore horizon, so establish that horizon before any schema/feed write.
    _run_host(["bash", "scripts/sentinel-base-backup.sh"], env=env, timeout=900)

    schema_code = (
        "import os; "
        "from sentinel import schema; "
        "from sentinel.feed import store; "
        "c=store.connect(os.environ['SENTINEL_DATABASE_URL']); "
        "schema.ensure_schema(c); store.migrate_schema(c); c.close()"
    )
    schema_url = (
        "postgresql://sentinel:e2e-postgres-password-363@127.0.0.1:5432/sentinel"
    )
    postgres_container = _compose_service_container_id("sentinel-postgres", env=env)
    _run_host([
        "docker", "run", "--rm", "--network", f"container:{postgres_container}",
        "--entrypoint", "python", "-e", f"SENTINEL_DATABASE_URL={schema_url}",
        runtime_ref, "-c", schema_code,
    ], env=env, timeout=300)

    days = _session_days()
    if not days:
        raise HarnessFailure("deterministic Sharadar fixture has no seed sessions")
    _run_host([
        "bash", "scripts/sentinel-compose.sh", "--run",
        "run", "--rm", "-T", "--no-deps", "sentinel", "feed-seed",
        "--from", days[0].isoformat(), "--to", days[-1].isoformat(),
    ], env=env, timeout=1800)
    _FIXTURE_READY = True


def _clean_runtime() -> None:
    global _FIXTURE_READY
    _FIXTURE_READY = False
    _run_host(
        ["bash", "scripts/sentinel-compose.sh", "--run", "down"],
        timeout=300,
    )


def _invoke(*, target: str = "SHADOW", extra_env: dict[str, str] | None = None,
            timeout: int = 5400, prepare_fixture: bool = True) -> subprocess.CompletedProcess[str]:
    if prepare_fixture:
        _bootstrap_financial_fixture()
    env = dict(os.environ)
    env.update(extra_env or {})
    env["NO_COLOR"] = "1"
    argv = [*ENTRYPOINT, "--local-full-certification", "--target", target]
    return subprocess.run(
        argv, cwd=ROOT, env=env, text=True, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, timeout=timeout, check=False,
    )


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


def _success_evidence(completed: subprocess.CompletedProcess[str], commit: str) -> dict:
    phases = _phase_names(completed.stdout)
    missing = [phase for phase in REQUIRED_PHASES if phase not in phases]
    if completed.returncode != 0 or SUCCESS not in completed.stdout or missing:
        tail = completed.stdout[-5000:]
        raise HarnessFailure(
            f"canonical GO failed rc={completed.returncode} missing_phases={missing}:\n{tail}")
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
        completed = _invoke(target="PAPER", timeout=300, prepare_fixture=False)
        expected = "PAPER ACCOUNT PREFLIGHT - GET ONLY"
    elif name == "source-preflight":
        # This lane is run with a failing Tables server and must reach the
        # read-only source authority before refusing.
        completed = _invoke(timeout=1800, prepare_fixture=False)
        expected = "READ-ONLY SHARADAR PREFLIGHT"
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
        "schema": "sentinel.production-go-e2e/1",
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

        if sensitivity:
            with _source_server(fail_source=True) as port, _temporary_environment_file(
                    port=port, backup_dir=backup):
                result["sensitivity"].append(
                    _sensitivity_case("source-preflight", port=port, backup_dir=backup))

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
