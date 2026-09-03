#!/usr/bin/env python3
"""Real-container regression for the GO cold-start/marker protocol.

This is CI-only destructive work inside a unique Compose project. It never uses
the production ``sentinel`` project or its volumes.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Mapping

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import sentinel_deployment_bootstrap as deploy_bootstrap  # noqa: E402
import sentinel_go_24x7_entry as source_final  # noqa: E402
import sentinel_go_probe_contract as contract  # noqa: E402
import sentinel_go_readonly_data_preflight as preflight  # noqa: E402
import sentinel_go_validate as go  # noqa: E402


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def _run_probe(runner, compose_args, env: Mapping[str, str], code: str,
               *, database_url: str | None = None):
    command = [
        "docker", "compose", *compose_args, "--profile", "cli", "run",
        "--rm", "-T", "--no-deps",
    ]
    if database_url is not None:
        command.extend(["--env", "SENTINEL_DATABASE_URL=" + database_url])
    command.extend(["--entrypoint", "python", "sentinel", "-c", code])
    return runner.run(command, env=env)


def _preparation_failure(completed):
    matches = []
    for stream in (completed.stdout or "", completed.stderr or ""):
        for line in stream.splitlines():
            if not line.startswith(contract.PREPARATION_FAILURE_MARKER):
                continue
            try:
                value = json.loads(
                    line[len(contract.PREPARATION_FAILURE_MARKER):])
            except ValueError:
                return None
            if not isinstance(value, dict):
                return None
            matches.append(value)
    return matches[0] if len(matches) == 1 else None


def main(argv=None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    runtime_image = args[0] if args else "sentinel:latest"
    project = "sentinel-go-probe-ci-%d" % os.getpid()
    compose_args = ["-p", project, "-f", "docker-compose.sentinel.yml"]
    env = dict(os.environ)
    env.update({
        "SENTINEL_POSTGRES_PASSWORD": "ci-probe-database-password",
        "SENTINEL_PUBLICATION_RECEIPT_KEY": "ci-probe-publication-receipt-key",
        "SENTINEL_BACKUP_DIR": "/ci/unused-backup",
        "SHARADAR_API_KEY": "ci-probe-sharadar-key",
        "SENTINEL_RUNTIME_IMAGE_REF": runtime_image,
        "SENTINEL_GO_POSTGRES_START_TIMEOUT_SECONDS": "120",
    })
    runner = go.CommandRunner()
    prefix = ["docker", "compose", *compose_args]

    def cleanup() -> None:
        subprocess.run(
            prefix + ["down", "-v", "--remove-orphans"],
            cwd=str(ROOT), env=env, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, check=False)

    cleanup()
    try:
        failure = contract.ensure_postgres_ready(
            runner, env=env, compose_args=compose_args)
        _require(failure is None, "cold-start PostgreSQL helper did not pass")

        identity = runner.run(prefix + [
            "--profile", "cli", "run", "--rm", "-T", "--no-deps",
            "--entrypoint", "sh", "sentinel", "-ceu",
            "test \"$(id -u)\" = 10001; test \"$(id -g)\" = 10001",
        ], env=env)
        _require(identity.returncode == 0,
                 "ordinary Sentinel probe did not run as uid/gid 10001")

        empty = _run_probe(
            runner, compose_args, env, preflight._READ_ONLY_CODE)
        report = preflight._payload(empty)
        _require(empty.returncode == 0, "empty-DB read-only probe crashed")
        _require(report is not None, "empty-DB read-only probe emitted no marker")
        _require(report.get("status") == "RECOVERY_REQUIRED",
                 "empty database was not typed as recovery-required")
        _require(report.get("reason_code") == "CORPUS_SCHEMA_NOT_INSTALLED",
                 "empty database recovery reason changed")

        stopped = runner.run(prefix + ["stop", contract.POSTGRES_SERVICE], env=env)
        _require(stopped.returncode == 0, "could not stop probe PostgreSQL")
        unavailable = _run_probe(
            runner, compose_args, env, preflight._READ_ONLY_CODE)
        unavailable_report = preflight._payload(unavailable)
        _require(unavailable.returncode == 0,
                 "stopped-DB child escaped the structured failure envelope")
        _require(unavailable_report is not None,
                 "stopped-DB child emitted no structured marker")
        _require(unavailable_report.get("status") == "REFUSED",
                 "stopped database did not refuse")
        _require(unavailable_report.get("reason_code") == "DATABASE_CONNECT_UNAVAILABLE",
                 "stopped database did not retain its causal reason")

        failure = contract.ensure_postgres_ready(
            runner, env=env, compose_args=compose_args)
        _require(failure is None, "stopped PostgreSQL did not recover to healthy")

        broken_code = preflight._READ_ONLY_CODE.replace(
            "from sentinel.feed import (",
            "from sentinel_missing_for_go_probe import (", 1)
        broken = _run_probe(runner, compose_args, env, broken_code)
        broken_report = preflight._payload(broken)
        _require(broken.returncode == 0,
                 "runtime import failure escaped the structured envelope")
        _require(broken_report is not None,
                 "runtime import failure emitted no marker")
        _require(broken_report.get("reason_code") == "RUNTIME_IMPORT_UNAVAILABLE",
                 "runtime import failure lost its causal reason")

        bad = _run_probe(
            runner, compose_args, env, preflight._READ_ONLY_CODE,
            database_url=(
                "postgresql://sentinel:ci-intentionally-wrong@"
                "sentinel-postgres:5432/sentinel"))
        bad_report = preflight._payload(bad)
        _require(bad.returncode == 0,
                 "bad-auth child escaped the structured failure envelope")
        _require(bad_report is not None,
                 "bad-auth child emitted no marker")
        _require(bad_report.get("reason_code") == "DATABASE_CONNECT_UNAVAILABLE",
                 "bad-auth failure lost its causal reason")
        marker_text = bad.stdout or ""
        _require("ci-intentionally-wrong" not in marker_text,
                 "bad-auth marker leaked the synthetic password")
        _require("postgresql://" not in marker_text,
                 "bad-auth marker leaked a database URL")

        mutable_import_code = source_final._PREPARATION_CODE.replace(
            "from sentinel import backup_guard, schema",
            "from sentinel_missing_for_go_probe import backup_guard, schema", 1)
        mutable_import = _run_probe(
            runner, compose_args, env, mutable_import_code)
        mutable_import_report = _preparation_failure(mutable_import)
        _require(mutable_import.returncode != 0,
                 "24x7 import failure did not fail the child")
        _require(mutable_import_report is not None,
                 "24x7 import failure emitted no preparation marker")
        _require(
            mutable_import_report.get("reason_code")
            == "PREPARATION_RUNTIME_IMPORT_FAILURE",
            "24x7 import failure lost its causal reason")

        mutable_bad = _run_probe(
            runner, compose_args, env, source_final._PREPARATION_CODE,
            database_url=(
                "postgresql://sentinel:ci-24x7-intentionally-wrong@"
                "sentinel-postgres:5432/sentinel"))
        mutable_bad_report = _preparation_failure(mutable_bad)
        _require(mutable_bad.returncode != 0,
                 "24x7 bad-auth failure did not fail the child")
        _require(mutable_bad_report is not None,
                 "24x7 bad-auth failure emitted no preparation marker")
        _require(
            mutable_bad_report.get("reason_code")
            == "PREPARATION_DATABASE_CONNECT_FAILURE",
            "24x7 bad-auth failure lost its causal reason")
        mutable_marker_text = mutable_bad.stdout or ""
        _require("ci-24x7-intentionally-wrong" not in mutable_marker_text,
                 "24x7 bad-auth marker leaked the synthetic password")
        _require("postgresql://" not in mutable_marker_text,
                 "24x7 bad-auth marker leaked a database URL")

        original_compose_args = deploy_bootstrap._compose_args
        original_backup_target = deploy_bootstrap._require_backup_target
        deploy_bootstrap._compose_args = lambda _env: compose_args
        deploy_bootstrap._require_backup_target = lambda _env: None
        try:
            state = deploy_bootstrap._receipt_ancestry(env)
            _require(
                state == deploy_bootstrap.SAFE_FRESH_DATABASE,
                "fresh database was not safe for first-install receipt authority")

            # The generation guard must own the same advisory lock canonical
            # publication uses. A second publisher-shaped lock attempt must fail
            # for the whole yielded ancestry interval.
            with deploy_bootstrap._receipt_ancestry_guard(env) as locked_state:
                _require(
                    locked_state == deploy_bootstrap.SAFE_FRESH_DATABASE,
                    "locked fresh ancestry changed classification")
                competing = deploy_bootstrap._psql(
                    env, compose_args,
                    "SELECT pg_try_advisory_lock(%d)::int"
                    % deploy_bootstrap.CORPUS_LOCK_KEY)
                _require(
                    competing == "0",
                    "receipt bootstrap did not exclude canonical publication")
            released = deploy_bootstrap._psql(
                env, compose_args,
                "SELECT pg_try_advisory_lock(%d)::int"
                % deploy_bootstrap.CORPUS_LOCK_KEY)
            _require(
                released == "1",
                "receipt bootstrap did not release publication authority")

            deploy_bootstrap._psql(
                env, compose_args,
                "CREATE TABLE sentinel_corpus_publications (version BIGINT PRIMARY KEY);"
                " INSERT INTO sentinel_corpus_publications(version) VALUES (7)")
            try:
                deploy_bootstrap._receipt_ancestry(env)
            except deploy_bootstrap.BootstrapRefused as exc:
                _require(
                    "cannot distinguish a verified pre-receipt database" in str(exc),
                    "ambiguous 1:0:0 ancestry refused for the wrong reason")
            else:
                raise RuntimeError(
                    "publication history without receipt authority was grandfathered")

            deploy_bootstrap._psql(
                env, compose_args,
                "CREATE TABLE sentinel_publication_validation_policy ("
                "id BOOLEAN PRIMARY KEY, required_after_version BIGINT NOT NULL);"
                " INSERT INTO sentinel_publication_validation_policy"
                "(id,required_after_version) VALUES (TRUE,7);"
                " CREATE TABLE sentinel_publication_validation_receipts ("
                "publication_version BIGINT PRIMARY KEY)")
            state = deploy_bootstrap._receipt_ancestry(env)
            _require(
                state == deploy_bootstrap.SAFE_RECEIPT_POLICY_WITHOUT_RECEIPTS,
                "empty receipt-policy era was not recognized")

            deploy_bootstrap._psql(
                env, compose_args,
                "INSERT INTO sentinel_publication_validation_receipts"
                "(publication_version) VALUES (8)")
            state = deploy_bootstrap._receipt_ancestry(env)
            _require(
                state == deploy_bootstrap.AUTHENTICATED_RECEIPTS_EXIST,
                "authenticated receipt ancestry did not fence key rotation")
        finally:
            deploy_bootstrap._compose_args = original_compose_args
            deploy_bootstrap._require_backup_target = original_backup_target

        print("GO_PROBE_RUNTIME_INTEGRATION_PASS")
        return 0
    finally:
        cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
