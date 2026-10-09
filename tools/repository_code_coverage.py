"""Inventory all repository source and report branch coverage without exclusions.

This is test-only reporting. It grants no installation or broker authority.
The coverage dependency belongs to the existing CI test lens.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sqlite3
import subprocess
from typing import Iterable


LANGUAGES = {'.py': 'python', '.sh': 'shell', '.js': 'javascript',
             '.cjs': 'javascript', '.mjs': 'javascript', '.ts': 'typescript'}
# Python execution of a renderer does not measure its embedded browser code.
EMBEDDED_LANGUAGES = {'sentinel/panel/render.py': ('javascript',)}
DEFAULT_MAPS = (
    ('/app/sentinel/', 'sentinel/'),
    ('/app/tools/', 'tools/'),
    ('/app/docs/', 'docs/'),
    ('/work/repo/', ''),
    ('/work/scripts/', 'scripts/'),
    ('/work/tools/', 'tools/'),
    ('/work/research/', 'research/'),
    ('/work/audit/', 'audit/'),
    ('/work/docs/', 'docs/'),
    ('/work/shared/stock_strategy_shared/', 'shared/stock_strategy_shared/'),
    ('/usr/local/lib/python3.12/site-packages/stock_strategy_shared/',
     'shared/stock_strategy_shared/'),
)


def relative_source(value: str) -> str:
    path = PurePosixPath(value)
    if (not value or '\\' in value or path.is_absolute()
            or any(part in {'', '.', '..'} for part in value.split('/'))):
        raise ValueError('source path must be a canonical repository-relative path')
    return path.as_posix()


def test_source(value: str) -> bool:
    path = PurePosixPath(value)
    return ('tests' in path.parts
            or (path.parts[0] in {'research', 'docs'}
                and path.name.startswith('test_'))
            or path.name == 'conftest.py')


def source_inventory(root: Path, tracked: Iterable[str], *, revision: str) -> dict:
    root = root.resolve()
    seen = set()
    source = []
    for raw in tracked:
        name = relative_source(raw)
        if name in seen:
            raise ValueError('duplicate tracked path: ' + name)
        seen.add(name)
        language = LANGUAGES.get(PurePosixPath(name).suffix)
        if language is None or test_source(name):
            continue
        path = root / name
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root):
            raise ValueError('source is not an ordinary repository file: ' + name)
        content = path.read_bytes()
        source.append({'path': name, 'language': language,
                       'sha256': hashlib.sha256(content).hexdigest(),
                       'bytes': len(content),
                       'embedded_languages': list(EMBEDDED_LANGUAGES.get(name, ()))})
    if not source:
        raise ValueError('repository source inventory is empty')
    return {'schema': 'sentinel.repository-code-coverage/1', 'revision': revision,
            'source': sorted(source, key=lambda item: item['path'])}


def _canonical_measured(value: str, root: Path, mappings) -> str | None:
    candidate = Path(value)
    if candidate.is_absolute() and candidate.is_relative_to(root):
        return candidate.relative_to(root).as_posix()
    for prefix, relative in sorted(mappings, key=lambda pair: -len(pair[0])):
        if value.startswith(prefix):
            return relative_source(relative + value[len(prefix):])
    return None


def _empty_unflushed_child(path: Path) -> bool:
    """Recognize only empty coverage storage, never repair or discard counters."""
    if re.fullmatch(r'coverage\.[^.]+\.pid[0-9]+\.[^.]+', path.name) is None:
        return False
    if path.stat().st_size == 0:
        return True
    known = {'coverage_schema', 'meta', 'file', 'context', 'line_bits', 'arc', 'tracer'}
    try:
        with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro',
                                     uri=True, timeout=1)) as conn:
            tables = {row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            if not tables <= known:
                return False
            return all(conn.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0] == 0
                       for table in tables)
    except sqlite3.DatabaseError:
        return False


def report(root: Path, manifest: dict, data_paths: Iterable[Path],
           *, mappings=DEFAULT_MAPS) -> dict:
    import coverage

    root = root.resolve()
    source = manifest['source']
    if not source:
        raise ValueError('repository source inventory is empty')
    names = [relative_source(item['path']) for item in source]
    if len(names) != len(set(names)):
        raise ValueError('duplicate source in manifest')
    expected = {item['path']: item for item in source}
    discovered = {
        path.relative_to(root).as_posix()
        for path in root.rglob('*') if path.is_file()
        and path.suffix in LANGUAGES
        and not test_source(path.relative_to(root).as_posix())}
    if discovered != set(expected):
        raise ValueError('source snapshot and manifest inventories differ')
    for name, item in expected.items():
        path = root / name
        if item.get('embedded_languages', []) != list(EMBEDDED_LANGUAGES.get(name, ())):
            raise ValueError('embedded language obligation differs: ' + name)
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError('source escaped its snapshot: ' + name)
        if hashlib.sha256(path.read_bytes()).hexdigest() != item['sha256']:
            raise ValueError('source hash differs from manifest: ' + name)

    # Start with an empty branch database; every source is analyzed even when
    # no test imported it. Never let coverage's imported-file discovery define
    # the repository denominator.
    cov = coverage.Coverage(data_file=None, branch=True)
    for setting in ('exclude_lines', 'exclude_also', 'partial_branches', 'partial_also'):
        cov.set_option('report:' + setting, [])
    combined = cov.get_data()
    combined.add_arcs({str(root / name): [] for name in names if name.endswith('.py')})
    inputs, unmapped = [], set()
    for data_path in data_paths:
        receipt = {'file': str(data_path),
                   'sha256': hashlib.sha256(data_path.read_bytes()).hexdigest()}
        data = coverage.CoverageData(basename=str(data_path))
        try:
            data.read()
        except coverage.exceptions.DataError:
            if not _empty_unflushed_child(data_path):
                raise
            inputs.append({**receipt, 'status': 'UNFLUSHED_EMPTY_CHILD'})
            continue
        measured_files = data.measured_files()
        if not measured_files:
            inputs.append({**receipt, 'status': 'EMPTY_NO_EXECUTED_PATHS'})
            continue
        if not data.has_arcs():
            raise ValueError('branch coverage is required: ' + str(data_path))
        inputs.append({**receipt, 'status': 'BRANCH_MEASUREMENTS'})
        for measured in measured_files:
            name = _canonical_measured(measured, root, mappings)
            if name not in expected or not name.endswith('.py'):
                unmapped.add(measured)
                continue
            actual = Path(measured)
            if not actual.is_file():
                raise ValueError('measured source cannot be authenticated: ' + measured)
            if hashlib.sha256(actual.read_bytes()).hexdigest() != expected[name]['sha256']:
                raise ValueError('measured source hash mismatch: ' + measured)
            combined.add_arcs({str(root / name): data.arcs(measured) or []})

    files, domains = [], {}
    total = {'statements': 0, 'missing_statements': 0,
             'branches': 0, 'missing_branches': 0}
    unmeasured_languages = set()
    for item in source:
        name = item['path']
        unmeasured_languages.update(item.get('embedded_languages', []))
        if not name.endswith('.py'):
            unmeasured_languages.add(item.get('language', LANGUAGES[Path(name).suffix]))
            files.append({**item, 'status': 'UNMEASURED_LANGUAGE'})
            continue
        analysis = cov._analyze(str(root / name))
        numbers = analysis.numbers
        counts = {'statements': numbers.n_statements,
                  'missing_statements': numbers.n_missing,
                  'branches': numbers.n_branches,
                  'missing_branches': numbers.n_missing_branches}
        if numbers.n_excluded:
            raise ValueError('coverage excluded repository source: ' + name)
        domain = PurePosixPath(name).parts[0]
        domain_total = domains.setdefault(domain, {key: 0 for key in total})
        for key, value in counts.items():
            total[key] += value
            domain_total[key] += value
        files.append({**item, **counts, 'missing_lines': sorted(analysis.missing),
                      'missing_arcs': {str(key): value for key, value in
                                       analysis.missing_branch_arcs().items()}})

    def percentage(counts):
        denominator = counts['statements'] + counts['branches']
        missing = counts['missing_statements'] + counts['missing_branches']
        return 100.0 * (denominator - missing) / denominator if denominator else None

    for counts in [total, *domains.values()]:
        counts['combined_percent'] = percentage(counts)
    complete = (total['missing_statements'] == total['missing_branches'] == 0
                and not unmeasured_languages)
    return {'schema': manifest['schema'], 'revision': manifest['revision'],
            'status': 'COMPLETE' if complete else 'INCOMPLETE',
            'coverage_exclusions': [], 'python': total, 'domains': domains,
            'unmeasured_languages': sorted(unmeasured_languages),
            'unmapped_measured_files': sorted(unmapped), 'inputs': inputs, 'files': files}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('inventory', 'report'))
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--manifest', type=Path)
    parser.add_argument('--data', type=Path, action='append', default=[])
    parser.add_argument('--require-complete', action='store_true')
    args = parser.parse_args(argv)
    if args.action == 'inventory':
        tracked = subprocess.check_output(['git', 'ls-files', '-z'], cwd=args.root)
        revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'],
                                           cwd=args.root, text=True).strip()
        result = source_inventory(args.root,
                                  (name.decode() for name in tracked.split(b'\0') if name),
                                  revision=revision)
    else:
        if args.manifest is None:
            parser.error('report requires --manifest')
        result = report(args.root, json.loads(args.manifest.read_text()), args.data)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({key: result[key] for key in
                      ('schema', 'revision', 'status', 'python', 'unmeasured_languages')
                      if key in result}))
    return 2 if args.require_complete and result.get('status') != 'COMPLETE' else 0


if __name__ == '__main__':
    raise SystemExit(main())
