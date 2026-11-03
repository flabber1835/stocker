"""Bounded GitHub-hosted capacity probe; no trading or input acquisition."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
from typing import Mapping

REPOSITORY = "flabber1835/stocker"
BRANCH = "refs/heads/codex/capital-risk-research"
ACTOR = "flabber1835"
FORBIDDEN_CREDENTIALS = (
    "ALPACA_API_KEY", "ALPACA_SECRET_KEY", "APCA_API_KEY_ID",
    "APCA_API_SECRET_KEY", "DATABASE_URL", "PGPASSWORD",
    "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "OPENAI_API_KEY",
)


def check_context(env: Mapping[str, str]) -> None:
    expected = {
        "GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": REPOSITORY,
        "GITHUB_REF": BRANCH, "GITHUB_ACTOR": ACTOR,
        "RUNNER_ENVIRONMENT": "github-hosted", "RUNNER_OS": "Linux",
    }
    for name, value in expected.items():
        if env.get(name) != value:
            raise ValueError("REFUSED_CONTEXT_" + name)
    if env.get("GITHUB_EVENT_NAME") not in {"push", "workflow_dispatch"}:
        raise ValueError("REFUSED_EVENT")
    for name in FORBIDDEN_CREDENTIALS:
        if env.get(name):
            raise ValueError("REFUSED_CREDENTIAL_" + name)
    if not re.fullmatch(r"[0-9a-f]{40}", env.get("GITHUB_SHA", "")):
        raise ValueError("REFUSED_SOURCE_SHA")


def validate_request(value: dict) -> None:
    if (set(value) != {"schema", "request_id", "stage", "protocol_sha256"}
            or value["schema"] != "research.capital-risk-request/1"
            or value["stage"] != "probe"
            or not isinstance(value["request_id"], str)
            or not re.fullmatch(r"[a-z0-9-]{1,80}", value["request_id"])
            or not isinstance(value["protocol_sha256"], str)
            or not re.fullmatch(r"[0-9a-f]{64}", value["protocol_sha256"])):
        raise ValueError("REFUSED_PROBE_REQUEST")


def admitted_output(workspace: Path, output: Path) -> Path:
    workspace = workspace.resolve()
    allowed = (workspace / "artifacts/capital-risk").resolve()
    output = output.resolve()
    if not allowed.is_relative_to(workspace) or not output.is_relative_to(allowed):
        raise ValueError("REFUSED_OUTPUT_PATH")
    if output.suffix != ".json":
        raise ValueError("REFUSED_OUTPUT_FORMAT")
    return output


def memory_bytes() -> dict[str, int]:
    fields = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        key, value = line.split(":", 1)
        if key in {"MemTotal", "MemAvailable"}:
            fields[key] = int(value.split()[0]) * 1024
    if set(fields) != {"MemTotal", "MemAvailable"}:
        raise ValueError("REFUSED_MEMORY_UNKNOWN")
    return fields


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    check_context(os.environ)
    request = json.loads(args.request.read_bytes())
    validate_request(request)
    output = admitted_output(Path(os.environ["GITHUB_WORKSPACE"]), args.output)
    memory = memory_bytes()
    disk = shutil.disk_usage(output.parent.parent.parent)
    cpus = os.cpu_count()
    if cpus is None or cpus < 2 or memory["MemAvailable"] < 4 * 1024**3:
        raise ValueError("REFUSED_CPU_OR_MEMORY_CAPACITY")
    if disk.free < 12 * 1024**3:
        raise ValueError("REFUSED_DISK_CAPACITY")
    docker = subprocess.run(
        ["docker", "version", "--format", "{{json .Server}}"],
        capture_output=True, text=True, timeout=20, check=True,
    )
    server = json.loads(docker.stdout)
    if server.get("Os") != "linux":
        raise ValueError("REFUSED_DOCKER_PLATFORM")
    result = dict(
        schema="research.capital-risk-capacity/1", status="PROBE_PASSED",
        utc=datetime.now(timezone.utc).isoformat(), request=request,
        source_commit=os.environ["GITHUB_SHA"], repository=REPOSITORY,
        ref=BRANCH, actor=ACTOR, runner_environment="github-hosted",
        cpu_count=cpus, memory=memory, disk_free_bytes=disk.free,
        python=platform.python_version(),
        docker={key: server.get(key) for key in ("Version", "Os", "Arch")},
        production_credentials_absent=True, market_data_acquired=False,
        replay_started=False, production_contacted=False,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf8")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
