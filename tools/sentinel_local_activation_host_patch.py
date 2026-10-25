"""Owner-authorized, manifest-bound host handoff repair; signed runtime unchanged."""
import ast
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.sentinel_local_go_host_patch import (
    BASE, IMAGE, Refused, _document, _git, require, sha,
)

MODULE = 'scripts/sentinel_autonomous_deploy.py'
BASE_SHA = 'de30b4c60662b8e30a1e9b9ae7dae04c9891914c8245d90ae8d5b59472bcc96a'
FUNCTION = '_reviewed_shadow_lineage_preflight'
KEY = 'SENTINEL_TEST_IMAGE_DIGEST'


def reviewed_definition(old, new):
    require(sha(old) == BASE_SHA, 'ACTIVATION_PATCH_BASE_CHANGED')
    original, candidate = ast.parse(old), ast.parse(new)
    selected = [n for n in candidate.body if isinstance(n, ast.FunctionDef) and n.name == FUNCTION]
    require(len(selected) == 1, 'ACTIVATION_PATCH_FUNCTION_CHANGED')
    definition = ast.parse(ast.unparse(selected[0])).body[0]
    tuples = [n for n in ast.walk(selected[0]) if isinstance(n, ast.Tuple)
        and any(isinstance(v, ast.Constant) and v.value == KEY for v in n.elts)]
    require(len(tuples) == 1, 'ACTIVATION_PATCH_FORWARDING_CHANGED')
    require(sum(isinstance(v, ast.Constant) and v.value == KEY for v in tuples[0].elts) == 1,
        'ACTIVATION_PATCH_FORWARDING_CHANGED')
    tuples[0].elts = [v for v in tuples[0].elts if not isinstance(v, ast.Constant) or v.value != KEY]
    require(ast.dump(original, include_attributes=False) == ast.dump(candidate, include_attributes=False),
        'ACTIVATION_PATCH_NEIGHBOR_CHANGED')
    return ast.Module(body=[definition], type_ignores=[])


def install(module, old, new):
    exec(compile(reviewed_definition(old, new), '<qualified local activation host patch>', 'exec'), module.__dict__)


def interpreter_source(source, deployed, manifest, python='/usr/bin/python3'):
    target = str(Path(deployed)/'scripts/sentinel_activation_coordinator.py')
    loader = str(Path(source)/'tools/sentinel_local_activation_host_patch.py')
    return ('#!'+python+'\nimport os,sys\nfrom pathlib import Path\nargs=sys.argv[1:]\n'
        +'if args and str(Path(args[0]).resolve()) == '+repr(target)+':\n'
        +' os.execv('+repr(python)+', ['+repr(python)+", '-B', "+repr(loader)
        +', '+repr(str(manifest))+']+args)\n'
        +'os.execv('+repr(python)+', ['+repr(python)+']+args)\n')


def verify(manifest):
    require(manifest['schema'] == 'sentinel.local-activation-host-patch/1'
        and manifest['authority_effect'] == 'NONE', 'ACTIVATION_PATCH_MANIFEST')
    source, deployed = Path(manifest['source']), Path(manifest['deployment'])
    require(_git(source, 'rev-parse', 'HEAD') == manifest['commit']
        and _git(source, 'merge-base', BASE, manifest['commit']) == BASE
        and not _git(source, 'status', '--porcelain', '--untracked-files=no')
        and _git(deployed, 'rev-parse', 'HEAD') == BASE
        and not _git(deployed, 'status', '--porcelain', '--untracked-files=no'), 'ACTIVATION_PATCH_SOURCE')
    receipt = Path(manifest['receipt'])
    require(sha(receipt.read_bytes()) == manifest['receipt_sha256'], 'ACTIVATION_PATCH_RECEIPT')
    record = _document(receipt)
    require(record['git_commit'] == BASE and record['runtime_image'] == record['test_image'] == IMAGE,
        'ACTIVATION_PATCH_RUNTIME')
    for name in ('tools/sentinel_local_activation_host_patch.py', 'tools/sentinel_local_go_host_patch.py'):
        require(sha((source/name).read_bytes()) == manifest['loaders'][name], 'ACTIVATION_PATCH_LOADER')
    require(sha(Path(__file__).read_bytes()) == manifest['loaders']['tools/sentinel_local_activation_host_patch.py'],
        'ACTIVATION_PATCH_EXECUTED_LOADER')
    require(manifest['qualification'], 'ACTIVATION_PATCH_QUALIFICATION')
    changed = _git(source, 'diff', '--name-only', BASE, manifest['commit']).splitlines()
    for evidence in manifest['qualification']:
        path = Path(evidence['path'])
        require(sha(path.read_bytes()) == evidence['sha256'], 'ACTIVATION_PATCH_REPORT')
        report = _document(path)
        require(report['commit'] == manifest['commit'] and report['final']
            and report['source_files_unchanged'] and report['results'], 'ACTIVATION_PATCH_TESTS')
        require(all(report['source_files'].get(name) == sha((source/name).read_bytes()) for name in changed),
            'ACTIVATION_PATCH_INPUTS')
        for result in report['results']:
            require(result['exit_code'] == 0 and result['passed'] > 0
                and result['skipped'] == result['deselected'] == 0
                and sha(Path(result['log']).read_bytes()) == result['log_sha256'], 'ACTIVATION_PATCH_TESTS')
    reviewed_definition((deployed/MODULE).read_bytes(), (source/MODULE).read_bytes())
    return source, deployed


def main():
    path = Path(sys.argv[1]); manifest = _document(path)
    source, deployed = verify(manifest)
    os.chdir(deployed); sys.path.insert(0, str(deployed/'scripts'))
    import sentinel_env
    values = sentinel_env.load(deployed/'.env')
    require(values.get('SENTINEL_LOCAL_PAPER_MODE') == 'OWNER_AUTHORIZED_FUNCTION_FIRST_V1'
        and values.get('SENTINEL_LOCAL_PAPER_BACKUP_POLICY') == 'REQUIRED_V1'
        and values.get('ALPACA_BASE_URL') == 'https://paper-api.alpaca.markets', 'ACTIVATION_PATCH_PAPER_ONLY')
    import sentinel_autonomous_deploy as core
    install(core, (deployed/MODULE).read_bytes(), (source/MODULE).read_bytes())
    import sentinel_activation_coordinator as coordinator
    # The interpreter trampoline scopes only this installed coordinator entry.
    # Canonical handoff thus retains the patch inside its systemd-owned process.
    launcher = path.parent/'activation-python'
    require(sha(launcher.read_bytes()) == manifest['launcher_sha256']
        and launcher.read_text() == interpreter_source(source, deployed, path), 'ACTIVATION_PATCH_LAUNCHER')
    args = sys.argv[2:]
    if args and args[0] == str(deployed/'scripts/sentinel_activation_coordinator.py'):
        args.pop(0)
    require(args and args[0] in {'--request', '--queue-from-installation'}, 'ACTIVATION_PATCH_ENTRY')
    sys.executable = str(launcher)
    if args[0] == '--request':
        with (path.parent/'activation-started.json').open('x') as stream:
            json.dump({'manifest_sha256': sha(path.read_bytes()), 'pid': os.getpid(), 'request': args[1]}, stream)
    result = coordinator.main(args)
    if args[0] == '--request':
        with (path.parent/'activation-exit.json').open('x') as stream:
            json.dump({'exit_code': result}, stream)
    return result


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (Refused, OSError, ValueError, KeyError) as exc:
        print('LOCAL ACTIVATION HOST PATCH REFUSED: '+str(exc), file=sys.stderr)
        raise SystemExit(2)
