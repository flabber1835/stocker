#!/usr/bin/env python3
"""Wait for one exact GitHub Actions check on one commit and require success."""
from __future__ import annotations

import argparse
import json
import os
import time
from urllib import error, parse, request

API = "https://api.github.com"
TERMINAL_SUCCESS = {"success"}


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
    matches.sort(key=lambda row: (row.get("started_at") or "", int(row.get("id") or 0)),
                 reverse=True)
    return matches[0]


def check_verdict(run: dict | None) -> str:
    if run is None:
        return "WAIT"
    status = run.get("status")
    if status != "completed":
        return "WAIT"
    conclusion = run.get("conclusion")
    return "PASS" if conclusion in TERMINAL_SUCCESS else "FAIL"


def fetch_check_runs(repository: str, sha: str, token: str) -> list[dict]:
    encoded_sha = parse.quote(sha, safe="")
    url = f"{API}/repos/{repository}/commits/{encoded_sha}/check-runs?per_page=100&filter=latest"
    req = request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "stocker-required-check-bridge",
    })
    try:
        with request.urlopen(req, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub check-runs query failed: HTTP {exc.code}: {detail}") from exc
    runs = payload.get("check_runs")
    if not isinstance(runs, list):
        raise RuntimeError("GitHub check-runs response did not contain check_runs")
    return runs


def require_check(repository: str, sha: str, name: str, token: str,
                  timeout_seconds: int, poll_seconds: int) -> dict:
    deadline = time.monotonic() + timeout_seconds
    last = None
    while True:
        run = select_check(fetch_check_runs(repository, sha, token), name)
        last = run
        verdict = check_verdict(run)
        if verdict == "PASS":
            return run
        if verdict == "FAIL":
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
    parser.add_argument("--token", default=os.environ.get("GITHUB_TOKEN"))
    parser.add_argument("--timeout-seconds", type=int, default=900)
    parser.add_argument("--poll-seconds", type=int, default=10)
    args = parser.parse_args()
    if not args.repository or not args.token:
        raise SystemExit("repository and GitHub token are required")
    run = require_check(
        args.repository, args.sha, args.name, args.token,
        args.timeout_seconds, args.poll_seconds)
    print(json.dumps({
        "schema": "stocker.required-check-bridge/1",
        "verdict": "PASS",
        "repository": args.repository,
        "sha": args.sha,
        "check": args.name,
        "check_run_id": run.get("id"),
        "conclusion": run.get("conclusion"),
        "html_url": run.get("html_url"),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
