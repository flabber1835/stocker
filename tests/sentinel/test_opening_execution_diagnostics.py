"""Fixed-size execution stage evidence, with no broker or database access."""

import asyncio
from dataclasses import dataclass, field
import logging
import subprocess
import sys

import pytest

from sentinel.paper import opening_diagnostics
from sentinel.automation import service as automation_service
from sentinel import opening_stage_log, supervisor_io


@dataclass(frozen=True)
class _Result:
    opening_stages_ms: dict = field(default_factory=dict)


def test_success_records_fixed_monotonic_stages(monkeypatch, caplog):
    ticks = iter((0, 1_200_000, 3_500_000, 3_600_000))
    monkeypatch.setattr(opening_diagnostics, 'perf_counter_ns', lambda: next(ticks))

    @opening_diagnostics.timed_execution
    async def operation():
        opening_diagnostics.mark('entry')
        return _Result()

    with caplog.at_level(logging.INFO, logger=opening_stage_log.LOGGER_NAME):
        result = asyncio.run(operation())
    assert result.opening_stages_ms == {'entry': 1, 'gateway_exit': 2}
    assert 'status=complete' in caplog.text
    assert 'last_stage=entry' in caplog.text


def test_refusal_logs_completed_stage_and_exception_type(caplog):
    @opening_diagnostics.timed_execution
    async def operation():
        opening_diagnostics.mark('shadow')
        raise RuntimeError('private cause must not enter stage log')

    with caplog.at_level(logging.INFO, logger=opening_stage_log.LOGGER_NAME):
        with pytest.raises(RuntimeError):
            asyncio.run(operation())
    assert 'status=exception' in caplog.text
    assert 'last_stage=shadow' in caplog.text
    assert 'exception_type=RuntimeError' in caplog.text
    assert 'private cause' not in caplog.text


def test_stage_vocabulary_and_cardinality_are_bounded():
    trace = opening_diagnostics._StageTrace()
    trace.mark('entry')
    with pytest.raises(ValueError, match='unknown or repeated'):
        trace.mark('entry')
    with pytest.raises(ValueError, match='unknown or repeated'):
        trace.mark('arbitrary-broker-payload')


def test_terminal_transition_timer_preserves_result_and_failure(monkeypatch, caplog):
    ticks = iter((0, 2_700_000, 4_000_000, 7_100_000))
    monkeypatch.setattr(automation_service.time, 'perf_counter_ns',
                        lambda: next(ticks))
    cycle = object()
    with caplog.at_level(logging.INFO, logger=opening_stage_log.LOGGER_NAME):
        assert automation_service._timed_terminal_transition(
            'EXECUTE', lambda: cycle) is cycle

        def refused():
            raise RuntimeError('terminal write refused')

        with pytest.raises(RuntimeError, match='terminal write refused'):
            automation_service._timed_terminal_transition('RECOVER', refused)
    assert ('path=EXECUTE returned=True elapsed_ms=2') in caplog.text
    assert ('path=RECOVER returned=False elapsed_ms=3') in caplog.text
    with pytest.raises(ValueError, match='unknown terminal'):
        automation_service._timed_terminal_transition('unknown', lambda: cycle)


def test_worker_entry_emits_real_terminal_timing_with_default_logging():
    code = '''
import logging
from sentinel import automation_worker
from sentinel import opening_stage_log
from sentinel.automation import service

assert logging.getLogger().level == logging.WARNING
assert not logging.getLogger().handlers

async def qualified_run():
    logging.getLogger('urllib3').info('third_party_info')
    logging.getLogger(opening_stage_log.LOGGER_NAME).info('unapproved_stage_payload')
    service._timed_terminal_transition("EXECUTE", lambda: object())
    return 0

automation_worker._run = qualified_run
result = automation_worker.main()
assert logging.getLogger().level == logging.WARNING
assert not logging.getLogger().handlers
raise SystemExit(result)
'''
    completed = subprocess.run(
        [sys.executable, '-c', code], capture_output=True, text=True,
        timeout=20, check=False)
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == ''
    assert ('automation_execution_stage stage=terminal_transition_and_commit '
            'path=EXECUTE returned=True elapsed_ms=') in completed.stderr
    assert len(completed.stderr.splitlines()) == 1


def test_worker_stage_sink_bounds_records_and_survives_delivery_failure(monkeypatch):
    delivered = []
    monkeypatch.setattr(supervisor_io, 'report', delivered.append)
    sink = opening_stage_log._WorkerStageSink()

    def record(template, args):
        return logging.LogRecord(
            opening_stage_log.LOGGER_NAME, logging.INFO, __file__, 1,
            template, args, None)

    template = ('automation_execution_stage stage=terminal_transition_and_commit '
                'path=%s returned=%s elapsed_ms=%d')
    sink.emit(record(template, ('EXECUTE', True, 2)))
    sink.emit(record('unapproved_stage_payload=%s', ('secret',)))
    sink.emit(record(template, ('EXECUTE\nprivate', True, 2)))
    sink.emit(record(template, ('X' * 600, True, 2)))
    assert delivered == [
        'automation_execution_stage stage=terminal_transition_and_commit '
        'path=EXECUTE returned=True elapsed_ms=2']

    def delivery_failed(_message):
        raise OSError('stderr unavailable')

    monkeypatch.setattr(supervisor_io, 'report', delivery_failed)
    sink.emit(record(template, ('RECOVER', False, 3)))


def test_logging_failure_cannot_change_terminal_or_gateway_result(monkeypatch):
    def logging_failed(*_args, **_kwargs):
        raise OSError('diagnostic sink unavailable')

    monkeypatch.setattr(opening_stage_log._LOGGER, 'info', logging_failed)
    cycle = object()
    assert automation_service._timed_terminal_transition('EXECUTE',
                                                         lambda: cycle) is cycle

    def refused():
        raise RuntimeError('terminal state unknown')

    with pytest.raises(RuntimeError, match='terminal state unknown'):
        automation_service._timed_terminal_transition('RECOVER', refused)

    @opening_diagnostics.timed_execution
    async def successful_gateway():
        opening_diagnostics.mark('entry')
        return _Result()

    assert 'entry' in asyncio.run(successful_gateway()).opening_stages_ms

    @opening_diagnostics.timed_execution
    async def refused_gateway():
        raise RuntimeError('original gateway refusal')

    with pytest.raises(RuntimeError, match='original gateway refusal'):
        asyncio.run(refused_gateway())
