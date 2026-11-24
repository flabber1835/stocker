"""Fixed-size execution stage evidence, with no broker or database access."""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import logging
from itertools import count
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


def test_projection_subphases_are_consecutive_and_bounded(monkeypatch, caplog):
    ticks = count()
    monkeypatch.setattr(opening_diagnostics, 'perf_counter_ns',
                        lambda: next(ticks) * 1_000_000)

    @opening_diagnostics.timed_execution
    async def operation():
        with opening_diagnostics.projection('initial'):
            for phase in opening_diagnostics._PROJECTION_PHASES:
                opening_diagnostics.projection_phase(phase)
            opening_diagnostics.projection_phase('state_target')
            opening_diagnostics.projection_phase('private-account-value')
        return _Result()

    with caplog.at_level(logging.INFO, logger=opening_stage_log.LOGGER_NAME):
        asyncio.run(operation())
    records = [message for message in caplog.messages
               if message.startswith('paper_projection_phase ')]
    assert records == [
        f'paper_projection_phase stage=initial phase={phase} elapsed_ms=1'
        for phase in opening_diagnostics._PROJECTION_PHASES
    ]
    assert 'private-account-value' not in caplog.text


def test_projection_refusal_emits_last_phase_without_secret(monkeypatch, caplog):
    ticks = count()
    monkeypatch.setattr(opening_diagnostics, 'perf_counter_ns',
                        lambda: next(ticks) * 1_000_000)
    refusal = RuntimeError('private account and certificate values')

    @opening_diagnostics.timed_execution
    async def operation():
        with opening_diagnostics.projection('final'):
            opening_diagnostics.projection_phase('state_target')
            raise refusal

    with caplog.at_level(logging.INFO, logger=opening_stage_log.LOGGER_NAME):
        with pytest.raises(RuntimeError) as caught:
            asyncio.run(operation())
    assert caught.value is refusal
    assert ('paper_projection_phase stage=final phase=state_target '
            'elapsed_ms=1') in caplog.messages
    assert 'private account' not in caplog.text


@pytest.mark.parametrize('failed_clock_call', (1, 2))
def test_projection_clock_failure_preserves_success(monkeypatch, failed_clock_call):
    ticks = count()

    def failing_clock():
        tick = next(ticks)
        if tick == failed_clock_call:
            raise RuntimeError('diagnostic clock unavailable')
        return tick * 1_000_000

    monkeypatch.setattr(opening_diagnostics, 'perf_counter_ns', failing_clock)

    @opening_diagnostics.timed_execution
    async def operation():
        with opening_diagnostics.projection('initial'):
            opening_diagnostics.projection_phase('state_target')
        return _Result()

    result = asyncio.run(operation())
    assert 'gateway_exit' in result.opening_stages_ms


def test_projection_finish_clock_failure_preserves_original_refusal(monkeypatch):
    ticks = count()

    def failing_clock():
        tick = next(ticks)
        if tick == 3:
            raise RuntimeError('diagnostic clock unavailable')
        return tick * 1_000_000

    monkeypatch.setattr(opening_diagnostics, 'perf_counter_ns', failing_clock)
    refusal = RuntimeError('original financial refusal')

    @opening_diagnostics.timed_execution
    async def operation():
        with opening_diagnostics.projection('final'):
            opening_diagnostics.projection_phase('state_target')
            raise refusal

    with pytest.raises(RuntimeError) as caught:
        asyncio.run(operation())
    assert caught.value is refusal


def test_preflight_times_a_refusal_and_preserves_its_exception(monkeypatch, caplog):
    ticks = iter((5_000_000, 17_250_000))
    monkeypatch.setattr(opening_stage_log, 'perf_counter_ns', lambda: next(ticks))
    refusal = RuntimeError('private detail')
    with caplog.at_level(logging.INFO, logger=opening_stage_log.LOGGER_NAME):
        with pytest.raises(RuntimeError) as caught:
            with opening_stage_log.preflight('cycle_authority'):
                raise refusal
    assert caught.value is refusal
    assert caplog.messages == ['automation_preflight_stage stage=cycle_authority elapsed_ms=12']


def test_close_preflight_separates_dispatch_delay_from_callback_time(monkeypatch, caplog):
    ticks = iter((5_000_000, 7_000_000, 10_000_000, 17_250_000))
    monkeypatch.setattr(opening_stage_log, 'perf_counter_ns', lambda: next(ticks))
    due_at = datetime(2026, 11, 20, 21, 0, tzinfo=timezone.utc)
    with caplog.at_level(logging.INFO, logger=opening_stage_log.LOGGER_NAME):
        with opening_stage_log.close_preflight(due_at + timedelta(seconds=2), due_at):
            with opening_stage_log.callback_startup('PREFLIGHT_RECOVER', 'callback_registration'):
                pass
    assert caplog.messages == [
        'automation_close_preflight event=dispatch retry_due_ms=2000',
        'automation_callback_startup stage=close_preflight_callback_registration event=begin',
        'automation_callback_startup stage=close_preflight_callback_registration event=end elapsed_ms=3',
        'automation_close_preflight event=return elapsed_ms=12',
    ]


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


def test_opening_startup_and_broker_spans_measure_only_owned_work(monkeypatch, caplog):
    ticks = iter(n * 1_000_000 for n in range(8))
    monkeypatch.setattr(opening_stage_log, 'perf_counter_ns', lambda: next(ticks))
    with caplog.at_level(logging.INFO, logger=opening_stage_log.LOGGER_NAME):
        with opening_stage_log.broker_read('observe', 'adapter'):
            pass
        with opening_stage_log.callback_startup('PREPARE', 'fork'):
            pass
        with opening_stage_log.callback_startup('EXECUTE', 'fork'):
            pass
        with pytest.raises(RuntimeError, match='private error'), opening_stage_log.broker_reads():
            for _ in range(2):
                with opening_stage_log.broker_read('observe', 'before_read'):
                    pass
            with opening_stage_log.broker_read('observe', 'adapter'):
                raise RuntimeError('private error')
    assert caplog.messages == [
        'automation_callback_startup stage=fork event=begin',
        'automation_callback_startup stage=fork event=end elapsed_ms=1',
        'paper_broker_read_timing operation=observe part=before_read count=2 elapsed_ms=2',
        'paper_broker_read_timing operation=observe part=adapter count=1 elapsed_ms=1',
    ]


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
        with opening_diagnostics.projection('initial'):
            opening_diagnostics.projection_phase('state_target')
        return _Result()

    assert 'entry' in asyncio.run(successful_gateway()).opening_stages_ms

    @opening_diagnostics.timed_execution
    async def refused_gateway():
        with opening_diagnostics.projection('final'):
            opening_diagnostics.projection_phase('state_target')
            raise RuntimeError('original gateway refusal')

    with pytest.raises(RuntimeError, match='original gateway refusal'):
        asyncio.run(refused_gateway())
