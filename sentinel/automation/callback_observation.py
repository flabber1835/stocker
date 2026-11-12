"""Read-only native facts shared by consumers of active automation callbacks."""

CURRENT_LEADER = """
FROM sentinel_automation_cycles c
JOIN sentinel_automation_control a ON a.id=1 AND a.generation=c.control_generation
  AND a.certificate_sha256=c.certificate_sha256 AND a.config_sha256=c.config_sha256
JOIN sentinel_automation_lease l ON l.id=1 AND l.control_generation=a.generation
LEFT JOIN sentinel_automation_service_instances s ON s.instance_id=l.holder_id
"""

ENABLED = "a.enabled AND NOT a.kill_switch_engaged AND a.authority_verdict='PASS'"


def active_instance(clock):
    """SQL predicate for native callback ownership at the caller's sampled clock."""
    return f"""
        c.last_fence_token=l.fence_token
        AND s.state=CASE c.state
            WHEN 'DISCOVERED' THEN 'PREFLIGHT_RECOVER_CALLBACK'
            WHEN 'REFRESHING_DATA' THEN 'REFRESH_CALLBACK'
            WHEN 'PREPARING' THEN 'PREPARE_CALLBACK'
            WHEN 'EXECUTING' THEN 'EXECUTE_CALLBACK'
            WHEN 'RECONCILING' THEN 'RECOVER_CALLBACK' END
        AND l.expires_at>{clock}
        AND s.heartbeat_at<={clock}
        AND s.heartbeat_at>{clock}-INTERVAL '30 seconds'
        AND s.callback_started_at>=c.updated_at
        AND s.callback_started_at<={clock}
        AND s.callback_deadline_at>s.callback_started_at
        AND s.callback_deadline_at>{clock}
    """


def broker_refresh(conn, cycle_id, state):
    """Original deadline for the exact live callback refreshing broker evidence."""
    if state not in {'DISCOVERED', 'EXECUTING', 'RECONCILING'}:
        return None
    with conn.cursor() as cur:
        cur.execute(f"""
            WITH sampled AS MATERIALIZED (SELECT clock_timestamp() AS at)
            SELECT s.callback_started_at,s.callback_deadline_at
            {CURRENT_LEADER}
            CROSS JOIN sampled
            WHERE {ENABLED} AND c.cycle_id=%s AND c.state=%s
              AND ({active_instance('sampled.at')})
              AND (c.state<>'DISCOVERED' OR (c.plan_id IS NULL
                AND c.failure_code IS NULL AND c.failure_detail IS NULL
                AND c.prepare_at<=s.callback_started_at AND sampled.at<c.execution_open_at))
            """, (cycle_id, state))
        return cur.fetchone()
