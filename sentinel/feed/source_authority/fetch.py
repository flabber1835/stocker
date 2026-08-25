"""Production source wrappers that apply row and seed authority upstream."""
from __future__ import annotations

import datetime as dt
import pickle
import tempfile
from typing import Optional

from sentinel.feed import coherence, sharadar, snapshot_source
from .dates import SepUpdateEnvelope, SourceAuthorityRefused, _strict_date
from .duplicates import CanonicalSourceFetch
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


class StableSharadarFetch(coherence.StableSharadarFetch):
    """Coherence guard with canonical-key and exact seed-membership authority."""

    def __init__(self, fetch, *, protect_sep=None,
                 corroborate_reference=None,
                 after_session: str | None = None,
                 seed_mode: bool = False):
        # Only the production snapshot membrane is entitled to claim complete
        # TICKERS structural authority. Injected deterministic fetch seams remain
        # usable for narrow financial/adversarial tests without pretending to be
        # a complete Sharadar TICKERS export.
        self._canonical_fetch = CanonicalSourceFetch(
            fetch, validate_tickers=(fetch is snapshot_source.fetch_table))
        self._seed_projection: Optional[SeedListingProjection] = None
        self.seed_coverage_evidence: Optional[dict] = None
        super().__init__(
            self._canonical_fetch, protect_sep=protect_sep,
            corroborate_reference=corroborate_reference,
            after_session=after_session, seed_mode=seed_mode)

    def __call__(self, table, params=None, **kwargs):
        rows = super().__call__(table, params, **kwargs)
        if table == sharadar.TICKERS and self._seed_mode:
            material = list(rows)
            if self._tickers_first is None:
                raise SourceAuthorityRefused(
                    "TICKERS projection has no stable source fingerprint")
            self._seed_projection = SeedListingProjection(
                material, source_digest=self._tickers_first.digest)
            return material
        return rows

    def _validated_seed_replay(self, rows, params):
        date_from = str(params.get("date.gte") or "")
        date_to = str(params.get("date.lte") or "")
        if not date_from or not date_to:
            raise coherence.SeedHistoryIncomplete(
                "seed SEP validation requires explicit date.gte/date.lte")
        if self._seed_resolver is None or self._seed_projection is None:
            raise coherence.SeedHistoryIncomplete(
                "seed SEP coverage validation has no stable TICKERS authority")
        coverage = SeedCoverageAccumulator(
            self._seed_projection, self._seed_resolver.resolve)
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
            try:
                evidence = coverage.require_complete(
                    date_from=date_from, date_to=date_to)
            except SourceAuthorityRefused as exc:
                raise coherence.SeedHistoryIncomplete(str(exc)) from exc
            coherence.assert_seed_history(
                sessions, date_from=date_from, date_to=date_to)
            self.seed_coverage_evidence = _merge_seed_coverage(
                self.seed_coverage_evidence, evidence)
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


def reconcile_sep_mutations(conn, *, fetch=sharadar.fetch_table,
                            through: str):
    """Run the existing CDC engine behind exact pre-fingerprint guards."""
    from sentinel.feed import maintenance

    cursor = maintenance.load_sep_cursor(conn)
    if cursor is None:
        return maintenance._reconcile_sep_mutations_core(
            conn, fetch=fetch, through=through)
    hi = _strict_date(through, field="SEP reconciliation through")
    if hi <= cursor.processed_through:
        return cursor
    lo = cursor.processed_through - dt.timedelta(days=1)
    guarded = CanonicalSourceFetch(
        fetch, sep_update_envelope=SepUpdateEnvelope.interval(
            lo, hi, context="SEP CDC request"))
    return maintenance._reconcile_sep_mutations_core(
        conn, fetch=guarded, through=through)


__all__ = ["StableSharadarFetch", "reconcile_sep_mutations"]
