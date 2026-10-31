"""Pure predecessor and exact-entrypoint admission; no hosted process invoked."""
import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
SOURCE = HERE / 'system_campaign_p02_h2_2023_job.py'


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
                 '<pure-h2-admission-contract>', 'exec'), namespace)
    return namespace[name]


def request_function(tmp_path, spec, *, remove_guard=False):
    selected = tmp_path / 'selected.json'
    selected.write_text(json.dumps(spec), encoding='utf8')

    class Root:
        def __truediv__(self, name):
            return selected if name == 'system-campaign-p02-h2-2023-predecessor.json' else HERE / name

    return function('expected_request', dict(
        HERE=Root(), json=json, need=need, SOURCES=(),
        sha256_file=lambda p: hashlib.sha256(p.read_bytes()).hexdigest(),
        PACKET_SOURCE_PATH='research/pooled_input_support/adapter.py'), remove_guard=remove_guard)


@pytest.mark.parametrize('field,value', [('arm', 'P03'), ('run_id', 41174261514),
    ('selected_session', '2023-08-07'), ('review_refusal', True)])
def test_other_candidate_old_parent_unsent_session_or_unadmitted_review_refuses(tmp_path, field, value):
    spec = json.loads((HERE / 'system-campaign-p02-h2-2023-predecessor.json').read_bytes())
    spec[field] = value
    with pytest.raises(ValueError, match='EXACT_CALENDAR_OWN_PREDECESSOR'):
        request_function(tmp_path, spec)()


def test_actual_parent_guard_removal_falsifier(tmp_path):
    spec = json.loads((HERE / 'system-campaign-p02-h2-2023-predecessor.json').read_bytes())
    spec['selected_session'] = '2023-08-07'
    with pytest.raises(ValueError):
        request_function(tmp_path, spec)()
    request_function(tmp_path, spec, remove_guard=True)()


def test_exact_financial_entrypoint_guard_and_its_removal():
    value = dict(Config=dict(Cmd=['-B', '-u', '/driver/system_campaign_p02_h2_2023_run.py',
        '--mode', 'economic', '--spec', '/out/spec.json',
        '--request', '/driver/system-campaign-p02-h2-2023-request.json']))
    actual = deepcopy(value)
    ns = dict(need=need, prior_inspect=lambda name, identity: actual)
    inspect = function('inspect', ns)
    assert inspect('capital-system-factual-p02-worker-123-1') == value
    actual['Config']['Cmd'][2] = '/driver/system_campaign_p02_spring2023_run.py'
    with pytest.raises(ValueError, match='EXACT_FINANCIAL_OR_REVIEW_ENTRYPOINT'):
        inspect('capital-system-factual-p02-worker-123-1')
    function('inspect', ns, remove_guard=True)('capital-system-factual-p02-worker-123-1')
