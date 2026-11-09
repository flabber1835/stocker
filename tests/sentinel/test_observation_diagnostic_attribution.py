"""Policy stays conservative while new incidents retain closed causal metadata."""
from types import SimpleNamespace

import pytest
from psycopg.errors import QueryCanceled

from sentinel import alert_service
from sentinel.automation import health, outbox

CANARY = 'synthetic-private-health-secret'


class Connection:
    def cursor(self):
        return self
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass
    def execute(self, *args):
        return self
    def fetchone(self):
        return ('control', 'lease')
    def rollback(self):
        pass


def read_failure(monkeypatch, error):
    monkeypatch.setattr(health.store, 'load_control', lambda _: SimpleNamespace(
        enabled=True, kill_switch_engaged=False, generation=158))
    def observe(_):
        if error is not None:
            raise error
        return (SimpleNamespace(observation_seq=7, reasons=('INVALID_SIGNATURE',)),)
    monkeypatch.setattr(health.journal, 'observation_integrity_issues', observe)
    return health.read_health(Connection())


def new_payload(monkeypatch, observed):
    monkeypatch.setattr(alert_service, '_health_cursor', lambda _: (None, 0, None))
    monkeypatch.setattr(outbox, 'enqueue', lambda conn, **kwargs: SimpleNamespace(**kwargs))
    return alert_service._enqueue_health_incident(Connection(), health=observed, max_attempts=3)


@pytest.mark.parametrize('error,code,kind,state', [
    (QueryCanceled(CANARY), 'READ_UNAVAILABLE', 'QueryCanceled', '57014'),
    (ValueError(CANARY), 'CHECK_FAILED', 'ValueError', None),
    (None, 'EVIDENCE_INVALID', None, None),
])
def test_health_and_new_immutable_payload_retain_cause_without_private_reason(monkeypatch, error, code, kind, state):
    observed = read_failure(monkeypatch, error)
    assert observed.healthy is False and observed.operational_ready is False
    assert observed.policy_state == 'UNCERTIFIABLE_OBSERVATIONS'
    alert = new_payload(monkeypatch, observed)
    assert alert.severity == 'CRITICAL' and alert.idempotency_key == 'automation-health-occurrence:1'
    diagnostic = alert.payload['observation_diagnostic']
    assert diagnostic == dict(schema='sentinel.observation-diagnostic/1', stage='OBSERVATION_INTEGRITY',
        code=code, exception_type=kind, errno=None, sqlstate=state)
    assert CANARY not in repr(alert.payload)


def test_existing_occurrence_keeps_original_payload_without_new_key_or_rewrite(monkeypatch):
    observed = read_failure(monkeypatch, QueryCanceled(CANARY))
    original = {'reason': observed.policy_state, 'control_generation': 158,
                'latest_cycle_id': None, 'latest_cycle_state': None, 'broker_outcome_unresolved': 0}
    key = outbox._json({'identity': (observed.policy_state, 158, None, None, 0)})
    monkeypatch.setattr(alert_service, '_health_cursor', lambda _: (key, 4, None))
    monkeypatch.setattr(outbox, 'load_alert', lambda *_: SimpleNamespace(payload=dict(original)))
    monkeypatch.setattr(outbox, 'enqueue', lambda conn, **kwargs: SimpleNamespace(**kwargs))
    alert = alert_service._enqueue_health_incident(Connection(), health=observed, max_attempts=3)
    assert alert.payload == original and 'observation_diagnostic' not in alert.payload
    assert alert.idempotency_key == 'automation-health-occurrence:4'


def test_existing_new_diagnostic_retains_first_cause_even_if_next_error_differs(monkeypatch):
    first = new_payload(monkeypatch, read_failure(monkeypatch, QueryCanceled(CANARY)))
    later = read_failure(monkeypatch, ValueError('different private reason'))
    key = outbox._json({'identity': (later.policy_state, 158, None, None, 0)})
    monkeypatch.setattr(alert_service, '_health_cursor', lambda _: (key, 1, None))
    monkeypatch.setattr(outbox, 'load_alert', lambda *_: SimpleNamespace(payload=first.payload))
    repeated = alert_service._enqueue_health_incident(Connection(), health=later, max_attempts=3)
    assert repeated.payload == first.payload
    assert repeated.payload['observation_diagnostic']['exception_type'] == 'QueryCanceled'


def _assert_cause_retained(monkeypatch):
    alert = new_payload(monkeypatch, read_failure(monkeypatch, QueryCanceled(CANARY)))
    assert 'observation_diagnostic' in alert.payload, 'original causal metadata was lost'


def test_removed_causal_attachment_is_detected(monkeypatch):
    _assert_cause_retained(monkeypatch)
    monkeypatch.setattr(health, '_observation_diagnostic', lambda error=None: None)
    with pytest.raises(AssertionError, match='original causal metadata was lost'):
        _assert_cause_retained(monkeypatch)
