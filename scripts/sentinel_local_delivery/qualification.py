"""Bind completed qualification logs to every tracked candidate file."""
from __future__ import annotations

from datetime import datetime
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import subprocess

from .model import read_json, require

SCHEMA = 'sentinel.local-paper-qualification/1'
OPERATIONAL_SCHEMA = 'sentinel.local-paper-qualification/2'
OPERATIONAL_SCOPE = 'SENTINEL_AND_CHANGED_TRACKED_V1'
_HEX = re.compile(r'[0-9a-f]{64}\Z')


def sha256_file(path):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), 'QUALIFICATION_FILE_UNSAFE')
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            result.update(block)
    return result.hexdigest()


def git(source, *args):
    """Read worktree metadata without relying on an inherited Git environment."""
    source = Path(source).resolve()
    metadata = source/'.git'
    if metadata.is_file():
        text = metadata.read_text().strip()
        require(text.startswith('gitdir: '), 'GIT_METADATA_SHAPE')
        raw = text.removeprefix('gitdir: ')
        if os.name != 'nt' and re.match(r'^[A-Za-z]:[\\/]', raw):
            raw = '/mnt/'+raw[0].lower()+'/'+raw[3:].replace('\\','/')
        metadata = Path(raw)
        if not metadata.is_absolute():
            metadata = source/metadata
    clean = {key:value for key,value in os.environ.items()
             if key in {'HOME','USER','LOGNAME','PATH','LANG','LC_ALL','TZ'}}
    result = subprocess.run(['git','--no-optional-locks','--git-dir',str(metadata),
        '--work-tree',str(source),*args],env=clean,capture_output=True,timeout=30)
    require(result.returncode == 0, 'QUALIFICATION_GIT_READ_REFUSED')
    return result.stdout.decode('utf-8').strip()


def source_files(source, *, scope=None, predecessor_commit=None):
    """Hash the complete declared input scope, never ignored local evidence."""
    require(scope is None or scope == OPERATIONAL_SCOPE, 'QUALIFICATION_SOURCE_SCOPE_INVALID')
    source = Path(source).resolve()
    names = git(source,'ls-files','-z').split('\0')
    names = [name for name in names if name]
    require(names and len(names) == len(set(names)), 'QUALIFICATION_SOURCE_SET_EMPTY')
    if scope == OPERATIONAL_SCOPE:
        require(re.fullmatch(r'[0-9a-f]{40}', predecessor_commit or '') is not None,
                'QUALIFICATION_PREDECESSOR_INVALID')
        changed = set(filter(None,git(source,'diff','--name-only','-z',
            predecessor_commit,'HEAD').split('\0')))
        require(all(name.startswith(('sentinel/','scripts/','tests/','docs/','tools/'))
                    for name in changed), 'QUALIFICATION_NONOPERATIONAL_DELTA')
        names = [name for name in names if name.startswith(
            ('sentinel/','scripts/sentinel_local_delivery/'))
            or name == 'scripts/sentinel_backed_local_patch.py' or name in changed]
        require(any(name.startswith('sentinel/') for name in names)
                and any(name.startswith('scripts/sentinel_local_delivery/') for name in names)
                and 'scripts/sentinel_backed_local_patch.py' in names,
                'QUALIFICATION_OPERATIONAL_INPUTS_MISSING')
    result = {}
    for name in sorted(names):
        path = PurePosixPath(name)
        require(not path.is_absolute() and '..' not in path.parts and '\\' not in name
                and name == path.as_posix() and '.env' not in path.parts,
                'QUALIFICATION_SOURCE_PATH_UNSAFE')
        selected = source/name
        require(selected.resolve().is_relative_to(source)
                and not any(parent.is_symlink() for parent in (selected,*selected.parents)
                            if parent.is_relative_to(source)), 'QUALIFICATION_SOURCE_PATH_UNSAFE')
        result[name] = sha256_file(selected)
    return result


def clean_candidate(source, commit, predecessor_commit):
    require(re.fullmatch(r'[0-9a-f]{40}', commit or '') is not None
            and re.fullmatch(r'[0-9a-f]{40}', predecessor_commit or '') is not None,
            'QUALIFICATION_COMMIT_INVALID')
    require(git(source,'rev-parse','HEAD') == commit and not git(source,'status','--porcelain'),
            'QUALIFICATION_SOURCE_NOT_CLEAN')
    branch = git(source,'branch','--show-current')
    require(bool(branch) and branch not in {'main','master'}, 'QUALIFICATION_FEATURE_BRANCH_REQUIRED')
    require(git(source,'merge-base',predecessor_commit,commit) == predecessor_commit,
            'QUALIFICATION_PREDECESSOR_NOT_ANCESTOR')


def validate_report(path, expected_sha, source, commit, predecessor_commit):
    """Derive success from retained exit/count/log evidence and current bytes."""
    require(isinstance(expected_sha,str) and _HEX.fullmatch(expected_sha) is not None
            and sha256_file(path) == expected_sha, 'QUALIFICATION_REPORT_CHANGED')
    report = read_json(path)
    operational = isinstance(report,dict) and report.get('schema') == OPERATIONAL_SCHEMA
    require(isinstance(report,dict) and set(report) == {
        'schema','commit','predecessor_commit','at','source_files','results',
        'source_files_unchanged','final'} | ({'source_scope'} if operational else set()),
        'QUALIFICATION_REPORT_SHAPE')
    require(report['schema'] in {SCHEMA,OPERATIONAL_SCHEMA} and report['commit'] == commit
            and report['predecessor_commit'] == predecessor_commit,
            'QUALIFICATION_RUNTIME_CHANGED')
    if operational:
        require(report['source_scope'] == OPERATIONAL_SCOPE, 'QUALIFICATION_SOURCE_SCOPE_INVALID')
    require(report['source_files_unchanged'] is True and report['final'] is True,
            'QUALIFICATION_NOT_FINAL')
    try:
        observed = datetime.fromisoformat(report['at'])
    except (TypeError,ValueError):
        require(False,'QUALIFICATION_TIME_INVALID')
    require(observed.utcoffset() is not None and observed.utcoffset().total_seconds() == 0,
            'QUALIFICATION_TIME_INVALID')
    clean_candidate(source,commit,predecessor_commit)
    current_files = (source_files(source,scope=report['source_scope'],
        predecessor_commit=predecessor_commit) if operational else source_files(source))
    require(report['source_files'] == current_files,
        'QUALIFIED_SOURCE_BYTES_CHANGED')
    results = report['results']
    require(isinstance(results,list) and results, 'QUALIFICATION_RESULTS_ABSENT')
    seen = set()
    for result in results:
        require(isinstance(result,dict) and set(result) == {
            'name','exit_code','passed','skipped','deselected','log','log_sha256','command'},
            'QUALIFICATION_RESULT_SHAPE')
        require(isinstance(result['name'],str) and result['name'] and result['name'] not in seen,
                'QUALIFICATION_RESULT_NAME')
        seen.add(result['name'])
        require(type(result['exit_code']) is int and result['exit_code'] == 0
                and type(result['passed']) is int and result['passed'] > 0
                and type(result['skipped']) is int and result['skipped'] == 0
                and type(result['deselected']) is int and result['deselected'] == 0,
                'QUALIFICATION_RESULT_NOT_PASSED')
        command = result['command']
        require(isinstance(command,list) and command and all(isinstance(arg,str) and arg for arg in command)
                and not any(arg == '--deselect' or arg.startswith('--deselect=') for arg in command),
                'QUALIFICATION_COMMAND_INVALID')
        log = Path(result['log'])
        require(log.is_absolute() and log.stat().st_size <= 64*1024*1024
                and isinstance(result['log_sha256'],str) and _HEX.fullmatch(result['log_sha256']) is not None
                and sha256_file(log) == result['log_sha256'], 'QUALIFICATION_LOG_CHANGED')
        lines = log.read_text(encoding='utf-8').splitlines()
        summaries = [line for line in lines if re.search(r'\b\d+ passed\b',line)]
        require(bool(summaries), 'QUALIFICATION_SUMMARY_ABSENT')
        summary = summaries[-1]
        count = re.search(r'\b(\d+) passed\b',summary)
        require(int(count[1]) == result['passed']
                and not re.search(r'\b[1-9]\d* (?:failed|errors?|skipped|deselected|xfailed|xpassed)\b',summary),
                'QUALIFICATION_SUMMARY_NOT_PASSED')
    return report
