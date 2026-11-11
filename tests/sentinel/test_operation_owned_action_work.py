"""Qualified old/new action semantics and executed work counters on PostgreSQL."""
import ast
from dataclasses import asdict
from datetime import date
import hashlib
import inspect
import json
from pathlib import Path
import re
import textwrap
from types import SimpleNamespace

import pytest

from sentinel.execution import feed_actions, reconcile
from sentinel.feed import actions_map, normalized_layout, rolling_store
from sentinel.feed.rolling_contract import PriceWindow, digest
from tests.sentinel.test_rolling_snapshot_publisher import conn, pg

__all__ = ['conn', 'pg']
BASE = '277160861e2353d8ad93d15da8e2615ebdb11c18'
BEFORE = {
    'sentinel.execution.reconcile': '0061e79de130e6c29f78b552a23322d77a7c9a9ce2ada56fa56dc12953cb07e2',
    'sentinel.execution.feed_actions': '8ce0436b4d58161f40ffb52900022529b23f3b565bdc9003a58eaa5f207e9b47',
}
START = date(2026, 9, 11)
END = date(2026, 9, 14)


def predecessor_function(module, name, namespace):
    path = Path(__file__).resolve().parents[1] / 'support/operation-read-277-sources.json'
    fixture = path.read_bytes()
    assert hashlib.sha256(fixture).hexdigest() == '3d7fd186d316c3285cde43af4735cb389c66fe72196ce749a89e0acc14e640c0'
    record = json.loads(fixture)
    assert record['schema'] == 'sentinel.operation-read-baseline/1'
    assert record['revision'] == BASE
    raw = record['modules'][module]['source'].encode()
    assert hashlib.sha256(raw).hexdigest() == BEFORE[module]
    tree = ast.parse(raw)
    function = next(node for node in tree.body
                    if isinstance(node, ast.FunctionDef) and node.name == name)
    scope = dict(namespace)
    exec(compile(ast.Module(body=[function], type_ignores=[]), '<authenticated277>', 'exec'), scope)
    return scope[name]


def old_lookup():
    policy = predecessor_function('sentinel.execution.reconcile',
                                  'reconcile_action_material', vars(reconcile))
    return predecessor_function('sentinel.execution.feed_actions', 'snapshot_lookup',
        dict(vars(feed_actions), candidate_query=normalized_layout.candidate_query,
             reconcile=SimpleNamespace(reconcile_action_material=policy)))


def action(verb, *, ticker='AAA', day='2026-09-14', value=None, identity='source'):
    payload = dict(date=day, action=verb, ticker=ticker, value=value, contraticker=None)
    return identity, payload, payload


def inputs(conn, *, verb='dividend', ticker='AAA', ratio=1., ambiguous=False,
           absent=False, bil=False, siblings=False, disposition='valid'):
    window = PriceWindow.through(END.isoformat())
    evidence = rolling_store.put_evidence(conn, {'fixture': 'operation-owned-action-inputs'})
    candidate = rolling_store.begin(conn, window=window, reference_sha256=evidence,
        source_evidence_sha256=evidence, expected_publication_version=None,
        dependencies_sha256=digest({}))
    if not absent:
        conn.execute("INSERT INTO sentinel_snapshot_bars VALUES(%s,'one',%s,'AAA',"
                     '100,100,100,1000,%s,0)', (candidate, END, ratio))
    if ambiguous:
        conn.execute("INSERT INTO sentinel_snapshot_bars VALUES(%s,'two',%s,'AAA',"
                     '100,100,100,1000,1,0)', (candidate, END))
    for day, raw in ((START, 100.), (END, 50. if bil else 100.)):
        conn.execute('INSERT INTO sentinel_snapshot_benchmarks VALUES(%s,%s,100,100,100,100,%s)',
                     (candidate, day, raw))
    splits = ([] if verb != 'split' or ticker == 'BIL' else [dict(
        ticker=ticker, session=END.isoformat(),
        disposition=(actions_map.SPLIT_CORROBORATED_DIRECT if disposition == 'valid' else 'UNRESOLVED'),
        applied_ratio=ratio)])
    proof = rolling_store.put_evidence(conn, {'split_dispositions': splits})
    conn.execute('INSERT INTO sentinel_snapshot_validations VALUES(%s,%s)', (candidate, proof))
    rows = [action(verb, ticker=ticker, value=2 if verb == 'split' else None)]
    if siblings:
        rows.append(action(verb, ticker=ticker, value=2, identity='sibling'))
    refs = SimpleNamespace(candidate_id=candidate, manifest=SimpleNamespace(window=window), actions=rows)
    pub = SimpleNamespace(run_id=None, version=17, window_end=END.isoformat())
    return refs, pub


def mapping_statement(statement):
    text = re.sub(r'\s+', ' ', str(statement)).strip()
    return text.startswith('SELECT security_id,split_ratio FROM ')


class CountCursor:
    def __init__(self, owner, cursor):
        self.owner, self.cursor = owner, cursor

    def __enter__(self):
        self.cursor.__enter__()
        return self

    def __exit__(self, *args):
        return self.cursor.__exit__(*args)

    def __getattr__(self, name):
        return getattr(self.cursor, name)

    def execute(self, statement, *args, **kwargs):
        self.owner.observe(statement)
        return self.cursor.execute(statement, *args, **kwargs)


class CountConnection:
    def __init__(self, connection, *, fail_mapping=False):
        self.connection, self.fail_mapping = connection, fail_mapping
        self.mappings = self.statements = 0

    def __getattr__(self, name):
        return getattr(self.connection, name)

    def observe(self, statement):
        self.statements += 1
        if mapping_statement(statement):
            self.mappings += 1
            if self.fail_mapping:
                raise OSError('private synthetic mapping read failure')

    def execute(self, statement, *args, **kwargs):
        self.observe(statement)
        return self.connection.execute(statement, *args, **kwargs)

    def cursor(self, *args, **kwargs):
        return CountCursor(self, self.connection.cursor(*args, **kwargs))


def captured(conn, refs, pub, function, monkeypatch, *, start=START, end=END, fail_mapping=False):
    counted = CountConnection(conn, fail_mapping=fail_mapping)
    router_calls = []
    original = normalized_layout.query_router

    def router(owner):
        router_calls.append(owner)
        return original(owner)

    with monkeypatch.context() as patch:
        patch.setattr(normalized_layout, 'query_router', router)
        patch.setitem(function.__globals__, 'query_router', router)
        try:
            result = function(counted, refs=refs, pub=pub, start=start, end=end)
            value = ('result', asdict(result))
        except Exception as error:
            value = ('error', type(error).__name__, str(error))
    return value, counted, len(router_calls)


@pytest.mark.parametrize('verb', sorted(reconcile.SAFE_NON_BOOK_ACTIONS))
def test_safe_actions_keep_full_output_without_mapping_work(conn, monkeypatch, verb):
    refs, pub = inputs(conn, verb=verb)
    before, old_count, old_routers = captured(conn, refs, pub, old_lookup(), monkeypatch)
    after, new_count, new_routers = captured(conn, refs, pub, feed_actions.snapshot_lookup, monkeypatch)
    assert before == after and after[0] == 'result'
    assert old_count.mappings == 1 and new_count.mappings == 0
    assert old_routers == 3 and new_routers == 1


@pytest.mark.parametrize('case,settings', [
    ('split', {'verb': 'split', 'ratio': 2.}),
    ('absent', {'verb': 'split', 'ratio': 2., 'absent': True}),
    ('ambiguous', {'verb': 'split', 'ratio': 2., 'ambiguous': True}),
    ('siblings', {'verb': 'split', 'ratio': 2., 'siblings': True}),
    ('unresolved', {'verb': 'split', 'ratio': 2., 'disposition': 'unsafe'}),
    ('unsupported', {'verb': 'spinoff'}),
    ('bil', {'verb': 'split', 'ticker': 'BIL', 'bil': True}),
])
def test_meaningful_output_and_refusals_match_complete_predecessor(conn, monkeypatch, case, settings):
    refs, pub = inputs(conn, **settings)
    before, old_count, _ = captured(conn, refs, pub, old_lookup(), monkeypatch)
    after, new_count, routers = captured(conn, refs, pub, feed_actions.snapshot_lookup, monkeypatch)
    assert before == after, case
    assert old_count.mappings == new_count.mappings
    assert routers == 1
    if case == 'siblings':
        assert after[0:2] == ('error', 'ValueError')
    elif case in {'absent', 'ambiguous', 'unresolved'}:
        assert after[1]['unresolved_events']
    elif case == 'unsupported':
        assert after[1]['unsupported_events']
    else:
        assert after[1]['scalar_events']


def test_mapping_io_failure_is_removed_only_for_ignored_actions(conn, monkeypatch):
    refs, pub = inputs(conn)
    before, _, _ = captured(conn, refs, pub, old_lookup(), monkeypatch, fail_mapping=True)
    after, _, routers = captured(conn, refs, pub, feed_actions.snapshot_lookup, monkeypatch, fail_mapping=True)
    assert before[0:2] == ('error', 'OSError')
    assert after[0] == 'result' and routers == 1
    refs.actions = [action('spinoff')]
    before, _, _ = captured(conn, refs, pub, old_lookup(), monkeypatch, fail_mapping=True)
    after, _, _ = captured(conn, refs, pub, feed_actions.snapshot_lookup, monkeypatch, fail_mapping=True)
    assert before == after and after[0:2] == ('error', 'OSError')


@pytest.mark.parametrize('kind', ['malformed_safe_date', 'window_start', 'future_window', 'predecessor_gap'])
def test_original_date_and_coverage_errors_remain_identical(conn, monkeypatch, kind):
    refs, pub = inputs(conn)
    start, end = START, END
    if kind == 'malformed_safe_date':
        refs.actions = [action('dividend', day='2026-09-13Tinvalid')]
    elif kind == 'window_start':
        start = refs.manifest.window.start.replace(year=2024)
    elif kind == 'future_window':
        end = date(2026, 9, 16)
    else:
        conn.execute('SET LOCAL session_replication_role=replica')
        conn.execute('DELETE FROM sentinel_snapshot_benchmarks WHERE candidate_id=%s AND session=%s',
                     (refs.candidate_id, START))
        conn.execute('SET LOCAL session_replication_role=origin')
    before, _, _ = captured(conn, refs, pub, old_lookup(), monkeypatch, start=start, end=end)
    after, _, _ = captured(conn, refs, pub, feed_actions.snapshot_lookup, monkeypatch, start=start, end=end)
    assert before == after and after[0] == 'error'


def test_each_operation_revalidates_structure_and_changed_source(conn, monkeypatch):
    refs, pub = inputs(conn)
    result, _, routers = captured(conn, refs, pub, feed_actions.snapshot_lookup, monkeypatch)
    assert result[0] == 'result' and routers == 1
    refs.actions = [action('spinoff')]
    result, count, routers = captured(conn, refs, pub, feed_actions.snapshot_lookup, monkeypatch)
    assert result[1]['unsupported_events'] and count.mappings == 1 and routers == 1
    # Private DDL alteration: a safe-only operation still needs the original
    # exact schema admission; no process/router cache may conceal a change.
    refs.actions = [action('dividend')]
    conn.execute('CREATE OR REPLACE VIEW sentinel_candidate_bars AS '
                 'SELECT * FROM sentinel_snapshot_bars WHERE false')
    before, _, _ = captured(conn, refs, pub, old_lookup(), monkeypatch)
    after, count, _ = captured(conn, refs, pub, feed_actions.snapshot_lookup, monkeypatch)
    assert before == after and after[0:2] == ('error', 'OperationalCatalogRefused')
    assert count.mappings == 0


def test_new_publication_never_reuses_the_previous_operation_router(conn, monkeypatch):
    previous, previous_pub = inputs(conn)
    result, _, routers = captured(conn, previous, previous_pub, feed_actions.snapshot_lookup, monkeypatch)
    assert result[0] == 'result' and routers == 1
    current, current_pub = inputs(conn, verb='split', ratio=2.)
    current_pub.version = 18
    assert current.candidate_id != previous.candidate_id
    before, _, _ = captured(conn, current, current_pub, old_lookup(), monkeypatch)
    after, count, routers = captured(conn, current, current_pub, feed_actions.snapshot_lookup, monkeypatch)
    assert before == after and after[1]['scalar_events']
    assert after[1]['scalar_events'][0]['publication_version'] == 18
    assert count.mappings == 1 and routers == 1
    current.actions = [action('split', value=3)]
    before, _, _ = captured(conn, current, current_pub, old_lookup(), monkeypatch)
    after, _, routers = captured(conn, current, current_pub, feed_actions.snapshot_lookup, monkeypatch)
    assert before == after and after[1]['unresolved_events'] and routers == 1


def compile_function(source, name, namespace):
    scope = dict(namespace)
    exec(compile(textwrap.dedent(source), '<executed-work-falsifier>', 'exec'), scope)
    return scope[name]


def test_restoring_safe_mapping_work_fails_executed_counter(conn, monkeypatch):
    source = inspect.getsource(reconcile.reconcile_action_material)
    guard = ('        elif _safe_non_book_action(verb):\n'
             '            # These rows remain source/cash evidence, but supply no scalar or\n'
             '            # material event here and do not need an equity mapping.\n'
             '            continue\n')
    assert source.count(guard) == 1
    mutant = compile_function(source.replace(guard, ''), 'reconcile_action_material', vars(reconcile))
    monkeypatch.setattr(reconcile, 'reconcile_action_material', mutant)
    with pytest.raises(AssertionError):
        test_safe_actions_keep_full_output_without_mapping_work(conn, monkeypatch, 'dividend')


def test_restoring_router_per_query_fails_executed_counter(conn, monkeypatch):
    source = inspect.getsource(feed_actions.snapshot_lookup)
    guard = '    query = query_router(conn)\n'
    assert source.count(guard) == 1
    mutant = compile_function(source.replace(guard,
        '    query = lambda statement: candidate_query(conn, statement)\n'), 'snapshot_lookup',
        dict(vars(feed_actions), candidate_query=normalized_layout.candidate_query))
    refs, pub = inputs(conn, verb='split', ratio=2.)
    expected, _, _ = captured(conn, refs, pub, old_lookup(), monkeypatch)
    actual, _, routers = captured(conn, refs, pub, mutant, monkeypatch)
    assert actual == expected
    with pytest.raises(AssertionError):
        assert routers == 1
