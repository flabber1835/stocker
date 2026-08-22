"""Falsifiers for the broker-free production forward-chain differential."""
from __future__ import annotations

import ast
import json
import os
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools import sentinel_forward_chain as FC


REPO = Path(os.environ.get("SENTINEL_REPO_ROOT") or FC.ROOT)


def _values(*, allocation="1.0", parent="1.0", damaged="0.1",
            shadow="100.0"):
    return {
        "nav": Decimal("1.0"),
        "allocation": Decimal(allocation),
        "parent_allocation": Decimal(parent),
        "shadow_equity": Decimal(shadow),
        "open_shadow_equity": Decimal(shadow),
        "shadow_dd": Decimal("-0.01"),
        "damaged": Decimal(damaged),
        "green": Decimal("0.2"),
        "r20": Decimal("0.03"),
        "r40": Decimal("0.04"),
        "stops20": 1,
        "stress_duration": 2,
    }


def _row(session, **kwargs):
    return FC.ReferenceRow(session=session, values=_values(**kwargs))


class TestCorrectedReferenceContract:

    def test_full_chain_is_exact_7188_session_xnys_axis(self):
        sessions = FC.calendar.sessions_in_range(
            FC.CHAIN_START, FC.REFERENCE_END
        )

        FC._validate_chain_axis(sessions)
        assert len(sessions) == FC.CHAIN_SESSION_COUNT == 7_188
        assert sessions[0] == "1998-01-02"
        assert sessions[-1] == "2026-07-31"

    def test_committed_tape_is_exact_5032_session_xnys_lineage(self):
        tape = FC.load_reference_tape()

        assert len(tape.rows) == FC.REFERENCE_SESSION_COUNT == 5_032
        assert tape.rows[0].session == "2006-07-31"
        assert tape.rows[-1].session == "2026-07-31"
        assert tape.sha256 == FC.FROZEN_REFERENCE_SHA256
        assert tape.expected_sha256 == FC.FROZEN_REFERENCE_SHA256
        assert tape.identity()["checksum_verified"] is True
        assert tape.checksum_manifest.endswith(
            "docs/sentinel-reference-implementation/SHA256SUMS.txt"
        )
        assert len(tape.checksum_manifest_sha256) == 64
        assert tape.path.endswith(
            "docs/sentinel-reference-implementation/sentinel_1p1_daily.csv"
        )

    def test_missing_row_is_refused_before_any_differential(self, tmp_path):
        lines = FC.REFERENCE_PATH.read_text(encoding="utf-8").splitlines()
        path = tmp_path / "short.csv"
        path.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")

        with pytest.raises(FC.ForwardChainRefused, match="exactly 5032"):
            FC._parse_reference_bytes(path.read_bytes(), path=path)

    def test_field_schema_mismatch_is_refused(self, tmp_path):
        text = FC.REFERENCE_PATH.read_text(encoding="utf-8")
        path = tmp_path / "wrong-field.csv"
        path.write_text(
            text.replace("shadow_dd", "drawdown", 1), encoding="utf-8"
        )

        with pytest.raises(FC.ForwardChainRefused, match="schema mismatch"):
            FC._parse_reference_bytes(path.read_bytes(), path=path)

    def test_session_axis_mismatch_is_refused_even_at_the_same_count(self,
                                                                    tmp_path):
        text = FC.REFERENCE_PATH.read_text(encoding="utf-8")
        # 2006-08-05 was a Saturday and sits between the adjacent rows, so the
        # local monotonicity check passes and the independent XNYS axis catches it.
        text = text.replace("2006-08-04,", "2006-08-05,", 1)
        path = tmp_path / "shifted-session.csv"
        path.write_text(text, encoding="utf-8")

        with pytest.raises(FC.ForwardChainRefused, match="exact corrected-lineage"):
            FC._parse_reference_bytes(path.read_bytes(), path=path)

    def test_crlf_conversion_is_a_checksum_failure(self, tmp_path):
        frozen = FC.REFERENCE_PATH.read_bytes()
        assert b"\r\n" not in frozen
        path = tmp_path / "crlf.csv"
        path.write_bytes(frozen.replace(b"\n", b"\r\n"))

        with pytest.raises(FC.ForwardChainRefused, match="checksum mismatch"):
            FC.load_reference_tape(path)

    def test_mutation_of_uncompared_nav_field_is_a_checksum_failure(self,
                                                                    tmp_path):
        frozen = FC.REFERENCE_PATH.read_bytes()
        original = b"2006-07-31,1.0,1.0,"
        changed = b"2006-07-31,9.0,1.0,"
        assert frozen.count(original) == 1
        path = tmp_path / "changed-ignored-field.csv"
        path.write_bytes(frozen.replace(original, changed, 1))

        with pytest.raises(FC.ForwardChainRefused, match="checksum mismatch"):
            FC.load_reference_tape(path)

    def test_manifest_digest_cannot_be_re_pinned_by_editing_the_manifest(self,
                                                                        tmp_path):
        manifest = FC.REFERENCE_CHECKSUMS_PATH.read_text(encoding="ascii")
        path = tmp_path / "SHA256SUMS.txt"
        path.write_text(
            manifest.replace(FC.FROZEN_REFERENCE_SHA256, "0" * 64, 1),
            encoding="ascii", newline="\n",
        )

        with pytest.raises(FC.ForwardChainRefused, match="frozen.*contract"):
            FC.load_reference_tape(checksums_path=path)

    def test_gitattributes_preserves_frozen_tape_bytes(self):
        attributes = (REPO / ".gitattributes").read_text(encoding="utf-8")
        assert (
            "docs/sentinel-reference-implementation/sentinel_1p1_daily.csv -text"
            in attributes.splitlines()
        )

    @pytest.mark.parametrize("sessions", [
        [FC.CHAIN_START] * FC.CHAIN_SESSION_COUNT,
        [FC.CHAIN_START, FC.REFERENCE_END],
    ])
    def test_full_chain_count_or_boundaries_cannot_be_narrowed(self, sessions):
        with pytest.raises(FC.ForwardChainRefused):
            FC._validate_chain_axis(sessions)


class TestDecisionBasisTiming:

    def _actual(self, *, effective="1.0", decision="0.55", damaged="0.1"):
        return {
            "effective_allocation": Decimal(effective),
            "next_allocation": Decimal(decision),
            "parent_allocation": Decimal("1.0"),
            "shadow_equity": Decimal("100.0"),
            "shadow_dd": Decimal("-0.01"),
            "damaged": Decimal(damaged),
            "green": Decimal("0.2"),
            "r20": Decimal("0.03"),
            "r40": Decimal("0.04"),
            "stops20": 1,
            "stress_duration": 2,
        }

    def test_close_t_decision_is_compared_to_next_session_allocation(self):
        today = _row("2025-04-07", allocation="1.0")
        tomorrow = _row("2025-04-08", allocation="0.55")
        actual = self._actual(effective="1.0", decision="0.55")

        divergence, compared = FC.compare_reference_session(
            today, actual, next_row=tomorrow
        )

        assert divergence is None
        assert compared == len(FC.SAME_SESSION_FIELDS) + 1
        # This is the falsifier for the tempting but wrong same-row alignment.
        assert actual["next_allocation"] != today.values["allocation"]

    def test_wrong_next_session_decision_names_both_dates(self):
        today = _row("2025-04-07", allocation="1.0")
        tomorrow = _row("2025-04-08", allocation="0.55")

        divergence, _ = FC.compare_reference_session(
            today, self._actual(decision="1.0"), next_row=tomorrow
        )

        assert divergence == {
            "production_session": "2025-04-07",
            "reference_session": "2025-04-08",
            "field": "allocation",
            "production_field": "target_core_exposure",
            "alignment": "current_close_decision_to_next_session_allocation",
            "expected": "0.55",
            "actual": "1.0",
        }

    def test_same_session_field_mismatch_is_the_first_divergence(self):
        today = _row("2025-04-07", damaged="0.2")

        divergence, _ = FC.compare_reference_session(
            today, self._actual(damaged="0.1"), next_row=None
        )

        assert divergence["field"] == "damaged"
        assert divergence["alignment"] == "current_close_observation"
        assert divergence["expected"] == "0.2"
        assert divergence["actual"] == "0.1"

    def test_final_close_target_is_not_compared_without_a_next_tape_row(self):
        final = _row(FC.REFERENCE_END, allocation="1.0")
        actual = self._actual(effective="1.0", decision="0.0")

        divergence, compared = FC.compare_reference_session(
            final, actual, next_row=None
        )

        assert divergence is None
        assert compared == len(FC.SAME_SESSION_FIELDS)
        assert actual["next_allocation"] != final.values["allocation"]


class _FakeState:
    def __init__(self, *, session=None, target=None):
        self.feed = {"series": {"P:A": {}}}
        self.last_decision = None if target is None else {
            "session": session,
            "target_core_exposure": target,
            "fast_severe_active": False,
            "slow_severe_active": False,
        }
        self.last_evidence = None if session is None else {
            "observation": {
                "session": session,
                "shadow_nav": 100.0,
                "shadow_drawdown": -0.01,
                "damaged_breadth": 0.1,
                "green_breadth": 0.2,
                "shadow_r20": 0.03,
                "shadow_r40": 0.04,
                "stops20": 1,
            }
        }
        self.controller = {"base_stress_duration": 2}
        self.last_processed_session = session

    @property
    def state_hash(self):
        return f"state:{self.last_processed_session}"


class TestCanonicalProductionDriver:

    def test_session_state_loader_warmup_and_advance_are_the_invoked_components(
            self, monkeypatch):
        calls = []
        sessions = [f"s{i:03d}" for i in range(42)]
        tape = FC.ReferenceTape(
            rows=(
                _row(sessions[-2], allocation="1.0"),
                _row(sessions[-1], allocation="0.55"),
            ),
            sha256="a" * 64,
            path="synthetic.csv",
        )

        class FakeController:
            def __init__(self, config):
                calls.append(("Controller", config))

        class FakeSessionState:
            @classmethod
            def fresh(cls, **kwargs):
                calls.append(("SessionState.fresh", kwargs))
                return _FakeState()

        def fake_window(_conn, *, start, end):
            calls.append(("load_window", start, end))
            return SimpleNamespace(sessions=sessions[:40])

        def fake_warm(state, window, *, publication_version):
            calls.append(("warm_session_state", publication_version))
            return state

        def fake_load(_conn, session, *, spy_sessions,
                      known_feed_security_ids):
            calls.append(("load_published_session", session, spy_sessions,
                          known_feed_security_ids))
            return SimpleNamespace(session=session, data_version=7)

        targets = {sessions[-2]: 0.55, sessions[-1]: 1.0}

        def fake_advance(state, published, *, controller_config,
                         strategy_identity):
            calls.append(("advance_state", published.session,
                          controller_config, strategy_identity))
            return _FakeState(
                session=published.session, target=targets[published.session]
            )

        monkeypatch.setattr(FC, "Controller", FakeController)
        monkeypatch.setattr(FC, "SessionState", FakeSessionState)
        monkeypatch.setattr(FC, "load_window", fake_window)
        monkeypatch.setattr(FC, "warm_session_state", fake_warm)
        monkeypatch.setattr(FC, "load_published_session", fake_load)
        monkeypatch.setattr(FC, "advance_state", fake_advance)

        result = FC.drive_forward_chain(
            object(), chain_sessions=sessions, tape=tape,
            controller_config="frozen-config",
            strategy_identity={"strategy": "sentinel"},
            publication_version=7,
        )

        names = [call[0] for call in calls]
        assert names.count("Controller") == 1
        assert names.count("SessionState.fresh") == 1
        assert names.count("load_window") == 1
        assert names.count("warm_session_state") == 1
        assert names.count("load_published_session") == 2
        assert names.count("advance_state") == 2
        assert all(
            call[2] == FC.REQUIRED_SPY_SESSIONS
            and call[3] == ("P:A",)
            for call in calls if call[0] == "load_published_session"
        )
        assert result["differential_verdict"] == "PASS"
        assert result["reference_sessions_compared"] == 2
        assert result["field_comparisons"] == 21
        assert result["final_close_decision_boundary"] == {
            "production_session": sessions[-1],
            "production_field": "target_core_exposure",
            "actual": "1.0",
            "reference_session": None,
            "status": "NOT_COMPARABLE_NO_NEXT_REFERENCE_SESSION",
            "excluded_from_verdict": True,
        }
        assert result["final_state_fingerprint"] == f"state:{sessions[-1]}"

    def test_loader_session_or_publication_mismatch_refuses(self, monkeypatch):
        sessions = [f"s{i:03d}" for i in range(42)]
        tape = FC.ReferenceTape(
            rows=(_row(sessions[-1]),), sha256="a" * 64,
            path="synthetic.csv",
        )
        monkeypatch.setattr(FC, "SessionState", SimpleNamespace(
            fresh=lambda **_kw: _FakeState()))
        monkeypatch.setattr(FC, "Controller", lambda _config: object())
        monkeypatch.setattr(
            FC, "load_window",
            lambda *_a, **_kw: SimpleNamespace(sessions=sessions[:40]),
        )
        monkeypatch.setattr(FC, "warm_session_state", lambda state, *_a, **_kw: state)
        monkeypatch.setattr(
            FC, "load_published_session",
            lambda *_a, **_kw: SimpleNamespace(
                session="wrong-session", data_version=7
            ),
        )

        with pytest.raises(FC.ForwardChainRefused, match="returned wrong-session"):
            FC.drive_forward_chain(
                object(), chain_sessions=sessions, tape=tape,
                controller_config=object(), strategy_identity={},
                publication_version=7,
            )


class TestReadOnlyProvenanceBoundary:

    def test_snapshot_is_repeatable_read_and_read_only(self):
        class Cursor:
            def __init__(self):
                self.statements = []
                self.answers = iter([("repeatable read",), ("on",)])

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def execute(self, sql):
                self.statements.append(sql)

            def fetchone(self):
                return next(self.answers)

        cursor = Cursor()
        conn = SimpleNamespace(cursor=lambda: cursor)

        result = FC._begin_read_only_snapshot(conn)

        assert cursor.statements[0] == (
            "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
        )
        assert result == {"isolation": "repeatable read", "read_only": "on"}

    @pytest.mark.parametrize("change", [
        {"data_version": 8},
        {"sessions": FC.CHAIN_SESSION_COUNT - 1},
        {"first_session": "1998-01-05"},
        {"corpus_hash": None},
    ])
    def test_incomplete_or_mismatched_corpus_identity_refuses(self, change):
        corpus = {
            "data_version": 7,
            "window": {"start": FC.CHAIN_START, "end": FC.REFERENCE_END},
            "first_session": FC.CHAIN_START,
            "last_session": FC.REFERENCE_END,
            "sessions": FC.CHAIN_SESSION_COUNT,
            "corpus_hash": "c" * 64,
        }
        corpus.update(change)

        with pytest.raises(FC.ForwardChainRefused):
            FC._validate_corpus_identity(corpus, publication_version=7)

    def test_report_binds_same_pin_to_corpus_chain_and_source(self, monkeypatch):
        rolled_back = []
        conn = SimpleNamespace(rollback=lambda: rolled_back.append(True))
        tape = FC.ReferenceTape(
            rows=(_row(FC.REFERENCE_START),), sha256="r" * 64,
            path="reference.csv",
        )
        held = SimpleNamespace(
            version=7, to_dict=lambda: {"version": 7, "label": "held"})
        events = []

        @contextmanager
        def fake_pin(_conn, *, commit):
            assert commit is False
            events.append("pin-enter")
            yield held
            events.append("pin-exit")

        corpus = {
            "data_version": 7,
            "window": {"start": FC.CHAIN_START, "end": FC.REFERENCE_END},
            "first_session": FC.CHAIN_START,
            "last_session": FC.REFERENCE_END,
            "sessions": FC.CHAIN_SESSION_COUNT,
            "corpus_hash": "c" * 64,
        }
        comparison = {
            "differential_verdict": "PASS",
            "chain_sessions_warmed": 40,
            "chain_sessions_advanced": 7_148,
            "reference_sessions_compared": 5_032,
            "field_comparisons": 55_351,
            "first_divergence": None,
            "final_close_decision_boundary": {
                "production_session": FC.REFERENCE_END,
                "status": "NOT_COMPARABLE_NO_NEXT_REFERENCE_SESSION",
            },
            "final_state_fingerprint": "state-hash",
        }
        monkeypatch.setattr(
            FC, "_begin_read_only_snapshot",
            lambda _conn: {"isolation": "repeatable read", "read_only": "on"},
        )
        monkeypatch.setattr(FC, "load_reference_tape", lambda _path: tape)
        monkeypatch.setattr(
            FC.calendar, "sessions_in_range", lambda *_args: ["chain"]
        )
        monkeypatch.setattr(FC, "_validate_chain_axis", lambda _sessions: None)
        monkeypatch.setattr(FC, "load_controller", lambda: SimpleNamespace(
            digest="d" * 64
        ))
        monkeypatch.setattr(
            FC, "runtime_strategy_identity",
            lambda _config: {"strategy": "sentinel"},
        )
        monkeypatch.setattr(
            FC, "_source_identity", lambda *_args: {"runner_sha256": "s" * 64}
        )
        monkeypatch.setattr(FC.publication, "pinned", fake_pin)
        monkeypatch.setattr(
            FC.publication, "assert_coherent",
            lambda _conn, *, exhaustive: SimpleNamespace(
                to_dict=lambda: {"coherent": True, "exhaustive": exhaustive}
            ),
        )
        monkeypatch.setattr(
            FC, "latest_visible_session", lambda _conn: FC.REFERENCE_END)

        def fake_corpus(_conn, *, start, end, publication_record):
            assert events == ["pin-enter"]
            assert (start, end, publication_record.version) == (
                FC.CHAIN_START, FC.REFERENCE_END, 7
            )
            events.append("corpus")
            return corpus

        monkeypatch.setattr(FC.identity, "_corpus_pinned", fake_corpus)
        monkeypatch.setattr(
            FC, "drive_forward_chain",
            lambda _conn, **kwargs: (
                events.append(("drive", kwargs["publication_version"]))
                or comparison
            ),
        )

        report = FC.run_certification(conn)

        assert events == ["pin-enter", "corpus", ("drive", 7), "pin-exit"]
        assert report["differential_verdict"] == "PASS"
        assert report["corpus_identity"]["corpus_hash"] == "c" * 64
        assert report["source_identity"]["runner_sha256"] == "s" * 64
        assert report["reference"]["sha256"] == "r" * 64
        assert report["held_publication"] == {
            "publication_fingerprint": FC.publication_fingerprint(held),
            "visible_frontier": FC.REFERENCE_END,
        }
        assert report["alignment"]["full_pass_allocation_coverage"] == {
            "effective_allocations": 5_032,
            "effective_decision_window": ["2006-07-28", "2026-07-30"],
            "close_decisions_compared_to_next_row": 5_031,
            "close_decision_window": ["2006-07-31", "2026-07-30"],
            "uncompared_close_decision": "2026-07-31",
        }
        assert report["runtime_authority_changed"] is False
        assert rolled_back == [True]

    def test_source_identity_contains_runner_production_and_reference_hashes(
            self, monkeypatch):
        monkeypatch.setattr(
            FC.identity, "environment", lambda: {"certified": False, "x": 1}
        )
        tape = FC.ReferenceTape(
            rows=(_row(FC.REFERENCE_START),), sha256="r" * 64,
            path="reference.csv",
        )

        result = FC._source_identity(
            SimpleNamespace(digest="d" * 64),
            {"strategy": "sentinel"}, tape,
        )

        assert len(result["environment_identity_sha256"]) == 64
        assert len(result["production_module_sha256"]) == 64
        assert len(result["runner_sha256"]) == 64
        assert result["reference_sha256"] == "r" * 64
        assert result["strategy_identity"] == {"strategy": "sentinel"}


def test_runner_imports_no_execution_or_broker_module():
    tree = ast.parse(Path(FC.__file__).read_text(encoding="utf-8"))
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)

    forbidden = ("sentinel.execution", "sentinel.paper", "alpaca")
    assert not [name for name in imports if name.startswith(forbidden)]


def test_output_artifact_refuses_overwrite(tmp_path):
    target = tmp_path / "evidence.json"
    target.write_text("keep", encoding="utf-8")

    with pytest.raises(FC.ForwardChainRefused, match="refusing overwrite"):
        FC._write_report({"differential_verdict": "PASS"}, target)

    assert target.read_text(encoding="utf-8") == "keep"


def test_output_artifact_is_complete_and_leaves_no_temporary(tmp_path):
    target = tmp_path / "evidence.json"

    FC._write_report({"differential_verdict": "PASS"}, target)

    assert json.loads(target.read_text(encoding="utf-8")) == {
        "differential_verdict": "PASS"}
    assert not list(tmp_path.glob(".evidence.json.tmp.*"))


def test_output_artifact_directory_open_failure_removes_publication_and_retries(
        tmp_path, monkeypatch):
    target = tmp_path / "evidence.json"
    real_open = os.open
    failed = False

    def fail_once(path, flags):
        nonlocal failed
        if Path(path) == tmp_path and not failed:
            failed = True
            raise OSError("injected post-link directory-open failure")
        return real_open(path, flags)

    monkeypatch.setattr(os, "open", fail_once)

    with pytest.raises(OSError, match="post-link directory-open failure"):
        FC._write_report({"differential_verdict": "PASS"}, target)

    assert failed is True
    assert not target.exists()
    assert not list(tmp_path.glob(".evidence.json.tmp.*"))

    FC._write_report({"differential_verdict": "PASS"}, target)
    assert json.loads(target.read_text(encoding="utf-8")) == {
        "differential_verdict": "PASS"
    }


def test_output_artifact_directory_fsync_failure_removes_publication_and_retries(
        tmp_path, monkeypatch):
    target = tmp_path / "evidence.json"
    real_fsync = os.fsync
    calls = 0

    def fail_second_call(fd):
        nonlocal calls
        calls += 1
        # The first call synchronizes the temporary file.  The second is the
        # first parent-directory fsync, after the final hard link exists.
        if calls == 2:
            raise OSError("injected post-link directory-fsync failure")
        return real_fsync(fd)

    monkeypatch.setattr(os, "fsync", fail_second_call)

    with pytest.raises(OSError, match="post-link directory-fsync failure"):
        FC._write_report({"differential_verdict": "PASS"}, target)

    assert calls >= 3  # cleanup synchronized the removal
    assert not target.exists()
    assert not list(tmp_path.glob(".evidence.json.tmp.*"))

    FC._write_report({"differential_verdict": "PASS"}, target)
    assert json.loads(target.read_text(encoding="utf-8")) == {
        "differential_verdict": "PASS"
    }


def test_cli_without_database_url_refuses_without_connecting(monkeypatch, capsys):
    monkeypatch.delenv("SENTINEL_DATABASE_URL", raising=False)
    monkeypatch.setattr(
        FC, "connect", lambda _url: pytest.fail("database must not be opened")
    )

    assert FC.main(["--quiet"]) == 2
    assert "SENTINEL_DATABASE_URL is unset" in capsys.readouterr().err


def test_generic_cli_failure_redacts_exception_detail(monkeypatch, capsys):
    secret = "postgresql://user:do-not-print@db/sentinel"
    monkeypatch.setenv("SENTINEL_DATABASE_URL", secret)

    def fail(_url):
        raise RuntimeError(f"connection failed for {secret}")

    monkeypatch.setattr(FC, "connect", fail)

    assert FC.main(["--quiet"]) == 2
    error = capsys.readouterr().err
    assert "RuntimeError" in error
    assert secret not in error
    assert "do-not-print" not in error
