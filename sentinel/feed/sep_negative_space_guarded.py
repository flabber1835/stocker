"""Guarded economic-preserving SEP negative-space retirement."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import dataclass

from sentinel.feed import domains, publication, sep_negative_space as core
from stock_strategy_shared.split_reconciliation import (
    SPLIT_UNRESOLVED,
    SplitStreamReconciler,
)

KIND = core.KIND
MAX_RETIREMENTS = core.MAX_RETIREMENTS
SCHEMA = core.SCHEMA
SepNegativeSpaceRefused = core.SepNegativeSpaceRefused
_ORIGINAL_REPAIR = core.repair_local_only
_ORIGINAL_RETIRE = core._retire_and_publish
_COMPLETE_SEP_AUTHORITY = "nasdaq-data-link-table-export-composite/v1"
_COMPLETE_ACTIONS_AUTHORITY = "nasdaq-data-link-table-export/v1"
_SEP_RETIREMENT_CAPABILITY = object()


@dataclass(frozen=True)
class _ValidatedRetirementAuthority:
    capability: object
    source_sha256: str
    actions_sha256: str
    observation_ceiling: str
    source_observation_boundary: str
    interval: tuple[str, str]
    source_rows: int
    actions_publication_version: int


def _evidence_sha256(value) -> str:
    payload = json.dumps(
        dict(value or {}), sort_keys=True, separators=(",", ":"),
        default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _assert_retired_rows_have_no_economic_events(conn, keys: list[dict]) -> None:
    """Every exact retirement target is economically empty in published state."""
    if not keys:
        return
    core._load_retire_table(conn, keys)
    effective = publication.effective_split_ratio("b")
    with conn.cursor() as cur:
        cur.execute(
            "SELECT b.security_id,b.session,b.ticker," + effective +
            ", b.dividend_per_share"
            f" FROM sentinel_bars b JOIN {core._TEMP_RETIRE_KEYS} r"
            " ON r.security_id=b.security_id AND r.session=b.session"
            " AND r.ticker=b.ticker WHERE " + publication.visible_predicate("b")
            + " ORDER BY b.session,b.security_id,b.ticker")
        rows = list(cur.fetchall())
    if len(rows) != len(keys):
        raise SepNegativeSpaceRefused(
            "SEP retirement target changed before economic-event proof")
    for sid, session, ticker, split_ratio, dividend in rows:
        split = float(split_ratio or 1.0)
        div = float(dividend or 0.0)
        if abs(split - 1.0) > 1e-12:
            raise SepNegativeSpaceRefused(
                "SEP retirement row carries an effective split event: "
                f"{sid}/{session}/{ticker} split_ratio={split:g}")
        if abs(div) > 1e-12:
            raise SepNegativeSpaceRefused(
                "SEP retirement row carries a dividend entitlement: "
                f"{sid}/{session}/{ticker} dividend_per_share={div:g}")


def _assert_current_actions_have_no_retirement_events(conn, keys: list[dict]) -> None:
    """Current complete ACTIONS may establish economics absent from a stale bar."""
    if not keys:
        return
    from sentinel.feed import actions_map, calendar, ingest_impl
    from sentinel.core.terminal import DIVIDEND_ACTIONS

    start = min(str(key["session"]) for key in keys)
    end = max(str(key["session"]) for key in keys)
    splits, dividends, rows, _ambiguous = ingest_impl._action_maps(conn, start, end)
    split_keys = {(str(t).upper(), str(s)) for t, s in splits}
    dividend_keys = {(str(t).upper(), str(s)) for t, s in dividends}

    sessions = calendar.sessions_in_range(start, end)
    for row in rows:
        if str(row.get("action") or "").lower() not in DIVIDEND_ACTIONS:
            continue
        session = actions_map.snap_to_session(str(row.get("date") or ""), sessions)
        if session is not None:
            dividend_keys.add((str(row.get("ticker") or "").upper(), str(session)))

    for key in keys:
        ticker = str(key["ticker"]).upper()
        session = str(key["session"])
        if (ticker, session) in split_keys:
            raise SepNegativeSpaceRefused(
                "SEP retirement target carries a current authoritative ACTIONS "
                f"split event: {key['security_id']}/{session}/{ticker}")
        if (ticker, session) in dividend_keys:
            raise SepNegativeSpaceRefused(
                "SEP retirement target carries a current authoritative ACTIONS "
                f"dividend entitlement: {key['security_id']}/{session}/{ticker}")


def _canonical_surviving_split_decision(
        conn, *, ticker: str, session: str, prev_row, next_row):
    """Re-run the surviving edge through the same split membrane as ingest."""
    from sentinel.feed import calendar, ingest_impl

    action_end = calendar.next_session(session)
    splits, _dividends, _rows, _ambiguous = ingest_impl._action_maps(
        conn, session, action_end)
    fallback = domains.split_ratio_from_domains(
        prev_row[0], prev_row[1], next_row[0], next_row[1])
    reconciler = SplitStreamReconciler(splits)
    return reconciler.decide(
        (str(ticker), str(session)),
        prev_close=prev_row[0], prev_raw=prev_row[1],
        close=next_row[0], raw=next_row[1],
        fallback_ratio=fallback)


def _assert_retirement_preserves_split_chain(conn, keys: list[dict]) -> None:
    """Resolve the next surviving edge with canonical ingest split semantics."""
    effective = publication.effective_split_ratio("b")
    visible = publication.visible_predicate("b")
    for key in keys:
        sid, session = key["security_id"], key["session"]
        with conn.cursor() as cur:
            cur.execute(
                "SELECT b.close_signal,b.close_unadjusted FROM sentinel_bars b"
                " WHERE b.security_id=%s AND b.session<%s AND " + visible +
                f" AND NOT EXISTS (SELECT 1 FROM {core._TEMP_RETIRE_KEYS} r"
                "  WHERE r.security_id=b.security_id AND r.session=b.session"
                "    AND r.ticker=b.ticker)"
                " ORDER BY b.session DESC LIMIT 1",
                (sid, session))
            prev_row = cur.fetchone()
            cur.execute(
                "SELECT b.session,b.ticker,b.close_signal,b.close_unadjusted," + effective +
                " FROM sentinel_bars b"
                " WHERE b.security_id=%s AND b.session>%s AND " + visible +
                f" AND NOT EXISTS (SELECT 1 FROM {core._TEMP_RETIRE_KEYS} r"
                "  WHERE r.security_id=b.security_id AND r.session=b.session"
                "    AND r.ticker=b.ticker)"
                " ORDER BY b.session ASC LIMIT 1",
                (sid, session))
            next_row = cur.fetchone()
        if next_row is None:
            continue
        next_session = str(next_row[0])
        next_ticker = str(next_row[1])
        next_prices = (next_row[2], next_row[3])
        effective_next = float(next_row[4] or 1.0)
        if prev_row is None:
            if abs(effective_next - 1.0) > 1e-12:
                raise SepNegativeSpaceRefused(
                    "SEP retirement would change the effective split chain for "
                    f"{sid} after {session}: no surviving predecessor remains, "
                    f"so canonical normalization yields no predecessor-derived "
                    f"split but published ratio is {effective_next:g}")
            continue

        decision = _canonical_surviving_split_decision(
            conn, ticker=next_ticker, session=next_session,
            prev_row=prev_row, next_row=next_prices)
        resolved = float(decision.ratio)
        if (decision.disposition == SPLIT_UNRESOLVED
                or abs(resolved - effective_next) > 1e-12):
            disposition = decision.disposition or "fallback"
            raise SepNegativeSpaceRefused(
                "SEP retirement would change the effective split chain for "
                f"{sid} after {session}: canonical bridge resolution is "
                f"{disposition}/{resolved:g} from price evidence "
                f"{decision.derived!r} and ACTIONS {decision.stated!r}, "
                f"published ratio is {effective_next:g}")


def _authority_time(value, *, field: str) -> dt.datetime:
    text = str(value or "").strip()
    if not text:
        raise SepNegativeSpaceRefused(
            f"production SEP retirement authority omitted {field}")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError as exc:
        raise SepNegativeSpaceRefused(
            f"production SEP retirement authority has invalid {field}") from exc
    if parsed.tzinfo is None:
        raise SepNegativeSpaceRefused(
            f"production SEP retirement authority {field} is timezone-naive")
    return parsed.astimezone(dt.timezone.utc)


def _authority_date(value, *, field: str) -> dt.date:
    return _authority_time(value, field=field).date()


def _require_production_retirement_authority(
        *, source_authority_evidence, actions_authority_evidence,
        observation_ceiling: dt.date, source_observation_boundary,
        fetch=None, start=None, end=None, source_rows=None):
    """Validate complete SEP+ACTIONS provenance and mint boundary capability."""
    source = dict(source_authority_evidence or {})
    actions = dict(actions_authority_evidence or {})
    if source.get("authority") != _COMPLETE_SEP_AUTHORITY or source.get("table") != "SEP":
        raise SepNegativeSpaceRefused(
            "production SEP retirement lacks complete SEP Exporter authority")
    if actions.get("authority") != _COMPLETE_ACTIONS_AUTHORITY or actions.get("table") != "ACTIONS":
        raise SepNegativeSpaceRefused(
            "production SEP retirement lacks fresh complete ACTIONS authority")
    evidence_ceiling = str(source.get("observation_ceiling") or "")
    if evidence_ceiling != observation_ceiling.isoformat():
        raise SepNegativeSpaceRefused(
            "complete SEP retirement authority is not bound to the frozen "
            "observation ceiling")
    boundary = _authority_time(
        source.get("source_observation_boundary"),
        field="source_observation_boundary")
    expected_boundary = _authority_time(
        source_observation_boundary, field="source_observation_boundary")
    if boundary != expected_boundary or boundary.date() != observation_ceiling:
        raise SepNegativeSpaceRefused(
            "complete SEP retirement authority is not bound to the frozen "
            "source observation boundary")
    refresh_time = _authority_time(
        source.get("last_refreshed_time"), field="last_refreshed_time")
    if refresh_time > boundary:
        raise SepNegativeSpaceRefused(
            "complete SEP retirement authority comes from a vendor refresh after "
            f"the frozen source observation boundary {boundary.isoformat()}")
    if start is not None and end is not None:
        if list(source.get("window") or []) != [str(start), str(end)]:
            raise SepNegativeSpaceRefused(
                "complete SEP retirement authority is bound to a different partition")
    if source_rows is not None:
        try:
            evidence_rows = int(source.get("source_rows"))
        except (TypeError, ValueError) as exc:
            raise SepNegativeSpaceRefused(
                "complete SEP retirement authority has invalid source row count") from exc
        if evidence_rows != int(source_rows):
            raise SepNegativeSpaceRefused(
                "complete SEP retirement authority row count disagrees with "
                "normalized source proof")
    if getattr(fetch, "_sentinel_sep_retirement_capability", None) is not \
            _SEP_RETIREMENT_CAPABILITY:
        raise SepNegativeSpaceRefused(
            "complete SEP retirement evidence is not backed by the canonical "
            "Exporter replay capability")

    _authority_time(actions.get("last_refreshed_time"), field="ACTIONS last_refreshed_time")
    _authority_time(actions.get("data_snapshot_time"), field="ACTIONS data_snapshot_time")
    try:
        actions_rows = int(actions.get("source_rows"))
        distinct_rows = int(actions.get("verified_distinct_rows"))
        actions_version = int(actions.get("verified_publication_version"))
        dt.date.fromisoformat(str(actions.get("verified_through")))
    except (TypeError, ValueError) as exc:
        raise SepNegativeSpaceRefused(
            "fresh complete ACTIONS retirement authority is structurally invalid") from exc
    if actions_rows < 0 or distinct_rows < 0 or actions_version < 1:
        raise SepNegativeSpaceRefused(
            "fresh complete ACTIONS retirement authority has invalid bounds")

    return _ValidatedRetirementAuthority(
        capability=_SEP_RETIREMENT_CAPABILITY,
        source_sha256=_evidence_sha256(source),
        actions_sha256=_evidence_sha256(actions),
        observation_ceiling=observation_ceiling.isoformat(),
        source_observation_boundary=boundary.isoformat(),
        interval=(str(start), str(end)),
        source_rows=int(source_rows),
        actions_publication_version=actions_version)


def _validate_retirement_authority_at_boundary(
        conn, *, plan: dict, validated_authority) -> None:
    """Revalidate durable plan evidence at the visibility-changing boundary."""
    token = validated_authority
    if not isinstance(token, _ValidatedRetirementAuthority) or \
            token.capability is not _SEP_RETIREMENT_CAPABILITY:
        raise SepNegativeSpaceRefused(
            "SEP retirement mutation boundary lacks validated dual-source authority")
    if _evidence_sha256(plan.get("source_authority")) != token.source_sha256:
        raise SepNegativeSpaceRefused(
            "SEP retirement SEP authority changed after validation")
    if _evidence_sha256(plan.get("actions_authority")) != token.actions_sha256:
        raise SepNegativeSpaceRefused(
            "SEP retirement ACTIONS authority changed after validation")
    if tuple(str(v) for v in plan.get("interval") or ()) != token.interval:
        raise SepNegativeSpaceRefused(
            "SEP retirement interval changed after dual-source validation")
    if int(plan.get("source_rows", -1)) != token.source_rows:
        raise SepNegativeSpaceRefused(
            "SEP retirement source row count changed after dual-source validation")
    keys = list(plan.get("keys") or [])
    if core._keys_digest(keys) != str(plan.get("keys_sha256") or ""):
        raise SepNegativeSpaceRefused(
            "SEP retirement durable key set changed after validation")
    current = publication.require_current(conn)
    if int(current.version) != token.actions_publication_version:
        raise SepNegativeSpaceRefused(
            "published corpus advanced after fresh ACTIONS retirement authority "
            "was established")


def _finalize_production_actions_authority(
        conn, *, source, start: str, end: str, keys: list[dict],
        source_authority_evidence, actions_authority_evidence):
    """Refresh ACTIONS at the final logical-retirement gate and revalidate proof."""
    authority = str((source_authority_evidence or {}).get("authority") or "")
    if authority != _COMPLETE_SEP_AUTHORITY:
        return actions_authority_evidence, keys

    from sentinel.feed import sep_reconciliation

    _lo, market_hi = core.recon._visible_bounds(conn)
    final_actions = sep_reconciliation._fresh_actions_retirement_authority(
        conn, through=market_hi)
    local_source = core._source_only_local_proof(conn, start=start, end=end)
    if (local_source.rows != source.rows
            or local_source.key_digest != source.key_digest):
        raise SepNegativeSpaceRefused(
            "published SEP keys changed while establishing final ACTIONS "
            "retirement authority")
    if local_source.value_digest != source.value_digest:
        raise SepNegativeSpaceRefused(
            "published SEP values changed while establishing final ACTIONS "
            "retirement authority")
    final_keys = core._local_only_keys(conn, start=start, end=end)
    if final_keys != keys:
        raise SepNegativeSpaceRefused(
            "SEP local-only retirement targets changed while establishing final "
            "ACTIONS authority")
    return final_actions, final_keys


def _retire_split_repairs(conn, *, run_id: str) -> None:
    """Compatibility seam: published split-repair evidence is append-only."""
    return None


def _retire_and_publish_authorized(
        conn, *, run, plan: dict, validated_authority=None):
    """Publish an append-only tombstone generation for the exact retirement keys."""
    if core._retire_and_publish is not _ORIGINAL_RETIRE:
        return core._retire_and_publish(conn, run=run, plan=plan)

    if plan.get("source_authority") is not None or plan.get("actions_authority") is not None:
        _validate_retirement_authority_at_boundary(
            conn, plan=plan, validated_authority=validated_authority)

    keys = list(plan["keys"])
    if core._keys_digest(keys) != str(plan.get("keys_sha256") or ""):
        raise SepNegativeSpaceRefused(
            "SEP retirement durable key set failed its append-only tombstone digest")
    core._load_retire_table(conn, keys)
    run_id = str(run.progress.run_id)
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT COUNT(*) FROM sentinel_bars b JOIN {core._TEMP_RETIRE_KEYS} r"
            " ON r.security_id=b.security_id AND r.session=b.session"
            " AND r.ticker=b.ticker WHERE " + publication.visible_predicate("b"))
        matched = int(cur.fetchone()[0])
        if matched != len(keys):
            raise SepNegativeSpaceRefused(
                "SEP retirement target changed after durable source proof; "
                f"expected {len(keys)} rows, found {matched}")
        cur.execute(
            "UPDATE feed_ingest_runs SET status='success',chunks_done=1,"
            " rows_dropped=%s,current_chunk='retire-local-only',"
            " completed_at=NOW(),updated_at=NOW() WHERE run_id=%s"
            " AND kind=%s AND status='running'",
            (len(keys), run_id, KIND))
        if int(cur.rowcount) != 1:
            raise SepNegativeSpaceRefused(
                "SEP retirement run lost RUNNING state before publication")
    return publication.publish(
        conn, run_id=run_id,
        window_start=plan["interval"][0], window_end=plan["interval"][1],
        evidence={"kind": KIND, "source_retirement": plan})


def repair_local_only(
        conn, *, fetch, start: str, end: str, observation_ceiling,
        expected_source, source_authority_evidence=None,
        actions_authority_evidence=None, source_observation_boundary=None):
    """Retire exact negative space only after source and economic proof."""
    if core.repair_local_only is not _ORIGINAL_REPAIR:
        return core.repair_local_only(
            conn, fetch=fetch, start=start, end=end,
            observation_ceiling=observation_ceiling,
            expected_source=expected_source)

    if source_authority_evidence is not None and actions_authority_evidence is None:
        raise SepNegativeSpaceRefused(
            "production SEP retirement lacks fresh complete ACTIONS authority")

    core.store._assert_corpus_locked(conn)
    ceiling = (
        observation_ceiling if isinstance(observation_ceiling, dt.date)
        else dt.date.fromisoformat(str(observation_ceiling)))
    core._create_source_table(conn)
    try:
        source = core._source_proof_and_keys(
            conn, fetch=fetch, start=start, end=end,
            observation_ceiling=ceiling)
        if (source.rows != expected_source.rows
                or source.key_digest != expected_source.key_digest
                or source.value_digest != expected_source.value_digest):
            raise SepNegativeSpaceRefused(
                "SEP source changed between mismatch detection and bounded "
                "retirement re-observation")
        local_source = core._source_only_local_proof(conn, start=start, end=end)
        if (local_source.rows != source.rows
                or local_source.key_digest != source.key_digest):
            raise SepNegativeSpaceRefused(
                "current SEP source contains keys absent from published local state; "
                "automatic negative-space retirement cannot repair insertion or "
                "identity drift")
        if local_source.value_digest != source.value_digest:
            raise SepNegativeSpaceRefused(
                "current SEP source values disagree with published local values; "
                "automatic negative-space retirement cannot repair value drift")
        keys = core._local_only_keys(conn, start=start, end=end)
        if len(keys) != int(core.recon._local_fingerprint(
                conn, start=start, end=end).rows - source.rows):
            raise SepNegativeSpaceRefused(
                "SEP local-only row count changed during retirement planning")
        actions_authority_evidence, keys = _finalize_production_actions_authority(
            conn, source=source, start=start, end=end, keys=keys,
            source_authority_evidence=source_authority_evidence,
            actions_authority_evidence=actions_authority_evidence)
        core._load_retire_table(conn, keys)
        _assert_retired_rows_have_no_economic_events(conn, keys)
        _assert_current_actions_have_no_retirement_events(conn, keys)
        _assert_retirement_preserves_split_chain(conn, keys)

        validated_authority = None
        if (core._retire_and_publish is _ORIGINAL_RETIRE
                and source_authority_evidence is not None):
            validated_authority = _require_production_retirement_authority(
                source_authority_evidence=source_authority_evidence,
                actions_authority_evidence=actions_authority_evidence,
                observation_ceiling=ceiling,
                source_observation_boundary=source_observation_boundary,
                fetch=fetch, start=start, end=end, source_rows=source.rows)

        plan = core._plan(
            start=start, end=end, source=source,
            expected_source=expected_source, keys=keys)
        if source_authority_evidence is not None:
            plan["source_authority"] = dict(source_authority_evidence)
        if actions_authority_evidence is not None:
            plan["actions_authority"] = dict(actions_authority_evidence)
        run = core.store.IngestRun(
            conn, KIND, date_from=start, date_to=end, chunks_total=1)
        run_id = str(run.progress.run_id)
        core._persist_plan(conn, run_id=run_id, plan=plan)
        try:
            published = _retire_and_publish_authorized(
                conn, run=run, plan=plan,
                validated_authority=validated_authority)
        except BaseException as exc:  # noqa: BLE001
            conn.rollback()
            if not core._publication_committed_for_run(conn, run_id):
                run.finish("failed", f"{type(exc).__name__}: {exc}")
            raise
        return {"publication": published, "plan": plan}
    finally:
        core._drop_temp(conn, core._TEMP_SOURCE_KEYS)
        core._drop_temp(conn, core._TEMP_RETIRE_KEYS)


__all__ = [
    "KIND", "MAX_RETIREMENTS", "SCHEMA", "SepNegativeSpaceRefused",
    "repair_local_only",
]
