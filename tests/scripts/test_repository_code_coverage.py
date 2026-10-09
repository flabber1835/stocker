"""Falsify missing-file, excluded-branch and unauthenticated coverage claims."""
import json
from pathlib import Path
import runpy
import sqlite3
import sys

import pytest

from tools import repository_code_coverage as reporter


PROGRAM = ('def choose(enabled):\n'
           '    if enabled:\n'
           '        return 1\n'
           '    return 0  # pragma: no cover\n')


def source(tmp_path, *, shell=False, untouched=False):
    root = tmp_path / 'repo'
    root.mkdir()
    (root / 'program.py').write_text(PROGRAM)
    tracked = ['program.py']
    if shell:
        (root / 'restore.sh').write_text('#!/bin/sh\nexit 2\n')
        tracked.append('restore.sh')
    if untouched:
        (root / 'unimported.py').write_text('raise RuntimeError("must stay visible")\n')
        tracked.append('unimported.py')
    manifest = reporter.source_inventory(root, tracked, revision='exact-source')
    return root, manifest


def evidence(tmp_path, root, *, both=False, measured=None):
    coverage = pytest.importorskip('coverage')
    path = measured or root / 'program.py'
    data_path = tmp_path / 'measured.coverage'
    cov = coverage.Coverage(data_file=str(data_path), branch=True,
                            include=[str(path)])
    cov.start()
    try:
        namespace = {}
        exec(compile(path.read_text(), str(path), 'exec'), namespace)
        assert namespace['choose'](True) == 1
        if both:
            assert namespace['choose'](False) == 0
    finally:
        cov.stop()
        cov.save()
    return data_path


def test_unimported_files_and_pragma_excluded_edges_stay_in_denominator(tmp_path):
    root, manifest = source(tmp_path, untouched=True)
    result = reporter.report(root, manifest, [evidence(tmp_path, root)])
    files = {item['path']: item for item in result['files']}
    assert files['unimported.py']['statements'] == 1
    assert files['unimported.py']['missing_lines'] == [1]
    assert files['program.py']['missing_lines'] == [4]
    assert files['program.py']['missing_arcs'] == {'2': [4]}
    assert result['python']['missing_statements'] == 2
    assert result['python']['missing_branches'] == 1
    assert result['coverage_exclusions'] == []
    assert result['status'] == 'INCOMPLETE'


def test_python_completion_never_certifies_unmeasured_shell(tmp_path):
    root, manifest = source(tmp_path, shell=True)
    result = reporter.report(root, manifest, [evidence(tmp_path, root, both=True)])
    assert result['python']['combined_percent'] == 100
    assert result['status'] == 'INCOMPLETE'
    assert result['unmeasured_languages'] == ['shell']
    assert next(item for item in result['files'] if item['path'] == 'restore.sh')[
        'status'] == 'UNMEASURED_LANGUAGE'


def test_complete_python_report_requires_both_outcomes(tmp_path):
    root, manifest = source(tmp_path)
    result = reporter.report(root, manifest, [evidence(tmp_path, root, both=True)])
    assert result['status'] == 'COMPLETE'
    assert result['python']['combined_percent'] == 100
    assert result['domains']['program.py'] == result['python']


def test_empty_evidence_is_zero_coverage_not_an_empty_success(tmp_path):
    root, manifest = source(tmp_path)
    result = reporter.report(root, manifest, [])
    assert result['python']['combined_percent'] == 0
    assert result['status'] == 'INCOMPLETE'
    assert result['inputs'] == []


@pytest.mark.parametrize('name', ['', '/absolute.py', '../escaped.py',
                                'a/../escaped.py', './file.py', 'a//file.py',
                                'a\\file.py'])
def test_ambiguous_source_paths_are_refused(name):
    with pytest.raises(ValueError, match='canonical repository-relative'):
        reporter.relative_source(name)


def test_inventory_retains_research_and_reference_source_and_ignores_tests(tmp_path):
    for name in ['sentinel/a.py', 'research/run.py', 'audit/check.py',
                 'docs/reference.py', 'tools/test_responsibility_lib.py',
                 'scripts/test_go_probe_runtime_integration.py', 'tests/test_a.py',
                 'research/tests/test_a.py', 'docs/test_reference.py',
                 'README.md']:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('pass\n')
    manifest = reporter.source_inventory(tmp_path, [
        path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob('*')
        if path.is_file()], revision='revision')
    assert {item['path'] for item in manifest['source']} == {
        'sentinel/a.py', 'research/run.py', 'audit/check.py', 'docs/reference.py',
        'tools/test_responsibility_lib.py', 'scripts/test_go_probe_runtime_integration.py'}
    assert all(item['language'] == 'python' and item['bytes'] == 5
               for item in manifest['source'])


def test_duplicate_and_empty_inventory_are_refused(tmp_path):
    (tmp_path / 'a.py').write_text('pass\n')
    with pytest.raises(ValueError, match='duplicate tracked'):
        reporter.source_inventory(tmp_path, ['a.py', 'a.py'], revision='r')
    with pytest.raises(ValueError, match='empty'):
        reporter.source_inventory(tmp_path, [], revision='r')


def test_missing_source_file_cannot_disappear_from_inventory(tmp_path):
    with pytest.raises(ValueError, match='ordinary repository file'):
        reporter.source_inventory(tmp_path, ['missing.py'], revision='r')


def test_symlinked_source_is_refused(tmp_path):
    target = tmp_path / 'target.py'
    target.write_text('pass\n')
    link = tmp_path / 'link.py'
    link.symlink_to(target)
    with pytest.raises(ValueError, match='ordinary repository file'):
        reporter.source_inventory(tmp_path, ['link.py'], revision='r')


def test_source_changes_invalidate_retained_evidence(tmp_path):
    root, manifest = source(tmp_path)
    data = evidence(tmp_path, root)
    (root / 'program.py').write_text('pass\n')
    with pytest.raises(ValueError, match='source hash differs'):
        reporter.report(root, manifest, [data])


def test_duplicate_source_manifest_is_refused(tmp_path):
    root, manifest = source(tmp_path)
    manifest['source'].append(dict(manifest['source'][0]))
    with pytest.raises(ValueError, match='duplicate source'):
        reporter.report(root, manifest, [])


def test_omitting_a_source_from_the_manifest_cannot_improve_coverage(tmp_path):
    root, manifest = source(tmp_path, untouched=True)
    manifest['source'] = [item for item in manifest['source']
                          if item['path'] != 'unimported.py']
    with pytest.raises(ValueError, match='inventories differ'):
        reporter.report(root, manifest, [evidence(tmp_path, root, both=True)])


def test_line_only_evidence_cannot_claim_branch_completion(tmp_path):
    coverage = pytest.importorskip('coverage')
    root, manifest = source(tmp_path)
    path = tmp_path / 'lines.coverage'
    data = coverage.CoverageData(basename=str(path))
    data.add_lines({str(root / 'program.py'): [1, 2, 3, 4]})
    data.write()
    with pytest.raises(ValueError, match='branch coverage is required'):
        reporter.report(root, manifest, [path])


def test_alias_coverage_is_authenticated_before_combination(tmp_path):
    root, manifest = source(tmp_path)
    actual = tmp_path / 'runtime'
    actual.mkdir()
    measured = actual / 'program.py'
    measured.write_text(PROGRAM)
    data = evidence(tmp_path, root, both=True, measured=measured)
    mappings = [(str(actual) + '/', '')]
    assert reporter.report(root, manifest, [data], mappings=mappings)[
        'status'] == 'COMPLETE'
    measured.write_text('pass\n')
    with pytest.raises(ValueError, match='measured source hash mismatch'):
        reporter.report(root, manifest, [data], mappings=mappings)


def test_unknown_measured_files_are_reported_without_covering_source(tmp_path):
    root, manifest = source(tmp_path)
    foreign = tmp_path / 'foreign.py'
    foreign.write_text(PROGRAM)
    result = reporter.report(root, manifest, [
        evidence(tmp_path, root, both=True, measured=foreign)])
    assert result['python']['combined_percent'] == 0
    assert result['unmapped_measured_files'] == [str(foreign)]


@pytest.mark.parametrize('measured,expected', [
    ('/work/shared/stock_strategy_shared/broker/order_status.py',
     'shared/stock_strategy_shared/broker/order_status.py'),
    ('/usr/local/lib/python3.12/site-packages/stock_strategy_shared/broker/order_status.py',
     'shared/stock_strategy_shared/broker/order_status.py'),
    ('/work/repo/shared/stock_strategy_shared/broker/order_status.py',
     'shared/stock_strategy_shared/broker/order_status.py'),
    ('/work/shared/unrelated.py', None),
])
def test_shared_library_paths_preserve_exact_repository_ownership(tmp_path, measured, expected):
    assert reporter._canonical_measured(measured, tmp_path, reporter.DEFAULT_MAPS) == expected


def test_completion_gate_refuses_an_incomplete_report(tmp_path):
    root, manifest = source(tmp_path)
    manifest_path = tmp_path / 'manifest.json'
    manifest_path.write_text(json.dumps(manifest))
    output = tmp_path / 'report.json'
    assert reporter.main(['report', '--root', str(root), '--manifest',
                          str(manifest_path), '--output', str(output),
                          '--require-complete']) == 2
    assert json.loads(output.read_text())['status'] == 'INCOMPLETE'


def test_embedded_browser_code_cannot_disappear_behind_python_completion(tmp_path):
    root, manifest = source(tmp_path)
    renderer = root / 'sentinel/panel/render.py'
    renderer.parent.mkdir(parents=True)
    renderer.write_text('')
    manifest = reporter.source_inventory(root, ['program.py', 'sentinel/panel/render.py'],
                                         revision='exact-source')
    result = reporter.report(root, manifest, [evidence(tmp_path, root, both=True)])
    assert result['python']['combined_percent'] == 100
    assert result['unmeasured_languages'] == ['javascript']
    assert result['status'] == 'INCOMPLETE'
    renderer_entry = next(item for item in manifest['source']
                          if item['path'] == 'sentinel/panel/render.py')
    renderer_entry.pop('embedded_languages')
    with pytest.raises(ValueError, match='embedded language obligation differs'):
        reporter.report(root, manifest, [])


def test_empty_manifest_and_deleted_measured_source_are_refused(tmp_path):
    root, manifest = source(tmp_path)
    with pytest.raises(ValueError, match='empty'):
        reporter.report(root, {**manifest, 'source': []}, [])
    actual = tmp_path / 'runtime'
    actual.mkdir()
    measured = actual / 'program.py'
    measured.write_text(PROGRAM)
    data = evidence(tmp_path, root, both=True, measured=measured)
    measured.unlink()
    with pytest.raises(ValueError, match='cannot be authenticated'):
        reporter.report(root, manifest, [data], mappings=[(str(actual) + '/', '')])


def test_cli_inventory_and_complete_report_preserve_source_identity(tmp_path, monkeypatch):
    root, manifest = source(tmp_path)
    commands = []

    def git_output(command, **kwargs):
        commands.append((command, kwargs))
        return 'exact-source\n' if kwargs.get('text') else b'program.py\0README.md\0'

    monkeypatch.setattr(reporter.subprocess, 'check_output', git_output)
    manifest_path = tmp_path / 'out/manifest.json'
    assert reporter.main(['inventory', '--root', str(root),
                          '--output', str(manifest_path)]) == 0
    assert json.loads(manifest_path.read_text()) == manifest
    assert [item[0] for item in commands] == [
        ['git', 'ls-files', '-z'], ['git', 'rev-parse', 'HEAD']]
    data = evidence(tmp_path, root, both=True)
    report_path = tmp_path / 'out/report.json'
    assert reporter.main(['report', '--root', str(root), '--manifest',
                          str(manifest_path), '--data', str(data), '--output',
                          str(report_path), '--require-complete']) == 0
    assert json.loads(report_path.read_text())['status'] == 'COMPLETE'


def test_cli_report_without_manifest_is_an_argument_error(tmp_path):
    with pytest.raises(SystemExit) as failure:
        reporter.main(['report', '--root', str(tmp_path), '--output',
                       str(tmp_path / 'report.json')])
    assert failure.value.code == 2


def test_parent_symlink_cannot_escape_source_inventory(tmp_path):
    root = tmp_path / 'repo'
    root.mkdir()
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'program.py').write_text(PROGRAM)
    (root / 'subdir').symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match='ordinary repository file'):
        reporter.source_inventory(root, ['subdir/program.py'], revision='r')


def test_report_snapshot_symlink_is_refused_even_when_bytes_match(tmp_path):
    root, manifest = source(tmp_path)
    outside = tmp_path / 'outside.py'
    outside.write_text(PROGRAM)
    (root / 'program.py').unlink()
    (root / 'program.py').symlink_to(outside)
    with pytest.raises(ValueError, match='escaped its snapshot'):
        reporter.report(root, manifest, [])


def test_coverage_dependency_cannot_silently_keep_its_default_exclusions(
        tmp_path, monkeypatch):
    coverage = pytest.importorskip('coverage')
    root, manifest = source(tmp_path)
    # Model an incompatible dependency that ignores explicit report settings.
    # Its real parser then excludes PROGRAM's pragma-marked return statement.
    class IncompatibleCoverage(coverage.Coverage):
        def __init__(self, *args, **kwargs):
            # Explicit defaults make this fault independent of an outer
            # coverage campaign's own blank exclusion configuration.
            kwargs['config_file'] = False
            super().__init__(*args, **kwargs)

        def set_option(self, *args):
            pass

    monkeypatch.setattr(coverage, 'Coverage', IncompatibleCoverage)
    with pytest.raises(ValueError, match='excluded repository source'):
        reporter.report(root, manifest, [])


def test_actual_cli_entrypoint_writes_an_inventory_and_returns_zero(
        tmp_path, monkeypatch):
    root, manifest = source(tmp_path)
    output = tmp_path / 'entrypoint.json'
    monkeypatch.setattr(reporter.subprocess, 'check_output',
                        lambda command, **kwargs: 'exact-source\n'
                        if kwargs.get('text') else b'program.py\0')
    monkeypatch.setattr(sys, 'argv', [str(reporter.__file__), 'inventory',
                                    '--root', str(root), '--output', str(output)])
    with pytest.raises(SystemExit) as finished:
        runpy.run_path(str(reporter.__file__), run_name='__main__')
    assert finished.value.code == 0
    assert json.loads(output.read_text()) == manifest


def test_empty_child_database_contributes_no_paths_and_cannot_hide_a_file(tmp_path):
    coverage = pytest.importorskip('coverage')
    root, manifest = source(tmp_path, untouched=True)
    empty_path = tmp_path / 'empty-child.coverage'
    empty = coverage.CoverageData(basename=str(empty_path))
    empty.add_lines({})
    empty.write()
    assert empty.measured_files() == set() and not empty.has_arcs()
    result = reporter.report(root, manifest, [
        evidence(tmp_path, root, both=True), empty_path])
    assert result['status'] == 'INCOMPLETE'
    assert result['python']['missing_statements'] == 1
    assert result['inputs'][-1]['status'] == 'EMPTY_NO_EXECUTED_PATHS'
    unimported = next(item for item in result['files'] if item['path'] == 'unimported.py')
    assert unimported['missing_lines'] == [1]


def unflushed_child(tmp_path, *, extra_table=False, recorded_row=False):
    path = tmp_path / 'coverage.fixture.pid123.token'
    with sqlite3.connect(path) as conn:
        conn.execute('CREATE TABLE coverage_schema (version integer)')
        conn.execute('CREATE TABLE meta (key text, value text)')
        conn.execute('CREATE TABLE file (id integer, path text)')
        if extra_table:
            conn.execute('CREATE TABLE unknown_payload (content text)')
        if recorded_row:
            conn.execute("INSERT INTO meta VALUES ('has_arcs', '1')")
    return path


def test_unfinished_empty_child_header_has_no_coverage_and_keeps_its_receipt(tmp_path):
    root, manifest = source(tmp_path, untouched=True)
    path = unflushed_child(tmp_path)
    before = path.read_bytes()
    result = reporter.report(root, manifest, [evidence(tmp_path, root, both=True), path])
    assert result['status'] == 'INCOMPLETE'
    assert result['python']['missing_statements'] == 1
    assert result['inputs'][-1]['status'] == 'UNFLUSHED_EMPTY_CHILD'
    assert path.read_bytes() == before


@pytest.mark.parametrize('kind', ['unknown_table', 'recorded_row', 'damaged_bytes'])
def test_nonempty_or_unrecognized_child_data_failure_is_never_dropped(tmp_path, kind):
    coverage = pytest.importorskip('coverage')
    root, manifest = source(tmp_path)
    path = unflushed_child(tmp_path, extra_table=kind == 'unknown_table',
                          recorded_row=kind == 'recorded_row')
    if kind == 'damaged_bytes':
        path.write_bytes(b'not a SQLite coverage database')
    before = path.read_bytes()
    with pytest.raises(coverage.exceptions.DataError):
        reporter.report(root, manifest, [path])
    assert path.read_bytes() == before


def test_empty_child_storage_requires_a_child_identity(tmp_path):
    child = tmp_path / 'coverage.fixture.pid123.token'
    child.touch()
    assert reporter._empty_unflushed_child(child)
    foreign = tmp_path / 'arbitrary-data'
    foreign.touch()
    assert not reporter._empty_unflushed_child(foreign)


@pytest.mark.parametrize('header', [False, True])
def test_proven_empty_child_never_reaches_a_mutating_loader(tmp_path, monkeypatch, header):
    coverage = pytest.importorskip('coverage')
    root, manifest = source(tmp_path, untouched=True)
    path = unflushed_child(tmp_path) if header else tmp_path / 'coverage.fixture.pid123.token'
    if not header:
        path.touch()
    before = path.read_bytes()
    actual = coverage.CoverageData

    def empty_reader_is_forbidden(*args, **kwargs):
        if kwargs.get('basename'):
            pytest.fail('proven-empty counter reached the mutating coverage loader')
        return actual(*args, **kwargs)

    monkeypatch.setattr(coverage, 'CoverageData', empty_reader_is_forbidden)
    result = reporter.report(root, manifest, [path])
    assert result['inputs'][0]['status'] == 'UNFLUSHED_EMPTY_CHILD'
    assert result['python']['combined_percent'] == 0
    assert result['status'] == 'INCOMPLETE'
    assert path.read_bytes() == before


def test_loader_cannot_change_retained_evidence_or_credit_a_changed_copy(tmp_path, monkeypatch):
    coverage = pytest.importorskip('coverage')
    root, manifest = source(tmp_path)
    path = evidence(tmp_path, root, both=True)
    before = path.read_bytes()
    original = coverage.CoverageData
    targets = []

    class MutatingReader(original):
        def read(self):
            target = Path(self.data_filename())
            targets.append(target)
            super().read()
            target.write_bytes(target.read_bytes() + b'changed during load')

    monkeypatch.setattr(coverage, 'CoverageData', MutatingReader)
    with pytest.raises(ValueError, match='changed serialized evidence'):
        reporter.report(root, manifest, [path])
    assert len(targets) == 1 and targets[0] != path
    assert not targets[0].exists()
    assert path.read_bytes() == before
