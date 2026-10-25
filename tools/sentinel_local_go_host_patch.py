"""One owner-approved host-only repair over an unchanged signed PAPER runtime.

Invoked only by an operation-scoped interpreter launcher at the original GO
entry. This loader changes four argument handoffs, never a validator or result.
The separate manifest identifies local host code without claiming CI coverage.
"""
from __future__ import annotations

import ast
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

BASE = 'dda0195ce0374c4bb4a9c322937ba6dd0819b34f'
IMAGE = 'ghcr.io/flabber1835/stocker/sentinel@sha256:5280f246bc1ca4115c509f4c981e4588c83a6f98ccb0faf94df11868b168b2e0'
BASE_FILES = {
    'scripts/sentinel_go_validate.py': '66cd2d8493e7e722bb5fad95003a3e969e9e56a7ed88b863d2b4bc07f60cca79',
    'scripts/sentinel_go_validate_entry.py': 'f1155a3e73d2cd8abf15150f939f171c3cbbd6c382a27b950980cc7e50f57c8e',
}
FUNCTIONS = ('probe_active_wealth_parity', 'probe_sharadar_readiness',
             'probe_database_financial_health')
KEY = 'SENTINEL_TEST_IMAGE_DIGEST'
ALLOWED = frozenset({*BASE_FILES,
    'docs/go-probe-artifact-identity.md', 'docs/sentinel-deployment.md',
    'tests/sentinel/test_go_probe_artifact_identity.py',
    'tests/scripts/test_sentinel_go_validate.py',
    'tools/sentinel_local_go_host_patch.py',
    'tests/sentinel/test_local_go_host_patch.py'})


class Refused(RuntimeError):
    pass


def require(value, reason):
    if not value:
        raise Refused(reason)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _dump(node):
    return ast.dump(node, include_attributes=False)


def reviewed_definitions(old_go, old_entry, new_go, new_entry):
    """Whole-module proof: only the four documented argument additions differ."""
    require(sha(old_go) == BASE_FILES['scripts/sentinel_go_validate.py']
        and sha(old_entry) == BASE_FILES['scripts/sentinel_go_validate_entry.py'],
        'HOST_PATCH_BASE_BYTES_CHANGED')
    original = ast.parse(old_go)
    candidate = ast.parse(new_go)
    normalized = deepcopy(candidate)
    selected = []
    for name in FUNCTIONS:
        nodes = [n for n in normalized.body if isinstance(n, ast.FunctionDef) and n.name == name]
        require(len(nodes) == 1, 'HOST_PATCH_FUNCTION_CHANGED')
        removals = 0
        for node in ast.walk(nodes[0]):
            if not isinstance(node, ast.List):
                continue
            indices = [i for i in range(1, len(node.elts))
                if isinstance(node.elts[i], ast.Constant) and node.elts[i].value == KEY
                and isinstance(node.elts[i-1], ast.Constant) and node.elts[i-1].value == '--env']
            require(len(indices) <= 1, 'HOST_PATCH_ARGUMENT_AMBIGUOUS')
            if indices:
                index = indices[0]
                del node.elts[index-1:index+1]
                removals += 1
        require(removals == 1, 'HOST_PATCH_ARGUMENT_CHANGED')
        selected.extend(n for n in candidate.body if isinstance(n, ast.FunctionDef) and n.name == name)
    require(_dump(original) == _dump(normalized), 'HOST_PATCH_NEIGHBOR_CHANGED')
    entry = ast.parse(new_entry)
    assignments = [n for n in entry.body if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == '_FEED_ENV_KEYS' for t in n.targets)]
    require(len(assignments) == 1 and isinstance(assignments[0].value, ast.Tuple),
        'HOST_PATCH_FORWARDING_TUPLE_CHANGED')
    forwarded = ast.literal_eval(assignments[0].value)
    require(forwarded.count(KEY) == 1, 'HOST_PATCH_FORWARDING_KEY_CHANGED')
    assignments[0].value.elts = [n for n in assignments[0].value.elts
        if not isinstance(n, ast.Constant) or n.value != KEY]
    require(_dump(ast.parse(old_entry)) == _dump(entry), 'HOST_PATCH_ENTRY_NEIGHBOR_CHANGED')
    return ast.Module(body=selected, type_ignores=[]), forwarded


def install(go, entry, *, old_go, old_entry, new_go, new_entry, filename):
    definitions, forwarded = reviewed_definitions(old_go, old_entry, new_go, new_entry)
    exec(compile(definitions, filename, 'exec'), go.__dict__)
    entry._FEED_ENV_KEYS = forwarded


def _document(path):
    def unique(items):
        result = {}
        for key, value in items:
            require(key not in result, 'HOST_PATCH_DUPLICATE_KEY')
            result[key] = value
        return result
    return json.loads(Path(path).read_bytes(), object_pairs_hook=unique)


def _git(root, *args):
    return subprocess.run(['git', '--no-optional-locks', '-C', str(root), *args],
        capture_output=True, text=True, check=True, timeout=30).stdout.strip()


def verify(manifest):
    require(manifest.get('schema') == 'sentinel.local-go-host-patch/1'
        and manifest.get('authority_effect') == 'NONE', 'HOST_PATCH_MANIFEST_CHANGED')
    source, deployed = Path(manifest['source']), Path(manifest['deployment'])
    require(source.is_absolute() and deployed.is_absolute() and source != deployed,
        'HOST_PATCH_ROOTS_CHANGED')
    require(_git(deployed, 'rev-parse', 'HEAD') == BASE
        and not _git(deployed, 'status', '--porcelain', '--untracked-files=no'),
        'HOST_PATCH_INSTALLED_SOURCE_CHANGED')
    commit = manifest['host_patch_commit']
    require(re.fullmatch('[0-9a-f]{40}', commit)
        and _git(source, 'rev-parse', 'HEAD') == commit
        and not _git(source, 'status', '--porcelain', '--untracked-files=no')
        and _git(source, 'merge-base', BASE, commit) == BASE, 'HOST_PATCH_SOURCE_CHANGED')
    changed = set(_git(source, 'diff', '--name-only', BASE, commit).splitlines())
    require(set(BASE_FILES) <= changed <= ALLOWED, 'HOST_PATCH_DELTA_CHANGED')
    require(sha(Path(__file__).read_bytes()) == manifest['loader_sha256']
        == sha((source/'tools/sentinel_local_go_host_patch.py').read_bytes()), 'HOST_PATCH_LOADER_CHANGED')
    receipt = Path(manifest['installation_receipt'])
    require(sha(receipt.read_bytes()) == manifest['installation_sha256'], 'HOST_PATCH_RECEIPT_CHANGED')
    recorded = _document(receipt)
    require(recorded.get('schema') == 'sentinel.installation-receipt/1'
        and recorded.get('git_commit') == BASE and recorded.get('runtime_image') == IMAGE
        and recorded.get('test_image') == IMAGE and recorded.get('installation_state') == 'INSTALLED'
        and recorded.get('activation_state') == 'FENCED', 'HOST_PATCH_RUNTIME_CHANGED')
    require(sha((deployed/'.env').read_bytes()) == manifest['environment_sha256'],
        'HOST_PATCH_CONFIGURATION_CHANGED')
    require(len(manifest['qualification']) >= 2, 'HOST_PATCH_QUALIFICATION_REQUIRED')
    for item in manifest['qualification']:
        path = Path(item['path'])
        require(sha(path.read_bytes()) == item['sha256'], 'HOST_PATCH_QUALIFICATION_CHANGED')
        report = _document(path)
        require(report.get('commit') == commit and report.get('final') is True
            and report.get('source_files_unchanged') is True and report.get('results'),
            'HOST_PATCH_QUALIFICATION_INCOMPLETE')
        for name in changed:
            require(report['source_files'].get(name) == sha((source/name).read_bytes()),
                'HOST_PATCH_QUALIFIED_SOURCE_CHANGED')
        for result in report['results']:
            require(result.get('exit_code') == 0 and type(result.get('passed')) is int
                and result['passed'] > 0 and result.get('skipped') == 0
                and result.get('deselected') == 0, 'HOST_PATCH_TESTS_NOT_PASS')
            log = Path(result['log'])
            require(sha(log.read_bytes()) == result['log_sha256'], 'HOST_PATCH_TEST_LOG_CHANGED')
            counts = re.findall(r'\b(\d+) passed\b', log.read_text())
            require(counts and int(counts[-1]) == result['passed'], 'HOST_PATCH_TEST_COUNTS_CHANGED')
    for name, expected in BASE_FILES.items():
        require(sha((deployed/name).read_bytes()) == expected, 'HOST_PATCH_BASE_BYTES_CHANGED')
    reviewed_definitions(*[(deployed/name).read_bytes() for name in BASE_FILES],
        *[(source/name).read_bytes() for name in BASE_FILES])
    return source, deployed


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    require(args, 'HOST_PATCH_MANIFEST_REQUIRED')
    manifest_path = Path(args.pop(0))
    require(manifest_path.is_absolute() and not manifest_path.is_symlink(), 'HOST_PATCH_MANIFEST_PATH')
    manifest = _document(manifest_path)
    source, deployed = verify(manifest)
    os.chdir(deployed)
    sys.path.insert(0, str(deployed/'scripts'))
    import sentinel_env
    values = sentinel_env.load(deployed/'.env')
    require(values.get('SENTINEL_LOCAL_PAPER_MODE') == 'OWNER_AUTHORIZED_FUNCTION_FIRST_V1'
        and values.get('SENTINEL_LOCAL_PAPER_BACKUP_POLICY') == 'REQUIRED_V1'
        and values.get('ALPACA_BASE_URL', 'https://paper-api.alpaca.markets')
            == 'https://paper-api.alpaca.markets', 'HOST_PATCH_BACKED_PAPER_REQUIRED')
    import sentinel_go_lock
    require(sentinel_go_lock.lifecycle_lock_is_held(), 'HOST_PATCH_LIFECYCLE_LOCK_REQUIRED')
    import sentinel_go_validate as go
    import sentinel_go_validate_entry as entry
    install(go, entry, old_go=(deployed/list(BASE_FILES)[0]).read_bytes(),
        old_entry=(deployed/list(BASE_FILES)[1]).read_bytes(),
        new_go=(source/list(BASE_FILES)[0]).read_bytes(),
        new_entry=(source/list(BASE_FILES)[1]).read_bytes(),
        filename=str(source/list(BASE_FILES)[0]))
    started = {'schema': 'sentinel.local-go-host-patch-start/1', 'authority_effect': 'NONE',
        'runtime_commit': BASE, 'runtime_image': IMAGE, 'host_patch_commit': manifest['host_patch_commit'],
        'manifest_sha256': sha(manifest_path.read_bytes()), 'pid': os.getpid()}
    with (manifest_path.parent/'entry-started.json').open('x') as stream:
        stream.write(json.dumps(started, sort_keys=True)+'\n')
    # Import overlays after installing the qualified definitions so their saved
    # function references point to the actual local host patch.
    import sentinel_go_verified_entry
    return sentinel_go_verified_entry.main(args)


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (Refused, OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        print('LOCAL GO HOST PATCH REFUSED: '+type(exc).__name__+': '+str(exc), file=sys.stderr)
        raise SystemExit(2)
