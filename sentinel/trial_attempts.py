"""Immutable cycle-scoped trial history and a single daily economic view."""
from collections import defaultdict
from datetime import date
import re
from typing import Mapping

PREFIX = 'trial-account:v2:verification-attempt:v1:'


def key(session: date, cycle_id: str) -> str:
    from sentinel import trial
    if not isinstance(cycle_id, str) or re.fullmatch(r'[A-Za-z0-9_-]{1,128}', cycle_id) is None:
        raise trial.TrialEvidenceRefused('trial attempt requires an exact cycle identity')
    return f'{PREFIX}{session.isoformat()}:{cycle_id}'


def stored(conn, *, session, cycle_id):
    from sentinel import trial
    value = trial._stored(conn, key(session, cycle_id))
    if value is None:
        legacy = trial._stored(conn, f'{trial.VERIFICATION_PREFIX}{session.isoformat()}')
        if legacy is not None and (legacy[1].get('cycle') or {}).get('cycle_id') == cycle_id:
            value = legacy
    return value


def _scope(cycle):
    return tuple(getattr(cycle, name, None) for name in (
        'deployment_id', 'broker', 'broker_account_id', 'takeover_epoch',
        'decision_session', 'effective_session'))


def _unsent(conn, cycle) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT EXISTS(SELECT 1 FROM sentinel_automation_cycle_events "
                    "WHERE cycle_id=%s AND (from_state IN ('EXECUTING','RECONCILING') "
                    "OR to_state IN ('EXECUTING','RECONCILING'))) OR "
                    "EXISTS(SELECT 1 FROM sentinel_commands WHERE plan_id=%s)",
                    (cycle.cycle_id, cycle.plan_id))
        return not cur.fetchone()[0]


def select(conn, records: list[dict]) -> list[dict]:
    """Authenticate attempts before selecting at most one economic cycle/day."""
    from sentinel import trial
    from sentinel.automation import integrity, store

    days = defaultdict(dict)
    for record in records:
        cycle_id = (record.get('cycle') or {}).get('cycle_id')
        if not isinstance(cycle_id, str) or not cycle_id:
            raise trial.TrialEvidenceRefused('trial attempt has no cycle identity')
        previous = days[record['session']].get(cycle_id)
        if previous is not None and previous != record:
            raise trial.TrialEvidenceRefused('one trial cycle has contradictory immutable records')
        days[record['session']][cycle_id] = record
    result = []
    for session, attempts in sorted(days.items()):
        if len(attempts) == 1:
            result.append(next(iter(attempts.values())))
            continue
        cycles = [store.load_cycle(conn, cycle_id) for cycle_id in sorted(attempts)]
        first_scope = _scope(cycles[0])
        if any(value is None for value in first_scope):
            raise trial.TrialEvidenceRefused('multiple trial attempts require a complete native scope')
        for cycle in cycles:
            record = attempts[cycle.cycle_id]
            binding = record.get('binding')
            if (not isinstance(binding, Mapping) or _scope(cycle) != first_scope
                    or str(cycle.effective_session) != session
                    or (record.get('cycle') or {}).get('state') != cycle.state.value
                    or not cycle.state.terminal
                    or any(binding.get(name) != getattr(cycle, name) for name in (
                        'deployment_id', 'broker', 'broker_account_id', 'takeover_epoch'))):
                raise trial.TrialEvidenceRefused('trial attempts disagree with their native scope/state')
            integrity.validate_cycle_lineage(conn, cycle)
        successes = [cycle for cycle in cycles if cycle.state.value == 'SUCCEEDED']
        if len(successes) > 1:
            raise trial.TrialEvidenceRefused('multiple successful trial cycles name one effective session')
        chosen = (successes[0] if successes else
                  max(cycles, key=lambda cycle: (cycle.control_generation, cycle.cycle_id)))
        if any(not _unsent(conn, other) for other in cycles if other.cycle_id != chosen.cycle_id):
            raise trial.TrialEvidenceRefused('another same-session trial attempt has transport evidence')
        result.append(attempts[chosen.cycle_id])
    return result


def recover_unsent_failures(conn, cycle, *, now):
    """Recover missed audit callbacks only for positively unsent native failures."""
    from sentinel import trial
    from sentinel.automation import integrity, store

    if any(value is None for value in _scope(cycle)):
        return  # An unbound historical diagnostic cannot authorize reconstruction.
    integrity.validate_cycle_lineage(conn, cycle)
    for other in store._cycles_in_scope(conn, cycle):
        if (other.cycle_id == cycle.cycle_id or not other.state.terminal
                or other.state.value == 'SUCCEEDED'
                or stored(conn, session=other.effective_session, cycle_id=other.cycle_id) is not None):
            continue
        integrity.validate_cycle_lineage(conn, other)
        if not _unsent(conn, other):
            continue
        record = trial._terminal_failure(other, now)
        record['recovered_terminal_callback'] = True
        record['evidence_sha256'] = trial._sha(record)
        trial._insert_immutable(conn, name=key(other.effective_session, other.cycle_id),
                                session=other.effective_session, state=record)
