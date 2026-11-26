"""Nested guard timings preserve fresh authority and contain no broker data."""

from datetime import date
import logging
from types import SimpleNamespace

import pytest

from sentinel import opening_stage_log
from sentinel.authority import AuthorityRefused
from sentinel.execution import authority_gate
from sentinel.execution.guarded import BrokerOperation, PaperPreparationGrant


class _Cursor:
    def __init__(self, events):
        self.events = events

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, statement):
        self.events.append(statement)


class _Connection:
    def __init__(self, events):
        self.events = events

    def cursor(self):
        return _Cursor(self.events)

    def commit(self):
        self.events.append("commit")

    def close(self):
        self.events.append("close")


def _check(monkeypatch, events, validate):
    monkeypatch.setattr(authority_gate, "load_rollout_state",
                        lambda _conn: SimpleNamespace(mode="paper"))
    monkeypatch.setattr(authority_gate.feed_inputs, "require_current",
                        lambda _conn: SimpleNamespace(version=9))

    def factory():
        events.append("connection")
        return _Connection(events)

    def authority(_conn, **kwargs):
        events.append(kwargs["required_operation"])
        return SimpleNamespace(certificate_sha256="certificate")

    return authority_gate.build_fresh_execution_check(
        connection_factory=factory,
        paper_base_url="https://paper-api.alpaca.markets",
        runtime_identity=lambda: {}, strategy_identity=lambda: {},
        validate_grant=validate, authority_check=authority,
        publish_operational_evidence=False)


def test_fresh_guard_phases_are_fixed_and_aggregated_inside_broker_trace(
        monkeypatch, caplog):
    events = []
    grant = PaperPreparationGrant("private-account", date(2026, 11, 23))
    observed = object()

    def validate(_conn, received, operation, result):
        assert received is grant
        assert operation is BrokerOperation.OBSERVE
        assert result is None or result is observed
        events.append("validated")

    check = _check(monkeypatch, events, validate)
    with caplog.at_level(logging.INFO, logger=opening_stage_log.LOGGER_NAME):
        check(grant, BrokerOperation.OBSERVE, None)
        with opening_stage_log.broker_reads():
            for part in ("before_read", "after_read"):
                with opening_stage_log.broker_read("observe", part):
                    check(grant, BrokerOperation.OBSERVE,
                          observed if part == "after_read" else None)
                    with opening_stage_log.guard_phase("account=private-account"):
                        pass
            with opening_stage_log.broker_read("observe", "adapter"):
                with opening_stage_log.guard_phase("signed_authority"):
                    pass

    phases = [message for message in caplog.messages
              if message.startswith("paper_guard_phase ")]
    assert len(phases) == 17
    assert {message.split(" phase=")[1].split(" count=")[0]
            for message in phases} == {
        "connection_setup", "read_only_setup", "grant_structural",
        "publication_rollout", "signed_authority", "result_evidence",
        "current_publication", "runtime_identity", "strategy_identity",
    }
    assert {message.split(" part=")[1].split(" phase=")[0]
            for message in phases} == {"before_read", "after_read"}
    assert not any("part=before_read phase=result_evidence" in message
                   for message in phases)
    assert all("operation=observe " in message for message in phases)
    assert all("elapsed_ms=" in message for message in phases)
    assert all(" count=1 " in message for message in phases)
    assert "private-account" not in caplog.text
    assert events.count("connection") == 3
    assert events.count("validated") == 3
    assert events.count("PREPARE_READ") == 3
    assert events.count("close") == 3
    assert events.count("commit") == 3


def test_idle_authority_phases_are_per_request_and_preserve_refusal(caplog):
    refusal = AuthorityRefused("private certificate detail")
    with caplog.at_level(logging.INFO, logger=opening_stage_log.LOGGER_NAME):
        with pytest.raises(AuthorityRefused) as caught:
            with opening_stage_log.idle_authority_phases():
                with opening_stage_log.guard_phase("current_publication"):
                    pass
                with opening_stage_log.guard_phase("certificate_bindings"):
                    raise refusal
        with opening_stage_log.idle_authority_phases():
            with opening_stage_log.guard_phase("current_publication"):
                pass
            with opening_stage_log.guard_phase("private certificate detail"):
                pass
            opening_stage_log.authority_rows("publication_rows", 3)
    assert caught.value is refusal
    phases = [message for message in caplog.messages
              if message.startswith("automation_idle_authority_phase ")]
    assert len(phases) == 3
    assert sum("phase=current_publication count=1" in message for message in phases) == 2
    assert sum("phase=certificate_bindings count=1" in message for message in phases) == 1
    assert "automation_idle_authority_rows kind=publication_rows count=1 rows=3" in caplog.messages
    assert "private certificate detail" not in caplog.text


def test_idle_diagnostics_survive_the_worker_reply_and_ignore_unrecognized_payload(caplog):
    import json

    reply = {}
    with caplog.at_level(logging.INFO, logger=opening_stage_log.LOGGER_NAME):
        with opening_stage_log.idle_authority_phases(reply):
            with opening_stage_log.guard_phase('current_publication'):
                opening_stage_log.authority_rows('publication_rows', 3)
        assert not caplog.messages
        reply['phases']['private'] = (1, 123)
        reply['phases']['certificate_bindings'] = (True, 1000)
        opening_stage_log.emit_idle_authority_phases(json.loads(json.dumps(reply)))
    assert len(caplog.messages) == 2
    assert 'phase=current_publication count=1' in caplog.messages[0]
    assert 'kind=publication_rows count=1 rows=3' in caplog.messages[1]


def test_publication_row_count_is_aggregated_without_values(caplog):
    with caplog.at_level(logging.INFO, logger=opening_stage_log.LOGGER_NAME):
        with opening_stage_log.broker_reads():
            with opening_stage_log.broker_read("observe", "before_read"):
                opening_stage_log.authority_rows("publication_rows", 2)
                opening_stage_log.authority_rows("publication_rows", 3)
                opening_stage_log.authority_rows("private account", 99)
    assert "paper_guard_rows operation=observe part=before_read kind=publication_rows count=2 rows=5" in caplog.messages
    assert "private account" not in caplog.text


def test_timing_failure_cannot_replace_original_authority_refusal(monkeypatch):
    events = []
    refusal = AuthorityRefused("private refusal detail")

    def validate(*_args):
        raise refusal

    check = _check(monkeypatch, events, validate)
    grant = PaperPreparationGrant("private-account", date(2026, 11, 23))

    ticks = 0

    def broken_clock():
        nonlocal ticks
        ticks += 1
        if ticks == 7:
            raise RuntimeError("diagnostic clock failed")
        return ticks

    def broken_log(*_args):
        raise RuntimeError("diagnostic log failed")

    monkeypatch.setattr(opening_stage_log, "perf_counter_ns", broken_clock)
    monkeypatch.setattr(opening_stage_log._LOGGER, "info", broken_log)
    with opening_stage_log.broker_reads():
        with opening_stage_log.broker_read("observe", "before_read"):
            with pytest.raises(AuthorityRefused) as caught:
                check(grant, BrokerOperation.OBSERVE, None)
    assert caught.value is refusal
    assert ticks == 8
    assert events.count("close") == 1
    assert "PREPARE_READ" not in events
