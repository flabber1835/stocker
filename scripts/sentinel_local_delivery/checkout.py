#!/usr/bin/env python3
"""Stage exact routine Sentinel checkouts without materializing historical filings."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import subprocess


FILING_ARCHIVE = 'sec-filings'
CHECKOUT_PATTERNS = ('/*', f'!/{FILING_ARCHIVE}/')
FILING_ARCHIVE_ERROR = (
    'Historical SEC filings are present. Use the Sentinel host sparse checkout '
    'with patterns /* and !/sec-filings/.'
)


class CheckoutRefused(RuntimeError):
    pass


def has_filing_archive(worktree: Path) -> bool:
    # A file or a dangling symlink also occupies the excluded path.
    return os.path.lexists(worktree / FILING_ARCHIVE)


def _git(directory: Path, *args: str) -> str:
    env = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
    result = subprocess.run(
        ['git', '--no-optional-locks', '-C', str(directory), *args],
        text=True, capture_output=True, env=env, timeout=180,
    )
    if result.returncode:
        raise CheckoutRefused(result.stderr.strip() or f'git {args[0]} failed')
    return result.stdout.strip()


def check_worktree(worktree: Path) -> None:
    if not worktree.is_dir():
        raise CheckoutRefused('The worktree directory is unavailable.')
    if has_filing_archive(worktree):
        raise CheckoutRefused(FILING_ARCHIVE_ERROR)


def create_worktree(repository: Path, worktree: Path, *, branch: str, revision: str) -> None:
    if re.fullmatch(r'[0-9a-f]{40}', revision) is None:
        raise CheckoutRefused('Use the full verified commit SHA.')
    if os.path.lexists(worktree):
        raise CheckoutRefused('The new worktree path already exists.')
    worktree = worktree.resolve()
    if _git(repository, 'rev-parse', '--verify', revision + '^{commit}') != revision:
        raise CheckoutRefused('The verified commit is unavailable in this repository.')
    _git(repository, 'worktree', 'add', '--no-checkout', '-b', branch, '--', str(worktree), revision)
    _git(worktree, 'sparse-checkout', 'set', '--no-cone', *CHECKOUT_PATTERNS)
    _git(worktree, 'read-tree', '-mu', 'HEAD')
    check_worktree(worktree)
    if (_git(worktree, 'rev-parse', 'HEAD') != revision
            or _git(worktree, 'status', '--porcelain', '--untracked-files=all')):
        raise CheckoutRefused('The staged worktree differs from the verified revision.')


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    create = commands.add_parser('create', help='Stage an exact revision in a new sparse worktree')
    create.add_argument('--repository', type=Path, required=True)
    create.add_argument('--worktree', type=Path, required=True)
    create.add_argument('--branch', required=True)
    create.add_argument('--revision', required=True)
    check = commands.add_parser('check', help='Check an existing operational worktree')
    check.add_argument('--worktree', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'create':
            create_worktree(args.repository, args.worktree, branch=args.branch, revision=args.revision)
        else:
            check_worktree(args.worktree)
    except (CheckoutRefused, OSError, subprocess.TimeoutExpired) as exc:
        parser.exit(2, f'REFUSED: {exc}\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
