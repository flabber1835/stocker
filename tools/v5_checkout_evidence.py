#!/usr/bin/env python3
"""Bind full-PIT acceptance to the event's exact synthetic merge result."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess


def evidence(*, event_name, event, expected_sha, repo, run_id, run_attempt):
    def git(*args):
        return subprocess.check_output(['git', '-C', str(repo), *args], text=True).strip()

    commit = git('rev-parse', 'HEAD')
    tree = git('rev-parse', 'HEAD^{tree}')
    parents = [line.split()[1] for line in git('cat-file', '-p', 'HEAD').splitlines()
               if line.startswith('parent ')]
    if commit != expected_sha:
        raise ValueError('checkout differs from event SHA')
    base = head = None
    if event_name == 'pull_request':
        pr = event['pull_request']
        base, head = pr['base']['sha'], pr['head']['sha']
        if parents != [base, head]:
            raise ValueError('checkout is not the event base/head synthetic merge')
        scope = 'PULL_REQUEST_MERGE'
    elif event_name == 'merge_group':
        group = event['merge_group']
        base, head = group['base_sha'], group['head_sha']
        ancestor = subprocess.run(['git', '-C', str(repo), 'merge-base',
                                   '--is-ancestor', base, commit], capture_output=True)
        if commit != head or len(parents) < 2 or ancestor.returncode != 0 or commit == base:
            raise ValueError('checkout differs from merge group result/base')
        scope = 'MERGE_GROUP'
    elif event_name == 'workflow_dispatch':
        scope = 'DIAGNOSTIC_COMMIT_ONLY'
    else:
        raise ValueError('unsupported full-PIT event')
    return dict(commit=commit, tree=tree, parents=parents, base=base, head=head,
                scope=scope, event_name=event_name, run_id=run_id, run_attempt=run_attempt)


def verify_current_pr(*, event, repo, commit):
    """A main/head update during the long replay invalidates its acceptance."""
    pr = event['pull_request']
    number = int(event['number'])
    refs = [f"refs/heads/{pr['base']['ref']}", f'refs/pull/{number}/head',
            f'refs/pull/{number}/merge']
    output = subprocess.check_output(['git', '-C', str(repo), 'ls-remote',
                                      'origin', *refs], text=True)
    actual = {ref: sha for sha, ref in (line.split() for line in output.splitlines())}
    expected = dict(zip(refs, [pr['base']['sha'], pr['head']['sha'], commit]))
    if actual != expected:
        raise ValueError('pull-request base/head/merge changed during full-PIT replay; rerun current merge')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--verify-current', action='store_true')
    args = parser.parse_args()
    event = json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text())
    result = evidence(event_name=os.environ['GITHUB_EVENT_NAME'], event=event,
        expected_sha=os.environ['GITHUB_SHA'], repo=Path.cwd(),
        run_id=os.environ['GITHUB_RUN_ID'], run_attempt=os.environ['GITHUB_RUN_ATTEMPT'])
    if args.verify_current:
        if json.loads(args.output.read_text()) != result:
            raise ValueError('checkout evidence changed during replay')
        if os.environ['GITHUB_EVENT_NAME'] == 'pull_request':
            verify_current_pr(event=event, repo=Path.cwd(), commit=result['commit'])
    else:
        args.output.write_text(json.dumps(result, indent=2) + '\n')


if __name__ == '__main__':
    main()
