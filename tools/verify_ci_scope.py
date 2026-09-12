#!/usr/bin/env python3
"""Fail-closed proof for exact-head execution and synthetic-tree reuse."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
from typing import Dict, Optional


SHA = re.compile(r"[0-9a-f]{40}")
SCOPES = {"exact-head", "synthetic-merge"}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=root, text=True, stderr=subprocess.STDOUT
    ).strip()


def require_sha(value: str, name: str) -> str:
    require(SHA.fullmatch(value) is not None, f"{name} is not an exact Git SHA")
    return value


def verify_scope(
    *,
    root: Path,
    scope: str,
    expected_head: str,
    expected_event_sha: str,
    expected_base: Optional[str] = None,
) -> Dict[str, object]:
    require(scope in SCOPES, f"unsupported CI scope: {scope}")
    head = require_sha(expected_head, "expected head")
    event_sha = require_sha(expected_event_sha, "expected event")
    tested_commit = require_sha(git(root, "rev-parse", "HEAD"), "tested commit")
    tested_tree = require_sha(git(root, "rev-parse", "HEAD^{tree}"), "tested tree")

    result: Dict[str, object] = {
        "schema": "sentinel.ci-scope-proof/1",
        "scope": scope,
        "tested_commit": tested_commit,
        "tested_tree": tested_tree,
        "full_execution_required": scope == "exact-head",
        "tree_evidence_reused": False,
    }
    if scope == "exact-head":
        require(tested_commit == head, "exact-head checkout differs from advertised PR head")
        return result

    base = require_sha(expected_base or "", "expected base")
    require(tested_commit == event_sha,
            "synthetic-merge checkout differs from advertised event SHA")
    parents = git(root, "rev-list", "--parents", "-n", "1", "HEAD").split()
    require(len(parents) == 3, "synthetic-merge checkout is not a two-parent commit")
    actual_base, actual_head = parents[1], parents[2]
    require(actual_base == base,
            "synthetic-merge first parent differs from advertised PR base")
    require(actual_head == head,
            "synthetic-merge second parent differs from advertised PR head")
    head_tree = require_sha(git(root, "rev-parse", "HEAD^2^{tree}"), "PR-head tree")
    require(tested_tree == head_tree,
            "synthetic merge changes the certified PR-head source tree")
    result.update({
        "base_parent": actual_base,
        "head_parent": actual_head,
        "head_tree": head_tree,
        "tree_evidence_reused": True,
    })
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--scope", choices=sorted(SCOPES), required=True)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--expected-event-sha", required=True)
    parser.add_argument("--expected-base")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = verify_scope(
            root=args.root,
            scope=args.scope,
            expected_head=args.expected_head,
            expected_event_sha=args.expected_event_sha,
            expected_base=args.expected_base,
        )
    except (AssertionError, subprocess.CalledProcessError) as exc:
        print(f"REFUSED: {exc}")
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
