"""Local capacity evidence must reject incomplete work and resource pressure."""
import argparse
import ast
import inspect
import json

import pytest

from tools.acquisition_resources import fixtures, measurement, runner


def test_sampler_retains_phase_peaks_without_retaining_samples(tmp_path, monkeypatch):
    monitor = measurement.Measurement(tmp_path)
    monkeypatch.setattr(measurement, 'cgroup', lambda: {'final': True})
    monkeypatch.setattr(measurement, 'process_peak', lambda: 123)
    for index in range(10000):
        monitor._record(dict(phase='first' if index < 5000 else 'second',
            working=10000-index, anon=index, storage=dict(
                cache_bytes=index, partial_bytes=10000-index, other_bytes=1)))
    result = monitor.result()
    assert monitor.samples == result['samples'] == 10000
    assert len(monitor.phases) == 2
    assert result['phases']['first'] == dict(working_peak_bytes=10000, anon_peak_bytes=4999)
    assert result['phases']['second'] == dict(working_peak_bytes=5000, anon_peak_bytes=9999)
    assert result['working_peak_bytes'] == 10000
    assert result['sampled_disk_peaks'] == dict(cache_bytes=9999, partial_bytes=10000, other_bytes=1)


def healthy():
    return dict(cgroup=dict(limit=1000, events=dict(oom=0, oom_kill=0)),
                samples=10, working_peak_bytes=799)


def invalid(guard):
    value = healthy()
    if guard == 0:
        value["cgroup"]["limit"] = 2000
    elif guard == 1:
        value["samples"] = 0
    elif guard == 2:
        value["cgroup"]["events"]["oom"] = 1
    elif guard == 3:
        value["cgroup"]["events"]["oom_kill"] = 1
    elif guard == 4:
        value["working_peak_bytes"] = 800
    return value


def test_positive_control_and_memory_boundary():
    assert measurement.qualifies(healthy(), 1000)
    for peak in (0, -1, 800, 1000):
        value = healthy()
        value["working_peak_bytes"] = peak
        assert not measurement.qualifies(value, 1000)


@pytest.mark.parametrize("guard", range(5))
def test_pressure_or_missing_samples_refuses(guard):
    assert not measurement.qualifies(invalid(guard), 1000)


@pytest.mark.parametrize("key", ("oom", "oom_kill"))
def test_missing_kernel_events_cannot_pass(key):
    value = healthy()
    del value["cgroup"]["events"][key]
    with pytest.raises(KeyError):
        measurement.qualifies(value, 1000)


@pytest.mark.parametrize("guard", range(5))
def test_each_guard_has_a_killed_removal_mutant(guard):
    # Execute the actual predicate with exactly one conjunct removed. The same
    # negative input above must catch it, with a valid positive control retained.
    tree = ast.parse(inspect.getsource(measurement.qualifies))
    returned = tree.body[0].body[0].value
    assert isinstance(returned, ast.BoolOp) and len(returned.values) == 5
    returned.values[guard] = ast.Constant(value=True)
    namespace = {}
    exec(compile(ast.fix_missing_locations(tree), "<removed-resource-guard>", "exec"), namespace)
    mutant = namespace["qualifies"]
    assert mutant(healthy(), 1000)
    with pytest.raises(AssertionError):
        assert not mutant(invalid(guard), 1000)


def test_cgroup_working_set_excludes_inactive_file_cache(tmp_path):
    for name, value in {"memory.current": "900", "memory.peak": "950", "memory.max": "1000",
                        "memory.stat": "anon 300\ninactive_file 400\n",
                        "memory.events": "oom 0\noom_kill 0\n"}.items():
        (tmp_path / name).write_text(value)
    result = measurement.cgroup(tmp_path)
    assert result["working"] == 500 and result["anon"] == 300 and result["peak"] == 950
    (tmp_path / "memory.max").write_text("max\n")
    unbounded = measurement.cgroup(tmp_path)
    assert unbounded["limit"] is None and unbounded["working"] == result["working"]
    assert not measurement.qualifies({**healthy(), "cgroup": unbounded}, 1000)
    (tmp_path / "memory.peak").unlink()
    with pytest.raises(FileNotFoundError):
        measurement.cgroup(tmp_path)


@pytest.mark.parametrize("kernel_limit,expected", [("max", None), ("1000", 1000)])
def test_database_sampler_uses_the_kernel_ceiling(monkeypatch, kernel_limit, expected):
    stats = ("oom 0\noom_kill 0\nfile 100\ninactive_file 100\nactive_file 0\n"
             "anon 400\nshmem 0\nslab_unreclaimable 0\nkernel_stack 0\npagetables 0")
    monkeypatch.setattr(runner, "command", lambda *args: f"500\n600\n{kernel_limit}\n{stats}")
    result = runner.database_memory("database")
    assert result["limit"] == expected
    assert measurement.qualifies({**healthy(), "cgroup": result}, 1000) == (expected == 1000)


def test_native_resource_profile_reuses_retained_price_pages(tmp_path, monkeypatch):
    import threading
    from http.server import ThreadingHTTPServer
    from tests.support.postgres import _EphemeralPostgres
    from tools.acquisition_resources import worker
    profile = fixtures.Profile(name="test", securities=2, tickers=3, actions=7, formation=False)
    server = ThreadingHTTPServer(('127.0.0.1', 0), fixtures.handler(profile))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    db = _EphemeralPostgres()
    db.start()
    thread.start()
    try:
        monkeypatch.setenv('RESOURCE_DSN', db.sync_dsn)
        monkeypatch.setenv('SENTINEL_STATE_DIR', str(tmp_path))
        monkeypatch.setenv('ALPACA_API_KEY', 'fixture-data-id')
        monkeypatch.setenv('ALPACA_SECRET_KEY', 'fixture-data-secret')
        monkeypatch.setenv('OPENFIGI_API_KEY', 'fixture-mapping')
        from sentinel import backup_runtime_authority
        monkeypatch.setattr(backup_runtime_authority, 'POLICY_MARKER', tmp_path/'no-policy')
        result = worker.run(profile, 2, address=f'http://127.0.0.1:{server.server_port}')
        cold, replay = result['cycles']
        assert cold['rows'] == replay['rows'] == 600
        assert cold['provider']['/v2/stocks/bars'] == replay['provider']['/v2/stocks/bars'] > 0
        assert cold['provider']['/v3/mapping'] == replay['provider']['/v3/mapping'] > 0
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
        db.stop()


@pytest.mark.parametrize("failure", (RuntimeError, KeyboardInterrupt))
def test_primary_failure_is_retained_even_when_cleanup_fails(tmp_path, monkeypatch, failure):
    def command(*args, **kwargs):
        if args[1:3] == ("image", "inspect"):
            return '[{"Id":"synthetic-image"}]'
        if args[1:3] == ("network", "create"):
            return "created"
        if args[1:3] == ("volume", "create"):
            raise failure("primary creation failure")
        if args[1] == "inspect":
            return "[]"
        raise RuntimeError("cleanup failure")
    monkeypatch.setattr(runner, "command", command)
    output = tmp_path / "report.json"
    args = argparse.Namespace(profile="smoke", worker_memory_mib=4096,
                              worker_cpus=2, deadline_seconds=60, image="fixture", output=output, cycles=2)
    assert runner.run(args)
    result = json.loads(output.read_text())
    assert result["verdict"] == "FAIL"
    assert "primary creation failure" in result["failure"]
    assert "cleanup failure" in result["cleanup_errors"][0]
