"""Pure timing-wrapper and boundary tests; no historical financial execution."""
import importlib.util
import io
import json
from pathlib import Path
import pytest

PATH = Path(__file__).resolve().parents[1]/'full_system_benchmark.py'
spec = importlib.util.spec_from_file_location('full_system_benchmark_test', PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_observation_returns_same_object_and_separates_profiled_calls(tmp_path):
    result = object(); seen = []
    def original(value, *, amount):
        seen.append((value, amount)); return result
    stream = (tmp_path/'timings.jsonl').open('w+'); wrapped = module.wrap_call(original, 'test', stream, 2)
    assert wrapped(4, amount=7) is result
    assert wrapped(9, amount=2) is result
    assert seen == [(4, 7), (9, 2)]
    stream.seek(0); rows = [json.loads(s) for s in stream.read().splitlines()]; stream.close()
    assert [r['ordinal'] for r in rows] == [1, 2]
    assert [r['profiled'] for r in rows] == [False, True]
    assert 'profile' not in rows[0] and rows[1]['profile']


def test_observation_preserves_exception_and_records_failure_timing(tmp_path):
    stream = (tmp_path/'timings.jsonl').open('w+'); error = ValueError('synthetic original failure')
    def original(): raise error
    wrapped = module.wrap_call(original, 'test', stream, 1)
    with pytest.raises(ValueError) as caught: wrapped()
    assert caught.value is error
    stream.seek(0); assert json.loads(stream.read())['profiled'] is True; stream.close()


def test_measurement_refuses_local_financial_entry(monkeypatch):
    monkeypatch.delenv('FULL_SYSTEM_HOSTED', raising=False)
    with pytest.raises(ValueError, match='HOSTED_ONLY'): module.measure()
    # Actual guard-removal falsifier: a missing guard reaches its next hosted
    # filesystem dependency. It must not execute a historical transition.
    source = PATH.read_text()
    guarded = "need(os.environ.get('FULL_SYSTEM_HOSTED') == '1' and Path('/fixed').is_dir()\n         and str(Path(__file__).resolve()).startswith('/driver/'), 'HOSTED_ONLY')"
    assert source.count(guarded) == 1
    broken = source.replace(guarded, 'pass', 1)
    namespace = {'__name__': 'guard_removal_test', '__file__': str(PATH)}
    exec(compile(broken, str(PATH), 'exec'), namespace)
    with pytest.raises(FileNotFoundError): namespace['measure']()
