"""Read-only validation for Sentinel's installed feed schema.

Feed migration is an explicit deployment operation owned by
:func:`sentinel.feed.store.migrate_schema`. Runtime callers use this module only
to prove that the relations they are about to trust still have the reviewed
shape. The runtime proof is catalog-only: it never creates, alters, drops,
updates, or repairs anything. The migration function is separate and reachable
only through the explicit store migration API.
"""
from __future__ import annotations

from sentinel import schema as behavioral_schema
from sentinel.feed.domains import SEP_FORBIDDEN_COLUMNS
from sentinel.feed.schema import DDL as _BASE_DDL
from sentinel.feed.universe_projection import DDL as _UNIVERSE_PROJECTION_DDL

# The projection is a migration-owned derived read model rather than raw corpus
# evidence. Keep its installation beside the runtime schema contract so an old
# appliance refuses before a reader can query a relation that has not yet been
# explicitly migrated.
DDL = [*_BASE_DDL, *_UNIVERSE_PROJECTION_DDL]


_SCHEMA_LOCK = (1_397_050_964, 1_179_796_516)  # SENT / FEED.
_SCHEMA_LOCK_TIMEOUT_MS = 2_000
_TOTAL_RETURN_COLUMN = SEP_FORBIDDEN_COLUMNS[0]


class FeedSchemaRefused(behavioral_schema.SchemaMigrationRefused):
    """The installed feed schema is missing, damaged, incompatible, or moving."""


def _refuse(detail: str) -> FeedSchemaRefused:
    return FeedSchemaRefused(
        "feed-schema operator action required: " + detail
        + ". Routine runtime validation performed no DDL; run the explicit "
          "deployment/schema migration while automation is quiesced"
    )


_RELATIONS = {
    "sentinel_bars": ("r", "p", False, False, False),
    "sentinel_spy_total_return": ("r", "p", False, False, False),
    "sentinel_defensive_bars": ("r", "p", False, False, False),
    "sentinel_ingest_rejections": ("r", "p", False, False, False),
    "sentinel_rejection_truncation": ("r", "p", False, False, False),
    "sentinel_corpus_anomalies": ("r", "p", False, False, False),
    "sentinel_actions": ("r", "p", False, False, False),
    "sentinel_universe": ("r", "p", False, False, False),
    "feed_universe_current": ("r", "p", False, False, False),
    "sentinel_corpus_publications": ("r", "p", False, False, False),
    "sentinel_publication_validation_policy": ("r", "p", False, False, False),
    "sentinel_publication_validation_receipts": ("r", "p", False, False, False),
    "sentinel_bar_split_repairs": ("r", "p", False, False, False),
    "feed_ingest_runs": ("r", "p", False, False, False),
    "sentinel_action_generations": ("r", "p", False, False, False),
    "sentinel_action_observations": ("r", "p", False, False, False),
    "sentinel_action_generation_events": ("r", "p", False, False, False),
    "sentinel_anomaly_observation_events": ("r", "p", False, False, False),
    "sentinel_readiness_snapshots": ("r", "p", False, False, False),
    "sentinel_corpus_quarantine": ("r", "p", False, False, False),
    "sentinel_sep_staging": ("r", "u", False, False, False),
    "sentinel_active_ingest_rejections": ("v", "p", False, False, False),
    "sentinel_active_actions": ("v", "p", False, False, False),
}


_COLUMNS = {
    "sentinel_bars": {
        "security_id": ("text", True), "session": ("date", True),
        "ticker": ("text", True), "close_signal": ("double precision", False),
        "close_unadjusted": ("double precision", True),
        "open_unadjusted": ("double precision", False),
        "volume": ("double precision", False),
        "split_ratio": ("double precision", True),
        "dividend_per_share": ("double precision", True),
        "last_written_run_id": ("uuid", False),
    },
    "sentinel_spy_total_return": {
        "session": ("date", True), _TOTAL_RETURN_COLUMN: ("double precision", True),
        "last_written_run_id": ("uuid", False),
    },
    "sentinel_defensive_bars": {
        "security_id": ("text", True), "session": ("date", True),
        "ticker": ("text", True),
        "open_signal": ("double precision", False),
        "close_signal": ("double precision", True),
        "close_adjusted": ("double precision", False),
        "close_unadjusted": ("double precision", True),
        "last_written_run_id": ("uuid", False),
    },
    "sentinel_ingest_rejections": {
        "observation_id": ("bigint", True), "ticker": ("text", True),
        "session": ("date", True), "reason": ("text", True),
        "close_unadjusted": ("double precision", False),
        "volume": ("double precision", False),
        "first_seen": ("timestamp with time zone", True),
        "last_written_run_id": ("uuid", False),
    },
    "sentinel_rejection_truncation": {
        "run_id": ("uuid", True), "chunk": ("text", True),
        "window_start": ("date", True), "window_end": ("date", True),
        "retained": ("bigint", True), "truncated": ("bigint", True),
        "recorded_at": ("timestamp with time zone", True),
    },
    "sentinel_corpus_anomalies": {
        "observation_id": ("bigint", True), "kind": ("text", True),
        "ticker": ("text", True), "session": ("date", True),
        "detail": ("text", False),
        "first_seen": ("timestamp with time zone", True),
        "last_written_run_id": ("uuid", False),
    },
    "sentinel_actions": {
        "ticker": ("text", True), "session": ("date", True),
        "action": ("text", True), "value": ("double precision", False),
        "contraticker": ("text", False), "last_written_run_id": ("uuid", False),
    },
    "sentinel_universe": {
        "permaticker": ("text", True), "ticker": ("text", True),
        "category": ("text", False), "sector": ("text", False),
        "related_tickers": ("text", False), "first_price_date": ("date", False),
        "last_price_date": ("date", False), "is_delisted": ("boolean", False),
        "snapshot_date": ("date", True), "last_written_run_id": ("uuid", False),
    },
    "feed_universe_current": {
        "permaticker": ("text", True), "ticker": ("text", True),
        "category": ("text", False), "category_snapshot_date": ("date", False),
        "sector": ("text", False), "sector_snapshot_date": ("date", False),
        "related_tickers": ("text", False),
        "related_tickers_snapshot_date": ("date", False),
        "first_price_date": ("date", False), "last_price_date": ("date", False),
        "is_delisted": ("boolean", False),
        "is_delisted_snapshot_date": ("date", False),
        "snapshot_date": ("date", True),
    },
    "sentinel_corpus_publications": {
        "version": ("bigint", True), "previous_version": ("bigint", False),
        "run_id": ("uuid", False),
        "published_at": ("timestamp with time zone", True),
        "window_start": ("date", False), "window_end": ("date", False),
        "evidence": ("jsonb", True),
    },
    "sentinel_publication_validation_policy": {
        "id": ("boolean", True),
        "required_after_version": ("bigint", True),
    },
    "sentinel_publication_validation_receipts": {
        "publication_version": ("bigint", True),
        "previous_version": ("bigint", False),
        "run_id": ("uuid", False),
        "published_at": ("timestamp with time zone", True),
        "window_start": ("date", False), "window_end": ("date", False),
        "evidence": ("jsonb", True),
        "origin_run_status": ("text", False),
        "previous_receipt_sha256": ("text", False),
        "receipt_sha256": ("text", True),
        "receipt_hmac_sha256": ("text", True),
    },
    "sentinel_bar_split_repairs": {
        "security_id": ("text", True), "session": ("date", True),
        "split_ratio": ("double precision", True),
        "prior_split_ratio": ("double precision", True),
        "last_written_run_id": ("uuid", True),
        "repaired_at": ("timestamp with time zone", True),
    },
    "feed_ingest_runs": {
        "run_id": ("uuid", True), "kind": ("text", True),
        "status": ("text", True),
        "started_at": ("timestamp with time zone", True),
        "updated_at": ("timestamp with time zone", True),
        "completed_at": ("timestamp with time zone", False),
        "date_from": ("date", False), "date_to": ("date", False),
        "chunks_total": ("integer", True), "chunks_done": ("integer", True),
        "rows_written": ("bigint", True), "rows_dropped": ("bigint", True),
        "current_chunk": ("text", False), "error_message": ("text", False),
        "source_git_commit": ("text", False),
        "runtime_image_digest": ("text", False),
        "publication_recovery": ("jsonb", True),
    },
    "sentinel_action_generations": {
        "last_written_run_id": ("uuid", True), "window_start": ("date", True),
        "window_end": ("date", True), "source_rows": ("bigint", True),
        "observed_at": ("timestamp with time zone", True),
    },
    "sentinel_action_observations": {
        "source_row_id": ("text", True), "source_payload": ("jsonb", True),
        "ticker": ("text", True), "session": ("date", True),
        "action": ("text", True), "name": ("text", False),
        "value": ("double precision", False), "contraticker": ("text", False),
        "contraname": ("text", False), "disposition": ("text", True),
        "last_written_run_id": ("uuid", True),
        "observed_at": ("timestamp with time zone", True),
    },
    "sentinel_action_generation_events": {
        "event_id": ("bigint", True), "generation_run_id": ("uuid", True),
        "state": ("text", True), "actor_run_id": ("uuid", False),
        "reason": ("text", True),
        "occurred_at": ("timestamp with time zone", True),
    },
    "sentinel_anomaly_observation_events": {
        "event_id": ("bigint", True), "observation_id": ("bigint", True),
        "state": ("text", True), "actor_run_id": ("uuid", False),
        "reason": ("text", True),
        "occurred_at": ("timestamp with time zone", True),
    },
    "sentinel_readiness_snapshots": {
        "snapshot_id": ("bigint", True),
        "computed_at": ("timestamp with time zone", True),
        "ready": ("boolean", True), "checks_passed": ("integer", True),
        "checks_total": ("integer", True), "checks": ("jsonb", True),
    },
    "sentinel_corpus_quarantine": {
        "assessment_id": ("bigint", True),
        "assessment_sha256": ("text", True),
        "assessed_at": ("timestamp with time zone", True),
        "run_id": ("uuid", True),
        "publication_version": ("bigint", False),
        "boundary_start": ("date", True), "boundary_end": ("date", True),
        "affected_start": ("date", True), "affected_end": ("date", True),
        "production_blocking": ("boolean", True),
        "affected_securities": ("jsonb", True),
        "evidence_kinds": ("jsonb", True), "reasons": ("jsonb", True),
        "row_counts": ("jsonb", True),
    },
    "sentinel_sep_staging": {
        "run_id": ("uuid", True), "chunk": ("text", True),
        "session": ("date", True), "ticker": ("text", True),
        "open": ("double precision", False), "close": ("double precision", False),
        "closeunadj": ("double precision", False),
        _TOTAL_RETURN_COLUMN: ("double precision", False), "volume": ("double precision", False),
    },
    "sentinel_active_ingest_rejections": {
        "observation_id": ("bigint", False), "ticker": ("text", False),
        "session": ("date", False), "reason": ("text", False),
        "close_unadjusted": ("double precision", False),
        "volume": ("double precision", False),
        "first_seen": ("timestamp with time zone", False),
        "last_written_run_id": ("uuid", False),
        "publication_version": ("bigint", False),
    },
    "sentinel_active_actions": {
        "source_row_id": ("text", False), "source_payload": ("jsonb", False),
        "ticker": ("text", False), "session": ("date", False),
        "action": ("text", False), "name": ("text", False),
        "value": ("double precision", False), "contraticker": ("text", False),
        "contraname": ("text", False), "last_written_run_id": ("uuid", False),
        "publication_version": ("bigint", False),
    },
}


_PRIMARY_KEYS = {
    "sentinel_bars": "primary key (security_id, session)",
    "sentinel_spy_total_return": "primary key (session)",
    "sentinel_defensive_bars": "primary key (session)",
    "sentinel_ingest_rejections": "primary key (observation_id)",
    "sentinel_rejection_truncation": "primary key (run_id, chunk)",
    "sentinel_corpus_anomalies": "primary key (observation_id)",
    "sentinel_actions": "primary key (ticker, session, action)",
    "sentinel_universe": "primary key (permaticker, ticker, snapshot_date)",
    "feed_universe_current": "primary key (permaticker, ticker)",
    "sentinel_corpus_publications": "primary key (version)",
    "sentinel_publication_validation_policy": "primary key (id)",
    "sentinel_publication_validation_receipts": "primary key (publication_version)",
    "sentinel_bar_split_repairs": "primary key (security_id, session, last_written_run_id)",
    "feed_ingest_runs": "primary key (run_id)",
    "sentinel_action_generations": "primary key (last_written_run_id)",
    "sentinel_action_observations": "primary key (last_written_run_id, source_row_id)",
    "sentinel_action_generation_events": "primary key (event_id)",
    "sentinel_anomaly_observation_events": "primary key (event_id)",
    "sentinel_readiness_snapshots": "primary key (snapshot_id)",
    "sentinel_corpus_quarantine": "primary key (assessment_id)",
}

_CONSTRAINT_WITNESSES = {
    "sentinel_corpus_publications": (
        ("c", ("jsonb_typeof(evidence)", "object")),
    ),
    "sentinel_publication_validation_policy": (
        ("c", ("id",)),
        ("c", ("required_after_version", ">=", "0")),
    ),
    "sentinel_publication_validation_receipts": (
        ("f", ("foreign key (publication_version)",
               "sentinel_corpus_publications", "version",
               "deferrable initially deferred")),
        ("c", ("jsonb_typeof(evidence)", "object")),
        ("c", ("receipt_sha256", "[0-9a-f]{64}")),
        ("c", ("receipt_hmac_sha256", "[0-9a-f]{64}")),
    ),
    "sentinel_defensive_bars": (
        ("c", ("security_id", "sentinel:bil")),
        ("c", ("ticker", "bil")),
        ("c", ("open_signal", ">", "0", "nan", "infinity")),
        ("c", ("close_signal", ">", "0", "nan", "infinity")),
        ("c", ("close_adjusted", ">", "0", "nan", "infinity")),
        ("c", ("close_unadjusted", ">", "0", "nan", "infinity")),
    ),
    "sentinel_bar_split_repairs": (
        ("f", ("foreign key (security_id, session)", "sentinel_bars",
               "security_id, session", "on delete cascade")),
        ("c", ("(split_ratio >", "0")),
        ("c", ("(prior_split_ratio >", "0")),
    ),
    "feed_ingest_runs": (("c", ("status", "running", "success", "failed")),),
    "sentinel_action_generations": (
        ("c", ("source_rows", ">=", "0")),
        ("c", ("window_start", "<=", "window_end")),
    ),
    "sentinel_action_observations": (("c", ("disposition", "present", "removed")),),
    "sentinel_action_generation_events": (
        ("f", ("foreign key (generation_run_id)", "sentinel_action_generations",
               "last_written_run_id", "on delete restrict")),
        ("u", ("unique (generation_run_id, state)",)),
        ("c", ("state", "pending", "published", "aborted", "superseded")),
    ),
    "sentinel_anomaly_observation_events": (
        ("f", ("foreign key (observation_id)", "sentinel_corpus_anomalies",
               "observation_id", "on delete restrict")),
        ("u", ("unique (observation_id, state)",)),
        ("c", ("state", "pending", "published", "aborted", "superseded")),
    ),
}


_INDEXES = {
    "idx_sentinel_bars_session": False,
    "idx_sentinel_bars_predecessor": False,
    "idx_sentinel_spy_total_return_written_by": False,
    "idx_sentinel_defensive_bars_written_by": False,
    "idx_sentinel_rejections_session": False,
    "idx_sentinel_rejections_written_by": False,
    "uq_sentinel_rejection_run_observation": True,
    "uq_sentinel_rejection_legacy_observation": True,
    "idx_sentinel_rejections_active_projection_key": False,
    "idx_sentinel_trunc_window": False,
    "idx_sentinel_anomalies_session": False,
    "idx_sentinel_anomalies_written_by": False,
    "uq_sentinel_anomaly_run_observation": True,
    "uq_sentinel_anomaly_legacy_observation": True,
    "uq_sentinel_anomaly_split_event_run": True,
    "idx_sentinel_publications_prev": False,
    "idx_sentinel_publications_run": False,
    "idx_sentinel_bars_written_by": False,
    "idx_sentinel_bars_active_rejection_lookup": False,
    "idx_sentinel_actions_written_by": False,
    "idx_sentinel_universe_written_by": False,
    "idx_sentinel_split_repairs_written_by": False,
    "idx_sentinel_split_repairs_bar": False,
    "idx_feed_ingest_runs_started": False,
    "idx_sentinel_action_obs_written_by": False,
    "idx_sentinel_action_obs_window": False,
    "idx_sentinel_action_generation_events_latest": False,
    "uq_sentinel_action_generation_terminal": True,
    "idx_sentinel_anomaly_events_latest": False,
    "uq_sentinel_anomaly_terminal_event": True,
    "idx_sentinel_readiness_computed": False,
    "sentinel_corpus_quarantine_assessment_sha256_key": True,
    "idx_sentinel_quarantine_run_assessed": False,
    "idx_sentinel_quarantine_blocking": False,
}

_INDEX_WITNESSES = {
    "idx_sentinel_bars_predecessor": (
        "on public.sentinel_bars", "(security_id, session desc)",
        "include (close_signal, close_unadjusted)"),
    "uq_sentinel_rejection_run_observation": (
        "(ticker, session, reason, last_written_run_id)", "where",
        "last_written_run_id is not null"),
    "uq_sentinel_rejection_legacy_observation": (
        "(ticker, session, reason)", "where", "last_written_run_id is null"),
    "idx_sentinel_rejections_active_projection_key": (
        "upper(ticker)", "session", "reason", "observation_id desc"),
    "uq_sentinel_anomaly_run_observation": (
        "(kind, ticker, session, last_written_run_id)", "where",
        "last_written_run_id is not null"),
    "uq_sentinel_anomaly_legacy_observation": (
        "(kind, ticker, session)", "where", "last_written_run_id is null"),
    "uq_sentinel_anomaly_split_event_run": (
        "on public.sentinel_corpus_anomalies",
        "(ticker, session, last_written_run_id)", "where",
        "last_written_run_id is not null", "split_authoritative_applied",
        "split_corroborated_derived", "split_only_derived",
        "seam_split_uncorroborated", "split_disagreement",
        "ambiguous_split_multiplicity", "split_resolved_no_event"),
    "idx_sentinel_bars_written_by": (
        "(last_written_run_id)", "where", "last_written_run_id is not null"),
    "idx_sentinel_bars_active_rejection_lookup": (
        "on public.sentinel_bars", "upper(ticker)", "session",
        "last_written_run_id", "where", "last_written_run_id is not null"),
    "idx_sentinel_action_obs_written_by": ("(last_written_run_id)",),
    "idx_sentinel_action_obs_window": (
        "on public.sentinel_action_observations",
        "(session, ticker, action, source_row_id)"),
    "uq_sentinel_action_generation_terminal": (
        "(generation_run_id)", "where", "state", "published", "aborted",
        "superseded"),
    "uq_sentinel_anomaly_terminal_event": (
        "(observation_id)", "where", "state", "published", "aborted",
        "superseded"),
}
_INDEX_FORBIDDEN = {
    "idx_sentinel_action_obs_window": (" where ",),
    "idx_sentinel_action_obs_written_by": (" where ",),
}

_VIEW_WITNESSES = {
    "sentinel_active_ingest_rejections": (
        "sentinel_ingest_rejections", "sentinel_corpus_publications",
        "sentinel_bars", "row_number() over", "upper(", "first_seen",
        "publication_version", "active_rank"),
    "sentinel_active_actions": (
        "sentinel_actions", "sentinel_action_observations",
        "sentinel_corpus_publications", "rank() over", "source_row_id",
        "publication_version", "disposition", "present"),
}

_TRIGGER_WITNESSES = {
    **{
        table: {
            "sentinel_guard_strategy_row_mutation": (
                "before delete or update", "for each row",
                "execute function sentinel_guard_strategy_row_mutation()"),
        }
        for table in (
            "sentinel_bars", "sentinel_spy_total_return",
            "sentinel_defensive_bars",
            "sentinel_universe", "sentinel_actions",
            "sentinel_bar_split_repairs", "sentinel_action_generations",
            "sentinel_action_observations", "sentinel_corpus_anomalies",
            "sentinel_ingest_rejections",
        )
    },
    **{
        table: {
            "sentinel_refuse_append_only_mutation": (
                "before delete or update", "for each row",
                "execute function sentinel_refuse_append_only_mutation()"),
        }
        for table in (
            "sentinel_publication_validation_receipts",
            "sentinel_publication_validation_policy",
            "sentinel_action_generation_events",
            "sentinel_anomaly_observation_events",
            "sentinel_corpus_quarantine",
        )
    },
    "sentinel_corpus_publications": {
        "sentinel_refuse_append_only_mutation": (
            "before delete or update", "for each row",
            "execute function sentinel_refuse_append_only_mutation()"),
        "sentinel_require_publication_receipt": (
            "create constraint trigger", "after insert", "for each row",
            "deferrable initially deferred",
            "execute function sentinel_require_publication_receipt()"),
    },
}


def _fold(value: object) -> str:
    return behavioral_schema._normal_sql(value).casefold()


def _validate_constraints(constraints) -> None:
    for table, expected in _PRIMARY_KEYS.items():
        valid = [item for item in constraints.get(table, ())
                 if item[1] == "p" and item[3]]
        if len(valid) != 1 or _fold(valid[0][2]) != expected:
            raise _refuse(
                f"relation {table!r} primary-key semantics differ from the "
                "reviewed feed schema")
    for table, witnesses in _CONSTRAINT_WITNESSES.items():
        for kind, tokens in witnesses:
            candidates = [_fold(item[2]) for item in constraints.get(table, ())
                          if item[1] == kind and item[3]]
            folded = tuple(token.casefold() for token in tokens)
            if not any(all(token in definition for token in folded)
                       for definition in candidates):
                raise _refuse(
                    f"relation {table!r} is missing a reviewed {kind!r} "
                    "constraint witness")


def _validate_catalog(catalog) -> None:
    relations, columns, constraints, indexes, triggers = catalog
    for name, expected in _RELATIONS.items():
        observed = relations.get(name)
        if observed != expected:
            raise _refuse(
                f"relation {name!r} has shape {observed!r}, expected {expected!r}")
        actual_triggers = triggers.get(name, {})
        expected_triggers = _TRIGGER_WITNESSES.get(name, {})
        if set(actual_triggers) != set(expected_triggers):
            raise _refuse(
                f"relation {name!r} has application triggers "
                f"{sorted(actual_triggers)!r}, expected "
                f"{sorted(expected_triggers)!r}")
        for trigger_name, witnesses in expected_triggers.items():
            definition, enabled = actual_triggers[trigger_name]
            folded = _fold(definition)
            if enabled != "O" or any(
                    witness not in folded for witness in witnesses):
                raise _refuse(
                    f"application trigger {trigger_name!r} on {name!r} "
                    "has changed semantics or is not enabled")
    for table, expected_columns in _COLUMNS.items():
        actual_columns = columns.get(table, {})
        if set(actual_columns) != set(expected_columns):
            raise _refuse(
                f"relation {table!r} has columns {sorted(actual_columns)!r}, "
                f"expected {sorted(expected_columns)!r}")
        for name, expected in expected_columns.items():
            type_name, not_null, _default = actual_columns[name]
            observed = (type_name, not_null)
            if observed != expected:
                raise _refuse(
                    f"column {table}.{name} has {observed!r}, expected {expected!r}")
    _validate_constraints(constraints)
    by_name = {}
    for table, table_indexes in indexes.items():
        for name, value in table_indexes.items():
            by_name[name] = (table, value)
    for name, unique in _INDEXES.items():
        item = by_name.get(name)
        if item is None:
            raise _refuse(f"critical index {name!r} is missing")
        table, (_definition, is_unique, valid, ready, live) = item
        if is_unique != unique or not (valid and ready and live):
            raise _refuse(
                f"critical index {name!r} on {table!r} is not usable with "
                "the reviewed uniqueness contract")
    for name, witnesses in _INDEX_WITNESSES.items():
        definition = _fold(by_name[name][1][0])
        if any(token.casefold() not in definition for token in witnesses):
            raise _refuse(f"critical index {name!r} has changed semantics")
        if any(token.casefold() in definition
               for token in _INDEX_FORBIDDEN.get(name, ())):
            raise _refuse(f"critical index {name!r} has unexpected predicate semantics")


def _validate_views(cur) -> None:
    for view, witnesses in _VIEW_WITNESSES.items():
        cur.execute("SELECT pg_catalog.pg_get_viewdef(%s::regclass,true)",
                    (f"public.{view}",))
        row = cur.fetchone()
        if not row or row[0] is None:
            raise _refuse(f"view {view!r} has no definition")
        definition = _fold(row[0])
        if any(token.casefold() not in definition for token in witnesses):
            raise _refuse(f"view {view!r} has changed semantics")


def require_feed_schema(conn) -> None:
    """Validate installed feed structure with catalog SELECTs only."""
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_xact_lock_shared(%s,%s)",
                        _SCHEMA_LOCK)
            row = cur.fetchone()
            if not row or not bool(row[0]):
                raise _refuse(
                    "the explicit feed migration lock is held; runtime will "
                    "not race a changing catalog")
            catalog = behavioral_schema._read_catalog(cur)
            _validate_catalog(catalog)
            _validate_views(cur)
        conn.rollback()
    except BaseException:
        conn.rollback()
        raise


def migrate_feed_schema(conn) -> None:
    """Explicit atomic feed installation/upgrade; never called by runtime."""
    try:
        with conn.cursor() as cur:
            cur.execute(f"SET LOCAL lock_timeout TO '{_SCHEMA_LOCK_TIMEOUT_MS}ms'")
            cur.execute("SELECT pg_try_advisory_xact_lock(%s,%s)", _SCHEMA_LOCK)
            row = cur.fetchone()
            if not row or not bool(row[0]):
                raise _refuse(
                    "another feed migration or runtime catalog proof holds the "
                    "feed schema lock")
            for statement in DDL:
                cur.execute(statement)
            catalog = behavioral_schema._read_catalog(cur)
            _validate_catalog(catalog)
            _validate_views(cur)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


__all__ = ["FeedSchemaRefused", "migrate_feed_schema", "require_feed_schema"]
