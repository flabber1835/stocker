from __future__ import annotations

import importlib.util
import datetime as dt
import hashlib
import hmac
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import shutil
import contextlib
from types import SimpleNamespace

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "tools" / "production_go_e2e_harness.py"
SPEC = importlib.util.spec_from_file_location("production_go_e2e_harness", PATH)
assert SPEC is not None and SPEC.loader is not None
harness = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(harness)

FULL_QUALIFICATION = "${{ needs.qualification-source.outputs.mode == 'full' }}"
MANUAL_FULL_GO = (
    "${{ needs.qualification-source.outputs.mode == 'full' && "
    "(github.event_name == 'workflow_dispatch') }}")


def _require_manual_full_go(workflow):
    composition = workflow["jobs"]["composition"]
    assert composition["strategy"]["matrix"]["campaign"] == (
        "${{ fromJSON(github.event_name != 'workflow_dispatch' && '[\"smoke\"]' || "
        "inputs.campaign == 'positive' && '[\"positive\"]' || "
        "'[\"operator\",\"preparation\",\"financial\",\"handoff\"]') }}")
    dispatch = workflow.get("on", workflow.get(True))["workflow_dispatch"]["inputs"]["campaign"]
    assert dispatch["default"] == "all"
    assert dispatch["options"] == ["all", "positive"]
    steps = composition["steps"]
    launchers = [step for step in steps
                 if "python tools/production_go_e2e_audit.py" in step.get("run", "")]
    assert len(launchers) == 1
    assert '"${sensitivity[@]}"' in launchers[0]["run"]
    assert "if [ '${{ matrix.campaign }}' != positive ]; then" in launchers[0]["run"]
    assert "sensitivity=(--sensitivity)" in launchers[0]["run"]
    evidence = next(step for step in steps
                    if step.get("name") == "Verify canonical GO evidence")
    for step in [*launchers, evidence]:
        assert step.get("if") == MANUAL_FULL_GO
    assert composition["needs"] == ["qualification-source", "database-preflight"]
    preflight = workflow["jobs"]["database-preflight"]
    assert preflight["needs"] == "qualification-source"
    checks = {
        "Run authority matrix and real host-process regressions",
        "Re-run adjacent GO authority regressions",
        "Run physical restore and upgrade seam",
        "Run real Docker/PostgreSQL composition gates",
        "Verify live evidence",
    }
    automatic = [step for step in steps if step.get("name") in checks]
    assert len(automatic) == len(checks)
    assert all(step.get("if") == FULL_QUALIFICATION for step in automatic)
    database_check = next(step for step in preflight["steps"]
                          if step.get("name") == "Exercise real read-only cursors and predecessor plan")
    assert database_check.get("if") == FULL_QUALIFICATION
    assert "if" not in workflow["jobs"]["database-preflight"]
    assert "if" not in composition


def test_full_go_is_manual_but_fast_checks_remain_automatic():
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/production-composition-harness.yml").read_text())
    _require_manual_full_go(workflow)
    for step in workflow["jobs"]["composition"]["steps"]:
        if step.get("if") == MANUAL_FULL_GO:
            guard = step.pop("if")
            with pytest.raises(AssertionError):
                _require_manual_full_go(workflow)
            step["if"] = guard


@pytest.mark.parametrize("replacement", [None, FULL_QUALIFICATION,
    "github.event_name == 'workflow_dispatch'",
    "${{ needs.qualification-source.outputs.mode == 'full' || "
    "(github.event_name == 'workflow_dispatch') }}"])
def test_full_go_rejects_loss_of_either_manual_or_qualification_guard(replacement):
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/production-composition-harness.yml").read_text())
    for step in workflow["jobs"]["composition"]["steps"]:
        if step.get("if") == MANUAL_FULL_GO:
            step["if"] = replacement
            with pytest.raises(AssertionError):
                _require_manual_full_go(workflow)
            step["if"] = MANUAL_FULL_GO


@pytest.mark.parametrize("job,step_name", [
    ("composition", "Run authority matrix and real host-process regressions"),
    ("database-preflight", "Exercise real read-only cursors and predecessor plan"),
])
def test_fast_composition_checks_cannot_become_manual(job, step_name):
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/production-composition-harness.yml").read_text())
    step = next(step for step in workflow["jobs"][job]["steps"]
                if step.get("name") == step_name)
    step["if"] = MANUAL_FULL_GO
    with pytest.raises(AssertionError):
        _require_manual_full_go(workflow)


def test_script_process_can_load_production_session_calendar(tmp_path):
    python_path = os.pathsep.join(filter(None, (
        str(ROOT / "shared"), os.environ.get("PYTHONPATH", ""))))
    env = dict(os.environ, PYTHONPATH=python_path)
    completed = subprocess.run(
        [sys.executable, "-c",
         "import runpy,sys; h=runpy.run_path(sys.argv[1]); "
         "assert h['_latest_closed_session']().isoformat()", str(PATH)],
        cwd=tmp_path, env=env, text=True, capture_output=True, timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_canonical_entrypoint_is_real_production_go():
    assert harness.ENTRYPOINT == ("bash", "scripts/sentinel-go-validate.sh")
    assert harness.REQUIRED_PHASES[-3:] == (
        "CERTIFICATION + FINANCIAL READINESS",
        "PROMOTE EXACT CERTIFIED RUNTIME",
        "POST-VALIDATION HANDOFF",
    )


def test_full_go_budget_covers_measured_work_and_preserves_refusal(monkeypatch):
    from scripts import sentinel_go_observability as observability

    # Run 35900585894: complete lens 11,952s, preparation 571s, first
    # image proof 1,242s. Both images must run; retain 20m for later gates.
    measured_work = 11952 + 571 + 2 * 1242 + 1200
    deadlines = []
    prepared = []

    def replay_timing(controller, go, command, *, cwd, env, raw_stream):
        deadline = observability._timeout_seconds(controller, go, command)
        deadlines.append(deadline)
        assert raw_stream is True
        assert command == [*harness.ENTRYPOINT, '--local-full-certification',
                           '--target', 'SHADOW']
        return subprocess.CompletedProcess(
            command, 0 if measured_work < deadline else 124,
            stdout='measured timeline', stderr='')

    monkeypatch.setattr(harness, '_bootstrap_financial_fixture',
                        lambda: prepared.append(True))
    monkeypatch.setattr(harness, '_fixture_cli', contextlib.nullcontext)
    monkeypatch.setattr(observability, '_streaming_run', replay_timing)
    assert harness._invoke().returncode == 0
    assert prepared == [True]
    # An actual refusal is returned unchanged; a larger default is not a bypass.
    assert harness._invoke(timeout=measured_work - 1,
                           prepare_fixture=False).returncode == 124
    assert prepared == [True]

    workflow = yaml.safe_load(
        (ROOT / '.github/workflows/production-composition-harness.yml').read_text())
    budget = workflow['jobs']['composition']['timeout-minutes']
    matched = re.search(r"workflow_dispatch' && (\d+) \|\| (\d+)", budget)
    assert matched is not None
    # Fixture/build/retention run outside GO's clock; do not shorten PR smoke.
    assert int(matched[1]) * 60 >= deadlines[0] + 30 * 60
    assert int(matched[2]) == 180


@pytest.mark.parametrize("initial", ["0", "1", ""])
def test_cold_go_establishes_real_backup_before_schema_and_requires_empty_history(monkeypatch, tmp_path, initial):
    calls = []
    key = 'fixture-receipt-key-'+'1'*32
    (tmp_path/'.env').write_text('SENTINEL_PUBLICATION_RECEIPT_KEY='+key)
    monkeypatch.setattr(harness, 'ROOT', tmp_path)
    monkeypatch.setattr(harness, "_FIXTURE_READY", False)
    monkeypatch.setattr(harness, "VALIDATED_RUNTIME_POINTER", tmp_path / "selection")
    monkeypatch.setattr(harness, "_git_head", lambda: "a"*40)
    monkeypatch.setattr(harness, "_compose_service_container_id", lambda *a, **k: "b"*64)
    def host(argv, **kw):
        calls.append(argv)
        if 'schema.ensure_schema' in argv[-1]:
            assert '-e' in argv and 'SENTINEL_PUBLICATION_RECEIPT_KEY' in argv
            assert kw['env']['SENTINEL_PUBLICATION_RECEIPT_KEY'] == key
        return subprocess.CompletedProcess(argv, 0, stdout=initial if "SELECT count(*)" in argv[-1] else "")
    monkeypatch.setattr(harness, "_run_host", host)
    if initial == "0":
        harness._bootstrap_financial_fixture()
        assert harness.SEEDED_PUBLICATION == {"version": 0, "visible_frontier": None}
    else:
        with pytest.raises(harness.HarnessFailure, match="empty publication history"):
            harness._bootstrap_financial_fixture()
    assert next(i for i,row in enumerate(calls) if 'scripts/sentinel-base-backup.sh' in row) < next(
        i for i,row in enumerate(calls) if 'schema.ensure_schema' in row[-1])


def test_publication_observer_authenticates_with_the_fixture_receipt_key(
        monkeypatch, tmp_path):
    from scripts import sentinel_env
    from sentinel.feed import publication

    key_name = publication.RECEIPT_KEY_ENV
    monkeypatch.delenv(key_name, raising=False)
    monkeypatch.setattr(harness, "ROOT", tmp_path)
    monkeypatch.setattr(harness, "_SOURCE_SETTINGS", {})
    monkeypatch.setattr(harness, "_docker_host_gateway", lambda: "127.0.0.1")
    monkeypatch.setattr(harness, "_git_head", lambda: "a" * 40)
    harness._write_env(tmp_path / ".env", port=8123, backup_dir=tmp_path / "backup")
    seeded_key = sentinel_env.load(tmp_path / ".env")[key_name]
    assert sentinel_env.load(tmp_path / ".env")["SENTINEL_SHADOW_STARTING_CASH"] == "50000"
    receipt = {"publication_version": 1, "run_id": "fixture-seed"}
    expected = hmac.new(
        seeded_key.encode(), json.dumps(
            receipt, sort_keys=True, separators=(",", ":")).encode(),
        hashlib.sha256).hexdigest()
    observed = []

    def run_host(argv, *, env, timeout):
        if argv[0] == "bash":
            checked = subprocess.run(
                ["bash", "-c",
                 '. "$1"; PYTHON="$2"; shift 2; sentinel_require_compose_envelope "$@"',
                 "observer-test", str(ROOT / "scripts/sentinel-env.sh"),
                 sys.executable, "base", *argv[3:]],
                text=True, capture_output=True, timeout=10, check=False)
            assert checked.returncode == 0, checked.stderr
            return subprocess.CompletedProcess(argv, 0, stdout="b" * 64 + "\n")
        assert argv[:2] == ["docker", "run"]
        # Apply Docker's explicit environment forwarding, then authenticate a
        # receipt with the actual production guard. Ambient host values alone
        # cannot make a missing container setting pass this check.
        container_env = {}
        for index, arg in enumerate(argv[:-1]):
            if arg in {"-e", "--env"}:
                name, separator, value = argv[index + 1].partition("=")
                container_env[name] = value if separator else env.get(name, "")
        with monkeypatch.context() as process:
            process.delenv(key_name, raising=False)
            for name, value in container_env.items():
                process.setenv(name, value)
            observed.append(publication._receipt_hmac(receipt))
        return subprocess.CompletedProcess(argv, 0, stdout='{"version": 1}')

    monkeypatch.setattr(harness, "_run_host", run_host)
    harness._publication_identity()
    assert observed == [expected]


@pytest.mark.parametrize("rolling", [False, True], ids=["legacy-seed", "rolling-startup"])
def test_publication_observer_reads_the_selected_generation(monkeypatch, tmp_path, capsys, rolling):
    from sentinel.core import decision
    from sentinel.feed import rolling_go_inputs, store

    selected = SimpleNamespace(version=2, window_end="2026-09-22")
    events = []

    class Connection:
        def cursor(self):
            return contextlib.nullcontext(self)
        def execute(self, sql):
            assert "REPEATABLE READ, READ ONLY" in sql
        def rollback(self):
            events.append("rollback")
        def close(self):
            events.append("close")

    @contextlib.contextmanager
    def pinned(conn):
        assert isinstance(conn, Connection)
        events.append("authenticated pin")
        yield selected

    monkeypatch.setattr(harness, "ROOT", tmp_path)
    (tmp_path / ".env").write_text("SENTINEL_POSTGRES_PASSWORD=fixture\n")
    monkeypatch.setattr(harness, "_compose_service_container_id", lambda *_a, **_k: "b" * 64)
    monkeypatch.setattr(harness, "_git_head", lambda: "a" * 40)
    monkeypatch.setenv("SENTINEL_DATABASE_URL", "fixture-only")
    monkeypatch.setattr(store, "connect", lambda _: Connection())
    monkeypatch.setattr(rolling_go_inputs, "pinned", pinned)
    monkeypatch.setattr(rolling_go_inputs, "is_rolling", lambda value: rolling)
    monkeypatch.setattr(decision, "publication_fingerprint", lambda value: "c" * 64)

    def legacy_frontier(conn):
        assert not rolling, "rolling generation must not read an older legacy frontier"
        return "2026-09-21"

    monkeypatch.setattr(store, "latest_visible_session", legacy_frontier)

    def run_host(argv, **_kwargs):
        assert argv[-2] == "-c"
        exec(compile(argv[-1], "<publication-observer>", "exec"), {})
        return subprocess.CompletedProcess(argv, 0, stdout=capsys.readouterr().out)

    monkeypatch.setattr(harness, "_run_host", run_host)
    value = harness._publication_identity()
    assert value == dict(version=2, publication_fingerprint="c" * 64,
                        visible_frontier="2026-09-22" if rolling else "2026-09-21")
    assert events == ["authenticated pin", "rollback", "close"]


def test_compose_go_child_gets_alpaca_keys_only_for_preparation():
    compose = (ROOT / "docker-compose.sentinel.yml").read_text(encoding="utf-8")
    go_child = compose.split("  sentinel:\n", 1)[1].split("  sentinel-panel:\n", 1)[0]
    assert "ALPACA_API_KEY:" not in go_child
    assert "ALPACA_SECRET_KEY:" not in go_child
    assert "OPENFIGI_API_KEY:" not in go_child
    preparation = (ROOT / "scripts/sentinel_go_validate.py").read_text(encoding="utf-8")
    assert '"--env", "ALPACA_API_KEY"' in preparation
    assert '"--env", "ALPACA_SECRET_KEY"' in preparation


def test_phase_parser_is_stage_sensitive():
    output = "\n=== HOST COMPATIBILITY ===\n[GO] ok\n=== RUNTIME SELECTION PREFLIGHT ===\n"
    assert harness._phase_names(output) == [
        "HOST COMPATIBILITY", "RUNTIME SELECTION PREFLIGHT"
    ]


def test_preparation_child_uses_native_clients_against_isolated_http_fixture(monkeypatch):
    from sentinel.feed import alpaca_transport, openfigi, publisher_pipeline
    from sentinel.feed.alpaca_source import AlpacaSource
    monkeypatch.setenv('ALPACA_API_KEY', 'fixture-data-id')
    monkeypatch.setenv('ALPACA_SECRET_KEY', 'fixture-data-secret')
    monkeypatch.setenv('OPENFIGI_API_KEY', 'fixture-mapping')
    monkeypatch.setattr(publisher_pipeline, '_operational_source', publisher_pipeline._operational_source)
    child = ['compose', 'run', '--entrypoint', 'python', 'sentinel', '-c',
             "marker = 'SENTINEL_GO_PREPARATION='"]
    with harness._source_server(end='2026-09-25', bind='127.0.0.1') as port:
        address = f'http://127.0.0.1:{port}'
        assert harness.fixture_docker_arguments(['compose', 'up'], address) == ['compose', 'up']
        exec(harness.fixture_docker_arguments(child, address)[-1], {})
        source = publisher_pipeline._operational_source(None, None, None, corrections=None, verify_during_coverage=False)
        assert isinstance(source, AlpacaSource)
        assets, _ = source.client.get(alpaca_transport.ASSETS)
        selected = openfigi.inventory(assets)[2:3]
        mapped, _ = source.classifier.mapping(selected)
        assert openfigi.classify(selected[0], mapped[0])[0]
        bars = list(source.client.pages(alpaca_transport.BAR_URL, {'symbols': 'S00000,SPY', 'timeframe':'1Day',
            'adjustment':'raw', 'feed':'sip', 'start':'2026-09-21', 'end':'2026-09-22', 'limit': 1}, key='bars'))
        assert len(bars) == 4 and {tuple(page) for page,_ in bars} == {('S00000',), ('SPY',)}
        actions = list(source.client.pages(alpaca_transport.ACTION_URL, {'start':'2026-09-01',
            'end':'2026-09-30', 'limit': 2}, key='corporate_actions'))
        assert len(actions) == 2 and actions[0][0]['cash_dividends'][0]['rate'] == '0.01'
        later = list(source.client.pages(alpaca_transport.ACTION_URL, {'start': '2026-10-01',
            'end': '2026-10-02', 'limit': 2}, key='corporate_actions'))
        assert [page['cash_dividends'] for page, _ in later] == [[]]
        harness.require_provider_requests(harness.SOURCE_REQUESTS)
        for endpoint in ('/v2/assets', '/v3/mapping', '/v2/stocks/bars', '/v1/corporate-actions'):
            with pytest.raises(harness.HarnessFailure, match='incomplete'):
                harness.require_provider_requests([r for r in harness.SOURCE_REQUESTS if r['endpoint'] != endpoint])
        monkeypatch.setenv('ALPACA_SECRET_KEY', 'unexpected')
        with pytest.raises(ValueError, match='only synthetic'):
            source.client.get(alpaca_transport.ASSETS)

def test_go_preparation_publishes_authenticated_native_history_and_reuses_it(monkeypatch, tmp_path):
    from datetime import datetime, timedelta, timezone
    from sentinel import backup_runtime_authority, identity, operational_schema, retained_go, schema
    from sentinel.feed import operational_snapshot, publisher_pipeline, publication, rolling_builder
    from sentinel.feed import rolling_go_inputs, rolling_store, runtime_schema, store
    from tests.support.postgres import _EphemeralPostgres
    from tools.acquisition_resources.fixtures import Profile

    # This reduced cardinality run exercises real production formation and
    # publication. The full GO campaign uses the production equity floor.
    profile = Profile(name='pr', securities=3, tickers=4, actions=7)
    monkeypatch.setattr(rolling_builder, 'MIN_ADMITTED_COMMON_STOCKS', 3)
    monkeypatch.setattr(backup_runtime_authority, 'POLICY_MARKER', tmp_path/'no-backup-media')
    monkeypatch.setattr(identity, 'require_feed_producer_identity',
                        lambda: {'schema':'fixture-producer/1','git_commit':'a'*40})
    monkeypatch.setattr(publisher_pipeline, '_operational_source', publisher_pipeline._operational_source)
    monkeypatch.setenv('ALPACA_API_KEY', 'fixture-data-id')
    monkeypatch.setenv('ALPACA_SECRET_KEY', 'fixture-data-secret')
    monkeypatch.setenv('OPENFIGI_API_KEY', 'fixture-mapping')
    monkeypatch.setenv(publication.RECEIPT_KEY_ENV, 'fixture-publication-receipt-'+'1'*32)
    target = "2026-09-25"
    monkeypatch.setattr(operational_snapshot, '_now', lambda: datetime(2026, 9, 26, tzinfo=timezone.utc))
    server = _EphemeralPostgres()
    server.start()
    try:
        with harness._source_server(profile=profile, end=target, bind='127.0.0.1') as port, store.connect(server.sync_dsn) as db:
            schema.ensure_schema(db)
            runtime_schema.migrate_feed_schema(db)
            operational_schema.install_quiescent(db)
            child = ['compose','run','--entrypoint','python','sentinel','-c',"mark='SENTINEL_GO_PREPARATION='"]
            exec(harness.fixture_docker_arguments(child, f'http://127.0.0.1:{port}')[-1], {})
            deadline = datetime.now(timezone.utc) + timedelta(minutes=5)
            receipt = retained_go.prepare(db, target_session=target, absolute_deadline=deadline)
            with rolling_go_inputs.pinned(db) as active:
                assert active.window_end == target and active.version == receipt['data_version']
            manifest = rolling_store.manifest(db, receipt['candidate_id'])
            assert manifest.provider == 'ALPACA_OPENFIGI'
            assert manifest.bar_count == len(manifest.window.sessions)*3 == 426*3
            original = list(harness.SOURCE_REQUESTS)
            harness.require_provider_requests(original)
            again = retained_go.prepare(db, target_session=target, absolute_deadline=deadline)
            assert again['candidate_id'] == receipt['candidate_id']
            assert harness.SOURCE_REQUESTS == original
    finally:
        server.stop()

def test_shadow_host_account_probe_reaches_only_the_refusing_local_fixture(monkeypatch):
    import urllib.request
    from urllib.error import URLError
    from scripts import sentinel_go_validate as go
    monkeypatch.setattr(harness.shutil, 'which', lambda *args, **kwargs: '/usr/bin/docker')
    monkeypatch.setattr(urllib.request, '_opener', None)
    with harness._source_server(end='2026-09-25', bind='127.0.0.1') as port:
        local = f'http://127.0.0.1:{port}'
        monkeypatch.setattr(harness, '_SOURCE_SETTINGS', dict(address=local))
        with harness._fixture_cli({}) as private_env, monkeypatch.context() as host:
            for key in ('HTTPS_PROXY', 'https_proxy', 'NO_PROXY', 'no_proxy'):
                host.setenv(key, private_env[key])
            errors = []
            def observe(request, **kwargs):
                try:
                    return urllib.request.urlopen(request, **kwargs)
                except URLError as exc:
                    errors.append(str(exc.reason))
                    raise
            gate, _ = go.probe_alpaca_account(env=dict(ALPACA_API_KEY='fixture-data-id',
                ALPACA_SECRET_KEY='fixture-data-secret'), now_text='2026-09-25T21:00:00Z', urlopen=observe)
            assert gate.status != go.PASS
            assert len(errors) == 1 and '403' in errors[0]
            assert not harness.SOURCE_REQUESTS
