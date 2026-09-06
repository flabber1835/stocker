#!/usr/bin/env python3
"""Publish an immutable run-scoped research checkpoint with bounded push retries."""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import time

BRANCH = 'research/champion-certification-economic-integrity'


def git(repo: Path, *args: str, check: bool = True):
    return subprocess.run(['git', '-C', str(repo), *args], check=check, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input', required=True, type=Path)
    p.add_argument('--kind', required=True, choices=['audit', 'replay'])
    args = p.parse_args()
    workspace = Path(os.environ['GITHUB_WORKSPACE']).resolve()
    source = args.input.resolve()
    if not source.is_relative_to(workspace) or not source.is_dir() or not any(source.iterdir()):
        raise ValueError('publication source must be a populated workspace directory')
    run, attempt = os.environ['GITHUB_RUN_ID'], os.environ['GITHUB_RUN_ATTEMPT']
    if not run.isdigit() or not attempt.isdigit():
        raise ValueError('invalid run identity')
    repo = workspace / 'audit-src'
    relative = Path('research/champion-economic-integrity/security-truth/audit-v2') / f'{run}-{attempt}' / args.kind
    for retry in range(3):
        target = workspace / f'publish-truth-{args.kind}-{retry}'
        git(repo, 'fetch', 'origin', f'refs/heads/{BRANCH}')
        git(repo, 'worktree', 'add', '--detach', str(target), 'FETCH_HEAD')
        try:
            git(target, 'sparse-checkout', 'set', '--no-cone', '/' + str(relative.parent) + '/')
            destination = target / relative
            if destination.exists():
                raise RuntimeError('immutable checkpoint destination already exists')
            shutil.copytree(source, destination)
            git(target, 'add', str(relative))
            git(target, 'config', 'user.name', 'github-actions[bot]')
            git(target, 'config', 'user.email', '41898282+github-actions[bot]@users.noreply.github.com')
            git(target, 'commit', '-m', f'audit: retain factual type {args.kind} checkpoint {run}-{attempt}')
            result = git(target, 'push', 'origin', f'HEAD:refs/heads/{BRANCH}', check=False)
            if result.returncode == 0:
                commit = git(target, 'rev-parse', 'HEAD').stdout.strip()
                print(f'PUBLISHED kind={args.kind} commit={commit} path={relative}', flush=True)
                with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as handle:
                    handle.write(f'\nRetained {args.kind} checkpoint: `{commit}` / `{relative}`\n')
                return 0
            print(result.stderr, flush=True)
        finally:
            # This is a disposable publication worktree; the evidence source is separate.
            git(repo, 'worktree', 'remove', '--force', str(target))
        time.sleep(2)
    raise RuntimeError('checkpoint push failed after three fresh-head attempts; artifact remains available')


if __name__ == '__main__':
    raise SystemExit(main())
