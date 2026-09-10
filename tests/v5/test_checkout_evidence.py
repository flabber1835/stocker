"""Falsify full-PIT acceptance on actual Git commit graphs."""
import os
from pathlib import Path
import subprocess

import pytest

from tools.v5_checkout_evidence import evidence, verify_current_pr


@pytest.fixture
def graph(tmp_path):
    env = dict(os.environ, GIT_AUTHOR_NAME='Test', GIT_AUTHOR_EMAIL='test@example.invalid',
               GIT_COMMITTER_NAME='Test', GIT_COMMITTER_EMAIL='test@example.invalid')
    def git(*args, input=None):
        return subprocess.check_output(['git', '-C', str(tmp_path), *args],
                                       input=input, text=True, env=env).strip()
    git('init', '-q')
    tree = git('mktree', input='')
    base = git('commit-tree', tree, '-m', 'base')
    head = git('commit-tree', tree, '-p', base, '-m', 'feature')
    advanced = git('commit-tree', tree, '-p', base, '-m', 'advanced main')
    merge = git('commit-tree', tree, '-p', base, '-p', head, '-m', 'merge')
    git('checkout', '--detach', '-q', merge)
    return tmp_path, git, base, head, advanced, merge, tree


def check(graph, *, event_name='pull_request', event=None, sha=None):
    repo, git, base, head, advanced, merge, tree = graph
    return evidence(event_name=event_name,
        event=event or {'pull_request': {'base': {'sha': base}, 'head': {'sha': head}}},
        expected_sha=sha or merge, repo=repo, run_id='123', run_attempt='2')


def test_pr_evidence_binds_both_parents_and_tree(graph):
    repo, git, base, head, advanced, merge, tree = graph
    assert check(graph) == dict(commit=merge, tree=tree, parents=[base, head],
        base=base, head=head, scope='PULL_REQUEST_MERGE', event_name='pull_request',
        run_id='123', run_attempt='2')


@pytest.mark.parametrize('fault', ['head_checkout', 'wrong_sha', 'base_advanced', 'head_changed', 'parents_reversed'])
def test_stale_or_wrong_merge_refuses(graph, fault):
    repo, git, base, head, advanced, merge, tree = graph
    event = {'pull_request': {'base': {'sha': base}, 'head': {'sha': head}}}
    sha = merge
    if fault == 'head_checkout':
        git('checkout', '--detach', '-q', head)
        sha = head
    elif fault == 'wrong_sha':
        sha = head
    elif fault == 'base_advanced':
        event['pull_request']['base']['sha'] = advanced
    elif fault == 'head_changed':
        event['pull_request']['head']['sha'] = advanced
    else:
        event['pull_request']['base']['sha'], event['pull_request']['head']['sha'] = head, base
    with pytest.raises(ValueError, match='checkout'):
        check(graph, event=event, sha=sha)


def test_merge_group_binds_result_and_base(graph):
    repo, git, base, head, advanced, merge, tree = graph
    event = {'merge_group': {'base_sha': base, 'head_sha': merge}}
    assert check(graph, event_name='merge_group', event=event)['scope'] == 'MERGE_GROUP'
    for field, wrong in [('base_sha', advanced), ('head_sha', head)]:
        with pytest.raises(ValueError, match='merge group'):
            check(graph, event_name='merge_group', event={'merge_group': {**event['merge_group'], field: wrong}})

    stacked = git('commit-tree', tree, '-p', merge, '-p', advanced, '-m', 'stacked queue')
    git('checkout', '--detach', '-q', stacked)
    assert check(graph, event_name='merge_group', sha=stacked,
                 event={'merge_group': {'base_sha': base, 'head_sha': stacked}})['scope'] == 'MERGE_GROUP'


@pytest.mark.parametrize('changed', [None, 'base', 'head', 'merge', 'missing_merge'])
def test_remote_change_during_replay_invalidates_acceptance(graph, changed):
    repo, git, base, head, advanced, merge, tree = graph
    refs = {'base': 'refs/heads/main', 'head': 'refs/pull/342/head', 'merge': 'refs/pull/342/merge'}
    for ref, sha in [('base', base), ('head', head), ('merge', merge)]:
        git('update-ref', refs[ref], sha)
    git('remote', 'add', 'origin', str(repo))
    event = {'number': 342, 'pull_request': {'base': {'ref': 'main', 'sha': base}, 'head': {'sha': head}}}
    if changed is None:
        verify_current_pr(event=event, repo=repo, commit=merge)
        return
    if changed == 'missing_merge':
        git('update-ref', '-d', refs['merge'])
    else:
        git('update-ref', refs[changed], advanced)
    with pytest.raises(ValueError, match='changed during full-PIT replay'):
        verify_current_pr(event=event, repo=repo, commit=merge)


def test_manual_run_is_diagnostic_and_push_cannot_claim_merge_gate(graph):
    assert check(graph, event_name='workflow_dispatch')['scope'] == 'DIAGNOSTIC_COMMIT_ONLY'
    with pytest.raises(ValueError, match='unsupported'):
        check(graph, event_name='push')


def test_workflow_tests_event_merge_and_keeps_manual_check_separate():
    root = Path(os.environ.get('SENTINEL_REPO_ROOT', Path(__file__).resolve().parents[2]))
    workflow = (root / '.github/workflows/v5-equivalence.yml').read_text()
    assert '  pull_request:' in workflow and '  merge_group:' in workflow
    assert '  push:' not in workflow
    assert 'ref: ${{ github.sha }}' in workflow
    assert "fetch-depth: ${{ github.event_name == 'merge_group' && 0 || 2 }}" in workflow
    assert "'full-pit-diagnostic' || 'full-pit-equivalence'" in workflow
    assert 'python tools/v5_checkout_evidence.py' in workflow
    assert 'python tools/v5_checkout_evidence.py --verify-current' in workflow
    assert "result['checkout'] = checkout" in workflow
