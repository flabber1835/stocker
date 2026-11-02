"""Own-prefix and dispatch guards without importing or executing a launcher."""
import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
SOURCE = HERE / 'system_campaign_p02_outcome_job.py'


def need(value, label):
    if not value:
        raise ValueError(label)


def function(name, namespace, *, remove_guard=False):
    fn, = [n for n in ast.parse(SOURCE.read_bytes()).body
           if isinstance(n, ast.FunctionDef) and n.name == name]
    if remove_guard:
        sites = [i for i, n in enumerate(fn.body) if isinstance(n, ast.Expr)
                 and isinstance(n.value, ast.Call) and isinstance(n.value.func, ast.Name)
                 and n.value.func.id == 'need']
        assert len(sites) == 1
        fn.body[sites[0]] = ast.Pass()
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])),
                 '<pure-chinook-dispatch-contract>', 'exec'), namespace)
    return namespace[name]


def request_function(tmp_path, spec, *, remove_guard=False):
    selected = tmp_path / 'selected.json'
    selected.write_text(json.dumps(spec), encoding='utf8')

    class Root:
        def __truediv__(self, name):
            return selected if name == 'system-campaign-p02-outcome-predecessor.json' else HERE / name

    return function('expected_request', dict(HERE=Root(), json=json, need=need, SOURCES=(),
        sha256_file=lambda p: hashlib.sha256(p.read_bytes()).hexdigest(),
        inherited_request=lambda: json.loads((HERE/'system-campaign-p02-chinook-request.json').read_bytes()),
        PACKET_SOURCE_PATH='research/pooled_input_support/adapter.py'), remove_guard=remove_guard)


@pytest.mark.parametrize('field,value', [('arm', 'P03'), ('run_id', 41180417283),
    ('selected_session', '2023-08-09'), ('review_refusal', True)])
def test_wrong_candidate_older_same_date_parent_or_unsent_cursor_refuses(tmp_path, field, value):
    spec = json.loads((HERE / 'system-campaign-p02-outcome-predecessor.json').read_bytes())
    spec[field] = value
    with pytest.raises(ValueError, match='OUTCOME_EXACT_OWN_ADMITTED_32_INPUT_PREDECESSOR'):
        request_function(tmp_path, spec)()


def test_actual_parent_guard_removal_falsifier(tmp_path):
    spec = json.loads((HERE / 'system-campaign-p02-outcome-predecessor.json').read_bytes())
    spec['run_id'] = 41180417283
    with pytest.raises(ValueError):
        request_function(tmp_path, spec)()
    request_function(tmp_path, spec, remove_guard=True)()


def test_foreign_entrypoint_refuses_and_guard_removal_is_detectable():
    actual = dict(Config=dict(Cmd=['-B', '-u', '/driver/system_campaign_p02_outcome_run.py',
        '--mode', 'economic', '--spec', '/out/spec.json',
        '--request', '/driver/system-campaign-p02-outcome-request.json']))
    expected = deepcopy(actual)
    namespace = dict(need=need, prior_inspect=lambda name, identity: actual)
    inspect = function('inspect', namespace)
    assert inspect('capital-system-factual-p02-worker-123-1') == expected
    actual['Config']['Cmd'][2] = '/driver/system_campaign_p02_chinook_run.py'
    with pytest.raises(ValueError, match='EXACT_FINANCIAL_OR_REVIEW_ENTRYPOINT'):
        inspect('capital-system-factual-p02-worker-123-1')
    function('inspect', namespace, remove_guard=True)('capital-system-factual-p02-worker-123-1')


def test_gate_precedes_financial_entry_and_keeps_all_old_input_contexts():
    tree = ast.parse((HERE / 'system_campaign_p02_outcome_run.py').read_bytes())
    run, = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'run']
    calls = [n for n in ast.walk(run) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute) and ast.unparse(n.func) == 'timing.call']
    gate, = [n for n in calls if len(n.args) > 1 and ast.unparse(n.args[1]) == 'qualify']
    replay, = [n for n in calls if len(n.args) > 1 and ast.unparse(n.args[1]) == 'backtest.main']
    assert gate.lineno < replay.lineno
    context, = [n for n in ast.walk(run) if isinstance(n, ast.With)
                and 'ccodec' in [ast.unparse(v.context_expr) for v in n.items]]
    assert [ast.unparse(v.context_expr) for v in context.items] == [
        'v1', 'spin', 'alder', 'prior.idempotent_dispatch(alder)', 'zcodec', 'codec',
        'amendment', 'completion', 'acodec', 'ccodec', 'ocodec']
    assert gate in list(ast.walk(context)) and replay in list(ast.walk(context))


def test_single_trigger_and_encrypted_storage_preserve_the_existing_scope():
    raw = (HERE.parents[1] / '.github/workflows/capital-system-p02-outcome.yml').read_text()
    assert "paths: ['research/capital_risk/system-campaign-p02-outcome-request.json']" in raw
    assert 'group: system-optimization-002-p02-only' in raw and 'cancel-in-progress: false' in raw
    assert raw.count('system_campaign_p02_outcome_job.py --request') == 1
    assert raw.count('retention-days: 7') == 2
    assert 'system-p02-outcome-${{ github.sha }}' in raw
    assert 'system-p02-outcome-diagnostics-${{ github.sha }}' in raw
    assert all(name not in raw for name in ('daily.jsonl', 'book/', 'worker.log'))
