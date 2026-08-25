from __future__ import annotations

from pathlib import Path
import textwrap


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text()
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one replacement, found {count}: {old[:100]!r}")
    target.write_text(text.replace(old, new, 1))


def append_once(path: str, marker: str, material: str) -> None:
    target = Path(path)
    text = target.read_text()
    if marker in text:
        raise RuntimeError(f"{path}: append marker already exists: {marker}")
    target.write_text(text.rstrip() + "\n\n" + material.lstrip())


# ---------------------------------------------------------------------------
# Source envelope wiring.
# ---------------------------------------------------------------------------
replace_once(
    "sentinel/feed/authority.py",
    "from sentinel.feed import action_source\n",
    "from sentinel.feed import action_source, source_validation\n",
)
replace_once(
    "sentinel/feed/authority.py",
    "def observe_sep(rows: Iterable[Mapping]) -> SourceObservation:\n"
    "    fingerprint = _CommutativeFingerprint()\n"
    "    sessions: dict[str, DomainCounts] = {}\n"
    "    for row in rows:\n",
    "def observe_sep(rows: Iterable[Mapping], *, params: Mapping | None = None,\n"
    "                observation_through: str | _dt.date | None = None\n"
    "                ) -> SourceObservation:\n"
    "    fingerprint = _CommutativeFingerprint()\n"
    "    sessions: dict[str, DomainCounts] = {}\n"
    "    for row in source_validation.validated_market_rows(\n"
    "            \"SEP\", rows, params, observation_through=observation_through):\n",
)
replace_once(
    "sentinel/feed/authority.py",
    "    def __init__(self, fetch, *, protect_sep=None, corroborate_actions=None,\n"
    "                 after_session: str | None = None):\n",
    "    def __init__(self, fetch, *, protect_sep=None, corroborate_actions=None,\n"
    "                 after_session: str | None = None,\n"
    "                 observation_through: str | _dt.date | None = None):\n",
)
replace_once(
    "sentinel/feed/authority.py",
    "        self._after_session = after_session\n"
    "        self._actions_first: SourceObservation | None = None\n",
    "        self._after_session = after_session\n"
    "        self._observation_through = observation_through\n"
    "        self._actions_first: SourceObservation | None = None\n",
)
replace_once(
    "sentinel/feed/authority.py",
    "        if table == sharadar.SEP and self._protect_sep(params or {}):\n"
    "            return self._stable_sep(table, params, **kwargs)\n\n"
    "        return self._fetch(table, params, **kwargs)\n",
    "        if table == sharadar.SEP:\n"
    "            if self._protect_sep(params or {}):\n"
    "                return self._stable_sep(table, params, **kwargs)\n"
    "            return source_validation.validated_market_rows(\n"
    "                table, self._fetch(table, params, **kwargs), params,\n"
    "                observation_through=self._observation_through)\n"
    "        if table == sharadar.SFP:\n"
    "            return source_validation.validated_market_rows(\n"
    "                table, self._fetch(table, params, **kwargs), params,\n"
    "                observation_through=self._observation_through)\n\n"
    "        return self._fetch(table, params, **kwargs)\n",
)
replace_once(
    "sentinel/feed/authority.py",
    "        first = observe_sep(self._fetch(table, params, **kwargs))\n",
    "        first = observe_sep(\n"
    "            self._fetch(table, params, **kwargs), params=params,\n"
    "            observation_through=self._observation_through)\n",
)
replace_once(
    "sentinel/feed/authority.py",
    "            for row in self._fetch(table, params, **kwargs):\n"
    "                fingerprint.add(_sep_payload(row))\n",
    "            for row in source_validation.validated_market_rows(\n"
    "                    table, self._fetch(table, params, **kwargs), params,\n"
    "                    observation_through=self._observation_through):\n"
    "                fingerprint.add(_sep_payload(row))\n",
)

# CDC must prove the update envelope before either stable observation is hashed.
replace_once(
    "sentinel/feed/maintenance.py",
    "    renormalize, sharadar, snapshot_export, store, universe)\n",
    "    renormalize, sharadar, snapshot_export, source_validation, store, universe)\n",
)
replace_once(
    "sentinel/feed/maintenance.py",
    "    def __init__(self, fetch):\n"
    "        self._fetch = fetch\n"
    "        self.max_sep_lastupdated: Optional[dt.date] = None\n",
    "    def __init__(self, fetch, *, through: str | dt.date | None = None):\n"
    "        self._fetch = fetch\n"
    "        self._through = (None if through is None else\n"
    "                         dt.date.fromisoformat(str(through)))\n"
    "        self.max_sep_lastupdated: Optional[dt.date] = None\n",
)
replace_once(
    "sentinel/feed/maintenance.py",
    "                    if (self.max_sep_lastupdated is None\n"
    "                            or observed > self.max_sep_lastupdated):\n"
    "                        self.max_sep_lastupdated = observed\n",
    "                    if self._through is not None and observed > self._through:\n"
    "                        raise SharadarMutationRefused(\n"
    "                            f\"SEP lastupdated {observed} is beyond seed \"\n"
    "                            f\"observation boundary {self._through}\")\n"
    "                    if (self.max_sep_lastupdated is None\n"
    "                            or observed > self.max_sep_lastupdated):\n"
    "                        self.max_sep_lastupdated = observed\n",
)
replace_once(
    "sentinel/feed/maintenance.py",
    "def _stable_rows(fetch, table: str, params: Mapping[str, str]) -> list[dict]:\n"
    "    first = [dict(row) for row in fetch(table, params)]\n"
    "    second = [dict(row) for row in fetch(table, params)]\n",
    "def _stable_rows(fetch, table: str, params: Mapping[str, str]) -> list[dict]:\n"
    "    if table == sharadar.SEP:\n"
    "        first = [dict(row) for row in source_validation.validated_market_rows(\n"
    "            table, fetch(table, params), params)]\n"
    "        second = [dict(row) for row in source_validation.validated_market_rows(\n"
    "            table, fetch(table, params), params)]\n"
    "    else:\n"
    "        first = [dict(row) for row in fetch(table, params)]\n"
    "        second = [dict(row) for row in fetch(table, params)]\n",
)
replace_once(
    "sentinel/feed/maintenance.py",
    "        if session_date < published_from or session_date > published_through:\n"
    "            continue\n",
    "        if session_date < published_from or session_date > published_through:\n"
    "            raise SharadarMutationRefused(\n"
    "                f\"SEP mutation row {ticker}/{session} lies outside the \"\n"
    "                f\"published authority horizon {published_from}..\"\n"
    "                f\"{published_through}; refusing to filter source evidence\")\n",
)

replace_once(
    "sentinel/feed/ingest.py",
    "    tracked = maintenance.LastUpdatedTrackingFetch(fetch)\n"
    "    guarded = coherence.StableSharadarFetch(\n",
    "    tracked = maintenance.LastUpdatedTrackingFetch(fetch, through=final_hi)\n"
    "    guarded = coherence.StableSharadarFetch(\n",
)
replace_once(
    "sentinel/feed/ingest.py",
    "        after_session=None, seed_mode=True)\n",
    "        after_session=None, seed_mode=True,\n"
    "        observation_through=final_hi)\n",
)

# ---------------------------------------------------------------------------
# TICKERS model validation and exact seed listing completeness.
# ---------------------------------------------------------------------------
replace_once(
    "sentinel/feed/coherence.py",
    "from sentinel.feed import authority, calendar, universe\n",
    "from sentinel.feed import authority, calendar, source_validation, universe\n"
    "from stock_strategy_shared.wealth_core.eligibility import is_common_equity\n",
)
replace_once(
    "sentinel/feed/coherence.py",
    "class SeedHistoryIncomplete(RuntimeError):\n"
    "    \"\"\"Historical SEP evidence is inconsistent with a complete seed source.\"\"\"\n",
    "class SeedHistoryIncomplete(RuntimeError):\n"
    "    \"\"\"Historical SEP evidence is inconsistent with a complete seed source.\"\"\"\n\n"
    "    def __init__(self, message: str, *, coverage_evidence=None):\n"
    "        super().__init__(message)\n"
    "        self.coverage_evidence = list(coverage_evidence or [])\n",
)
seed_types = '''

@dataclass(frozen=True)
class SeedExpectedListing:
    ticker: str
    first_session: str | None
    last_session: str | None
    strategy_eligible: bool

    def covers(self, session: str) -> bool:
        return not ((self.first_session and session < self.first_session)
                    or (self.last_session and session > self.last_session))


# No ratio waiver.  Any future exception must name one ticker/session/kind and
# carry a reviewed source explanation in the change that adds it.
SEED_COVERAGE_EXCEPTIONS: frozenset[tuple[str, str, str]] = frozenset()


def _expected_seed_listings(rows: Iterable[Mapping]) -> tuple[SeedExpectedListing, ...]:
    return tuple(
        SeedExpectedListing(
            ticker=str(row.get("ticker") or "").strip().upper(),
            first_session=(str(row.get("firstpricedate"))
                           if row.get("firstpricedate") else None),
            last_session=(str(row.get("lastpricedate"))
                          if row.get("lastpricedate") else None),
            strategy_eligible=is_common_equity(row.get("category")),
        )
        for row in rows
    )


def assert_seed_listing_coverage(
        observed: Mapping[str, set[str]],
        expected_listings: Iterable[SeedExpectedListing], *,
        date_from: str, date_to: str) -> list[dict]:
    """Require exact strategy-eligible source membership on every seed session."""
    listings = tuple(expected_listings)
    if not listings:
        raise SeedHistoryIncomplete(
            "historical seed has no stable TICKERS listing authority")
    evidence: list[dict] = []
    failures: list[str] = []
    for session in calendar.sessions_in_range(date_from, date_to):
        active = [item for item in listings if item.covers(session)]
        active_all = {item.ticker for item in active}
        eligible = {item.ticker for item in active if item.strategy_eligible}
        ineligible = active_all - eligible
        got = {str(ticker).strip().upper()
               for ticker in observed.get(session, set()) if str(ticker).strip()}
        missing = sorted(
            ticker for ticker in eligible - got
            if (ticker, session, "missing") not in SEED_COVERAGE_EXCEPTIONS)
        extra = sorted(
            ticker for ticker in got - active_all
            if (ticker, session, "extra") not in SEED_COVERAGE_EXCEPTIONS)
        absent_ineligible = ineligible - got
        item = {
            "session": session,
            "expected_eligible_count": len(eligible),
            "observed_expected_count": len(eligible.intersection(got)),
            "missing_eligible": missing,
            "missing_eligible_count": len(missing),
            "extra": extra,
            "extra_count": len(extra),
            "absent_ineligible_count": len(absent_ineligible),
        }
        evidence.append(item)
        if missing or extra:
            failures.append(
                f"{session}: missing eligible={missing[:8]}"
                f"{' ...' if len(missing) > 8 else ''}; "
                f"extra={extra[:8]}{' ...' if len(extra) > 8 else ''}")
    if failures:
        raise SeedHistoryIncomplete(
            "Sharadar SEP seed does not exactly cover the stable TICKERS "
            "strategy-eligible listing set: " + "; ".join(failures[:5]),
            coverage_evidence=evidence)
    return evidence
'''
replace_once(
    "sentinel/feed/coherence.py",
    "\n\nclass _Fingerprint:\n",
    seed_types + "\n\nclass _Fingerprint:\n",
)
replace_once(
    "sentinel/feed/coherence.py",
    "    def __init__(self, fetch, *, protect_sep=None,\n"
    "                 corroborate_reference=None,\n"
    "                 after_session: str | None = None,\n"
    "                 seed_mode: bool = False):\n",
    "    def __init__(self, fetch, *, protect_sep=None,\n"
    "                 corroborate_reference=None,\n"
    "                 after_session: str | None = None,\n"
    "                 seed_mode: bool = False,\n"
    "                 observation_through: str | _dt.date | None = None):\n",
)
replace_once(
    "sentinel/feed/coherence.py",
    "            corroborate_actions=reference,\n"
    "            after_session=after_session)\n",
    "            corroborate_actions=reference,\n"
    "            after_session=after_session,\n"
    "            observation_through=observation_through)\n",
)
replace_once(
    "sentinel/feed/coherence.py",
    "        self._seed_resolver = None\n"
    "        self._tickers_listings: tuple[universe.Listing, ...] | None = None\n",
    "        self._seed_resolver = None\n"
    "        self._seed_expected_listings: tuple[SeedExpectedListing, ...] = ()\n"
    "        self._seed_coverage_evidence: list[dict] = []\n"
    "        self._tickers_listings: tuple[universe.Listing, ...] | None = None\n",
)
replace_once(
    "sentinel/feed/coherence.py",
    "            rows = list(self._fetch(table, params, **kwargs))\n"
    "            relevant = assert_tickers_metadata(rows)\n",
    "            rows = list(self._fetch(table, params, **kwargs))\n"
    "            relevant = source_validation.validate_tickers(\n"
    "                _sep_ticker_rows(rows))\n"
    "            relevant = assert_tickers_metadata(relevant)\n",
)
replace_once(
    "sentinel/feed/coherence.py",
    "            self._seed_resolver = universe.IdentityResolver(listings)\n"
    "            return relevant\n",
    "            self._seed_resolver = universe.IdentityResolver(listings)\n"
    "            self._seed_expected_listings = _expected_seed_listings(relevant)\n"
    "            return relevant\n",
)
replace_once(
    "sentinel/feed/coherence.py",
    "            rows = list(self._fetch(table, params, **kwargs))\n"
    "            self._sfp_first = observe_sfp(rows)\n",
    "            rows = list(source_validation.validated_market_rows(\n"
    "                \"SFP\", self._fetch(table, params, **kwargs), params))\n"
    "            self._sfp_first = observe_sfp(rows)\n",
)
replace_once(
    "sentinel/feed/coherence.py",
    "            rows = list(self._fetch(\n"
    "                sharadar.TICKERS, dict(self._tickers_params or {}),\n"
    "                **dict(self._tickers_kwargs or {})))\n"
    "            relevant = assert_tickers_metadata(rows)\n",
    "            rows = list(self._fetch(\n"
    "                sharadar.TICKERS, dict(self._tickers_params or {}),\n"
    "                **dict(self._tickers_kwargs or {})))\n"
    "            relevant = source_validation.validate_tickers(\n"
    "                _sep_ticker_rows(rows))\n"
    "            relevant = assert_tickers_metadata(relevant)\n",
)
replace_once(
    "sentinel/feed/coherence.py",
    "            rows = list(self._fetch(\n"
    "                sharadar.SFP, dict(self._sfp_params or {}),\n"
    "                **dict(self._sfp_kwargs or {})))\n"
    "            authority.require_stable(\"SFP\", self._sfp_first, observe_sfp(rows))\n",
    "            rows = list(source_validation.validated_market_rows(\n"
    "                \"SFP\", self._fetch(\n"
    "                    sharadar.SFP, dict(self._sfp_params or {}),\n"
    "                    **dict(self._sfp_kwargs or {})),\n"
    "                dict(self._sfp_params or {})))\n"
    "            authority.require_stable(\"SFP\", self._sfp_first, observe_sfp(rows))\n",
)
replace_once(
    "sentinel/feed/coherence.py",
    "        spool = tempfile.TemporaryFile(mode=\"w+b\")\n"
    "        sessions: dict[str, SeedSessionCounts] = {}\n"
    "        try:\n"
    "            for row in rows:\n"
    "                row = dict(row)\n"
    "                session = str(row.get(\"date\") or \"\")\n"
    "                ticker = str(row.get(\"ticker\") or \"\")\n"
    "                resolved = bool(session and ticker and resolver(ticker, session))\n"
    "                if session:\n"
    "                    sessions[session] = sessions.get(\n"
    "                        session, SeedSessionCounts()).add(\n"
    "                            row, resolved=resolved)\n"
    "                pickle.dump(row, spool, protocol=pickle.HIGHEST_PROTOCOL)\n"
    "            assert_seed_history(\n"
    "                sessions, date_from=date_from, date_to=date_to)\n"
    "            spool.seek(0)\n",
    "        spool = tempfile.TemporaryFile(mode=\"w+b\")\n"
    "        sessions: dict[str, SeedSessionCounts] = {}\n"
    "        observed_tickers: dict[str, set[str]] = {}\n"
    "        try:\n"
    "            for row in rows:\n"
    "                row = dict(row)\n"
    "                session = str(row.get(\"date\") or \"\")\n"
    "                ticker = str(row.get(\"ticker\") or \"\").strip().upper()\n"
    "                resolved = bool(session and ticker and resolver(ticker, session))\n"
    "                if session:\n"
    "                    sessions[session] = sessions.get(\n"
    "                        session, SeedSessionCounts()).add(\n"
    "                            row, resolved=resolved)\n"
    "                    if ticker:\n"
    "                        observed_tickers.setdefault(session, set()).add(ticker)\n"
    "                pickle.dump(row, spool, protocol=pickle.HIGHEST_PROTOCOL)\n"
    "            try:\n"
    "                coverage = assert_seed_listing_coverage(\n"
    "                    observed_tickers, self._seed_expected_listings,\n"
    "                    date_from=date_from, date_to=date_to)\n"
    "            except SeedHistoryIncomplete as exc:\n"
    "                self._seed_coverage_evidence.extend(exc.coverage_evidence)\n"
    "                raise\n"
    "            self._seed_coverage_evidence.extend(coverage)\n"
    "            assert_seed_history(\n"
    "                sessions, date_from=date_from, date_to=date_to)\n"
    "            spool.seek(0)\n",
)
replace_once(
    "sentinel/feed/coherence.py",
    "    def _validated_daily_listing_replay(self, rows):\n",
    "    def pop_seed_coverage_evidence(self) -> list[dict]:\n"
    "        evidence = self._seed_coverage_evidence\n"
    "        self._seed_coverage_evidence = []\n"
    "        return evidence\n\n"
    "    def _validated_daily_listing_replay(self, rows):\n",
)

# ---------------------------------------------------------------------------
# Publication generation outranks observation date in current identity state.
# ---------------------------------------------------------------------------
replace_once(
    "sentinel/feed/universe.py",
    "      ORDER BY snapshot_date DESC,candidate DESC),NULL))[1]",
    "      ORDER BY candidate DESC,snapshot_date DESC),NULL))[1]",
)
# Same text appears twice (first and last bounds); replace the remaining copy.
replace_once(
    "sentinel/feed/universe.py",
    "      ORDER BY snapshot_date DESC,candidate DESC),NULL))[1]",
    "      ORDER BY candidate DESC,snapshot_date DESC),NULL))[1]",
)

projection = Path("sentinel/feed/universe_projection.py")
text = projection.read_text()
text = text.replace(
    "ORDER BY u.snapshot_date DESC,u.authority_version DESC",
    "ORDER BY u.authority_version DESC,u.snapshot_date DESC")
if text.count("ORDER BY u.authority_version DESC,u.snapshot_date DESC") < 5:
    raise RuntimeError("universe projection generation-order replacement incomplete")
projection.write_text(text)
replace_once(
    "sentinel/feed/universe_projection.py",
    "def _newer_value(value: str, observed: str) -> str:\n"
    "    return f\"\"\"CASE\n"
    "        WHEN EXCLUDED.{observed} IS NULL THEN feed_universe_current.{value}\n"
    "        WHEN feed_universe_current.{observed} IS NULL\n"
    "          OR EXCLUDED.{observed} >= feed_universe_current.{observed}\n"
    "          THEN EXCLUDED.{value}\n"
    "        ELSE feed_universe_current.{value} END\"\"\"\n",
    "def _newer_value(value: str, observed: str) -> str:\n"
    "    # project_run is called only inside publication order. The candidate\n"
    "    # generation therefore outranks observation chronology; NULL remains\n"
    "    # sparse carry-forward rather than an erasure.\n"
    "    return f\"\"\"CASE\n"
    "        WHEN EXCLUDED.{observed} IS NULL THEN feed_universe_current.{value}\n"
    "        ELSE EXCLUDED.{value} END\"\"\"\n",
)
replace_once(
    "sentinel/feed/universe_projection.py",
    "def _newer_date(observed: str) -> str:\n"
    "    return f\"\"\"CASE\n"
    "        WHEN EXCLUDED.{observed} IS NULL\n"
    "          THEN feed_universe_current.{observed}\n"
    "        WHEN feed_universe_current.{observed} IS NULL\n"
    "          OR EXCLUDED.{observed} >= feed_universe_current.{observed}\n"
    "          THEN EXCLUDED.{observed}\n"
    "        ELSE feed_universe_current.{observed} END\"\"\"\n",
    "def _newer_date(observed: str) -> str:\n"
    "    return f\"COALESCE(EXCLUDED.{observed}, feed_universe_current.{observed})\"\n",
)
replace_once(
    "sentinel/feed/universe_projection.py",
    "def _newer_bound(value: str) -> str:\n"
    "    \"\"\"Latest non-null listing bound; later authority may narrow the interval.\"\"\"\n"
    "    return f\"\"\"CASE\n"
    "        WHEN EXCLUDED.{value} IS NULL THEN feed_universe_current.{value}\n"
    "        WHEN EXCLUDED.snapshot_date >= feed_universe_current.snapshot_date\n"
    "          THEN EXCLUDED.{value}\n"
    "        ELSE feed_universe_current.{value} END\"\"\"\n",
    "def _newer_bound(value: str) -> str:\n"
    "    \"\"\"Later publication generation wins; NULL carries prior evidence.\"\"\"\n"
    "    return f\"COALESCE(EXCLUDED.{value}, feed_universe_current.{value})\"\n",
)
identity_functions = '''

_IDENTITY_REBUILD_INSERT = """
INSERT INTO feed_universe_current
      (permaticker,ticker,category,category_snapshot_date,
       sector,sector_snapshot_date,
       related_tickers,related_tickers_snapshot_date,
       first_price_date,last_price_date,
       is_delisted,is_delisted_snapshot_date,snapshot_date)
SELECT u.permaticker,u.ticker,
  (ARRAY_REMOVE(ARRAY_AGG(u.category ORDER BY u.snapshot_date DESC),NULL))[1],
  MAX(u.snapshot_date) FILTER (WHERE u.category IS NOT NULL),
  (ARRAY_REMOVE(ARRAY_AGG(u.sector ORDER BY u.snapshot_date DESC),NULL))[1],
  MAX(u.snapshot_date) FILTER (WHERE u.sector IS NOT NULL),
  (ARRAY_REMOVE(ARRAY_AGG(u.related_tickers ORDER BY u.snapshot_date DESC),NULL))[1],
  MAX(u.snapshot_date) FILTER (WHERE u.related_tickers IS NOT NULL),
  (ARRAY_REMOVE(ARRAY_AGG(u.first_price_date ORDER BY u.snapshot_date DESC),NULL))[1],
  (ARRAY_REMOVE(ARRAY_AGG(u.last_price_date ORDER BY u.snapshot_date DESC),NULL))[1],
  (ARRAY_REMOVE(ARRAY_AGG(u.is_delisted ORDER BY u.snapshot_date DESC),NULL))[1],
  MAX(u.snapshot_date) FILTER (WHERE u.is_delisted IS NOT NULL),
  MAX(u.snapshot_date)
FROM sentinel_universe u
WHERE u.last_written_run_id=%s
  AND u.permaticker IS NOT NULL AND u.ticker IS NOT NULL
GROUP BY u.permaticker,u.ticker
"""


def _assert_identity_rebuild_projection(conn, *, run_id: str) -> int:
    """Prove exact membership and listing bounds before publication can commit."""
    with conn.cursor() as cur:
        cur.execute(
            "WITH candidate AS ("
            " SELECT u.permaticker,u.ticker,"
            "  (ARRAY_REMOVE(ARRAY_AGG(u.first_price_date"
            "    ORDER BY u.snapshot_date DESC),NULL))[1] AS first_price_date,"
            "  (ARRAY_REMOVE(ARRAY_AGG(u.last_price_date"
            "    ORDER BY u.snapshot_date DESC),NULL))[1] AS last_price_date"
            " FROM sentinel_universe u WHERE u.last_written_run_id=%s"
            "   AND u.permaticker IS NOT NULL AND u.ticker IS NOT NULL"
            " GROUP BY u.permaticker,u.ticker), differences AS ("
            " SELECT COALESCE(c.permaticker,p.permaticker) AS permaticker,"
            "        COALESCE(c.ticker,p.ticker) AS ticker"
            " FROM candidate c FULL OUTER JOIN feed_universe_current p"
            "   ON p.permaticker=c.permaticker AND p.ticker=c.ticker"
            " WHERE c.permaticker IS NULL OR p.permaticker IS NULL"
            "    OR p.first_price_date IS DISTINCT FROM c.first_price_date"
            "    OR p.last_price_date IS DISTINCT FROM c.last_price_date)"
            " SELECT (SELECT COUNT(*) FROM candidate),"
            "        (SELECT COUNT(*) FROM feed_universe_current),"
            "        (SELECT COUNT(*) FROM differences)",
            (str(run_id),))
        candidate_count, projection_count, differences = map(int, cur.fetchone())
    if candidate_count <= 0:
        raise RuntimeError(
            f"identity rebuild {run_id} has no candidate TICKERS membership")
    if candidate_count != projection_count or differences:
        raise RuntimeError(
            f"identity rebuild {run_id} projection mismatch before publication: "
            f"candidate={candidate_count}, projection={projection_count}, "
            f"differences={differences}")
    return candidate_count


def _replace_identity_rebuild_run(conn, *, run_id: str) -> int:
    """Replace current identity state in the caller's publication transaction."""
    with conn.cursor() as cur:
        cur.execute("DELETE FROM feed_universe_current")
        cur.execute(_IDENTITY_REBUILD_INSERT, (str(run_id),))
        written = max(0, int(cur.rowcount or 0))
    _assert_identity_rebuild_projection(conn, run_id=run_id)
    return written
'''
replace_once(
    "sentinel/feed/universe_projection.py",
    "\n\ndef retire_absent_from_run(conn, *, run_id: str) -> int:\n",
    identity_functions + "\n\ndef retire_absent_from_run(conn, *, run_id: str) -> int:\n",
)
replace_once(
    "sentinel/feed/universe_projection.py",
    "def project_run(conn, *, run_id: str) -> int:\n"
    "    \"\"\"Merge one candidate generation; caller owns the publication transaction.\n\n"
    "    This function NEVER commits. `publication.publish` invokes it before the\n"
    "    publication row is committed, so either both projection and publication\n"
    "    become durable or neither does.\n"
    "    \"\"\"\n"
    "    sql = _PROJECT_RUN.format(predicate=\"u.last_written_run_id=%s\")\n"
    "    with conn.cursor() as cur:\n"
    "        cur.execute(sql, (str(run_id),))\n"
    "        return max(0, int(cur.rowcount or 0))\n",
    "def project_run(conn, *, run_id: str) -> int:\n"
    "    \"\"\"Project one later publication generation without committing.\"\"\"\n"
    "    with conn.cursor() as cur:\n"
    "        cur.execute(\n"
    "            \"SELECT publication_recovery->>'schema' FROM feed_ingest_runs\"\n"
    "            \" WHERE run_id=%s\", (str(run_id),))\n"
    "        row = cur.fetchone()\n"
    "    if row is None:\n"
    "        raise RuntimeError(f\"projection run {run_id} has no ingest lifecycle\")\n"
    "    if row[0] == 'sentinel.identity-rebuild/1':\n"
    "        return _replace_identity_rebuild_run(conn, run_id=run_id)\n"
    "    sql = _PROJECT_RUN.format(predicate=\"u.last_written_run_id=%s\")\n"
    "    with conn.cursor() as cur:\n"
    "        cur.execute(sql, (str(run_id),))\n"
    "        return max(0, int(cur.rowcount or 0))\n",
)
replace_once(
    "sentinel/feed/universe_projection.py",
    "    sql = _PROJECT_RUN.format(\n"
    "        predicate=\"u.last_written_run_id IS NULL AND u.snapshot_date=%s\")\n"
    "    with conn.cursor() as cur:\n"
    "        cur.execute(sql, (snapshot_date,))\n"
    "        return max(0, int(cur.rowcount or 0))\n",
    "    # Legacy imports are not ordered publication generations. Reconstruct\n"
    "    # from all visible evidence so observation chronology remains their only\n"
    "    # authority rather than reusing the later-generation merge rule.\n"
    "    with conn.cursor() as cur:\n"
    "        cur.execute(_REBUILD_DELETE)\n"
    "        cur.execute(_REBUILD_INSERT)\n"
    "        return max(0, int(cur.rowcount or 0))\n",
)

# ---------------------------------------------------------------------------
# Manual daily boundary is an explicit/latest-closed XNYS decision session.
# ---------------------------------------------------------------------------
replace_once(
    "sentinel/__main__.py",
    "    sub.add_parser(\"feed-daily\", help=\"fetch since the stored frontier\")\n",
    "    fd = sub.add_parser(\"feed-daily\", help=\"fetch since the stored frontier\")\n"
    "    fd.add_argument(\"--through\", default=None,\n"
    "                    help=\"closed XNYS decision session (YYYY-MM-DD)\")\n",
)
resolve_helper = '''

def _resolve_feed_daily_through(value: str | None, *, now_et=None) -> str:
    """Resolve/refuse the exact closed XNYS decision boundary before mutation."""
    from sentinel.feed import calendar

    observation = (now_et if now_et is not None else
                   datetime.now(ZoneInfo(calendar.EXCHANGE_TZ)))
    latest = calendar.latest_closed_session(observation)
    if value is None:
        return latest
    try:
        requested = datetime.strptime(str(value), "%Y-%m-%d").date().isoformat()
    except ValueError as exc:
        raise ValueError("--through must be an ISO date YYYY-MM-DD") from exc
    try:
        calendar.session_window(requested)
    except Exception as exc:
        raise ValueError(f"--through {requested} is not an XNYS session") from exc
    if requested > latest:
        raise ValueError(
            f"--through {requested} is later than latest fully closed XNYS "
            f"session {latest}")
    return requested
'''
replace_once(
    "sentinel/__main__.py",
    "\ndef cmd_feed(config: SentinelConfig, args) -> int:\n",
    resolve_helper + "\n\ndef cmd_feed(config: SentinelConfig, args) -> int:\n",
)
replace_once(
    "sentinel/__main__.py",
    "    from sentinel.feed import ingest\n"
    "    from sentinel.feed import store as feed_store\n\n"
    "    # BEFORE database construction.  A stale image is allowed to describe\n",
    "    from sentinel.feed import ingest\n"
    "    from sentinel.feed import store as feed_store\n\n"
    "    resolved_through = None\n"
    "    if args.command == \"feed-daily\":\n"
    "        try:\n"
    "            resolved_through = _resolve_feed_daily_through(args.through)\n"
    "        except ValueError as exc:\n"
    "            print(f\"REFUSED: {exc}\", file=sys.stderr)\n"
    "            return EXIT_CONFIG\n"
    "        print(json.dumps({\n"
    "            \"schema\": \"sentinel.feed-daily-boundary/1\",\n"
    "            \"resolved_decision_session\": resolved_through,\n"
    "            \"calendar\": \"XNYS\",\n"
    "        }, sort_keys=True))\n\n"
    "    # BEFORE database construction.  A stale image is allowed to describe\n",
)
replace_once(
    "sentinel/__main__.py",
    "        else:\n"
    "            p = ingest.daily(conn)\n",
    "        else:\n"
    "            p = ingest.daily(conn, today=resolved_through)\n",
)

# ---------------------------------------------------------------------------
# Adversarial regression tests.
# ---------------------------------------------------------------------------
Path("tests/sentinel/test_issue_250_source_authority.py").write_text(textwrap.dedent(r'''
    """Issue #250 source-envelope, identity-model, seed, and CLI falsifiers."""
    from __future__ import annotations

    from datetime import datetime
    from zoneinfo import ZoneInfo

    import pytest

    from sentinel.__main__ import _resolve_feed_daily_through
    from sentinel.feed import coherence, source_validation


    def _bar(**overrides):
        row = {
            "ticker": "AAA", "date": "2026-08-24", "open": 10,
            "close": 11, "closeunadj": 11, "volume": 100,
            "lastupdated": "2026-08-24",
        }
        row.update(overrides)
        return row


    def _ticker(permaticker="P1", ticker="AAA", **overrides):
        row = {
            "table": "SEP", "permaticker": permaticker, "ticker": ticker,
            "category": "Domestic Common Stock", "firstpricedate": "2026-08-24",
            "lastpricedate": "2026-08-24", "isdelisted": "N",
        }
        row.update(overrides)
        return row


    def test_market_envelope_collapses_exact_repeat_and_refuses_conflict():
        params = {"date.gte": "2026-08-24", "date.lte": "2026-08-24"}
        assert len(list(source_validation.validated_market_rows(
            "SEP", [_bar(), _bar()], params))) == 1
        with pytest.raises(source_validation.ConflictingSourceDuplicate):
            list(source_validation.validated_market_rows(
                "SEP", [_bar(), _bar(close=12)], params))


    @pytest.mark.parametrize("row,params,through", [
        (_bar(date="2026-08-21"),
         {"date.gte": "2026-08-24", "date.lte": "2026-08-24"}, None),
        (_bar(date="2026-08-23"),
         {"date.gte": "2026-08-23", "date.lte": "2026-08-23"}, None),
        (_bar(lastupdated="2026-08-25"),
         {"date.gte": "2026-08-24", "date.lte": "2026-08-24"}, "2026-08-24"),
        (_bar(lastupdated="2026-08-20"),
         {"lastupdated.gte": "2026-08-21", "lastupdated.lte": "2026-08-24"}, None),
    ])
    def test_market_envelope_refuses_outside_non_session_and_watermark(row, params, through):
        with pytest.raises(source_validation.SourceEnvelopeRefused):
            list(source_validation.validated_market_rows(
                "SEP", [row], params, observation_through=through))


    @pytest.mark.parametrize("rows", [
        [_ticker(firstpricedate="2026-08-25", lastpricedate="2026-08-24")],
        [_ticker(isdelisted="MAYBE")],
        [_ticker(), _ticker(category="Preferred Stock")],
        [_ticker("P1", "AAA", firstpricedate="2026-08-20", lastpricedate="2026-08-24"),
         _ticker("P2", "AAA", firstpricedate="2026-08-24", lastpricedate="2026-08-25")],
    ])
    def test_tickers_impossible_or_conflicting_models_refuse(rows):
        with pytest.raises(source_validation.SourceEnvelopeRefused):
            source_validation.validate_tickers(rows)


    def test_tickers_exact_duplicate_collapses():
        assert len(source_validation.validate_tickers([_ticker(), _ticker()])) == 1


    def test_stable_partial_seed_missing_one_eligible_listing_refuses_exactly():
        expected = (
            coherence.SeedExpectedListing("AAA", "2026-08-24", "2026-08-24", True),
            coherence.SeedExpectedListing("BBB", "2026-08-24", "2026-08-24", True),
            coherence.SeedExpectedListing("ETF", "2026-08-24", "2026-08-24", False),
        )
        with pytest.raises(coherence.SeedHistoryIncomplete) as failure:
            coherence.assert_seed_listing_coverage(
                {"2026-08-24": {"AAA"}}, expected,
                date_from="2026-08-24", date_to="2026-08-24")
        evidence = failure.value.coverage_evidence[0]
        assert evidence["missing_eligible"] == ["BBB"]
        assert evidence["extra"] == []
        assert evidence["absent_ineligible_count"] == 1


    def test_daily_boundary_ignores_utc_rollover_and_refuses_non_session_future():
        # 17:30 PDT is already 00:30 UTC on Aug 25; the decision boundary is
        # still the fully closed Aug 24 XNYS session.
        now = datetime(2026, 8, 24, 17, 30, tzinfo=ZoneInfo("America/Los_Angeles"))
        assert _resolve_feed_daily_through(None, now_et=now) == "2026-08-24"
        with pytest.raises(ValueError, match="not an XNYS session"):
            _resolve_feed_daily_through("2026-08-23", now_et=now)
        with pytest.raises(ValueError, match="later than latest fully closed"):
            _resolve_feed_daily_through("2026-08-25", now_et=now)
''').lstrip())

append_once(
    "tests/sentinel/test_issue_246_identity_rebuild.py",
    "test_older_observation_identity_generation_replaces_bounds",
    textwrap.dedent('''
    def test_older_observation_identity_generation_replaces_bounds(conn, monkeypatch):
        _publish_base(conn)
        monkeypatch.setattr(
            IR, "_unused_snapshot_date", lambda *a, **k: "2026-08-19")
        corrected = _candidate_rows()
        for row in corrected:
            row["firstpricedate"] = "2026-08-20"
            row["lastpricedate"] = "2026-08-20"
        with S.corpus_write_lock(conn):
            plan = IR.prepare(
                conn, date_from="2026-08-20", date_to="2026-08-21",
                observed_on="2026-08-24")
            run = S.IngestRun(
                conn, "seed", date_from=plan.market_start, date_to=plan.market_end)
            IR.record_plan(conn, run_id=run.progress.run_id, plan=plan)
            rows = IR.verify_candidate(
                conn, run_id=run.progress.run_id, plan=plan, rows=corrected)
            IR.write_bars_claiming(
                conn, [_bar("P1", "BTLN"), _bar("P3", "KEEP"),
                       _bar("P4", "NEW")],
                run_id=run.progress.run_id, batch_size=2)
            IR.publish_completed_run(conn, run=run, rows=rows, plan=plan)

        with conn.cursor() as cur:
            cur.execute(
                "SELECT permaticker,ticker,first_price_date,last_price_date"
                " FROM feed_universe_current ORDER BY permaticker,ticker")
            rows = [(str(p), str(t), str(f), str(l))
                    for p, t, f, l in cur.fetchall()]
        assert rows == [
            ("P1", "BTLN", "2026-08-20", "2026-08-20"),
            ("P3", "KEEP", "2026-08-20", "2026-08-20"),
            ("P4", "NEW", "2026-08-20", "2026-08-20"),
        ]


    def test_identity_projection_assertion_failure_rolls_back_replacement(
            conn, monkeypatch):
        from sentinel.feed import universe_projection as UP

        base = _publish_base(conn)
        with S.corpus_write_lock(conn):
            plan, run, rows = _prepare_candidate(conn)
            original = UP._assert_identity_rebuild_projection

            def fail_after_exact_projection(connection, *, run_id):
                original(connection, run_id=run_id)
                raise RuntimeError("post-replacement assertion fault")

            monkeypatch.setattr(UP, "_assert_identity_rebuild_projection",
                                fail_after_exact_projection)
            with pytest.raises(RuntimeError, match="post-replacement"):
                IR.publish_completed_run(conn, run=run, rows=rows, plan=plan)

        assert P.require_current(conn).version == base.version
        with conn.cursor() as cur:
            cur.execute(
                "SELECT permaticker,ticker FROM feed_universe_current"
                " ORDER BY permaticker,ticker")
            pairs = [(str(p), str(t)) for p, t in cur.fetchall()]
        assert pairs == [("P1", "GGRP"), ("P2", "LBRDK"), ("P3", "KEEP")]
    ''')
)

# Keep formatting deterministic and fail early on syntax errors in the workflow.
