"""Fresh owner-authorized PAPER intent after native terminal recovery."""
from sentinel import local_paper
from sentinel.automation.model import AutomationRefused, CycleState


def eligible(conn, *, spec, cycles, config):
    if not local_paper.require_bound_account(conn):
        return False
    if config is None or config.debug_window_for(spec) is None or not cycles:
        return False
    from sentinel.automation import integrity, store
    recovered = False
    for cycle in cycles:
        integrity.validate_cycle_lineage(conn, cycle)
        if (cycle.control_generation >= spec.control_generation
                or cycle.historical_state_only
                or (cycle.deployment_id, cycle.broker, cycle.broker_account_id,
                    cycle.takeover_epoch, cycle.decision_session, cycle.effective_session)
                != (spec.deployment_id, spec.broker, spec.broker_account_id,
                    spec.takeover_epoch, spec.decision_session, spec.effective_session)):
            return False
        if store._unsent_retirement(cycle, spec, debug=True):
            # Preserve the negative transport proof for ordinary retirements.
            with conn.cursor() as cur:
                cur.execute("SELECT EXISTS(SELECT 1 FROM sentinel_automation_cycle_events "
                    "WHERE cycle_id=%s AND (from_state IN ('EXECUTING','RECONCILING') "
                    "OR to_state IN ('EXECUTING','RECONCILING'))) OR "
                    "EXISTS(SELECT 1 FROM sentinel_commands WHERE plan_id=%s)",
                    (cycle.cycle_id, cycle.plan_id))
                if cur.fetchone()[0]:
                    return False
            continue
        if (cycle.state is not CycleState.SUPERSEDED
                or cycle.failure_code != 'OLD_GENERATION_RECOVERED'
                or not cycle.plan_id or not cycle.last_clean_reconciliation_id
                or cycle.diagnostic.get('clean') is not True
                or cycle.diagnostic.get('unresolved') != []
                or cycle.diagnostic.get('foreign_orders') != []
                or cycle.diagnostic.get('foreign_positions') != []):
            return False
        with conn.cursor() as cur:
            cur.execute("SELECT EXISTS(SELECT 1 FROM sentinel_observations o "
                "JOIN sentinel_observation_provenance p ON p.observation_seq=o.seq "
                "WHERE o.seq=%s AND o.runtime_state='RUNNING' "
                "AND o.completeness='COMPLETE' AND p.broker=%s "
                "AND p.broker_account_id=%s AND p.canonical_payload_sha256 IS NOT NULL)",
                (int(cycle.last_clean_reconciliation_id), spec.broker, spec.broker_account_id))
            if not cur.fetchone()[0]:
                return False
            cur.execute("SELECT EXISTS(SELECT 1 FROM sentinel_commands WHERE plan_id=%s "
                "AND state NOT IN ('FILLED','CANCELLED','REJECTED','SUPERSEDED'))", (cycle.plan_id,))
            if cur.fetchone()[0]:
                return False
        recovered = True
    return recovered


def require(conn, *, spec, cycles, config):
    if not eligible(conn, spec=spec, cycles=cycles, config=config):
        raise AutomationRefused('local PAPER continuation lacks terminal account-bound recovery')
