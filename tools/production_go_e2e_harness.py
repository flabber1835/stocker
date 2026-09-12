#!/usr/bin/env python3
"""True process/container/database E2E for the supported production GO command."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

import production_go_e2e_support as e2e

ROOT = Path(__file__).resolve().parents[1]


def _stream_go(work: Path, env: dict[str, str], transcript: Path) -> int:
    process = subprocess.Popen(
        ["bash", "scripts/sentinel-go-validate.sh", "--local-full-certification",
         "--target", e2e.TARGET],
        cwd=str(work), env=env, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=1)
    with transcript.open("w", encoding="utf-8") as handle:
        assert process.stdout is not None
        for line in process.stdout:
            print(line, end="", flush=True)
            handle.write(line)
            handle.flush()
    return int(process.wait())


def _prebuild(work: Path, commit: str) -> tuple[str, str]:
    runtime = f"sentinel-go-runtime:{commit}"
    test = f"sentinel-go-test:{commit}"
    e2e.run([
        "docker", "build", "--network", "host", "--build-arg",
        f"SOURCE_GIT_SHA={commit}", "-t", runtime,
        "-f", "Dockerfile.sentinel", ".",
    ], cwd=work, capture=False)
    e2e.run([
        "docker", "build", "--network", "host", "--build-arg",
        f"SENTINEL_IMAGE={runtime}", "--build-arg", f"SOURCE_GIT_SHA={commit}",
        "-t", test, "-f", "Dockerfile.sentinel-test", ".",
    ], cwd=work, capture=False)
    runtime_id = e2e.digest_image(work, runtime)
    test_id = e2e.digest_image(work, test)
    e2e.run(["docker", "tag", runtime_id, "sentinel:latest"], cwd=work)
    return runtime_id, test_id


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--keep-workdir", action="store_true")
    args = parser.parse_args(argv)

    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    original_commit = e2e.git(ROOT, "rev-parse", "HEAD")
    if e2e.HEX40.fullmatch(original_commit) is None:
        raise e2e.E2ERefused("tested tree has no exact HEAD")

    temp = Path(tempfile.mkdtemp(prefix="sentinel-go-e2e-"))
    origin, work, backup = temp / "origin.git", temp / "work", temp / "backup"
    (backup / "wal").mkdir(parents=True)
    (backup / "base").mkdir(parents=True)
    (backup / "wal").chmod(0o777)
    (backup / "base").chmod(0o777)

    sharadar_proc = alpaca_proc = None
    sharadar_handle = alpaca_handle = None
    transcript = output.parent / "go-transcript.txt"

    try:
        e2e.run(["git", "init", "--bare", str(origin)], cwd=ROOT)
        # Actions checks PR heads out shallow and detached. The isolated origin
        # is intentionally local, so admit that shallow boundary and make its
        # advertised HEAD explicit before cloning the clean production main.
        e2e.run(["git", "--git-dir", str(origin), "config",
                 "receive.shallowUpdate", "true"], cwd=ROOT)
        e2e.run(["git", "push", "--force", str(origin),
                 f"{original_commit}:refs/heads/main"], cwd=ROOT)
        e2e.run(["git", "--git-dir", str(origin), "symbolic-ref", "HEAD",
                 "refs/heads/main"], cwd=ROOT)
        e2e.run(["git", "clone", str(origin), str(work)], cwd=ROOT)
        if e2e.git(work, "rev-parse", "HEAD") != original_commit:
            raise e2e.E2ERefused("isolated main does not equal tested commit")
        if e2e.git(work, "branch", "--show-current") != "main":
            raise e2e.E2ERefused("isolated tested tree is not main")
        if e2e.git(work, "status", "--porcelain", "--untracked-files=all"):
            raise e2e.E2ERefused("isolated tested tree is not clean")

        base_env = dict(os.environ)
        base_env["PYTHONPATH"] = os.pathsep.join(
            (str(work), str(work / "shared")))
        base_env.setdefault("SENTINEL_HOST_PYTHON", "python")

        runtime_id, _test_id = _prebuild(work, original_commit)
        e2e.run([
            "docker", "pull",
            "postgres:16@sha256:95206741a5b214807675e14165369d05b93a9cf692223b616d07cca227e74b0b",
        ], cwd=work, capture=False)

        sharadar_port = e2e.free_port()
        file_values = e2e.write_env(
            work / ".env", backup=backup,
            ndl_base=f"http://127.0.0.1:{sharadar_port}/api/v3/datatables/SHARADAR")
        env = {**base_env, **file_values}

        e2e.run(["bash", "scripts/sentinel-compose.sh", "--initialize-backup"],
                cwd=work, env=env)
        e2e.run(["bash", "scripts/sentinel-compose.sh", "--run", "up", "-d",
                 "sentinel-postgres"], cwd=work, env=env)
        e2e.wait_postgres(work, env)

        gateway = (e2e.run([
            "docker", "network", "inspect", "sentinel_default", "--format",
            "{{(index .IPAM.Config 0).Gateway}}",
        ], cwd=work, env=env).stdout or "").strip()
        if not gateway:
            raise e2e.E2ERefused("Sentinel Compose gateway is unavailable")
        file_values = e2e.write_env(
            work / ".env", backup=backup,
            ndl_base=f"http://{gateway}:{sharadar_port}/api/v3/datatables/SHARADAR")
        env = {**base_env, **file_values}

        target = e2e.current_source_final_target(work, env)
        password = e2e.fixture_value("postgres")
        dsn = f"postgresql://sentinel:{password}@127.0.0.1:5435/sentinel"
        seed_env = {
            **env, "SENTINEL_DATABASE_URL": dsn,
            "SENTINEL_GIT_COMMIT": original_commit,
            "SENTINEL_RUNTIME_IMAGE_DIGEST": runtime_id,
            "SENTINEL_FEED_AUTHORIZED": "CLEAN_HEAD_IMAGE_V1",
            "SENTINEL_FEED_GIT_COMMIT": original_commit,
            "SENTINEL_FEED_RUNTIME_IMAGE_DIGEST": runtime_id,
            "SENTINEL_IMAGE_SOURCE_REVISION": original_commit,
        }
        e2e.run([
            seed_env.get("SENTINEL_HOST_PYTHON", "python"),
            "tools/production_go_e2e_fixture.py", "seed",
            "--target", target, "--dsn", dsn,
            "--commit", original_commit, "--image-id", runtime_id,
        ], cwd=work, env=seed_env, capture=False)
        e2e.run(["bash", "scripts/sentinel-base-backup.sh"],
                cwd=work, env=env, capture=False)

        sharadar_handle = (output.parent / "sharadar-server.txt").open(
            "w", encoding="utf-8")
        sharadar_proc = subprocess.Popen(
            [env.get("SENTINEL_HOST_PYTHON", "python"),
             "tools/production_go_e2e_fixture.py", "serve-sharadar",
             "--port", str(sharadar_port), "--target", target],
            cwd=str(work), env=env, stdout=sharadar_handle,
            stderr=subprocess.STDOUT, text=True)

        ca_crt, alpaca_crt, alpaca_key = e2e.openssl_alpaca_certificate(temp, work)
        ca_bundle = temp / "ca-bundle.pem"
        system_bundle = Path("/etc/ssl/certs/ca-certificates.crt")
        ca_bundle.write_bytes(system_bundle.read_bytes() + b"\n" + ca_crt.read_bytes())
        env["SSL_CERT_FILE"] = str(ca_bundle)

        with e2e.hosts_mapping(work):
            alpaca_handle = (output.parent / "alpaca-server.txt").open(
                "w", encoding="utf-8")
            alpaca_proc = subprocess.Popen(
                ["sudo", "-E", env.get("SENTINEL_HOST_PYTHON", "python"),
                 "tools/production_go_e2e_fixture.py", "serve-alpaca",
                 "--port", "443", "--cert", str(alpaca_crt),
                 "--key", str(alpaca_key)],
                cwd=str(work), env=env, stdout=alpaca_handle,
                stderr=subprocess.STDOUT, text=True)
            time.sleep(1)
            if sharadar_proc.poll() is not None or alpaca_proc.poll() is not None:
                raise e2e.E2ERefused("external protocol substitute exited before GO")

            rc = _stream_go(work, env, transcript)
            text = transcript.read_text(encoding="utf-8")
            if rc != 0:
                raise e2e.E2ERefused(f"production GO entry returned {rc}")
            e2e.validate_lifecycle_transcript(text)
            authority = e2e.verify_final_authority(
                work=work, commit=original_commit, expected_target=target)

            evidence_dir = output.parent / "retained"
            evidence_dir.mkdir(parents=True, exist_ok=True)
            for relative in (
                Path("artifacts/sentinel/deployment/validated-artifact-handoff.json"),
                Path("artifacts/sentinel/deployment/validated-runtime.env"),
                Path("artifacts/sentinel/go-validation/stable-certification-ordinary-runtime.json"),
            ):
                source = work / relative
                shutil.copy2(source, evidence_dir / source.name)

        result = {
            "schema": "sentinel.production-go-e2e/1", "all_pass": True,
            "operator_entry": "bash scripts/sentinel-go-validate.sh",
            "operator_arguments": ["--local-full-certification", "--target", e2e.TARGET],
            "real_postgresql": True, "real_docker_compose": True,
            "external_substitutes": ["sharadar", "alpaca-paper-account"],
            "lifecycle_markers": list(e2e.LIFECYCLE_MARKERS),
            "lifecycle_markers_observed": len(e2e.LIFECYCLE_MARKERS),
            **authority,
        }
        output.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n",
                          encoding="utf-8")
        print("PRODUCTION_GO_E2E=PASS", flush=True)
        return 0
    except BaseException as exc:
        output.write_text(json.dumps({
            "schema": "sentinel.production-go-e2e/1", "all_pass": False,
            "error_type": type(exc).__name__, "error": str(exc)[-4000:],
            "git_commit": original_commit,
        }, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        raise
    finally:
        for process in (alpaca_proc, sharadar_proc):
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
        for handle in (alpaca_handle, sharadar_handle):
            if handle is not None:
                handle.close()
        if work.exists():
            e2e.run(
                ["bash", "scripts/sentinel-compose.sh", "--run", "down", "-v",
                 "--remove-orphans"], cwd=work,
                env=({**os.environ, **e2e.parse_env_for_cleanup(work / ".env")}
                     if (work / ".env").exists() else os.environ),
                check=False)
        if args.keep_workdir:
            print(f"PRODUCTION_GO_E2E_WORKDIR={temp}", flush=True)
        else:
            shutil.rmtree(temp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
