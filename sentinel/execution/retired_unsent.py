"""Durable proof that retired unfilled BUY stubs cannot require an order read."""
from collections.abc import Mapping

from sentinel.execution import journal
from sentinel.execution.states import IN_FLIGHT, TERMINAL, CommandState


_ACTIVE = sorted(state.value for state in IN_FLIGHT | {CommandState.PLANNED})


def no_planned_buy_native_match(payload, planned_keys):
    """A restored checkpoint is not proof if native list or exact GET found it."""
    if not planned_keys:
        return True
    orders, exact = payload.get('orders'), payload.get('exact_evidence')
    if not isinstance(orders, list) or not isinstance(exact, list):
        return False
    if any(not isinstance(order, Mapping)
           or not isinstance(order.get('client_key'), str)
           or order['client_key'] in planned_keys for order in orders):
        return False
    return not any(not isinstance(item, Mapping)
        or not isinstance(item.get('client_key'), str)
        or item['client_key'] in planned_keys and item.get('order') is not None
        or isinstance(item.get('order'), Mapping)
            and item['order'].get('client_key') in planned_keys
        for item in exact)


def only_retired_unsent_buys(conn, cycle, observation, counts, *, now):
    """Prove the global PLANNED set cannot require broker reconciliation."""
    planned_count = counts.get('PLANNED', 0)
    if (not cycle or cycle.get('state') != 'WAITING_OPEN'
            or not 0 < planned_count <= 100
            or counts != {'PLANNED': planned_count}
            or observation['completeness'] != 'COMPLETE'
            or observation['runtime_state'] != 'RUNNING'):
        return False

    return _retired_evidence(conn, cycle['cycle_id'], cycle.get('plan_id'), planned_count,
        current_keys=(), required_keys=None, waiting=(cycle.get('next_wake_at'), now,
        observation['sequence'], observation['observed_at']))


def retired_at_cutoff(conn, cycle, *, current_keys, retired_keys, deadline):
    """Exclude only identified, never-transported commands from a superseded plan."""
    if not retired_keys or len(current_keys | retired_keys) > 100 or current_keys & retired_keys:
        return False
    if conn.execute("SELECT 1 FROM sentinel_fills WHERE client_key=ANY(%s) LIMIT 1",
                    (sorted(retired_keys),)).fetchone():
        return False
    return _retired_evidence(conn, cycle.cycle_id, cycle.plan_id, len(retired_keys),
                             current_keys=current_keys, required_keys=retired_keys, deadline=deadline)


def _retired_evidence(conn, cycle_id, plan_id, retired_count, *, current_keys,
                      required_keys, waiting=None, deadline=None):
    # A pre-open display must still be anchored to the exact scheduled wake.
    # At cutoff the caller separately verifies both its saved and latest observations.
    if waiting is None:
        phase = "waiting.state IN ('EXECUTING','RECONCILING','RETRY_WAIT','SUPERSEDED')"
        phase_args = ()
    else:
        phase = """waiting.state='WAITING_OPEN' AND waiting.failure_code IS NULL
              AND waiting.next_wake_at=waiting.execute_at AND waiting.next_wake_at=%s
              AND %s<waiting.execute_at AND newest.seq=%s AND newest.observed_at=%s
              AND newest.seq::text=waiting.last_clean_reconciliation_id"""
        phase_args = waiting
    rows = conn.execute(f"""
        SELECT cmd.client_key, old.execute_at, old.completed_at, prior.seq,
               waiting.broker, waiting.broker_account_id, newest.seq
        FROM sentinel_automation_cycles waiting
        JOIN sentinel_automation_control control ON control.id=1
          AND waiting.control_generation=control.generation
          AND waiting.certificate_sha256=control.certificate_sha256
          AND waiting.config_sha256=control.config_sha256
          AND (waiting.deployment_id,waiting.broker,waiting.broker_account_id,waiting.takeover_epoch)
             =(control.deployment_id,control.broker,control.broker_account_id,control.takeover_epoch)
        JOIN sentinel_account_binding binding ON binding.id=1
          AND binding.ownership_state='SENTINEL_OWNED'
          AND (binding.deployment_id,binding.broker,binding.broker_account_id,binding.takeover_epoch)
             =(waiting.deployment_id,waiting.broker,waiting.broker_account_id,waiting.takeover_epoch)
        JOIN sentinel_execution_plans current ON current.plan_id=waiting.plan_id
          AND current.superseded_by IS NULL
          AND (current.decision_session,current.effective_session)
             =(waiting.decision_session,waiting.effective_session)
          AND (current.deployment_id,current.broker,current.broker_account_id,current.takeover_epoch)
             =(waiting.deployment_id,waiting.broker,waiting.broker_account_id,waiting.takeover_epoch)
          JOIN sentinel_commands cmd ON cmd.state='PLANNED'
            AND (cmd.deployment_id,cmd.broker,cmd.broker_account_id,cmd.takeover_epoch)
               =(waiting.deployment_id,waiting.broker,waiting.broker_account_id,waiting.takeover_epoch)
          JOIN sentinel_execution_plans expired ON expired.plan_id=cmd.plan_id
            AND expired.effective_session=current.decision_session
          AND (expired.deployment_id,expired.broker,expired.broker_account_id,expired.takeover_epoch)
             =(waiting.deployment_id,waiting.broker,waiting.broker_account_id,waiting.takeover_epoch)
        JOIN sentinel_automation_cycles old ON old.plan_id=expired.plan_id
            AND old.control_generation BETWEEN 1 AND waiting.control_generation
          AND (old.decision_session,old.effective_session)
             =(expired.decision_session,expired.effective_session)
          AND (old.deployment_id,old.broker,old.broker_account_id,old.takeover_epoch)
             =(waiting.deployment_id,waiting.broker,waiting.broker_account_id,waiting.takeover_epoch)
        JOIN sentinel_observations newest ON newest.seq=(SELECT max(seq) FROM sentinel_observations)

        JOIN sentinel_observations prior ON prior.seq::text=old.last_clean_reconciliation_id
          AND prior.seq<newest.seq AND prior.observed_at BETWEEN old.execute_at AND old.completed_at
        WHERE waiting.cycle_id=%s AND waiting.plan_id=%s AND ({phase})
          AND control.enabled AND NOT control.kill_switch_engaged
          AND control.authority_verdict='PASS'
          AND NOT waiting.historical_state_only AND NOT old.historical_state_only
          AND NOT (cmd.client_key=ANY(%s::text[]))
          AND old.state='SUPERSEDED' AND old.failure_code=%s
          AND old.completed_at<=newest.observed_at
          AND old.diagnostic->'clean'='true'::jsonb AND old.diagnostic->>'terminal_reason' IS NULL
          AND old.diagnostic->'unresolved'='[]'::jsonb
          AND old.diagnostic->'foreign_orders'='[]'::jsonb
          AND old.diagnostic->'foreign_positions'='[]'::jsonb
          AND old.diagnostic->'restricted_securities'='{{}}'::jsonb
          AND old.diagnostic->'expected'=old.diagnostic->'observed'

          AND newest.completeness='COMPLETE' AND newest.runtime_state='RUNNING'
          AND prior.completeness='COMPLETE' AND prior.runtime_state='RUNNING'
          AND cmd.side='BUY' AND cmd.filled_quantity=0 AND cmd.broker_order_id IS NULL
          AND (SELECT count(*) FROM sentinel_commands WHERE state=ANY(%s))=%s
            AND EXISTS (
                WITH RECURSIVE successors(plan_id,superseded_by,hops) AS (
                    SELECT expired.plan_id,expired.superseded_by,0
                    UNION ALL
                    SELECT next_plan.plan_id,next_plan.superseded_by,successors.hops+1
                    FROM successors
                    JOIN sentinel_execution_plans next_plan ON next_plan.plan_id=successors.superseded_by
                    WHERE successors.hops<32
                      AND (next_plan.decision_session,next_plan.effective_session)
                         =(current.decision_session,current.effective_session)
                      AND (next_plan.deployment_id,next_plan.broker,next_plan.broker_account_id,next_plan.takeover_epoch)
                         =(current.deployment_id,current.broker,current.broker_account_id,current.takeover_epoch)
                )
                SELECT 1 FROM successors WHERE plan_id=current.plan_id
            )
        LIMIT 101
        """, (cycle_id, plan_id, *phase_args, sorted(current_keys),
              'MAX_EXECUTION_LATENESS_EXCEEDED', _ACTIVE, retired_count + len(current_keys))).fetchall()
    keys = {row[0] for row in rows}
    anchor = {tuple(row[3:]) for row in rows}
    if (len(rows) != retired_count or len(keys) != retired_count or len(anchor) != 1
            or (required_keys is not None and keys != required_keys)):
        return False
    prior, broker, account, newest = anchor.pop()
    from sentinel.automation.missed_buy_alert import no_transport_chain
    if not all(no_transport_chain(conn, key, execute_at=opened, as_of=completed, deadline=deadline)
               for key, opened, completed, *_ in rows):
        return False

    terminal = {state.value for state in TERMINAL}
    for sequence in (prior, newest):
        payload = journal.load_observation_payload(conn, sequence)
        if (payload.get('completeness') != 'COMPLETE'
                or (payload.get('broker'), payload.get('account_id')) != (broker, account)
                or not no_planned_buy_native_match(payload, keys)
                or any(order.get('state') not in terminal for order in payload['orders'])):
            return False
    return True
