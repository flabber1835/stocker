"""Production source wrappers that apply row and seed authority upstream."""
from __future__ import annotations

import datetime as dt
import pickle
import tempfile
from typing import Mapping, Optional

from sentinel.feed import coherence, sharadar, snapshot_source
from .dates import SeedIdentityCollision, SepUpdateEnvelope, SourceAuthorityRefused, _strict_date
from .duplicates import CanonicalSourceFetch, _is_matching_update_request
from .coverage import SeedCoverageAccumulator
from .seed_model import SeedListingProjection


def _merge_counts(left: dict, right: dict) -> dict:
    result = {str(key): int(value) for key, value in left.items()}
    for key, value in right.items():
        result[str(key)] = result.get(str(key), 0) + int(value)
    return dict(sorted(result.items()))


def _merge_seed_coverage(current: Optional[dict], chunk: dict) -> dict:
    if current is None:
        return dict(chunk)
    if (current.get("schema") != "sentinel.seed-source-coverage/1"
            or chunk.get("schema") != current.get("schema")
            or chunk.get("source_projection_digest")
            != current.get("source_projection_digest")):
        raise SourceAuthorityRefused(
            "seed coverage chunks do not share one stable TICKERS authority")
    return {
        "schema": current["schema"],
        "interval": [current["interval"][0], chunk["interval"][1]],
        "source_projection_digest": current["source_projection_digest"],
        "sessions_checked": int(current["sessions_checked"]) + int(
            chunk["sessions_checked"]),
        "expected_eligible_total": int(current["expected_eligible_total"]) + int(
            chunk["expected_eligible_total"]),
        "received_eligible_total": int(current["received_eligible_total"]) + int(
            chunk["received_eligible_total"]),
        "missing_eligible_total": 0,
        "unexpected_eligible_total": 0,
        "unresolved_eligible_risk_total": 0,
        "reviewed_exceptions_applied_total": int(
            current["reviewed_exceptions_applied_total"]) + int(
                chunk["reviewed_exceptions_applied_total"]),
        "expected_ineligible_by_category": _merge_counts(
            current["expected_ineligible_by_category"],
            chunk["expected_ineligible_by_category"]),
        "received_ineligible_by_category": _merge_counts(
            current["received_ineligible_by_category"],
            chunk["received_ineligible_by_category"]),
        "missing_ineligible_by_category": _merge_counts(
            current["missing_ineligible_by_category"],
            chunk["missing_ineligible_by_category"]),
    }


def _require_complete_recovery_reference_tail(rows, params, required_keys):
    """Require replacement of every failed SFP key before durable SUCCESS.

    The caller freezes these keys under the corpus writer lock. This applies to
    every retry window, including same-day acquisition. Ordinary tail readiness
    remains separate from replacement of failed destructive writes.
    """
    observed = {(str(row.get("ticker") or "").strip().upper(),
                 str(row.get("date") or "")) for row in rows}
    missing = sorted(set(required_keys) - observed)
    if missing:
        request = dict(params or {})
        raise SourceAuthorityRefused(
            "daily SFP recovery is incomplete: "
            f"window={request.get('date.gte')}..{request.get('date.lte')}, "
            f"missing_failed_keys={len(missing)}, examples={missing[:8]}")
    return rows


class StableSharadarFetch(coherence.StableSharadarFetch):
    """Coherence guard with canonical-key and exact seed-membership authority."""

    def __init__(self, fetch, *, protect_sep=None,
                 corroborate_reference=None,
                 after_session: str | None = None,
                 seed_mode: bool = False, validate_tickers: bool = False,
                 identity_actions=(), identity_through=None, identity_fetch=None, alias_rejections=None,
                 reference_recovery: frozenset[tuple[str, str]] = frozenset(),
                 sep_update_envelope: SepUpdateEnvelope | None = None):
        self._canonical_fetch = CanonicalSourceFetch(
            fetch, validate_tickers=(validate_tickers or fetch is snapshot_source.fetch_table),
            sep_update_envelope=sep_update_envelope)
        self._seed_projection: Optional[SeedListingProjection] = None
        self.seed_coverage_evidence: Optional[dict] = None
        self._seed_mode = bool(seed_mode)
        from sentinel.feed import source_aliases
        self.alias_rejections = source_aliases.evidence()
        self._discovering_seed = False
        self._seed_native_digest = None
        self._reference_recovery = frozenset(reference_recovery)
        super().__init__(
            self._canonical_fetch, protect_sep=protect_sep,
            corroborate_reference=corroborate_reference,
            after_session=after_session, seed_mode=seed_mode,
            identity_actions=identity_actions, identity_through=identity_through,
            identity_fetch=identity_fetch, alias_rejections=alias_rejections)

    def __call__(self, table, params=None, **kwargs):
        rows = super().__call__(table, params, **kwargs)
        if table == sharadar.TICKERS and self._seed_mode:
            material = list(rows)
            if self._tickers_first is None:
                raise SourceAuthorityRefused(
                    "TICKERS projection has no stable source fingerprint")
            self._seed_projection = SeedListingProjection(
                material, source_digest=self._tickers_first.digest)
            self._seed_native_digest = self._tickers_first.digest
            return material
        if table == sharadar.SFP and self._reference_recovery:
            material = list(rows)
            return _require_complete_recovery_reference_tail(
                material, params, self._reference_recovery)
        if (table == sharadar.ACTIONS and self._seed_mode
                and self.identity_projection is not None and self._seed_projection is not None):
            self._freeze_identity()
        return rows

    def begin_seed_capture(self):
        self._discovering_seed = self._seed_mode

    def _freeze_identity(self):
        from sentinel.feed.symbol_identity import SymbolProjection
        base = self.identity_projection
        self.identity_projection = SymbolProjection(
            base.rows, base.actions, through=base.through, alias_rejections=self.alias_rejections)
        from sentinel.feed import source_aliases
        source_aliases.require_current(self.identity_projection, self.alias_rejections)
        self._seed_resolver = self.identity_projection.resolver()
        self._seed_projection = SeedListingProjection(
            (*self.identity_projection.rows, *self.identity_projection.alias_rows),
            source_digest=self.identity_projection.digest(self._seed_native_digest))

    def _discover_aliases(self, coverage, identity):
        from sentinel.feed import source_aliases
        found = source_aliases.discover(coverage, identity)
        self.alias_rejections = source_aliases.evidence(
            (*self.alias_rejections["records"], *found["records"]))

    def finalize_seed_capture(self, captured, *, date_from, date_to):
        if not self._seed_mode:
            return
        # Every year is rechecked against ONE projection after discovery ends.
        # Endpoint samples never substitute for this complete historical pass.
        self._freeze_identity()
        self._discovering_seed = False
        self.seed_coverage_evidence = None
        for lo, hi in sharadar.year_chunks(date_from, date_to):
            params = sharadar.date_params(lo, hi)
            for _ in self._validated_seed_replay(captured(sharadar.SEP, params), params):
                pass

    def preflight_seed_identity(self, *, tickers, fetch, date_from, date_to):
        """Detect source identity conflicts before requesting the full ACTIONS export."""
        if not self._seed_mode:
            return
        from sentinel.feed import symbol_identity
        rows = list(tickers)
        actions = symbol_identity.stable_rename_rows(fetch, through=date_to)
        self._identity_actions = tuple(actions)
        self._identity_through = date_to
        self._identity_fetch = fetch
        identity = symbol_identity.SymbolProjection(rows, actions, through=date_to)
        self.preflight_seed_membership(date_from=date_from, date_to=date_to,
                                      identity_projection=identity)

    def preflight_seed_membership(self, *, date_from, date_to, identity_projection=None):
        """Small diagnostic samples; never add them to publication evidence."""
        if not self._seed_mode:
            return
        from sentinel.feed import authority, calendar, progress
        sessions = calendar.sessions_in_range(date_from, date_to)
        if not sessions:
            raise coherence.SeedHistoryIncomplete("seed interval has no market sessions")
        from .seed_model import SEED_COVERAGE_EXCEPTIONS, SeedCoverageException
        # Existing onset exceptions depend on first-observed rows from another
        # session. Leave those dates to the full proof, without inventing that
        # evidence or treating a valid historical source as a new outage.
        contextual = {item.session for item in SEED_COVERAGE_EXCEPTIONS.values()
                      if isinstance(item, SeedCoverageException)}
        sessions = [session for session in sessions if session not in contextual]
        if not sessions:
            return
        projection, resolver = self._seed_projection, self._seed_resolver
        if identity_projection is not None:
            projection = SeedListingProjection(
                (*identity_projection.rows, *identity_projection.alias_rows),
                source_digest=identity_projection.digest(coherence.observe_tickers(identity_projection.rows).digest))
            resolver = identity_projection.resolver()
        sampled = sorted({sessions[0], sessions[-1]})
        identity = identity_projection or self.identity_projection
        material = []
        coverage = SeedCoverageAccumulator(projection, resolver.resolve)
        try:
            for session in sampled:
                # Both traversals use the canonical source, including duplicate
                # and price/date guards. Full capture still brackets all inputs.
                sample = authority.StableSharadarFetch(self._canonical_fetch)
                with progress.phase("seed_membership_preflight") as count:
                    for row in sample(sharadar.SEP, sharadar.date_params(session, session)):
                        coverage.add(row)
                        material.append(row)
                        count[0] += 1
            if identity is not None:
                self._discover_aliases(coverage, identity)
                from sentinel.feed.symbol_identity import SymbolProjection
                corrected = SymbolProjection(identity.rows, identity.actions, through=identity.through,
                                             alias_rejections=self.alias_rejections)
                coverage.close()
                coverage = SeedCoverageAccumulator(SeedListingProjection(
                    (*corrected.rows, *corrected.alias_rows), source_digest=corrected.digest(
                        coherence.observe_tickers(corrected.rows).digest)), corrected.resolver().resolve)
                for row in material:
                    coverage.add(row)
            coverage.require_no_collisions(date_from=sampled[0], date_to=sampled[-1])
            for session in sampled:
                try:
                    coverage.require_complete(date_from=session, date_to=session)
                except SourceAuthorityRefused as exc:
                    raise coherence.SeedHistoryIncomplete(str(exc)) from exc
        finally:
            coverage.close()

    def _validated_seed_replay(self, rows, params):
        date_from = str(params.get("date.gte") or "")
        date_to = str(params.get("date.lte") or "")
        if not date_from or not date_to:
            raise coherence.SeedHistoryIncomplete(
                "seed SEP validation requires explicit date.gte/date.lte")
        if self._seed_resolver is None or self._seed_projection is None:
            raise coherence.SeedHistoryIncomplete(
                "seed SEP coverage validation has no stable TICKERS authority")
        identity = self.identity_projection
        projection, resolver = self._seed_projection, self._seed_resolver
        if self._discovering_seed:
            from sentinel.feed.symbol_identity import SymbolProjection
            identity = SymbolProjection(identity.rows, identity.actions, through=identity.through)
            projection = SeedListingProjection((*identity.rows, *identity.alias_rows),
                                               source_digest=self._seed_native_digest)
            resolver = identity.resolver()
        coverage = SeedCoverageAccumulator(projection, resolver.resolve)
        spool = tempfile.TemporaryFile(mode="w+b")
        sessions: dict[str, coherence.SeedSessionCounts] = {}
        try:
            for raw in rows:
                row = dict(raw)
                resolved = coverage.add(row)
                session = str(row.get("date") or "")
                if session:
                    sessions[session] = sessions.get(
                        session, coherence.SeedSessionCounts()).add(
                            row, resolved=resolved)
                pickle.dump(row, spool, protocol=pickle.HIGHEST_PROTOCOL)
            if self._discovering_seed:
                self._discover_aliases(coverage, identity)
            else:
                self._finish_seed_chunk(coverage, sessions, date_from, date_to)
            spool.seek(0)
        except Exception:
            spool.close()
            raise
        finally:
            coverage.close()

        def replay():
            try:
                while True:
                    try:
                        yield pickle.load(spool)
                    except EOFError:
                        return
            finally:
                spool.close()
        return replay()

    def _finish_seed_chunk(self, coverage, sessions, date_from, date_to):
        try:
            evidence = coverage.require_complete(date_from=date_from, date_to=date_to)
        except SeedIdentityCollision:
            raise
        except SourceAuthorityRefused as exc:
            raise coherence.SeedHistoryIncomplete(str(exc)) from exc
        coherence.assert_seed_history(sessions, date_from=date_from, date_to=date_to)
        self.seed_coverage_evidence = _merge_seed_coverage(self.seed_coverage_evidence, evidence)


class _CdcThenReplayFetch:
    """Keep CDC update authority distinct from its bounded price-date replay.

    The maintenance engine first observes the exact lastupdated interval twice
    for source stability, then re-reads affected price-date windows through the
    canonical normalizer. The update-envelope membrane must fail closed for any
    drift in those CDC requests without incorrectly applying that envelope to
    the later, deliberately different date-window reads.
    """

    def __init__(self, fetch, envelope: SepUpdateEnvelope):
        self._envelope = envelope
        self._cdc = CanonicalSourceFetch(
            fetch, sep_update_envelope=envelope)
        self._replay = CanonicalSourceFetch(fetch)
        self._cdc_observations = 0

    @staticmethod
    def _is_exact_date_replay_request(params: Mapping) -> bool:
        return (
            set(params) == {"date.gte", "date.lte"}
            and bool(str(params.get("date.gte") or ""))
            and bool(str(params.get("date.lte") or ""))
        )

    def __call__(self, table, params=None, **kwargs):
        if table != sharadar.SEP:
            return self._replay(table, params, **kwargs)
        request = params or {}
        if _is_matching_update_request(request, self._envelope):
            self._cdc_observations += 1
            return self._cdc(table, params, **kwargs)
        if (self._cdc_observations >= 2
                and self._is_exact_date_replay_request(request)):
            return self._replay(table, params, **kwargs)
        return self._cdc(table, params, **kwargs)


def reconcile_sep_mutations(conn, *, fetch=sharadar.fetch_table,
                            through: str, reobserve_equal: bool = False):
    """Run SEP CDC behind the exact frozen through-date boundary.

    Equal cursors remain a terminal fast path unless the production caller
    explicitly requests same-date re-observation. A cursor beyond ``through`` is
    never admissible: it represents vendor authority observed outside the source
    boundary this reconciliation pass froze.
    """
    from sentinel.feed import maintenance

    cursor = maintenance.load_sep_cursor(conn)
    if cursor is None:
        if reobserve_equal:
            return maintenance._reconcile_sep_mutations_core(
                conn, fetch=fetch, through=through, reobserve_equal=True)
        return maintenance._reconcile_sep_mutations_core(
            conn, fetch=fetch, through=through)
    maintenance._require_cursor_scope(cursor)
    hi = _strict_date(through, field="SEP reconciliation through")
    if cursor.processed_through > hi:
        raise maintenance.SharadarMutationRefused(
            f"SEP mutation cursor {cursor.processed_through} is ahead of "
            f"requested reconciliation through {hi}; refusing to treat future "
            "durable authority as already current")
    if cursor.processed_through == hi and not reobserve_equal:
        return cursor
    lo = cursor.processed_through - dt.timedelta(days=1)
    envelope = SepUpdateEnvelope.interval(lo, hi, context="SEP CDC request")
    guarded = _CdcThenReplayFetch(fetch, envelope)
    if reobserve_equal:
        return maintenance._reconcile_sep_mutations_core(
            conn, fetch=guarded, through=through, reobserve_equal=True)
    return maintenance._reconcile_sep_mutations_core(
        conn, fetch=guarded, through=through)


__all__ = ["StableSharadarFetch", "reconcile_sep_mutations"]
