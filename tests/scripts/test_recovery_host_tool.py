"""Independent host verifier qualification cannot substitute for application evidence."""
from pathlib import Path

import pytest

from sentinel_local_delivery import cli, qualification, recovery_host_tool as tool
from sentinel_local_delivery.model import DeliveryRefused, digest


@pytest.fixture
def inputs(monkeypatch, tmp_path):
    executable = Path(tool.__file__).resolve().parents[2]/tool.COMMAND
    request = dict(handoff_mode='POST_TRADE_REACTIVATED', candidate=dict(commit='a'*40, image='image'),
                   predecessor=dict(commit='c'*40), qualification=dict(report_sha256='d'*64))
    report = dict(schema=qualification.OPERATIONAL_SCHEMA, source_scope=qualification.OPERATIONAL_SCOPE,
                  source_files={name:'h' for name in tool.HOST_DELTA},
                  results=[dict(command=['pytest', *sorted(tool.TESTS)])])
    info = dict(commit='b'*40, changes='A\tscripts/sentinel_local_delivery/reactivated_startup.py')
    monkeypatch.setattr(qualification, 'git', lambda root, *args:
                        info['commit'] if args[0] == 'rev-parse' else info['changes'])
    def validate(path, sha, root, commit, base):
        assert base == (request['predecessor']['commit'] if commit == request['candidate']['commit']
                        else request['candidate']['commit'])
        assert commit == info['commit']
        return report
    monkeypatch.setattr(qualification, 'validate_report', validate)
    monkeypatch.setattr(qualification, 'sha256_file', lambda path:'h')
    return executable, tmp_path/'report.json', request, report, info


def test_qualified_tool_binds_both_subjects_and_revalidates(inputs):
    executable, path, request, report, info = inputs
    result = tool.identify(executable, path, 'e'*64, request)
    assert (result['commit'], result['application_commit']) == (info['commit'], 'a'*40)
    assert result['request_sha256'] == digest(request)
    assert result['source_manifest_sha256'] == digest(report['source_files'])
    assert result['qualification_sha256'] == 'e'*64
    tool.revalidate(result, request)
    request['candidate']['image'] = 'other'
    with pytest.raises(DeliveryRefused, match='TOOL_CHANGED'):
        tool.revalidate(result, request)


@pytest.mark.parametrize('change', [
    '', 'M\tsentinel/automation/service.py', 'D\tscripts/sentinel_local_delivery/evidence.py',
    'M\tscripts/sentinel_local_delivery/evidence.py\nA\tunrelated', 'A\tdocs/other.md'])
def test_host_delta_is_scoped_to_the_compatibility_fix(inputs, change):
    executable, path, request, _, info = inputs
    info['changes'] = change
    with pytest.raises(DeliveryRefused, match='DELTA_REFUSED'):
        tool.identify(executable, path, 'e'*64, request)


@pytest.mark.parametrize(('mutation','error'), [
    ('partial','TESTS_FILTERED'), ('source','SOURCE_CHANGED'), ('digest','SOURCE_CHANGED'),
    ('schema','SCOPE_REQUIRED'), ('scope','SCOPE_REQUIRED'), ('mode','MODE_REFUSED'),
    ('executable','EXECUTABLE_CHANGED'), ('relative','REPORT_REQUIRED')])
def test_refuses_incomplete_or_unrelated_qualification(inputs, mutation, error):
    executable, path, request, report, _ = inputs
    if mutation == 'partial':
        report['results'][0]['command'][-1] += '::test_one'
    elif mutation == 'source':
        del report['source_files']['scripts/sentinel_local_delivery/reactivated_startup.py']
    elif mutation == 'digest':
        report['source_files'][tool.COMMAND] = 'edited'
    elif mutation == 'schema':
        report['schema'] = qualification.SCHEMA
    elif mutation == 'scope':
        report['source_scope'] = 'other'
    elif mutation == 'mode':
        request['handoff_mode'] = 'PRE_OPEN'
    elif mutation == 'executable':
        executable = path
    else:
        path = Path('report.json')
    with pytest.raises(DeliveryRefused, match=error):
        tool.identify(executable, path, 'e'*64, request)


def test_same_image_verifier_requires_own_report(inputs):
    executable, path, request, _, info = inputs
    info['commit'] = request['candidate']['commit']
    with pytest.raises(DeliveryRefused, match='APPLICATION_QUALIFICATION_CHANGED'):
        tool.identify(executable, path, 'e'*64, request)
    assert tool.identify(executable, path, 'd'*64, request)['commit'] == info['commit']


@pytest.mark.parametrize('option', [['-k','positive'], ['-m','quick'], ['--ignore=tests/scripts'],
                                    ['--collect-only']])
def test_refuses_filtered_suite_even_with_all_paths_present(inputs, option):
    executable, path, request, report, _ = inputs
    report['results'][0]['command'].extend(option)
    with pytest.raises(DeliveryRefused, match='TESTS_FILTERED'):
        tool.identify(executable, path, 'e'*64, request)


def test_missing_whole_required_module(inputs):
    executable, path, request, report, _ = inputs
    report['results'][0]['command'].pop()
    with pytest.raises(DeliveryRefused, match='TESTS_MISSING'):
        tool.identify(executable, path, 'e'*64, request)


def test_required_path_cannot_be_only_an_option_value(inputs):
    executable, path, request, report, _ = inputs
    argv = report['results'][0]['command']
    argv.insert(-1, '--basetemp')
    with pytest.raises(DeliveryRefused, match='TESTS_FILTERED'):
        tool.identify(executable, path, 'e'*64, request)


def test_only_explicit_pytest_launcher_and_positional_paths_count(inputs):
    executable, path, request, report, _ = inputs
    argv = ['docker','run','--rm','--entrypoint','python','sha256:'+'f'*64,
            '-m','pytest','-q','--tb=short','-p','no:cacheprovider',*sorted(tool.TESTS)]
    report['results'][0]['command'] = argv
    assert tool.identify(executable, path, 'e'*64, request)['application_commit'] == 'a'*40
    argv[4] = 'echo'
    with pytest.raises(DeliveryRefused, match='TEST_LAUNCHER'):
        tool.identify(executable, path, 'e'*64, request)
    report['results'][0]['command'] = ['echo','pytest',*sorted(tool.TESTS)]
    with pytest.raises(DeliveryRefused, match='TEST_LAUNCHER'):
        tool.identify(executable, path, 'e'*64, request)


def test_explicit_recovery_cli_selects_host_report():
    args = cli.parser(backed=True).parse_args(['recover-verification','--operation-dir','/op',
        '--recovery-id','initial-handoff','--host-qualification','/qualified','--host-qualification-sha256','a'*64])
    assert args.host_qualification == '/qualified' and args.host_qualification_sha256 == 'a'*64
