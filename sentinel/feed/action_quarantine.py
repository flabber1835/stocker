"""Generic, publication-bound quarantine for uncertain source actions."""
from __future__ import annotations

from sentinel.feed import actions_map, calendar, rolling_store

MAX_QUARANTINED_SECURITIES = 16


def prior_ids(conn, expected_version):
    """Carry unresolved permanent identities across operational publications."""
    if expected_version is None:
        return ()
    from sentinel.feed import operational_snapshot
    current = operational_snapshot._current(conn)
    if current is None or current.version != expected_version:
        raise ValueError("quarantine publication frontier changed")
    if "rolling_snapshot" not in current.evidence:
        return ()
    bound = operational_snapshot._bound(conn, current)
    candidate = bound["candidate_id"]
    row = conn.execute("SELECT validation_sha256 FROM sentinel_snapshot_validations "
                       "WHERE candidate_id=%s", (candidate,)).fetchone()
    validation = rolling_store.load_evidence(conn, row[0]) if row else {}
    if validation.get("snapshot_id") != bound["snapshot_id"]:
        raise ValueError("prior action quarantine is not snapshot-bound")
    ids = validation.get("action_quarantine", [])
    if not isinstance(ids, list) or any(not isinstance(item, dict) or
       not isinstance(item.get("security_id"), str) for item in ids):
        raise ValueError("invalid prior action quarantine")
    return tuple(ids)


def classify(identity, actions, sessions, *, prior=()):
    """Return affected permanent identities; ambiguous mapping always refuses."""
    splits, ambiguous = actions_map.split_rows_from_actions(actions, sessions)
    reasons = [{"ticker": item["ticker"], "session": item["session"],
                "reason": "AMBIGUOUS_SPLIT", "source": item} for item in ambiguous]
    reasons.extend({"ticker": item["ticker"],
                    "session": actions_map.snap_to_session(item["date"], sessions),
                    "reason": "UNUSABLE_DIVIDEND", "source": item}
                   for item in actions_map.unusable_dividend_rows_detail(actions))
    result = {item["security_id"]: item for item in prior}
    resolver = identity.resolver()
    for item in reasons:
        session = item["session"]
        if session is None:
            continue
        sid = resolver.resolve(item["ticker"], session)
        if sid is None:
            raise ValueError("uncertain action has no unambiguous permanent identity")
        result.setdefault(sid, {"security_id": sid, "reason": item["reason"],
                                "session": session, "source": item["source"]})
    if len(result) > MAX_QUARANTINED_SECURITIES:
        raise ValueError("systemic corporate-action uncertainty exceeds quarantine bound")
    return [result[sid] for sid in sorted(result)]


def safe_actions(actions, identity, quarantine, sessions):
    """Exclude uncertain economics from normalization, retaining raw references."""
    ids = {item["security_id"] for item in quarantine}
    resolver = identity.resolver()
    result = []
    for row in actions:
        session = actions_map.snap_to_session(str(row["date"]), sessions)
        sid = resolver.resolve(str(row["ticker"]), session) if session else None
        if sid not in ids:
            result.append(row)
    return result
