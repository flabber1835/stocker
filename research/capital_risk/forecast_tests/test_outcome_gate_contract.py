"""Pure scope and identity checks; no canonical controller is imported."""
import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from pathlib import PurePosixPath
from types import SimpleNamespace

import pytest

HERE = Path(__file__).resolve().parents[1]
SOURCE = HERE / 'system_campaign_outcome_gate_job.py'


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
                 '<pure-outcome-gate-scope>', 'exec'), namespace)
    return namespace[name]


def selected(tmp_path, spec, *, remove_guard=False):
    path = tmp_path / 'selected.json'
    path.write_text(json.dumps(spec), encoding='utf8')

    class Root:
        def __truediv__(self, name):
            return path if name == 'system-campaign-outcome-gate-predecessor.json' else HERE / name

    return function('expected_request', dict(HERE=Root(), json=json, need=need, SOURCES=(),
        sha256_file=lambda p: hashlib.sha256(p.read_bytes()).hexdigest()), remove_guard=remove_guard)


@pytest.mark.parametrize('field,value', [('arm', 'P03'), ('run_id', 41183110747),
    ('outer_sha256', 'b' * 64), ('selected_session', '2023-08-22')])
def test_other_arm_older_same_date_cp_or_logged_tail_cannot_be_selected(tmp_path, field, value):
    spec = json.loads((HERE / 'system-campaign-outcome-gate-predecessor.json').read_bytes())
    spec[field] = value
    with pytest.raises(ValueError, match='EXACT_OWN_ADMITTED_32_INPUT_PARENT'):
        selected(tmp_path, spec)()


def test_predecessor_guard_removal_falsifier(tmp_path):
    spec = json.loads((HERE / 'system-campaign-outcome-gate-predecessor.json').read_bytes())
    spec['run_id'] = 41183110747
    with pytest.raises(ValueError):
        selected(tmp_path, spec)()
    selected(tmp_path, spec, remove_guard=True)()


def test_financial_entrypoint_cannot_replace_the_component_gate():
    value = dict(Config=dict(Cmd=['-B', '-u', '/driver/system_campaign_outcome_gate.py',
        '--spec', '/out/spec.json', '--request', '/driver/system-campaign-outcome-gate-request.json']))
    current = deepcopy(value)
    namespace = dict(need=need, prior_inspect=lambda name, identity: current)
    inspect = function('inspect', namespace)
    assert inspect('capital-system-factual-p02-worker-123-1') == value
    current['Config']['Cmd'][2] = '/driver/system_campaign_p02_chinook_run.py'
    with pytest.raises(ValueError, match='EXACT_ZERO_FINANCIAL_ENTRYPOINT'):
        inspect('capital-system-factual-p02-worker-123-1')
    function('inspect', namespace, remove_guard=True)('capital-system-factual-p02-worker-123-1')


def test_inherited_sources_are_byte_identical_and_new_job_has_no_financial_call():
    prior = json.loads((HERE / 'system-campaign-p02-chinook-request.json').read_bytes())
    new = json.loads((HERE / 'system-campaign-outcome-gate-request.json').read_bytes())
    assert len(new['sources']) == 211
    assert all(new['sources'][name] == h for name, h in prior['sources'].items())
    assert not new['financial_replay_started'] and not new['new_input_adopted']
    for name in ('system_campaign_outcome_gate.py', 'system_campaign_outcome_gate_job.py'):
        tree = ast.parse((HERE / name).read_bytes())
        calls = [ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)]
        assert all('backtest' not in call for call in calls)
    raw = (HERE.parents[1] / '.github/workflows/capital-system-outcome-proof-gate.yml').read_text()
    assert "paths: ['research/capital_risk/system-campaign-outcome-gate-request.json']" in raw
    assert raw.count('system_campaign_outcome_gate_job.py --request') == 1
    assert 'group: system-optimization-002-p02-only' in raw
    assert 'cancel-in-progress: false' in raw and 'retention-days: 7' in raw
    assert all(name not in raw for name in ('book/', 'daily.jsonl', 'worker.log'))


def destination_guard(*, remove_guard=False):
    """Execute only the real path/capacity predicate on pure POSIX path objects."""
    class HostedPath(PurePosixPath):
        def resolve(self):
            return self

    tree = ast.parse((HERE / 'system_campaign_factual_admit.py').read_bytes())
    fn, = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'hosted_destination']
    if remove_guard:
        guards = [n for n in fn.body if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
                  and isinstance(n.value.func, ast.Name) and n.value.func.id == 'need']
        assert len(guards) == 1
        guards[0].value = ast.Constant(None)
    namespace = dict(Path=HostedPath, need=need, check_context=lambda env: None,
        os=SimpleNamespace(name='posix', environ={'RUNNER_TEMP': '/home/runner/work/_temp'}),
        shutil=SimpleNamespace(disk_usage=lambda p: SimpleNamespace(free=16 * 1024**3)))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])),
                 '<actual-hosted-destination-predicate-no-filesystem>', 'exec'), namespace)
    return namespace['hosted_destination']


def test_actual_component_destination_satisfies_existing_admission_guard():
    tree = ast.parse(SOURCE.read_bytes())
    call, = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name) and n.func.id == 'admit']
    expression = call.args[1]
    assert isinstance(expression, ast.BinOp) and ast.unparse(expression.left) == 'temp'
    suffix = ast.literal_eval(expression.right)
    assert str(destination_guard()('/home/runner/work/_temp/' + suffix)).endswith('/' + suffix)


def test_prior_rejected_path_and_actual_destination_guard_removal_falsifier():
    wrong = '/home/runner/work/_temp/outcome-gate-admitted-predecessor'
    with pytest.raises(ValueError, match='HOSTED_FACTUAL_DESTINATION_CAPACITY'):
        destination_guard()(wrong)
    assert str(destination_guard(remove_guard=True)(wrong)) == wrong
