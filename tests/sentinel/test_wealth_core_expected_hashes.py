"""The one-shot Wealth Core expected-hash producer and its refusals."""
from __future__ import annotations

import os
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from stock_strategy_shared.wealth_core.hashes import HASH_ORDER
from stock_strategy_shared.wealth_core.feed import (
    DecisionMetadataTimelineBuilder, SecurityMeta, VendorBar)
from tools import wealth_core_expected_hashes as TOOL


ROOT = Path(__file__).resolve().parents[2]
REPO = Path(os.environ.get("SENTINEL_REPO_ROOT") or ROOT)


class Result:
    def __init__(self, *, scalar=None, row=None):
        self.scalar = scalar
        self.row = row

    def scalar_one(self):
        return self.scalar

    def first(self):
        return self.row


class SnapshotConn:
    def __init__(self, *, read_only="on", isolation="repeatable read",
                 locked=True, source="sharadar", status="READY",
                 actions_evidence=True):
        self.read_only = read_only
        self.isolation = isolation
        self.locked = locked
        self.source = source
        self.status = status
        self.actions_evidence = actions_evidence
        self.calls = []

    def execute(self, statement, params=None):
        sql = str(statement)
        self.calls.append((sql, params))
        if "SHOW transaction_read_only" in sql:
            return Result(scalar=self.read_only)
        if "SHOW transaction_isolation" in sql:
            return Result(scalar=self.isolation)
        if "pg_try_advisory_xact_lock_shared" in sql:
            return Result(scalar=self.locked)
        if "FROM bt_data_version" in sql:
            return Result(row=("generation-7", self.status, self.source,
                               "2026-08-13T12:00:00+00:00", "seeded"))
        if "FROM bt_data_runs" in sql:
            row = None
            if self.actions_evidence:
                row = ("actions-run-3", "backfill", 664_039,
                       "1998-01-01", "2026-12-31",
                       "2026-08-10T10:00:00+00:00",
                       "2026-08-10T10:05:00+00:00", None)
            return Result(row=row)
        return Result()


class FakeBT:
    __file__ = str(ROOT / "services" / "backtester" / "app" /
                   "wealth_core_replay.py")

    def __init__(self, start="2024-06-03", end="2024-06-04", *,
                 actions=True, shift_start=False, bars=True):
        self.start = start
        self.end = end
        start_day = date.fromisoformat(start)
        # 127 history sessions: 126 retained feature sessions plus the
        # immediately preceding ACTION cutoff session.
        warm = [str(start_day - timedelta(days=n))
                for n in range(127, 0, -1)]
        measured = [start, end]
        if shift_start:
            measured = [str(start_day + timedelta(days=1)), end]
        self.sessions = [*warm, *measured]
        self.actions = ([{"date": start, "ticker": "AAA",
                          "action": "dividend", "value": 1.0}]
                        if actions else [])
        self.bars = ({start: [VendorBar(
            session=start, security_id="P:1", ticker="AAA",
            raw_close=100.0, raw_open=99.0, volume=1_000_000.0)]}
                     if bars else {})
        self.observed = {}

    def assert_raw_price_domain(self, _conn, start, end):
        self.observed["coverage_window"] = (start, end)
        return 0.997

    def load_sessions(self, _conn, _start, _end):
        return list(self.sessions)

    def load_meta_timeline(self, _conn, *, sessions):
        self.observed["meta_sessions"] = list(sessions)
        builder = DecisionMetadataTimelineBuilder(sessions)
        meta = SecurityMeta(
            security_id="P:1", ticker="AAA",
            category="Domestic Common Stock", permaticker="1",
            related_tickers=("AAA",), first_session="2000-01-01")
        for session in sessions:
            builder.add_snapshot(session, {"P:1": meta})
        return builder.finish()

    def load_identity(self, _conn, *, as_of):
        self.observed["identity_as_of"] = as_of
        return SimpleNamespace(unresolved={})

    def load_actions(self, _conn, start, end):
        self.observed["actions_window"] = (start, end)
        return list(self.actions)

    def actions_after_session(self, rows, exclusive_prior_session):
        self.observed["actions_filter_input"] = list(rows)
        self.observed["actions_exclusive_prior_session"] = \
            exclusive_prior_session
        return [row for row in rows
                if str(row["date"]) > exclusive_prior_session]

    @staticmethod
    def sessions_index(sessions):
        return list(sessions)

    def actions_effective_in_sessions(self, rows, sessions, included):
        included = set(included)
        selected = [
            row for row in rows
            if next((s for s in sessions if s >= str(row["date"])), None)
            in included
        ]
        self.observed["terminal_filter_input"] = list(rows)
        self.observed["terminal_filter_sessions"] = list(sessions)
        self.observed["terminal_filter_included"] = included
        self.observed["terminal_filter_output"] = selected
        return selected

    def split_ratios_from_actions(self, actions, _sessions):
        self.observed["split_actions"] = list(actions)
        mapping = {}
        for row in actions:
            if row["action"] != "split":
                continue
            mapped = next((s for s in _sessions if s >= str(row["date"])), None)
            if mapped is not None:
                mapping[(row["ticker"], mapped)] = float(row["value"])
        self.observed["split_mapping"] = mapping
        return mapping

    def dividends_from_actions(self, actions, _sessions):
        self.observed["dividend_actions"] = list(actions)
        mapping = {}
        for row in actions:
            if row["action"] != "dividend":
                continue
            mapped = next((s for s in _sessions if s >= str(row["date"])), None)
            if mapped is not None:
                mapping[(row["ticker"], mapped)] = float(row["value"])
        self.observed["dividend_mapping"] = mapping
        return mapping

    def load_bars(self, _conn, _start, _end, **_kwargs):
        return self.bars

    def require_usable_bars(self, bars, **_kwargs):
        if not any(bars.values()):
            raise TOOL.ExpectedHashesRefused(
                "zero-security run is not certification evidence")

    def require_usable_decision_bars(self, bars, _timeline, **_kwargs):
        if not any(bars.values()):
            raise TOOL.ExpectedHashesRefused(
                "zero-security run is not certification evidence")

    def terminal_events_from_actions(self, rows, sessions, **_kwargs):
        self.observed["terminal_actions"] = list(rows)
        self.observed["terminal_sessions"] = list(sessions)
        return []

    @staticmethod
    def unusable_dividend_rows(_actions):
        return 0


class TestSnapshotAuthority:

    def test_read_only_repeatable_read_and_lock_precede_generation(self):
        conn = SnapshotConn()
        generation, snapshot = TOOL.prepare_snapshot(conn)

        sql = [call[0] for call in conn.calls]
        assert sql[0].startswith(
            "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        assert next(i for i, s in enumerate(sql)
                    if "pg_try_advisory_xact_lock_shared" in s) < next(
                        i for i, s in enumerate(sql)
                        if "FROM bt_data_version" in s)
        assert snapshot["transaction_read_only"] is True
        assert generation.version == "generation-7"
        assert generation.source_mode == "sharadar"

    def test_a_non_read_only_transaction_stops_before_the_corpus_lock(self):
        conn = SnapshotConn(read_only="off")
        with pytest.raises(TOOL.ExpectedHashesRefused, match="read-only"):
            TOOL.prepare_snapshot(conn)
        assert not any("pg_try_advisory" in sql for sql, _ in conn.calls)

    def test_a_writer_holding_the_generation_lock_is_a_refusal(self):
        with pytest.raises(TOOL.ExpectedHashesRefused, match="published"):
            TOOL.prepare_snapshot(SnapshotConn(locked=False))

    @pytest.mark.parametrize("source", ["mock", "frozen", None])
    def test_only_a_sharadar_generation_can_produce_expected_hashes(self,
                                                                    source):
        with pytest.raises(TOOL.ExpectedHashesRefused, match="sharadar"):
            TOOL.prepare_snapshot(SnapshotConn(source=source))

    def test_a_non_ready_generation_is_refused(self):
        with pytest.raises(TOOL.ExpectedHashesRefused, match="not READY"):
            TOOL.prepare_snapshot(SnapshotConn(status="PUBLISHING"))


class TestWindowAndSource:

    def test_the_requested_bounds_must_be_the_observed_session_bounds(self):
        bt = FakeBT(end="2024-06-05", shift_start=True)
        with pytest.raises(TOOL.ExpectedHashesRefused,
                           match="must be trading sessions"):
            TOOL.load_corpus(object(), start=bt.start, end=bt.end, bt=bt)

    def test_reversed_and_noncanonical_dates_are_refused(self):
        with pytest.raises(TOOL.ExpectedHashesRefused, match="reversed"):
            TOOL.validate_window("2024-12-31", "2024-01-02")
        with pytest.raises(TOOL.ExpectedHashesRefused, match="ISO date"):
            TOOL.validate_window("06/03/2024", "2024-06-04")

    def test_exactly_126_sessions_warm_features_only(self):
        bt = FakeBT()
        conn = SnapshotConn()
        corpus = TOOL.load_corpus(
            conn, start=bt.start, end=bt.end, bt=bt)
        assert len(corpus["warmup_sessions"]) == 126
        assert corpus["sessions"] == [bt.start, bt.end]
        assert bt.observed["meta_sessions"] == [bt.start, bt.end]
        assert bt.observed["identity_as_of"] == bt.end
        assert corpus["source"]["split_source"] == "actions"
        assert corpus["source"]["actions_ingestion"]["coverage_complete"]
        assert len(corpus["source"]["actions_sha256"]) == 64
        evidence_params = next(params for sql, params in conn.calls
                               if "FROM bt_data_runs" in sql)
        assert evidence_params == {
            "start": date.fromisoformat(bt.start) - timedelta(days=400),
            "end": date.fromisoformat(bt.end),
        }

    def test_missing_actions_never_falls_back_to_derived_splits(self):
        bt = FakeBT(actions=False)
        with pytest.raises(TOOL.ExpectedHashesRefused, match="derived"):
            TOOL.load_corpus(
                SnapshotConn(), start=bt.start, end=bt.end, bt=bt)

    def test_zero_bars_after_reference_filtering_is_refused(self):
        bt = FakeBT(bars=False)
        with pytest.raises(TOOL.ExpectedHashesRefused,
                           match="zero-security run"):
            TOOL.load_corpus(
                SnapshotConn(), start=bt.start, end=bt.end, bt=bt)

    def test_action_cutoff_drops_old_rows_but_keeps_weekend_boundary_events(
            self):
        bt = FakeBT(start="2024-07-01", end="2024-07-02")
        prior = "2024-01-05"       # Friday, exclusive cutoff
        first = "2024-01-08"       # Monday, first retained warm-up session
        tail = [str(date(2024, 1, 8) + timedelta(days=n))
                for n in range(1, 126)]
        bt.sessions = [prior, first, *tail, bt.start, bt.end]
        bt.actions = [
            {"date": "2024-01-05", "ticker": "OLD_SPLIT", "action": "split",
             "value": 2.0, "contraticker": None},
            {"date": "2024-01-04", "ticker": "OLD_DIV", "action": "dividend",
             "value": 1.0, "contraticker": None},
            {"date": "2024-01-07", "ticker": "WEEKEND_SPLIT",
             "action": "split",
             "value": 3.0, "contraticker": None},
            {"date": "2024-01-07", "ticker": "WEEKEND_DIV",
             "action": "dividend",
             "value": 1.5, "contraticker": None},
        ]

        corpus = TOOL.load_corpus(
            SnapshotConn(), start=bt.start, end=bt.end, bt=bt)

        for key in ("split_actions", "dividend_actions"):
            assert {row["ticker"] for row in bt.observed[key]} == {
                "WEEKEND_SPLIT", "WEEKEND_DIV"}
        assert bt.observed["split_mapping"] == {
            ("WEEKEND_SPLIT", first): 3.0}
        assert bt.observed["dividend_mapping"] == {
            ("WEEKEND_DIV", first): 1.5}
        source = corpus["source"]
        assert source["actions_rows_loaded"] == 4
        assert source["actions_rows"] == 2
        assert source["actions_rows_at_or_before_prior_cutoff"] == 2
        assert source["actions_exclusive_prior_session"] == prior
        assert source["actions_first_retained_session"] == first
        assert source["actions_sha256"] == TOOL.actions_sha256(
            bt.observed["split_actions"])

    @pytest.mark.parametrize(("start", "end", "raw_date"), [
        ("2024-07-08", "2024-07-09", "2024-07-07"),  # Sunday -> Monday
        ("2022-04-18", "2022-04-19", "2022-04-15"),  # Good Friday
    ])
    def test_terminal_rows_are_selected_by_EFFECTIVE_session(
            self, start, end, raw_date):
        bt = FakeBT(start=start, end=end)
        start_day = date.fromisoformat(start)
        raw_day = date.fromisoformat(raw_date)
        history = []
        cursor = start_day - timedelta(days=1)
        while len(history) < 127:
            if cursor.weekday() < 5 and cursor != raw_day:
                history.append(str(cursor))
            cursor -= timedelta(days=1)
        bt.sessions = [*reversed(history), start, end]
        row = {"date": raw_date, "ticker": "AAA", "action": "delisted",
               "value": None, "contraticker": None}
        bt.actions = [row]

        TOOL.load_corpus(
            SnapshotConn(), start=start, end=end, bt=bt)

        assert bt.observed["terminal_filter_output"] == [row]
        assert bt.observed["terminal_actions"] == [row]
        assert bt.observed["terminal_sessions"] == bt.sessions[1:]

    def test_nonempty_actions_without_a_covering_ingest_are_refused(self):
        bt = FakeBT(actions=True)
        with pytest.raises(TOOL.ExpectedHashesRefused,
                           match="non-empty action table"):
            TOOL.load_corpus(
                SnapshotConn(actions_evidence=False),
                start=bt.start, end=bt.end, bt=bt)

    def test_insufficient_warmup_is_a_refusal_not_a_delayed_start(self):
        bt = FakeBT()
        bt.sessions = bt.sessions[-50:]
        with pytest.raises(TOOL.ExpectedHashesRefused, match="pre-start"):
            TOOL.load_corpus(
                SnapshotConn(), start=bt.start, end=bt.end, bt=bt)

    def test_exact_warmup_without_the_prior_action_cutoff_refuses(self):
        bt = FakeBT()
        bt.sessions = bt.sessions[1:]  # exactly 126 history sessions remain
        with pytest.raises(TOOL.ExpectedHashesRefused,
                           match="exclusive corporate-action cutoff"):
            TOOL.load_corpus(
                SnapshotConn(), start=bt.start, end=bt.end, bt=bt)

    def test_actions_digest_covers_the_rows_not_just_the_count(self):
        first = [{"date": "2024-01-02", "ticker": "AAA",
                  "action": "split", "value": "2.000000",
                  "contraticker": None}]
        changed = [{**first[0], "value": "3.000000"}]
        assert TOOL.actions_sha256(first) != TOOL.actions_sha256(changed)


class TestTheSevenHashContract:

    def test_all_seven_hashes_are_returned_in_canonical_order(self):
        raw = {name: format(i + 1, "064x")
               for i, name in enumerate(reversed(HASH_ORDER))}
        out = TOOL.validate_hashes(raw)
        assert tuple(out) == HASH_ORDER

    def test_a_missing_layer_is_a_refusal(self):
        raw = {name: "a" * 64 for name in HASH_ORDER[:-1]}
        with pytest.raises(TOOL.ExpectedHashesRefused, match="missing"):
            TOOL.validate_hashes(raw)

    @pytest.mark.parametrize("bad", ["", "A" * 64, "x" * 64, "a" * 63])
    def test_each_digest_must_be_complete_lowercase_sha256(self, bad):
        raw = {name: "a" * 64 for name in HASH_ORDER}
        raw[HASH_ORDER[0]] = bad
        with pytest.raises(TOOL.ExpectedHashesRefused, match="lowercase hex"):
            TOOL.validate_hashes(raw)


def test_the_run_warms_the_shared_feed_and_uses_streaming_hashes(monkeypatch):
    captured = {}

    def run_with_hashes(**kwargs):
        captured.update(kwargs)
        result = SimpleNamespace()
        hashes = SimpleNamespace(to_dict=lambda: {
            name: "a" * 64 for name in HASH_ORDER})
        return result, hashes

    import stock_strategy_shared.wealth_core.run as run_module
    monkeypatch.setattr(run_module, "run_with_hashes", run_with_hashes)
    warmup = [f"W{i:03d}" for i in range(126)]
    corpus = {
        "sessions": ["S001"], "warmup_sessions": warmup,
        "bars_by_session": {}, "meta": {}, "terminal_events": [],
    }

    _result, hashes, config_hash = TOOL.run_corpus(corpus)

    assert captured["hash_mode"] == "streaming"
    assert captured["sessions"] == ["S001"]
    assert tuple(captured["feed"]._seen_sessions) == tuple(warmup)
    from stock_strategy_shared.wealth_core.eligibility import EligibilityConfig
    from stock_strategy_shared.wealth_core.engine import WealthCoreConfig
    assert captured["starting_cash"] == 1_000_000.0
    assert captured["cfg"] == WealthCoreConfig()
    assert captured["eligibility_cfg"] == EligibilityConfig()
    assert captured["cfg"].volatility_profile == \
        captured["eligibility_cfg"].volatility_profile
    assert tuple(hashes) == HASH_ORDER
    assert config_hash


def test_real_load_corpus_to_artifact_reports_timeline_population(monkeypatch):
    conn = SnapshotConn()
    bt = FakeBT()
    hashes = {name: format(i + 1, "064x")
              for i, name in enumerate(HASH_ORDER)}
    result = SimpleNamespace(
        state=SimpleNamespace(cash=999_999.0, episodes={}),
        blocked_sessions=[])

    from stock_strategy_shared.runtime_identity import (
        wealth_core_baseline_identity,
    )
    canonical_config_hash = wealth_core_baseline_identity()["engine_config_hash"]
    monkeypatch.setattr(
        TOOL, "run_corpus",
        lambda _corpus: (result, hashes, canonical_config_hash))
    from stock_strategy_shared import identity_hashes
    monkeypatch.setattr(identity_hashes, "wealth_core_source_hash",
                        lambda: "b" * 64)
    from sentinel import identity as sentinel_identity
    monkeypatch.setattr(sentinel_identity, "rehearsal_identity", lambda: {
        "identity_hash": "d" * 64,
        "environment": {
            "python": "3.12.13", "certified": True,
            "pins_match": True, "sources_known": True, "pin_drift": {},
            "lock_present": True, "image_lock_sha256": "e" * 64,
        },
    })

    out = TOOL.produce(conn, start=bt.start, end=bt.end, bt=bt)

    assert out["schema"] == "wealth_core_expected_hashes.v1"
    assert out["status"] == "ready"
    assert tuple(out["hashes"]) == HASH_ORDER
    assert out["window"]["requested_start"] == bt.start
    assert out["corpus"]["version"] == "generation-7"
    assert out["corpus"]["source_mode"] == "sharadar"
    assert out["corpus"]["distinct_securities"] == 1
    assert out["corpus"]["first_session_securities"] == 1
    assert out["corpus"]["last_session_securities"] == 1
    assert out["corpus"]["maximum_session_securities"] == 1
    assert "securities" not in out["corpus"]
    assert out["corpus"]["normalized_input_hash"] == \
        hashes["normalized_input"]
    assert len(out["corpus"]["causal_input_sha256"]) == 64
    assert out["provenance"]["wealth_core_source_hash"] == "b" * 64
    assert len(out["provenance"]["canonical_loader_sha256"]) == 64
    assert len(out["provenance"]["producer_sha256"]) == 64
    assert out["provenance"]["runtime_identity_hash"] == "d" * 64
    assert out["provenance"]["runtime_environment"]["certified"] is True
    assert out["provenance"]["transaction_read_only"] is True
    behavior = out["run"]["behavior_identity"]
    assert behavior["starting_cash"] == out["run"]["starting_cash"]
    assert behavior["engine_config_hash"] == out["run"]["config_hash"]
    assert len(behavior["wealth_core_config_sha256"]) == 64
    assert len(behavior["eligibility_config_sha256"]) == 64
    assert behavior["wealth_core_config"]["n_slots"] == 25
    assert behavior["eligibility_config"]["min_history_sessions"] == 126

    sql = "\n".join(statement for statement, _ in conn.calls).upper()
    for mutation in ("INSERT ", "UPDATE ", "DELETE ", "TRUNCATE ",
                     "CREATE ", "ALTER ", "DROP "):
        assert mutation not in sql


def test_nonempty_static_meta_cannot_conceal_missing_timeline_population():
    with pytest.raises(TOOL.ExpectedHashesRefused,
                       match="static meta map is not population evidence"):
        TOOL.population_evidence({"meta": {"P:1": object()}})


def test_populated_run_cannot_emit_a_zero_session_population():
    builder = DecisionMetadataTimelineBuilder(["2021-01-04"])
    builder.add_snapshot("2021-01-04", {})
    with pytest.raises(TOOL.ExpectedHashesRefused,
                       match="zero or invalid timeline-derived securities"):
        TOOL.population_evidence({"metadata_timeline": builder.finish()})


def test_causal_hash_includes_warmup_while_seven_hash_contract_stays_separate():
    def bar(close):
        return SimpleNamespace(
            security_id="P:1", ticker="AAA", raw_close=close,
            raw_open=close, volume=1_000.0, split_ratio=1.0,
            dividend_per_share=0.0, tradeable=True,
            unresolved_corporate_action=False)

    base = {
        "warmup_sessions": ["2024-01-02"],
        "sessions": ["2024-01-03"],
        "bars_by_session": {
            "2024-01-02": [bar(10.0)], "2024-01-03": [bar(11.0)]},
    }
    changed = {**base, "bars_by_session": {
        **base["bars_by_session"], "2024-01-02": [bar(10.5)]}}
    assert TOOL.causal_input_sha256(base) != TOOL.causal_input_sha256(changed)
    # The producer still exposes exactly the canonical seven as `hashes`;
    # causal_input_sha256 is supplemental corpus provenance.
    assert "causal_input_sha256" not in HASH_ORDER


def test_uncertified_runtime_cannot_emit_a_ready_artifact(monkeypatch):
    bt = FakeBT()
    hashes = {name: "a" * 64 for name in HASH_ORDER}
    corpus = {
        "sessions": [bt.start, bt.end],
        "warmup_sessions": bt.sessions[1:127],
        "bars_by_session": {}, "meta": {"P:1": object()},
        "terminal_events": [], "source": {},
    }
    result = SimpleNamespace(
        state=SimpleNamespace(cash=1_000_000.0, episodes={}),
        blocked_sessions=[])
    monkeypatch.setattr(TOOL, "load_corpus", lambda *_args, **_kw: corpus)
    monkeypatch.setattr(
        TOOL, "run_corpus", lambda _corpus: (result, hashes, "config-hash"))
    from stock_strategy_shared import identity_hashes
    monkeypatch.setattr(
        identity_hashes, "wealth_core_source_hash", lambda: "b" * 64)
    from sentinel import identity as sentinel_identity
    monkeypatch.setattr(sentinel_identity, "rehearsal_identity", lambda: {
        "identity_hash": "d" * 64,
        "environment": {
            "certified": False, "pins_match": False,
            "sources_known": True, "pin_drift": {"changed": {}},
            "lock_present": True, "image_lock_sha256": "e" * 64,
        },
    })

    with pytest.raises(TOOL.ExpectedHashesRefused,
                       match="not running in the certified"):
        TOOL.produce(SnapshotConn(), start=bt.start, end=bt.end, bt=bt)


class TestAtomicOutput:

    def test_output_is_complete_and_existing_target_is_never_overwritten(
            self, tmp_path):
        target = tmp_path / "expected.json"
        artifact = {"schema": TOOL.SCHEMA, "status": "ready"}
        TOOL.write_artifact_atomic(target, artifact)
        before = target.read_bytes()
        assert before.endswith(b"\n")
        with pytest.raises(TOOL.ExpectedHashesRefused, match="overwrite"):
            TOOL.write_artifact_atomic(target, {"different": True})
        assert target.read_bytes() == before
        assert list(tmp_path.glob(".*.tmp")) == []

    def test_a_link_failure_leaves_no_target_or_temporary_file(
            self, tmp_path, monkeypatch):
        target = tmp_path / "expected.json"

        def fail_link(_source, _target):
            raise OSError("simulated publication failure")

        monkeypatch.setattr(os, "link", fail_link)
        with pytest.raises(TOOL.ExpectedHashesRefused, match="atomically"):
            TOOL.write_artifact_atomic(target, {"status": "ready"})
        assert not target.exists()
        assert list(tmp_path.glob(".*.tmp")) == []

    def test_a_post_link_temp_cleanup_failure_rolls_back_and_can_retry(
            self, tmp_path, monkeypatch):
        target = tmp_path / "expected.json"
        artifact = {"schema": TOOL.SCHEMA, "status": "ready"}
        real_unlink = Path.unlink
        failed = False

        def fail_first_published_temp(path, *args, **kwargs):
            nonlocal failed
            if (not failed and path.name.endswith(".tmp")
                    and target.exists()):
                failed = True
                raise OSError("simulated staging-name cleanup failure")
            return real_unlink(path, *args, **kwargs)

        monkeypatch.setattr(Path, "unlink", fail_first_published_temp)
        with pytest.raises(TOOL.ExpectedHashesRefused,
                           match="atomically") as exc:
            TOOL.write_artifact_atomic(target, artifact)
        assert isinstance(exc.value.__cause__, OSError)
        assert "staging-name cleanup" in str(exc.value.__cause__)
        assert not target.exists(), (
            "a failed command must not leave authoritative ready JSON")
        assert list(tmp_path.glob(".*.tmp")) == []

        # The injected fault was one-shot; rollback must leave the output name
        # reusable rather than converting a failed command into an overwrite
        # refusal on the operator's retry.
        TOOL.write_artifact_atomic(target, artifact)
        assert target.exists()
        assert list(tmp_path.glob(".*.tmp")) == []

    @pytest.mark.skipif(not hasattr(os, "O_DIRECTORY"),
                        reason="directory descriptor close is POSIX-only")
    def test_a_post_link_directory_close_failure_is_also_rolled_back(
            self, tmp_path, monkeypatch):
        target = tmp_path / "expected.json"
        artifact = {"schema": TOOL.SCHEMA, "status": "ready"}
        real_close = os.close
        failed = False

        def close_then_fail_once(fd):
            nonlocal failed
            real_close(fd)
            if not failed:
                failed = True
                raise OSError("simulated directory close failure")

        monkeypatch.setattr(os, "close", close_then_fail_once)
        with pytest.raises(TOOL.ExpectedHashesRefused,
                           match="atomically") as exc:
            TOOL.write_artifact_atomic(target, artifact)
        assert isinstance(exc.value.__cause__, OSError)
        assert "directory close" in str(exc.value.__cause__)
        assert not target.exists()
        assert list(tmp_path.glob(".*.tmp")) == []

        TOOL.write_artifact_atomic(target, artifact)
        assert target.exists()


def test_the_tool_stays_out_of_the_broker_facing_runtime():
    assert (ROOT / "tools" / "wealth_core_expected_hashes.py").is_file()
    assert not (REPO / "sentinel" / "wealth_core_expected_hashes.py").exists()
    source = (ROOT / "tools" / "wealth_core_expected_hashes.py").read_text()
    assert "app import wealth_core_replay" in source
    assert "run_with_hashes" in source
    assert "alpaca" not in source.lower()
    assert not any(word in source.upper() for word in (
        "INSERT INTO", "UPDATE BT_", "DELETE FROM", "TRUNCATE TABLE"))


def test_the_producer_is_copied_and_bound_as_a_certification_input():
    dockerfile = (REPO / "Dockerfile.sentinel-test").read_text()
    assert "COPY tools/ /work/tools/" in dockerfile

    import importlib.util
    manifest_path = REPO / "scripts" / "sentinel_manifest.py"
    spec = importlib.util.spec_from_file_location("sentinel_manifest", manifest_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    inputs = {(Path(source).relative_to(REPO).as_posix(), logical)
              for source, logical in module._certification_input_spec(REPO)}
    assert ("tools", "tools") in inputs


def test_producer_and_baseline_share_the_effective_session_boundary():
    producer = (ROOT / "tools" / "wealth_core_expected_hashes.py").read_text()
    load = producer[producer.index("def load_corpus("):
                    producer.index("def run_corpus(")]
    assert "measured_actions = bt.actions_effective_in_sessions(\n" \
           "        action_rows, full_index, measured)" in load
    assert "terminal_events_from_actions(\n" \
           "        measured_actions, full_index," in load

    baseline = (REPO / "services" / "bt-engine" / "app" /
                "wealth_core_api.py").read_text()
    corpus = baseline[baseline.index("async def _load_corpus"):
                      baseline.index("def _execute(")]
    assert "measured_action_rows = actions_effective_in_sessions(\n" \
           "                action_rows, full_idx, sessions)" in corpus
    assert "terminal_events_from_actions(\n" \
           "                    measured_action_rows, full_idx," in corpus


class TestTheDatabaseAuthorityIsExplicit:

    def test_missing_database_url_is_a_refusal(self, monkeypatch, capsys):
        monkeypatch.delenv("BT_DATABASE_URL", raising=False)
        assert TOOL.main(["--start", "2024-06-03",
                          "--end", "2024-06-04"]) == 2
        assert "BT_DATABASE_URL is unset" in capsys.readouterr().err

    def test_wrong_driver_is_refused_without_echoing_the_secret(self,
                                                                 monkeypatch,
                                                                 capsys):
        secret = "not-for-output"
        monkeypatch.setenv(
            "BT_DATABASE_URL", f"postgresql://reader:{secret}@db/backtest")
        assert TOOL.main(["--start", "2024-06-03",
                          "--end", "2024-06-04"]) == 2
        err = capsys.readouterr().err
        assert "postgresql+psycopg" in err
        assert secret not in err
