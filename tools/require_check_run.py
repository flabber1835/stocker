#!/usr/bin/env python3
"""Require one exact GitHub Actions check from one exact workflow and source SHA."""
from __future__ import annotations

import argparse
import json
import os
import re
import time
from typing import Callable
from urllib import error, parse, request

API = "https://api.github.com"
TERMINAL_SUCCESS = {"success"}
_ACTION_JOB = re.compile(r"/actions/runs/(\d+)/job/(\d+)(?:$|[/?#])")


def select_check(check_runs: object, name: str) -> dict | None:
    if not isinstance(check_runs, list):
        raise RuntimeError("GitHub check-runs response is malformed")
    matches = []
    for run in check_runs:
        if not isinstance(run, dict) or run.get("name") != name:
            continue
        app = run.get("app") or {}
        if app.get("slug") != "github-actions":
            continue
        matches.append(run)
    if not matches:
        return None
    # Check-run ids are monotonic. A newly queued rerun can have started_at=null,
    # so timestamps would incorrectly prefer an older completed success.
    matches.sort(key=lambda row: int(row.get("id") or 0), reverse=True)
    return matches[0]


def check_verdict(run: dict | None) -> str:
    if run is None:
        return "WAIT"
    status = run.get("status")
    if status != "completed":
        return "WAIT"
    conclusion = run.get("conclusion")
    return "PASS" if conclusion in TERMINAL_SUCCESS else "FAIL"


def _api_json(repository: str, suffix: str, token: str) -> object:
    url = f"{API}/repos/{repository}/{suffix.lstrip('/')}"
    req = request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "stocker-required-check-bridge",
    })
    try:
        with request.urlopen(req, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"GitHub API query failed: HTTP {exc.code}: {detail}") from exc


def fetch_check_runs(repository: str, sha: str, name: str, token: str) -> list[dict]:
    encoded_sha = parse.quote(sha, safe="")
    query = parse.urlencode({
        "check_name": name,
        "filter": "latest",
        "per_page": 100,
    })
    payload = _api_json(
        repository,
        f"commits/{encoded_sha}/check-runs?{query}",
        token,
    )
    if not isinstance(payload, dict):
        raise RuntimeError("GitHub check-runs response is malformed")
    runs = payload.get("check_runs")
    if not isinstance(runs, list):
        raise RuntimeError("GitHub check-runs response did not contain check_runs")
    return runs


def action_run_and_job_ids(check_run: dict) -> tuple[int, int]:
    details = check_run.get("details_url") or check_run.get("html_url") or ""
    match = _ACTION_JOB.search(str(details))
    if match is None:
        raise RuntimeError(
            "required GitHub Actions check does not expose an Actions run/job URL")
    return int(match.group(1)), int(match.group(2))


def verify_workflow_origin(
    repository: str,
    check_run: dict,
    expected_workflow: str,
    expected_sha: str,
    token: str,
    fetch_json: Callable[[str, str, str], object] | None = None,
) -> dict:
    fetcher = fetch_json or _api_json
    attached_sha = check_run.get("head_sha")
    if attached_sha != expected_sha:
        raise RuntimeError(
            f"required check is attached to {attached_sha}, expected {expected_sha}")
    url_run_id, job_id = action_run_and_job_ids(check_run)
    job = fetcher(repository, f"actions/jobs/{job_id}", token)
    if not isinstance(job, dict):
        raise RuntimeError("GitHub Actions job response is malformed")
    job_run_id = job.get("run_id")
    if not isinstance(job_run_id, int) or job_run_id != url_run_id:
        raise RuntimeError(
            f"required check Actions run identity disagrees: url={url_run_id} job={job_run_id}")
    job_sha = job.get("head_sha")
    if job_sha is not None and job_sha != expected_sha:
        raise RuntimeError(
            f"required check job is attached to {job_sha}, expected {expected_sha}")

    workflow_run = fetcher(repository, f"actions/runs/{job_run_id}", token)
    if not isinstance(workflow_run, dict):
        raise RuntimeError("GitHub Actions workflow-run response is malformed")
    path = workflow_run.get("path")
    if path != expected_workflow:
        raise RuntimeError(
            f"required check came from workflow {path!r}, expected {expected_workflow!r}")
    workflow_sha = workflow_run.get("head_sha")
    if workflow_sha != expected_sha:
        raise RuntimeError(
            f"required workflow run is attached to {workflow_sha}, expected {expected_sha}")
    return {
        "workflow": path,
        "workflow_run_id": job_run_id,
        "job_id": job_id,
        "head_sha": workflow_sha,
    }


def require_check(repository: str, sha: str, name: str, workflow: str, token: str,
                  timeout_seconds: int, poll_seconds: int) -> tuple[dict, dict]:
    deadline = time.monotonic() + timeout_seconds
    last = None
    while True:
        run = select_check(fetch_check_runs(repository, sha, name, token), name)
        last = run
        verdict = check_verdict(run)
        if run is not None and verdict != "WAIT":
            # Terminal status guarantees the job/run metadata has settled enough
            # to authenticate workflow origin without racing job creation.
            origin = verify_workflow_origin(
                repository, run, workflow, sha, token)
            if verdict == "PASS":
                return run, origin
            raise RuntimeError(
                f"required check {name!r} failed on {sha}: "
                f"conclusion={run.get('conclusion')} url={run.get('html_url')}")
        if time.monotonic() >= deadline:
            state = "missing" if last is None else f"status={last.get('status')}"
            raise RuntimeError(
                f"timed out waiting for required check {name!r} on {sha}: {state}")
        time.sleep(poll_seconds)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY"))
    parser.add_argument("--sha", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--workflow", required=True)
    parser.add_argument("--token", default=os.environ.get("GITHUB_TOKEN"))
    parser.add_argument("--timeout-seconds", type=int, default=900)
    parser.add_argument("--poll-seconds", type=int, default=10)
    args = parser.parse_args()
    if not args.repository or not args.token:
        raise SystemExit("repository and GitHub token are required")
    run, origin = require_check(
        args.repository, args.sha, args.name, args.workflow, args.token,
        args.timeout_seconds, args.poll_seconds)
    print(json.dumps({
        "schema": "stocker.required-check-bridge/2",
        "verdict": "PASS",
        "repository": args.repository,
        "check_suite_sha": args.sha,
        "check": args.name,
        "check_run_id": run.get("id"),
        "conclusion": run.get("conclusion"),
        "html_url": run.get("html_url"),
        **origin,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
