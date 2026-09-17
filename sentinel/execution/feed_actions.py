"""Snapshot action inputs for the existing execution reconciliation policy."""
from datetime import date

from sentinel.execution import feed_inputs, reconcile
from sentinel.feed import calendar, rolling_store, actions_map


def action_lookup(conn, *, start, end):
    pub = feed_inputs.current(conn)
    if not feed_inputs.is_rolling(pub):
        return reconcile.corpus_action_lookup(conn, start=start, end=end)
    from sentinel.feed import action_history
    retained = action_history.lookup(conn, pub, start=start, end=end)
    if retained is not None:
        return retained
    refs = feed_inputs.references(conn, pub)
    return snapshot_lookup(conn, refs=refs, pub=pub, start=start, end=end)


def snapshot_lookup(conn, *, refs, pub, start, end):
    """Canonical interpretation for an explicit, validated generation."""
    predecessor = date.fromisoformat(calendar.previous_sessions(start, 1)[0])
    if (predecessor < refs.manifest.window.start or end < start
            or str(end) > calendar.next_session(pub.window_end)):
        raise feed_inputs.ExecutionInputsRefused("ROLLING_ACTION_HISTORY_UNAVAILABLE")
    raw_start, raw_end = calendar.action_date_window(start, end)
    actions = [(date.fromisoformat(p["date"]), p["value"], source, p["action"], p["ticker"], p["contraticker"])
               for source, p, _ in refs.actions if raw_start <= p["date"] <= raw_end]
    with conn.cursor() as cur:
        cur.execute("SELECT security_id,session,ticker,split_ratio FROM sentinel_snapshot_bars "
                    "WHERE candidate_id=%s AND session>%s AND session<=%s AND split_ratio<>1 "
                    "ORDER BY session,security_id", (refs.candidate_id, start, end))
        equity = [(*row, pub.run_id, pub.version) for row in cur.fetchall()]
        cur.execute("SELECT session,bil_close_signal,bil_close_unadjusted "
                    "FROM sentinel_snapshot_benchmarks WHERE candidate_id=%s "
                    "AND session>=%s AND session<=%s ORDER BY session", (refs.candidate_id, predecessor, end))
        benchmarks = list(cur.fetchall())
        cur.execute("SELECT validation_sha256 FROM sentinel_snapshot_validations WHERE candidate_id=%s",
                    (refs.candidate_id,))
        validation_sha = cur.fetchone()[0]
    defensive = []
    for prior, row in zip(benchmarks, benchmarks[1:]):
        defensive.append(("SENTINEL:BIL", row[0], "BIL", row[1], row[2], prior[0], prior[1], prior[2],
                          pub.run_id, pub.version, pub.run_id, pub.version))
    # Never infer that a missing predecessor/pair means no split.
    expected = calendar.sessions_in_range(start, min(end, refs.manifest.window.end))
    wanted = [day for day in expected if day > str(start)]
    if [str(row[1]) for row in defensive] != wanted:
        raise feed_inputs.ExecutionInputsRefused("ROLLING_ACTION_PREDECESSOR_MISSING")
    validation = rolling_store.load_evidence(conn, validation_sha)
    dispositions = []
    corroborated = {actions_map.SPLIT_CORROBORATED_DIRECT, actions_map.SPLIT_CORROBORATED_QUANTIZED,
                    actions_map.SPLIT_CORROBORATED_SHIFTED, actions_map.SPLIT_CORROBORATED_BRIDGED}
    for item in validation["split_dispositions"]:
        if not str(start) < item["session"] <= str(end):
            continue
        value = item["disposition"]
        if value in corroborated:
            kind = "SPLIT_CORROBORATED_DERIVED"
        elif value == actions_map.SPLIT_AUTHORITATIVE_APPLIED:
            kind = "SPLIT_AUTHORITATIVE_APPLIED"
        elif value == actions_map.SPLIT_RESOLVED_NO_EVENT:
            kind = "SPLIT_RESOLVED_NO_EVENT"
        else:
            kind = "SPLIT_UNRESOLVED"
        dispositions.append({"ticker": item["ticker"], "session": item["session"], "kind": kind,
            "detail": "applied=" + str(item["applied_ratio"]),
            "observation_id": validation_sha, "publication_version": pub.version, "last_written_run_id": pub.run_id})

    def mapping(symbol, effective):
        with conn.cursor() as cur:
            cur.execute("SELECT security_id,split_ratio FROM sentinel_snapshot_bars "
                        "WHERE candidate_id=%s AND ticker=%s AND session=%s ORDER BY security_id",
                        (refs.candidate_id, symbol, effective))
            return [(*row, pub.run_id, pub.version) for row in cur.fetchall()]
    return reconcile.reconcile_action_material(start=start, end=end, action_rows=actions,
        published_equity_rows=equity, defensive_rows=defensive, dispositions=dispositions, equity_mapping=mapping)
