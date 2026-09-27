#!/usr/bin/env python3
"""Run live host/Docker composition gates that must not be reduced to mocks."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
TESTS = ROOT / "tests"
for path in (SCRIPTS, TESTS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import sentinel_go_probe_contract as probe_contract  # noqa: E402
from production_composition.contract import scenarios  # noqa: E402
from production_composition.extended_contract import EXTENDED_CASES  # noqa: E402

POSTGRES = (
    "postgres:16@sha256:"
    "95206741a5b214807675e14165369d05b93a9cf692223b616d07cca227e74b0b"
)


class HarnessFailure(RuntimeError):
    pass


def _run(argv, *, env=None, timeout=120):
    completed = subprocess.run(
        [str(item) for item in argv],
        cwd=ROOT,
        env=(dict(env) if env is not None else None),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )
    return completed


def _require(command, *, label):
    completed = _run(command)
    if completed.returncode != 0:
        raise HarnessFailure(
            f"{label} failed rc={completed.returncode}: "
            f"{(completed.stderr or completed.stdout)[-600:]}"
        )
    return completed


def _compose_text(*, health: str = "pg", service_name: str = "sentinel-postgres"):
    if health == "pg":
        healthcheck = """
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -h 127.0.0.1 -U postgres -d postgres"]
      interval: 1s
      timeout: 1s
      retries: 30
"""
    elif health == "never":
        healthcheck = """
    healthcheck:
      test: ["CMD-SHELL", "exit 1"]
      interval: 500ms
      timeout: 500ms
      retries: 100
"""
    else:
        healthcheck = ""
    return f"""services:
  {service_name}:
    image: {POSTGRES}
    environment:
      POSTGRES_PASSWORD: composition-only-password
    volumes:
      - pgdata:/var/lib/postgresql/data
{healthcheck}
volumes:
  pgdata:
"""


def _compose_args(path: Path, project: str):
    return ["-f", str(path), "-p", project]


def _cleanup(path: Path, project: str):
    _run([
        "docker", "compose", *_compose_args(path, project),
        "down", "-v", "--remove-orphans",
    ], timeout=60)


def _environment(timeout_seconds: int):
    env = dict(os.environ)
    env["SENTINEL_GO_POSTGRES_START_TIMEOUT_SECONDS"] = str(timeout_seconds)
    for key in list(env):
        if key.startswith("COMPOSE_") or key.startswith("DOCKER_"):
            env.pop(key, None)
    return env


def _verify_sql(path: Path, project: str, *, label: str,
                timeout_seconds: float = 10.0):
    deadline = time.monotonic() + timeout_seconds
    last = None
    while True:
        completed = _run([
            "docker", "compose", *_compose_args(path, project),
            "exec", "-T", "-e", "PGPASSWORD=composition-only-password",
            "sentinel-postgres",
            "psql", "-h", "127.0.0.1", "-U", "postgres", "-d", "postgres", "-Atqc",
            "SELECT 1",
        ])
        if completed.returncode == 0 and completed.stdout.strip() == "1":
            return
        last = completed
        if time.monotonic() >= deadline:
            detail = (completed.stderr or completed.stdout or "").strip()[-600:]
            raise HarnessFailure(
                f"{label}: PostgreSQL semantic probe failed "
                f"rc={completed.returncode}: {detail}"
            )
        time.sleep(0.25)


def _ensure_ready(path: Path, project: str, *, timeout_seconds: int, label: str):
    runner = probe_contract.DeadlineCommandRunner(cwd=ROOT)
    failure = probe_contract.ensure_postgres_ready(
        runner,
        env=_environment(timeout_seconds),
        compose_args=_compose_args(path, project),
    )
    if failure is not None:
        raise HarnessFailure(f"{label}: unexpected refusal {failure}")
    _verify_sql(
        path,
        project,
        label=label,
        timeout_seconds=min(10.0, float(timeout_seconds)),
    )


def _docker_case(tmp: Path, *, name: str, text: str, timeout_seconds: int,
                 expected_reason=None, verify_sql=False, restart=False):
    path = tmp / f"{name}.yml"
    path.write_text(text, encoding="utf-8")
    project = "sentinel-composition-" + uuid.uuid4().hex[:12]
    env = _environment(timeout_seconds)
    runner = probe_contract.DeadlineCommandRunner(cwd=ROOT)
    try:
        failure = probe_contract.ensure_postgres_ready(
            runner, env=env, compose_args=_compose_args(path, project))
        if expected_reason is None:
            if failure is not None:
                raise HarnessFailure(f"{name}: unexpected refusal {failure}")
            if verify_sql:
                _verify_sql(
                    path,
                    project,
                    label=name,
                    timeout_seconds=min(10.0, float(timeout_seconds)),
                )
            if restart:
                _require([
                    "docker", "compose", *_compose_args(path, project),
                    "restart", "sentinel-postgres",
                ], label=f"{name} restart")
                _ensure_ready(
                    path, project, timeout_seconds=timeout_seconds,
                    label=f"{name} after restart")
            return {"name": name, "status": "PASS", "reason": None}
        if failure is None:
            raise HarnessFailure(f"{name}: expected {expected_reason}, got PASS")
        reason = str(failure.get("reason") or "")
        allowed = (
            {expected_reason}
            if isinstance(expected_reason, str)
            else set(expected_reason)
        )
        if reason not in allowed:
            raise HarnessFailure(
                f"{name}: expected reason {sorted(allowed)}, got {reason}")
        return {"name": name, "status": "EXPECTED_REFUSAL", "reason": reason}
    finally:
        _cleanup(path, project)


def _recovery_case(tmp: Path, *, name: str, action: str):
    path = tmp / f"{name}.yml"
    path.write_text(_compose_text(), encoding="utf-8")
    project = "sentinel-composition-" + uuid.uuid4().hex[:12]
    args = _compose_args(path, project)
    try:
        _ensure_ready(path, project, timeout_seconds=45, label=f"{name} initial")
        sql = ["docker", "compose", *args, "exec", "-T", "sentinel-postgres",
               "psql", "-U", "postgres", "-d", "postgres", "-v", "ON_ERROR_STOP=1", "-Atqc"]
        _require(sql + ["CREATE TABLE recovery_marker (id integer PRIMARY KEY); "
                        "INSERT INTO recovery_marker VALUES (1)"], label=name)
        if action == "stop":
            _require([
                "docker", "compose", *args, "stop", "sentinel-postgres",
            ], label=f"{name} stop")
        elif action == "remove":
            _require([
                "docker", "compose", *args, "rm", "-sf", "sentinel-postgres",
            ], label=f"{name} remove")
        elif action == "network-down":
            _require([
                "docker", "compose", *args, "down", "--remove-orphans",
            ], label=f"{name} down")
        elif action == "image-delete":
            _require([
                "docker", "compose", *args, "down", "--remove-orphans",
            ], label=f"{name} down before image deletion")
            _require([
                "docker", "image", "rm", POSTGRES,
            ], label=f"{name} remove image")
        else:
            raise HarnessFailure(f"{name}: unknown recovery action {action}")
        _ensure_ready(path, project, timeout_seconds=45, label=f"{name} recovered")
        retained = _require(sql + ["SELECT id FROM recovery_marker"], label=name)
        if retained.stdout.strip() != "1":
            raise HarnessFailure(f"{name}: committed data did not survive recovery")
        return {"name": name, "status": "PASS", "reason": None}
    finally:
        _cleanup(path, project)


def _initialization_case(tmp: Path):
    name = "postgres-initialization-is-not-ready"
    path = tmp / f"{name}.yml"
    script = ("#!/bin/sh\ntouch /tmp/composition-initializing\n"
              "while [ ! -f /tmp/composition-release ]; do sleep 0.1; done\n")
    # The Docker daemon may be outside this controller's filesystem. Create
    # the fixture in the disposable container rather than bind a host path.
    command = ["bash", "-c", "printf '%s' " + shlex.quote(script)
               + " > /docker-entrypoint-initdb.d/hold-init.sh; "
               "exec docker-entrypoint.sh postgres"]
    text = _compose_text().replace(
        "    environment:", "    entrypoint: " + json.dumps(command) + "\n    environment:")
    path.write_text(text, encoding="utf-8")
    project = "sentinel-composition-" + uuid.uuid4().hex[:12]
    prefix = ["docker", "compose", *_compose_args(path, project)]
    try:
        _require(prefix + ["up", "-d", "sentinel-postgres"], label=name)
        deadline = time.monotonic() + 45
        while True:
            initialized = _run(prefix + [
                "exec", "-T", "sentinel-postgres", "test", "-f",
                "/tmp/composition-initializing"], timeout=5)
            if initialized.returncode == 0:
                break
            if time.monotonic() >= deadline:
                raise HarnessFailure(f"{name}: initialization fixture never started")
            time.sleep(0.25)
        # The temporary socket server really is accepting SQL during this hold.
        temporary = _require(prefix + [
            "exec", "-T", "sentinel-postgres", "psql", "-U", "postgres",
            "-d", "postgres", "-Atqc", "SELECT 1"], label=name)
        if temporary.stdout.strip() != "1":
            raise HarnessFailure(f"{name}: temporary SQL fixture unavailable")
        failure = probe_contract.ensure_postgres_ready(
            probe_contract.DeadlineCommandRunner(cwd=ROOT),
            env=_environment(3), compose_args=_compose_args(path, project))
        if failure is None or failure.get("reason") != "POSTGRES_HEALTH_TIMEOUT":
            raise HarnessFailure(f"{name}: temporary server admitted: {failure}")
        try:
            _verify_sql(path, project, label=name, timeout_seconds=1)
        except HarnessFailure:
            pass
        else:
            raise HarnessFailure(f"{name}: temporary server passed permanent SQL probe")
        _require(prefix + ["exec", "-T", "sentinel-postgres", "touch",
                           "/tmp/composition-release"], label=name)
        _ensure_ready(path, project, timeout_seconds=45, label=name)
        _require(prefix + ["stop", "sentinel-postgres"], label=name)
        _ensure_ready(path, project, timeout_seconds=45, label=f"{name} recovered")
        return {"name": name, "status": "PASS", "reason": None}
    finally:
        _cleanup(path, project)


def _scenario_count():
    return len(scenarios()) + len(EXTENDED_CASES)


def _crash_transaction_case(tmp: Path):
    """Real database process death: durable commit, rollback, bounded retry."""
    name = "postgres-crash-rollback-and-retry"
    path = tmp / (name + ".yml")
    path.write_text(_compose_text(), encoding="utf-8")
    project = "sentinel-composition-" + uuid.uuid4().hex[:12]
    prefix = ["docker", "compose", *_compose_args(path, project)]
    sql = prefix + ["exec", "-T", "-e", "PGAPPNAME=composition-observer",
                    "sentinel-postgres", "psql", "-U", "postgres", "-d", "postgres",
                    "-v", "ON_ERROR_STOP=1", "-Atqc"]
    worker = None
    try:
        _ensure_ready(path, project, timeout_seconds=45, label=name)
        _require(sql + ["CREATE TABLE recovery_marker (id integer PRIMARY KEY); "
                        "INSERT INTO recovery_marker VALUES (1)"], label=name)
        writer = prefix + ["exec", "-T", "-e", "PGAPPNAME=composition-open-tx",
                           "sentinel-postgres", "psql", "-U", "postgres", "-d", "postgres",
                           "-v", "ON_ERROR_STOP=1", "-Atqc",
                           "BEGIN; INSERT INTO recovery_marker VALUES (2); "
                           "SELECT pg_sleep(120); COMMIT"]
        worker = subprocess.Popen(writer, cwd=ROOT, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True)
        deadline = time.monotonic() + 15
        while True:
            observed = _require(sql + [
                "SELECT count(*) FROM pg_stat_activity WHERE "
                "application_name='composition-open-tx' AND wait_event='PgSleep'"
            ], label=name)
            if observed.stdout.strip() == "1":
                break
            if worker.poll() is not None or time.monotonic() >= deadline:
                raise HarnessFailure(f"{name}: worker never reached open transaction")
            time.sleep(0.1)
        _require(prefix + ["kill", "-s", "SIGKILL", "sentinel-postgres"], label=name)
        worker.communicate(timeout=15)
        if worker.returncode == 0:
            raise HarnessFailure(f"{name}: interrupted writer reported success")
        _ensure_ready(path, project, timeout_seconds=45, label=name)
        recovered = _require(sql + [
            "SELECT string_agg(id::text, ',' ORDER BY id) FROM recovery_marker"
        ], label=name)
        if recovered.stdout.strip() != "1":
            raise HarnessFailure(f"{name}: lost committed data or retained incomplete work")
        for _attempt in range(2):
            _require(sql + ["INSERT INTO recovery_marker VALUES (2) ON CONFLICT DO NOTHING"],
                     label=name)
        _require(prefix + ["restart", "sentinel-postgres"], label=name)
        _ensure_ready(path, project, timeout_seconds=45, label=name)
        final = _require(sql + [
            "SELECT string_agg(id::text, ',' ORDER BY id) FROM recovery_marker"
        ], label=name)
        if final.stdout.strip() != "1,2":
            raise HarnessFailure(f"{name}: retry did not converge durably")
        return {"name": name, "status": "PASS", "reason": None}
    finally:
        _cleanup(path, project)
        if worker is not None:
            if worker.poll() is None:
                worker.kill()
            worker.communicate(timeout=10)


def run_live(*, include_shared_image_removal: bool = False) -> dict:
    _require(["docker", "version"], label="Docker")
    _require(["docker", "compose", "version"], label="Docker Compose")
    results = []
    with tempfile.TemporaryDirectory(prefix="sentinel-composition-") as directory:
        tmp = Path(directory)
        results.append(_initialization_case(tmp))
        results.append(_crash_transaction_case(tmp))
        results.append(_docker_case(
            tmp,
            name="postgres-healthy-and-restart",
            text=_compose_text(),
            timeout_seconds=45,
            verify_sql=True,
            restart=True,
        ))
        results.append(_recovery_case(
            tmp, name="postgres-stopped-and-recovered", action="stop"))
        results.append(_recovery_case(
            tmp, name="postgres-removed-and-recovered", action="remove"))
        results.append(_recovery_case(
            tmp, name="postgres-network-down-and-recovered", action="network-down"))
        if include_shared_image_removal:
            results.append(_recovery_case(
                tmp, name="postgres-image-deleted-and-repulled", action="image-delete"))
        results.append(_docker_case(
            tmp,
            name="postgres-health-never-ready",
            text=_compose_text(health="never"),
            timeout_seconds=3,
            expected_reason="POSTGRES_HEALTH_TIMEOUT",
        ))
        results.append(_docker_case(
            tmp,
            name="postgres-service-missing",
            text=_compose_text(service_name="different-service"),
            timeout_seconds=5,
            expected_reason="POSTGRES_START_FAILED",
        ))
    return {
        "schema": "sentinel.production-composition-live/1",
        "matrix_scenarios": _scenario_count(),
        "live_results": results,
        "all_pass": all(
            item["status"] in {"PASS", "EXPECTED_REFUSAL"} for item in results),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--include-shared-image-removal", action="store_true",
                        help="delete/repull shared PostgreSQL image; disposable daemons only")
    args = parser.parse_args(argv)
    try:
        result = run_live(include_shared_image_removal=args.include_shared_image_removal)
        if not result["all_pass"]:
            raise HarnessFailure("one or more live gates failed")
    except (HarnessFailure, OSError, subprocess.TimeoutExpired) as exc:
        result = {
            "schema": "sentinel.production-composition-live/1",
            "matrix_scenarios": _scenario_count(),
            "all_pass": False,
            "failure": f"{type(exc).__name__}: {exc}",
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        print(result["failure"], file=sys.stderr)
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
