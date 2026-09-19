"""Admission through real sealed inputs and signed local authority, no broker."""
from contextlib import redirect_stdout
from copy import deepcopy
from datetime import datetime, timezone
from io import StringIO
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives import serialization

from sentinel import authority, binding, observation_authority as observation
from sentinel.core.decision import publication_fingerprint
from sentinel.feed import readers, readiness, publication, rolling_go_inputs
from sentinel.strategy import production_strategy
from tests.sentinel.test_rolling_go_inputs import issuer_source  # noqa: F401
from tests.sentinel.test_rolling_initialization import ready, start  # noqa: F401
from tests.sentinel.test_operational_snapshot import operational_source  # noqa: F401
from tests.sentinel.test_rolling_snapshot_publisher import conn, pg, source  # noqa: F401
from tests.sentinel.test_paper_observation_authority import (
    PRIVATE, KEY_ID, ROOTS, context, runtime_identity,
)

NOW = datetime(2026, 9, 15, 4, tzinfo=timezone.utc)


@pytest.fixture
def metadata_source(issuer_source):
    # Retain provider display text and extra numeric fields without imposing
    # signed-claim string restrictions on the immutable reference payload.
    issuer_source["TICKERS"][0].update(name="Cafe\u0301 Industries", numeric_extra="1.25")
    return issuer_source


@pytest.fixture
def published(metadata_source, ready):
    return ready


def _runtime():
    return {**runtime_identity(), "environment": {
        "compatible": True, "pins_match": True, "sources_known": True,
        "pin_drift": {}, "sentinel_source": {"hash": "b" * 64},
        "wealth_core_source": {"hash": "c" * 64}, "image_lock_sha256": "f" * 64}}


def _candidate(conn, warmup):
    return observation.build_candidate(
        conn, certificate_id="rolling-admission-0001", issuer_generation=1,
        deployment_id="nas-paper-observe", expected_account="paper-123",
        runtime_identity=_runtime(), strategy_identity=production_strategy()[1],
        automation_config_sha256="4" * 64, warmup=warmup,
        maximum_exposure="0.5", reviewer="offline-test", ticket="A21",
        not_before=NOW, now=NOW)


def _bind(conn):
    binding.bind(conn, deployment_id="nas-paper-observe", broker="alpaca",
                 broker_account_id="paper-123")


def test_warmup_is_the_selected_canonical_production_transition(conn, published):
    evidence = observation.current_warmup_evidence(conn, starting_cash=100000)
    assert evidence["warmup_sessions"] == 252
    assert evidence["measured_sessions"] == 253
    assert evidence["historical_certification"] == "NOT_GRANTED"
    assert evidence["strategy_identity_sha256"] == authority.canonical_sha256(production_strategy()[1])
    assert conn.execute("SELECT COUNT(*) FROM sentinel_processed_sessions").fetchone()[0] == 0
    conn.commit()
    # The independently invoked production initializer must reach this state.
    # Twenty slots, no positions/fills and unchanged cash falsify V1 bootstrap.
    actual = start(conn).state
    assert len(actual.wealth_core["slots"]) == 20
    assert not actual.wealth_core["episodes"] and actual.wealth_core["cash"] == 100000
    assert actual.state_hash == evidence["result_state_sha256"]
    assert conn.execute("SELECT COUNT(*) FROM sentinel_fills").fetchone()[0] == 0


def test_signed_rolling_candidate_installs_and_activates_with_reobserved_inputs(
        conn, published, tmp_path):
    from tools.sentinel_observation_authority import issue
    _bind(conn)
    warmup = observation.current_warmup_evidence(conn, starting_cash=100000)
    candidate = _candidate(conn, warmup)
    metadata = candidate["claims"]["bindings"]["current_metadata_snapshot"]
    assert metadata["snapshot_date"] == "2026-09-15"  # provider refresh, not decision date
    assert metadata["row_count"] == 25
    assert conn.execute("SELECT COUNT(*) FROM sentinel_universe").fetchone()[0] == 0
    document = tmp_path / "candidate.json"
    document.write_bytes(authority.canonical_json_bytes(candidate))
    private = tmp_path / "offline-test-key.pem"
    private.write_bytes(PRIVATE.private_bytes(serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    private.chmod(0o600)
    certificate = tmp_path / "certificate.json"
    digest = issue(candidate=document, private_key_file=private, key_id=KEY_ID,
                   output=certificate)
    claims = candidate["claims"]
    observed = authority.bind_current_immutable_identities(
        claims["bindings"], runtime_identity=_runtime(),
        strategy_identity=production_strategy()[1], paper_base_url=authority.PAPER_BASE_URL,
        automation_config_sha256="4" * 64, **observation.current_input_bindings(conn))
    ctx = context({**claims, "bindings": observed})
    authority.install_signed_certificate(conn, certificate_bytes=certificate.read_bytes(),
        confirm_sha256=digest, context=ctx, now=NOW, trust_roots=ROOTS)
    activated = authority.activate_signed_certificate(conn, certificate_sha256=digest,
        context=ctx, reason="offline rolling admission", now=NOW, trust_roots=ROOTS,
        confirm_controller_rollout=True)
    assert activated.authorization_mode == authority.PAPER_OBSERVATION_ONLY
    assert authority.load_rollout_state(conn).mode == authority.RolloutMode.CONTROLLER
    assert conn.execute("SELECT COUNT(*) FROM sentinel_commands").fetchone()[0] == 0


def test_public_candidate_cli_holds_one_generation_across_all_stages(
        conn, published, monkeypatch, capsys):
    from sentinel.cli import authority as command, feed
    from sentinel.feed import store
    _bind(conn)
    conn.commit()
    stages = []

    class Clock:
        @staticmethod
        def now(tz=None):
            return NOW

    def checked(name, operation):
        def call(*args, **kwargs):
            # An independent publisher cannot acquire the exclusive lock, even
            # before a stage takes its own nested pin.
            other = store.connect(conn.info.dsn)
            try:
                acquired = other.execute("SELECT pg_try_advisory_lock(%s)",
                                         (publication.CORPUS_LOCK_KEY,)).fetchone()[0]
                if acquired:
                    other.execute("SELECT pg_advisory_unlock(%s)", (publication.CORPUS_LOCK_KEY,))
                assert not acquired, "candidate released its generation between stages"
            finally:
                other.close()
            stages.append(name)
            return operation(*args, **kwargs)
        return call

    monkeypatch.setattr(command, "datetime", Clock)
    monkeypatch.setattr(command, "_current_system_identities", lambda: (_runtime(), production_strategy()[1]))
    monkeypatch.setattr(feed, "_closed_preview_frontier", checked("readiness", feed._closed_preview_frontier))
    monkeypatch.setattr(observation, "current_warmup_evidence", checked("warmup", observation.current_warmup_evidence))
    monkeypatch.setattr(observation, "build_candidate", checked("claims", observation.build_candidate))
    args = SimpleNamespace(certificate_id="rolling-cli-0001", issuer_generation=1,
        deployment_id="nas-paper-observe", expect_account="paper-123",
        not_before="2026-09-15T04:00:00Z", expires_at=None, cash=100000,
        maximum_exposure="0.5", reviewer="offline-test", ticket="A21")
    assert command.cmd_create_paper_observation_candidate(
        SimpleNamespace(database_url=conn.info.dsn), args) == command.EXIT_OK
    candidate = json.loads(capsys.readouterr().out)
    assert stages == ["readiness", "warmup", "claims"]
    assert candidate["claims"]["bindings"]["current_corpus"]["data_version"] == published["data_version"]
    assert candidate["retained_evidence"]["warmup"]["warmup_sessions"] == 252


def test_offline_issuer_refuses_rehashed_evidence_for_different_strategy_or_corpus(
        conn, published, tmp_path):
    from tools.sentinel_observation_authority import _candidate as read_candidate
    from tools.sentinel_certificate_issuer import IssuanceRefused
    _bind(conn)
    original = _candidate(conn, observation.current_warmup_evidence(conn, starting_cash=100000))
    path = tmp_path / "candidate.json"
    path.write_bytes(authority.canonical_json_bytes(original))
    assert read_candidate(path)[0] == original["claims"]
    for field, value in (("schema", "sentinel.paper-observation-warmup/1"),
                         ("current_corpus", {}), ("strategy_identity_sha256", "0" * 64),
                         ("decision_sha256", "0" * 64), ("warmup_input", {})):
        changed = deepcopy(original)
        evidence = changed["retained_evidence"]
        evidence["warmup"][field] = value
        # Content hashes are internally valid; this is a semantic binding test.
        changed["claims"]["retained_evidence"]["warmup_sha256"] = authority.canonical_sha256(evidence["warmup"])
        changed["claims"]["retained_evidence"]["sha256"] = authority.canonical_sha256(evidence)
        path.write_bytes(authority.canonical_json_bytes(changed))
        with pytest.raises(IssuanceRefused):
            read_candidate(path)


@pytest.mark.parametrize("field", ["publication_fingerprint", "strategy_identity_sha256", "decision_session"])
def test_candidate_refuses_warmup_for_different_generation_or_strategy(conn, published, field):
    _bind(conn)
    warmup = observation.current_warmup_evidence(conn, starting_cash=100000)
    warmup[field] = "different"
    with pytest.raises(authority.AuthorityRefused, match="warmup publication or strategy"):
        _candidate(conn, warmup)


def test_readiness_cache_is_bound_to_authenticated_publication(conn, published):
    report = readers.readiness(conn)
    assert report.ready
    readiness.save_snapshot(conn, report)
    frontier, snap = readers.status_snapshot(conn)
    assert frontier == "2026-09-14" and snap.ready
    assert readers.snapshot_matches(readers.current(conn), snap)
    stale = readiness.Readiness()
    stale.add("rolling publication binding", readiness.PASS, "a" * 64)
    readiness.save_snapshot(conn, stale)
    assert readers.status_snapshot(conn) == ("2026-09-14", None)
    # An otherwise green legacy verdict cannot certify these rolling inputs.
    legacy = readiness.Readiness()
    legacy.add("legacy ready", readiness.PASS, "different generation")
    readiness.save_snapshot(conn, legacy)
    assert readers.status_snapshot(conn) == ("2026-09-14", None)


def test_informational_paper_panel_receives_the_rolling_frontier(conn, published, monkeypatch):
    from sentinel import informational_paper_mirror as mirror
    from sentinel.feed import store
    from sentinel.panel import sources, model
    monkeypatch.setattr(sources, "_informational_mirror_count", lambda _: 1)
    monkeypatch.setattr(sources, "_latest_automation_cycle", lambda _: {
        "state": "SUCCEEDED", "plan_id": "test-plan", "plan_fingerprint": "a" * 64,
        "clean_reconciliation_id": "test-clean"})
    observed = []
    def permitted(_conn, **kwargs):
        assert kwargs["current_frontier"] == "2026-09-14"
        assert kwargs["current_publication_version"] == published["data_version"]
        observed.append(kwargs)
        return {"status": mirror.NO_UNIT_CHANGE}
    monkeypatch.setattr(mirror, "require_transport_permitted", permitted)
    monkeypatch.setattr(mirror, "require_current_plan_status", permitted)
    row = sources._dual_paper_row(conn, informational_paper_mirror=mirror,
                                  publication=readers, feed_store=store)
    assert len(observed) == 2 and row.status == model.OK
    assert "NOT VERIFIED" in row.value  # never converts transport evidence to P/L authority


def test_stale_readiness_is_a_failure_not_a_provider_retry_permission(conn, published, monkeypatch):
    monkeypatch.setattr(rolling_go_inputs.calendar, "latest_closed_session", lambda now=None: "2026-09-15")
    report = readers.readiness(conn, today="2026-09-16T04:00:00+00:00")
    assert not report.ready
    assert report.failures[0].name == "rolling source-final frontier"
    with pytest.raises(rolling_go_inputs.RollingGoRefused, match="NOT_READY"):
        rolling_go_inputs.validate(conn, readers.current(conn),
            now=datetime(2026, 9, 16, 4, tzinfo=timezone.utc))


def test_integrity_refusal_never_dispatches_to_a_different_reader(monkeypatch):
    from sentinel.feed import operational_snapshot
    def corrupt(_conn):
        raise publication.CorpusIncoherent("receipt mismatch")
    monkeypatch.setattr(publication, "current", corrupt)
    monkeypatch.setattr(operational_snapshot, "_current",
                        lambda _: pytest.fail("integrity failure fell back"))
    with pytest.raises(publication.CorpusIncoherent, match="receipt mismatch"):
        readers.current(object())


def test_generated_installer_programs_read_real_rolling_publication(conn, published, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "scripts"))
    import sentinel_autonomous_deploy as deploy
    import sentinel_autonomous_deploy_driver as driver
    import sentinel_autonomous_deploy_install_entry as install
    monkeypatch.setenv("SENTINEL_DATABASE_URL", conn.info.dsn)
    conn.commit()

    class LocalPython:
        def run(self, command, **kwargs):
            if command == ["up", "-d", "sentinel-panel"]:
                return subprocess.CompletedProcess(command, 0, "", "")
            assert command[-2] == "-c"
            captured = StringIO()
            with redirect_stdout(captured):
                exec(compile(command[-1], "<installer-program>", "exec"), {})
            return subprocess.CompletedProcess(command, 0, captured.getvalue(), "")

    task = object.__new__(install.InstallAnytimeDeploy)
    task.runner, task.base_compose = LocalPython(), []
    report = driver.AutonomousDeploy._readiness_verdict(task)
    assert report["ready"] and report["rolling"] and report["failures"] == []
    calls = []
    task.cfg = SimpleNamespace(data_wait_timeout_seconds=300)
    task.phase = lambda *_: None
    task._assert_wait_fence = lambda: None  # authority checked in its dedicated SQL tests
    task._base_cli = lambda args: calls.append(args)
    task._write_deployment_state = lambda *args, **kw: None
    task.refresh_data()
    assert calls == [["check-data"]]
    timing = task._causal_timing()
    assert timing["frontier"] == "2026-09-14"
    output = task.runner.run(["-c", deploy._DATA_PUBLICATION_CODE]).stdout
    payload = json.loads(output.split("SENTINEL_DEPLOY_DATA_BINDING=", 1)[1])
    assert payload["transaction_read_only"] is True
    assert payload["binding"] == {
        "visible_frontier": "2026-09-14",
        "publication_fingerprint": publication_fingerprint(readers.current(conn))}
