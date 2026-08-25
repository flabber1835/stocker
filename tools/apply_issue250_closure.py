from __future__ import annotations

from pathlib import Path
import textwrap


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text()
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"{path}: expected one replacement, found {count}: {old[:120]!r}")
    target.write_text(text.replace(old, new, 1))


def replace_between(path: str, start: str, end: str, replacement: str) -> None:
    target = Path(path)
    text = target.read_text()
    a = text.index(start)
    b = text.index(end, a)
    target.write_text(text[:a] + replacement.rstrip() + "\n\n" + text[b:])


# ---------------------------------------------------------------------------
# Source envelopes are proved in full before the first downstream row exists.
# ---------------------------------------------------------------------------
replace_once(
    "sentinel/feed/source_validation.py",
    "import math\nfrom pathlib import Path\n",
    "import math\nfrom pathlib import Path\nimport pickle\n",
)
replace_between(
    "sentinel/feed/source_validation.py",
    "def validated_market_rows(",
    "def validate_tickers(",
    r'''
def validated_market_rows(
    table: str,
    rows: Iterable[Mapping],
    params: Mapping | None = None,
    *,
    observation_through: str | dt.date | None = None,
) -> Iterator[Mapping]:
    """Prove a complete SEP/SFP observation, then replay it from spill.

    The first implementation validated while yielding. That still rolled back a
    failed publication, but it allowed an early row to enter staging/fingerprint
    state before a later off-envelope/conflicting row refused the observation.
    This membrane now scans and validates the entire response into an external
    relation before yielding its first row. Exact canonical repeats collapse in
    first-observed order; conflicting source keys refuse the whole observation.
    """
    source = str(table).strip().upper()
    if source not in {"SEP", "SFP"}:
        raise ValueError(f"market-row validation does not support {table!r}")
    date_lo, date_hi = _requested_date_bounds(params)
    update_lo, update_hi = _requested_update_bounds(params)
    through = (_strict_date(observation_through, label="observation through")
               if observation_through is not None else None)
    requested_sessions = None
    if date_lo is not None:
        requested_sessions = set(calendar.sessions_in_range(
            date_lo.isoformat(), date_hi.isoformat()))
    checked_sessions: set[str] = set()

    with tempfile.TemporaryDirectory(prefix="sentinel-source-rows-") as directory:
        db_path = Path(directory) / "rows.sqlite3"
        seen = sqlite3.connect(str(db_path))
        try:
            seen.execute("PRAGMA journal_mode=OFF")
            seen.execute("PRAGMA synchronous=OFF")
            seen.execute("PRAGMA temp_store=FILE")
            seen.execute(
                "CREATE TABLE source_rows ("
                " ordinal INTEGER PRIMARY KEY AUTOINCREMENT,"
                " source_key TEXT NOT NULL UNIQUE,"
                " canonical BLOB NOT NULL, row_blob BLOB NOT NULL)")
            pending = 0
            for raw in rows:
                row = dict(raw)
                ticker = str(row.get("ticker") or "").strip().upper()
                if not ticker:
                    raise SourceEnvelopeRefused(f"Sharadar {source} row has no ticker")
                session = _strict_date(
                    row.get("date"), label=f"Sharadar {source} {ticker} date")
                session_text = session.isoformat()
                if date_lo is not None and not date_lo <= session <= date_hi:
                    raise SourceEnvelopeRefused(
                        f"Sharadar {source} row {ticker}/{session_text} lies outside "
                        f"requested interval {date_lo}..{date_hi}")
                if requested_sessions is not None:
                    if session_text not in requested_sessions:
                        raise SourceEnvelopeRefused(
                            f"Sharadar {source} row {ticker}/{session_text} is not an "
                            "XNYS session in the requested market interval")
                elif session_text not in checked_sessions:
                    try:
                        calendar.session_window(session_text)
                    except Exception as exc:
                        raise SourceEnvelopeRefused(
                            f"Sharadar {source} row {ticker}/{session_text} is not an "
                            "XNYS session") from exc
                    checked_sessions.add(session_text)

                if source == "SEP":
                    updated_raw = row.get("lastupdated")
                    updated = None
                    if updated_raw is not None and str(updated_raw).strip():
                        updated = _strict_date(
                            updated_raw,
                            label=f"Sharadar SEP {ticker}/{session_text} lastupdated")
                    if update_lo is not None:
                        if updated is None or not update_lo <= updated <= update_hi:
                            raise SourceEnvelopeRefused(
                                f"Sharadar SEP row {ticker}/{session_text} has "
                                f"lastupdated={updated_raw!r} outside requested "
                                f"interval {update_lo}..{update_hi}")
                    if through is not None and updated is not None and updated > through:
                        raise SourceEnvelopeRefused(
                            f"Sharadar SEP row {ticker}/{session_text} has future "
                            f"lastupdated {updated} beyond observation boundary {through}")

                key = f"{ticker}\x00{session_text}"
                canonical = canonical_row_bytes(row)
                row_blob = pickle.dumps(row, protocol=pickle.HIGHEST_PROTOCOL)
                cursor = seen.execute(
                    "INSERT OR IGNORE INTO source_rows"
                    " (source_key,canonical,row_blob) VALUES (?,?,?)",
                    (key, canonical, row_blob))
                if cursor.rowcount == 0:
                    prior = seen.execute(
                        "SELECT canonical FROM source_rows WHERE source_key=?", (key,)
                    ).fetchone()
                    if prior is None or bytes(prior[0]) != canonical:
                        raise ConflictingSourceDuplicate(
                            f"Sharadar {source} returned conflicting duplicate source "
                            f"key ({ticker}, {session_text})")
                    continue
                pending += 1
                if pending >= 10_000:
                    seen.commit()
                    pending = 0
            seen.commit()

            cursor = seen.execute(
                "SELECT row_blob FROM source_rows ORDER BY ordinal")
            while True:
                batch = cursor.fetchmany(2_000)
                if not batch:
                    return
                for (row_blob,) in batch:
                    yield pickle.loads(bytes(row_blob))
        finally:
            seen.close()
''',
)


# ---------------------------------------------------------------------------
# Exact, linear-time per-session expected-listing coverage and evidence.
# ---------------------------------------------------------------------------
replace_once(
    "sentinel/feed/coherence.py",
    "import datetime as _dt\n",
    "import bisect\nimport datetime as _dt\n",
)
replace_between(
    "sentinel/feed/coherence.py",
    "def assert_seed_listing_coverage(",
    "class _Fingerprint:",
    r'''
def assert_seed_listing_coverage(
        observed: Mapping[str, set[str]],
        expected_listings: Iterable[SeedExpectedListing], *,
        date_from: str, date_to: str) -> list[dict]:
    """Require exact strategy-eligible source membership on every seed session.

    Listing intervals are swept once across the XNYS session axis. This avoids
    an O(sessions × all-listings) scan while retaining exact missing/extra and
    absent-ineligible evidence at each candidate session.
    """
    listings = tuple(expected_listings)
    if not listings:
        raise SeedHistoryIncomplete(
            "historical seed has no stable TICKERS listing authority")
    sessions = calendar.sessions_in_range(date_from, date_to)
    if not sessions:
        raise SeedHistoryIncomplete(
            f"historical seed interval {date_from}..{date_to} has no XNYS sessions")

    starts: dict[int, list[SeedExpectedListing]] = {}
    stops: dict[int, list[SeedExpectedListing]] = {}
    for item in listings:
        if not item.ticker:
            raise SeedHistoryIncomplete(
                "stable TICKERS listing authority contains a blank ticker")
        lo = item.first_session or sessions[0]
        hi = item.last_session or sessions[-1]
        start = bisect.bisect_left(sessions, max(lo, sessions[0]))
        stop = bisect.bisect_right(sessions, min(hi, sessions[-1]))
        if start >= stop:
            continue
        starts.setdefault(start, []).append(item)
        stops.setdefault(stop, []).append(item)

    eligible: set[str] = set()
    ineligible: set[str] = set()
    evidence: list[dict] = []
    failures: list[str] = []
    for index, session in enumerate(sessions):
        for item in stops.get(index, ()):
            (eligible if item.strategy_eligible else ineligible).discard(item.ticker)
        for item in starts.get(index, ()):
            (eligible if item.strategy_eligible else ineligible).add(item.ticker)
        active_all = eligible | ineligible
        got = {str(ticker).strip().upper()
               for ticker in observed.get(session, set()) if str(ticker).strip()}
        missing = sorted(
            ticker for ticker in eligible - got
            if (ticker, session, "missing") not in SEED_COVERAGE_EXCEPTIONS)
        extra = sorted(
            ticker for ticker in got - active_all
            if (ticker, session, "extra") not in SEED_COVERAGE_EXCEPTIONS)
        absent_ineligible = sorted(ineligible - got)
        observed_eligible = len(eligible.intersection(got))
        observed_ineligible = len(ineligible.intersection(got))
        item = {
            "session": session,
            "expected_listing_count": len(active_all),
            "expected_eligible_count": len(eligible),
            "expected_ineligible_count": len(ineligible),
            "observed_total_count": len(got),
            "observed_expected_count": observed_eligible,
            "observed_ineligible_count": observed_ineligible,
            "missing_eligible": missing,
            "missing_eligible_count": len(missing),
            "extra": extra,
            "extra_count": len(extra),
            "absent_ineligible": absent_ineligible,
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


class _Fingerprint:
''',
)
replace_once(
    "sentinel/feed/coherence.py",
    '''            rows = list(self._fetch(table, params, **kwargs))
            relevant = source_validation.validate_tickers(
                _sep_ticker_rows(rows))
            relevant = assert_tickers_metadata(relevant)
''',
    '''            rows = list(self._fetch(table, params, **kwargs))
            relevant = assert_tickers_metadata(rows)
            relevant = source_validation.validate_tickers(relevant)
''',
)
replace_once(
    "sentinel/feed/coherence.py",
    '''            rows = list(self._fetch(
                sharadar.TICKERS, dict(self._tickers_params or {}),
                **dict(self._tickers_kwargs or {})))
            relevant = source_validation.validate_tickers(
                _sep_ticker_rows(rows))
            relevant = assert_tickers_metadata(relevant)
''',
    '''            rows = list(self._fetch(
                sharadar.TICKERS, dict(self._tickers_params or {}),
                **dict(self._tickers_kwargs or {})))
            relevant = assert_tickers_metadata(rows)
            relevant = source_validation.validate_tickers(relevant)
''',
)


# ---------------------------------------------------------------------------
# Durable exact seed coverage evidence and a practical staging source key.
# ---------------------------------------------------------------------------
coverage_ddl = r'''
    # Exact expected-vs-observed source membership, at candidate-run/session
    # grain. Failed candidates retain their refusal evidence; publication does
    # not rewrite it into success.
    """CREATE TABLE IF NOT EXISTS sentinel_seed_coverage_evidence (
        run_id                         UUID NOT NULL,
        chunk                          TEXT NOT NULL,
        session                        DATE NOT NULL,
        expected_listing_count         INTEGER NOT NULL CHECK (expected_listing_count >= 0),
        expected_eligible_count        INTEGER NOT NULL CHECK (expected_eligible_count >= 0),
        expected_ineligible_count      INTEGER NOT NULL CHECK (expected_ineligible_count >= 0),
        observed_total_count           INTEGER NOT NULL CHECK (observed_total_count >= 0),
        observed_expected_count        INTEGER NOT NULL CHECK (observed_expected_count >= 0),
        observed_ineligible_count      INTEGER NOT NULL CHECK (observed_ineligible_count >= 0),
        missing_eligible               JSONB NOT NULL,
        missing_eligible_count         INTEGER NOT NULL CHECK (missing_eligible_count >= 0),
        extra                          JSONB NOT NULL,
        extra_count                    INTEGER NOT NULL CHECK (extra_count >= 0),
        absent_ineligible              JSONB NOT NULL,
        absent_ineligible_count        INTEGER NOT NULL CHECK (absent_ineligible_count >= 0),
        recorded_at                    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        PRIMARY KEY (run_id,chunk,session),
        FOREIGN KEY (run_id) REFERENCES feed_ingest_runs(run_id)
            ON DELETE RESTRICT)""",
    """CREATE INDEX IF NOT EXISTS idx_sentinel_seed_coverage_session
        ON sentinel_seed_coverage_evidence (session,run_id)""",
'''
replace_once(
    "sentinel/feed/schema.py",
    '''    """CREATE INDEX IF NOT EXISTS idx_feed_ingest_runs_started
        ON feed_ingest_runs (started_at DESC)""",

    # ACTIONS is delivered as a COMPLETE snapshot''',
    '''    """CREATE INDEX IF NOT EXISTS idx_feed_ingest_runs_started
        ON feed_ingest_runs (started_at DESC)""",
''' + coverage_ddl + '''
    # ACTIONS is delivered as a COMPLETE snapshot''',
)
replace_once(
    "sentinel/feed/schema.py",
    '''    """DROP TRIGGER IF EXISTS sentinel_guard_strategy_row_mutation ON sentinel_ingest_rejections""",
    """CREATE TRIGGER sentinel_guard_strategy_row_mutation
        BEFORE UPDATE OR DELETE ON sentinel_ingest_rejections
        FOR EACH ROW EXECUTE FUNCTION sentinel_guard_strategy_row_mutation()""",
''',
    '''    """DROP TRIGGER IF EXISTS sentinel_guard_strategy_row_mutation ON sentinel_ingest_rejections""",
    """CREATE TRIGGER sentinel_guard_strategy_row_mutation
        BEFORE UPDATE OR DELETE ON sentinel_ingest_rejections
        FOR EACH ROW EXECUTE FUNCTION sentinel_guard_strategy_row_mutation()""",
    """DROP TRIGGER IF EXISTS sentinel_guard_strategy_row_mutation ON sentinel_seed_coverage_evidence""",
    """CREATE TRIGGER sentinel_guard_strategy_row_mutation
        BEFORE UPDATE OR DELETE ON sentinel_seed_coverage_evidence
        FOR EACH ROW EXECUTE FUNCTION sentinel_guard_strategy_row_mutation()""",
''',
)
replace_once(
    "sentinel/feed/schema.py",
    '''    # NO INDEX, deliberately. This is written once and read once, in full: a
    # btree would pay random-I/O maintenance on every insert to save a sort that
    # PostgreSQL does better as one sequential pass and a merge. The (run_id,
    # chunk) scoping is satisfied by the same scan.
''',
    '''    # One practical UNIQUE source key is deliberate. The reusable source
    # membrane proves/collapses duplicates before this table, while the index
    # makes a future bypass fail closed instead of selecting an unjustified
    # last-write-wins row. PostgreSQL still performs the required session/ticker
    # read order as a bounded external sort.
''',
)
replace_once(
    "sentinel/feed/schema.py",
    '''    """ALTER TABLE sentinel_sep_staging
        ADD COLUMN IF NOT EXISTS closeadj DOUBLE PRECISION""",
]''',
    '''    """ALTER TABLE sentinel_sep_staging
        ADD COLUMN IF NOT EXISTS closeadj DOUBLE PRECISION""",
    # Explicit migration is quiesced. Staging is disposable scratch, so clear a
    # possibly interrupted pre-invariant chunk before installing uniqueness.
    """TRUNCATE TABLE sentinel_sep_staging""",
    """CREATE UNIQUE INDEX IF NOT EXISTS uq_sentinel_sep_staging_source_key
        ON sentinel_sep_staging (run_id,chunk,session,ticker)""",
]''',
)


# Runtime schema contract.
replace_once(
    "sentinel/feed/runtime_schema.py",
    '''    "feed_ingest_runs": ("r", "p", False, False, False),
    "sentinel_action_generations":''',
    '''    "feed_ingest_runs": ("r", "p", False, False, False),
    "sentinel_seed_coverage_evidence": ("r", "p", False, False, False),
    "sentinel_action_generations":''',
)
replace_once(
    "sentinel/feed/runtime_schema.py",
    '''    "sentinel_action_generations": {
''',
    '''    "sentinel_seed_coverage_evidence": {
        "run_id": ("uuid", True), "chunk": ("text", True),
        "session": ("date", True),
        "expected_listing_count": ("integer", True),
        "expected_eligible_count": ("integer", True),
        "expected_ineligible_count": ("integer", True),
        "observed_total_count": ("integer", True),
        "observed_expected_count": ("integer", True),
        "observed_ineligible_count": ("integer", True),
        "missing_eligible": ("jsonb", True),
        "missing_eligible_count": ("integer", True),
        "extra": ("jsonb", True), "extra_count": ("integer", True),
        "absent_ineligible": ("jsonb", True),
        "absent_ineligible_count": ("integer", True),
        "recorded_at": ("timestamp with time zone", True),
    },
    "sentinel_action_generations": {
''',
)
replace_once(
    "sentinel/feed/runtime_schema.py",
    '''    "feed_ingest_runs": "primary key (run_id)",
    "sentinel_action_generations":''',
    '''    "feed_ingest_runs": "primary key (run_id)",
    "sentinel_seed_coverage_evidence": "primary key (run_id, chunk, session)",
    "sentinel_action_generations":''',
)
replace_once(
    "sentinel/feed/runtime_schema.py",
    '''    "sentinel_action_generations": (
        ("c", ("source_rows", ">=", "0")),''',
    '''    "sentinel_seed_coverage_evidence": (
        ("f", ("foreign key (run_id)", "feed_ingest_runs", "run_id",
               "on delete restrict")),
        ("c", ("expected_listing_count", ">=", "0")),
        ("c", ("missing_eligible_count", ">=", "0")),
        ("c", ("extra_count", ">=", "0")),
        ("c", ("absent_ineligible_count", ">=", "0")),
    ),
    "sentinel_action_generations": (
        ("c", ("source_rows", ">=", "0")),''',
)
replace_once(
    "sentinel/feed/runtime_schema.py",
    '''    "idx_feed_ingest_runs_started": False,
    "idx_sentinel_action_obs_written_by":''',
    '''    "idx_feed_ingest_runs_started": False,
    "idx_sentinel_seed_coverage_session": False,
    "uq_sentinel_sep_staging_source_key": True,
    "idx_sentinel_action_obs_written_by":''',
)
replace_once(
    "sentinel/feed/runtime_schema.py",
    '''    "idx_sentinel_action_obs_written_by": ("(last_written_run_id)",),
''',
    '''    "idx_sentinel_seed_coverage_session": ("(session, run_id)",),
    "uq_sentinel_sep_staging_source_key": (
        "on public.sentinel_sep_staging", "(run_id, chunk, session, ticker)"),
    "idx_sentinel_action_obs_written_by": ("(last_written_run_id)",),
''',
)
replace_once(
    "sentinel/feed/runtime_schema.py",
    '''            "sentinel_ingest_rejections",
        )
''',
    '''            "sentinel_ingest_rejections",
            "sentinel_seed_coverage_evidence",
        )
''',
)


# ---------------------------------------------------------------------------
# Persist exact coverage evidence at run/session grain.
# ---------------------------------------------------------------------------
seed_writer = r'''
def write_seed_coverage_evidence(conn, *, run_id, chunk: str,
                                 evidence: Iterable[dict]) -> int:
    """Persist and re-read exact seed membership evidence before continuing."""
    _assert_corpus_locked(conn)
    writer = str(run_id)
    label = str(chunk)
    payload: list[tuple] = []
    seen_sessions: set[str] = set()
    for raw in evidence:
        row = dict(raw)
        session = str(row.get("session") or "")
        try:
            parsed = dt.date.fromisoformat(session)
        except ValueError as exc:
            raise ValueError(f"seed coverage has invalid session {session!r}") from exc
        if parsed.isoformat() != session or session in seen_sessions:
            raise ValueError(
                f"seed coverage session is non-canonical or duplicated: {session!r}")
        seen_sessions.add(session)
        lists = {}
        for key in ("missing_eligible", "extra", "absent_ineligible"):
            value = row.get(key)
            if not isinstance(value, list):
                raise ValueError(f"seed coverage {session} {key} is not a list")
            normalized = sorted({str(item).strip().upper() for item in value
                                 if str(item).strip()})
            if normalized != value:
                raise ValueError(
                    f"seed coverage {session} {key} is not sorted/unique/canonical")
            lists[key] = normalized
        counts = {key: int(row[key]) for key in (
            "expected_listing_count", "expected_eligible_count",
            "expected_ineligible_count", "observed_total_count",
            "observed_expected_count", "observed_ineligible_count",
            "missing_eligible_count", "extra_count",
            "absent_ineligible_count")}
        if any(value < 0 for value in counts.values()):
            raise ValueError(f"seed coverage {session} contains a negative count")
        if counts["expected_listing_count"] != (
                counts["expected_eligible_count"]
                + counts["expected_ineligible_count"]):
            raise ValueError(f"seed coverage {session} expected counts disagree")
        if counts["missing_eligible_count"] != len(lists["missing_eligible"]):
            raise ValueError(f"seed coverage {session} missing count disagrees")
        if counts["extra_count"] != len(lists["extra"]):
            raise ValueError(f"seed coverage {session} extra count disagrees")
        if counts["absent_ineligible_count"] != len(lists["absent_ineligible"]):
            raise ValueError(f"seed coverage {session} ineligible count disagrees")
        if (counts["observed_ineligible_count"]
                + counts["absent_ineligible_count"]
                != counts["expected_ineligible_count"]):
            raise ValueError(
                f"seed coverage {session} ineligible accounting is incomplete")
        if counts["observed_total_count"] != (
                counts["observed_expected_count"]
                + counts["observed_ineligible_count"] + counts["extra_count"]):
            raise ValueError(f"seed coverage {session} observed counts disagree")
        payload.append((
            writer, label, session,
            counts["expected_listing_count"], counts["expected_eligible_count"],
            counts["expected_ineligible_count"], counts["observed_total_count"],
            counts["observed_expected_count"], counts["observed_ineligible_count"],
            json.dumps(lists["missing_eligible"], separators=(",", ":")),
            counts["missing_eligible_count"],
            json.dumps(lists["extra"], separators=(",", ":")),
            counts["extra_count"],
            json.dumps(lists["absent_ineligible"], separators=(",", ":")),
            counts["absent_ineligible_count"]))
    if not payload:
        return 0
    sql = (
        "INSERT INTO sentinel_seed_coverage_evidence"
        " (run_id,chunk,session,expected_listing_count,expected_eligible_count,"
        "  expected_ineligible_count,observed_total_count,"
        "  observed_expected_count,observed_ineligible_count,missing_eligible,"
        "  missing_eligible_count,extra,extra_count,absent_ineligible,"
        "  absent_ineligible_count)"
        " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s::jsonb,%s,"
        "         %s::jsonb,%s)"
        " ON CONFLICT (run_id,chunk,session) DO NOTHING")
    try:
        with conn.cursor() as cur:
            cur.executemany(sql, payload)
            cur.execute(
                "SELECT run_id::text,chunk,session::text,expected_listing_count,"
                " expected_eligible_count,expected_ineligible_count,"
                " observed_total_count,observed_expected_count,"
                " observed_ineligible_count,missing_eligible,"
                " missing_eligible_count,extra,extra_count,absent_ineligible,"
                " absent_ineligible_count"
                " FROM sentinel_seed_coverage_evidence"
                " WHERE run_id=%s AND chunk=%s ORDER BY session",
                (writer, label))
            actual = list(cur.fetchall())
        expected = [
            tuple(item[:9])
            + (json.loads(item[9]), item[10], json.loads(item[11]), item[12],
               json.loads(item[13]), item[14])
            for item in payload]
        if actual != expected:
            raise ValueError(
                f"seed coverage evidence for run {writer}/{label} conflicts "
                "with an existing candidate observation")
        conn.commit()
        return len(payload)
    except BaseException:
        conn.rollback()
        raise
'''
replace_once(
    "sentinel/feed/store.py",
    "\ndef write_rejections(conn, rejections, *, run_id=None) -> int:\n",
    "\n" + seed_writer + "\n\ndef write_rejections(conn, rejections, *, run_id=None) -> int:\n",
)


# ---------------------------------------------------------------------------
# Seed path persists evidence and closes the multi-year source-generation race.
# ---------------------------------------------------------------------------
replace_once(
    "sentinel/feed/ingest_impl.py",
    "from sentinel.feed import domains, sharadar, universe\n",
    "from sentinel.feed import coherence, domains, sharadar, universe\n",
)
seed_helpers = r'''
def _pop_seed_coverage(fetch) -> list[dict] | None:
    pop = getattr(fetch, "pop_seed_coverage_evidence", None)
    return None if pop is None else list(pop())


def _persist_seed_coverage(conn, run, fetch, chunk: str, *, fallback=()) -> None:
    evidence = _pop_seed_coverage(fetch)
    if evidence is None:
        return
    if not evidence:
        evidence = list(fallback)
    if not evidence:
        raise coherence.SeedHistoryIncomplete(
            f"seed chunk {chunk} completed without exact TICKERS coverage evidence")
    feed_store.write_seed_coverage_evidence(
        conn, run_id=run.progress.run_id, chunk=chunk, evidence=evidence)
'''
replace_once(
    "sentinel/feed/ingest_impl.py",
    "\ndef _write_sfp_reference_rows(conn, rows: Iterable[dict], *, run_id) -> int:\n",
    "\n" + seed_helpers + "\n\ndef _write_sfp_reference_rows(conn, rows: Iterable[dict], *, run_id) -> int:\n",
)
old_loop = '''    for lo, hi in chunks:
        with run.chunk(lo[:4]):
            report = domains.NormalisationReport()
            # ACTIONS IS AUTHORITATIVE for splits and dividends, and this call
            # site is the defect being fixed: ACTIONS was fetched, stored and
            # then NOT passed here, so every dividend was 0.0 and every split
            # ratio came from price-domain inference. A genuine 3:2 is 1.5,
            # equidistant from the 1 and 2 the derived ratio snaps to, and S5
            # made that error matter by preserving fractional entitlement.
            splits, divs, action_rows, ambiguous_splits = _action_maps(
                conn, lo, hi, include_run_id=run.progress.run_id)
            # THE PREVIOUS OBSERVATION OF EACH SECURITY, from the corpus. Read
            # BEFORE this chunk writes anything, so it is strictly the state as
            # of the moment before the window opens. Without it the first bar of
            # every year derived "no split" — see store.previous_observations.
            bars = domains.normalise_sep_rows(
                _ordered_sep(conn,
                             fetch(sharadar.SEP, sharadar.date_params(lo, hi)),
                             run_id=run.progress.run_id, chunk=lo[:4]),
                resolve_identity=resolver,
                authoritative_splits=splits, dividends=divs,
                prior_observations=feed_store.previous_observations(conn, lo),
                report=report)
            written = feed_store.write_bars(
                conn, bars, run_id=run.progress.run_id, require_lock=True)
            # PERSIST THE EVIDENCE in the same breath as the bars. A refusal,
            # a truncation or an anomaly recorded only in memory dies with the
            # process, and the certification that needs it runs in a different
            # one, hours later.
            _persist_chunk_evidence(conn, run, lo[:4], lo, hi, report, splits,
                                    action_rows, action_rows, ambiguous_splits)
            run.progress.rows_written += written
            run.progress.rows_dropped += (report.dropped_no_raw_close
                                          + report.dropped_no_identity)
'''
new_loop = '''    for lo, hi in chunks:
        with run.chunk(lo[:4]):
            report = domains.NormalisationReport()
            try:
                # ACTIONS IS AUTHORITATIVE for splits and dividends, and this call
                # site is the defect being fixed: ACTIONS was fetched, stored and
                # then NOT passed here, so every dividend was 0.0 and every split
                # ratio came from price-domain inference. A genuine 3:2 is 1.5,
                # equidistant from the 1 and 2 the derived ratio snaps to, and S5
                # made that error matter by preserving fractional entitlement.
                splits, divs, action_rows, ambiguous_splits = _action_maps(
                    conn, lo, hi, include_run_id=run.progress.run_id)
                # THE PREVIOUS OBSERVATION OF EACH SECURITY, from the corpus. Read
                # BEFORE this chunk writes anything, so it is strictly the state as
                # of the moment before the window opens. Without it the first bar of
                # every year derived "no split" — see store.previous_observations.
                bars = domains.normalise_sep_rows(
                    _ordered_sep(conn,
                                 fetch(sharadar.SEP, sharadar.date_params(lo, hi)),
                                 run_id=run.progress.run_id, chunk=lo[:4]),
                    resolve_identity=resolver,
                    authoritative_splits=splits, dividends=divs,
                    prior_observations=feed_store.previous_observations(conn, lo),
                    report=report)
                written = feed_store.write_bars(
                    conn, bars, run_id=run.progress.run_id, require_lock=True)
                # PERSIST THE EVIDENCE in the same breath as the bars. A refusal,
                # a truncation or an anomaly recorded only in memory dies with the
                # process, and the certification that needs it runs in a different
                # one, hours later.
                _persist_chunk_evidence(
                    conn, run, lo[:4], lo, hi, report, splits,
                    action_rows, action_rows, ambiguous_splits)
                _persist_seed_coverage(conn, run, fetch, lo[:4])
                run.progress.rows_written += written
                run.progress.rows_dropped += (report.dropped_no_raw_close
                                              + report.dropped_no_identity)
            except coherence.SeedHistoryIncomplete as exc:
                _persist_seed_coverage(
                    conn, run, fetch, lo[:4],
                    fallback=getattr(exc, "coverage_evidence", ()))
                raise
'''
replace_once("sentinel/feed/ingest_impl.py", old_loop, new_loop)

replace_once(
    "sentinel/feed/ingest.py",
    '''        if tracked.max_sep_lastupdated is None:
            raise maintenance.MutationCursorUnavailable(
                "complete seed published but exposed no SEP lastupdated value; "
                "refusing to invent a mutation watermark")
        maintenance.establish_sep_cursor_after_seed(
            conn, through=tracked.max_sep_lastupdated,
            publication_version=published.version)
''',
    '''        if tracked.max_sep_lastupdated is None:
            raise maintenance.MutationCursorUnavailable(
                "complete seed published but exposed no SEP lastupdated value; "
                "refusing to invent a mutation watermark")
        # The annual seed observations do not share a vendor generation token.
        # Re-read every published year through the same stable/envelope membrane
        # and prove exact normalized key+value overlap before a CDC watermark can
        # suppress any historical update interval.
        overlap = sep_reconciliation.reconcile_all(
            conn, fetch=fetch, through=seed_to)
        watermarks = [item.max_lastupdated for item in overlap
                      if item.max_lastupdated is not None]
        if not overlap or not watermarks:
            raise maintenance.MutationCursorUnavailable(
                "post-seed complete overlap reconciliation exposed no bounded "
                "SEP lastupdated authority; CDC cursor remains unestablished")
        watermark = max(watermarks)
        if watermark > _dt.date.fromisoformat(seed_to):
            raise maintenance.MutationCursorUnavailable(
                f"post-seed SEP watermark {watermark} exceeds observation "
                f"boundary {seed_to}")
        maintenance.establish_sep_cursor_after_complete_reconciliation(
            conn, through=watermark,
            publication_version=published.version)
''',
)

# Every public daily call is explicit; CLI and automation resolve the closed
# XNYS session before entering this authority boundary.
replace_once(
    "sentinel/feed/ingest.py",
    '''def daily(conn, *, fetch: Callable[..., Iterable[dict]] = sharadar.fetch_table,
          resolve_identity=None, overlap_days: int = _impl.DAILY_OVERLAP_DAYS,
          today: Optional[str] = None):
    fetch = _authoritative_source(fetch)
    _validate_source_before_run(fetch)
    resolved_today = today or _today()
''',
    '''def daily(conn, *, fetch: Callable[..., Iterable[dict]] = sharadar.fetch_table,
          resolve_identity=None, overlap_days: int = _impl.DAILY_OVERLAP_DAYS,
          today: Optional[str] = None):
    if today is None:
        raise ValueError(
            "daily ingress requires an explicit closed XNYS decision session")
    fetch = _authoritative_source(fetch)
    _validate_source_before_run(fetch)
    resolved_today = str(today)
    try:
        from sentinel.feed import calendar
        calendar.session_window(resolved_today)
    except Exception as exc:
        raise ValueError(
            f"daily ingress boundary {resolved_today!r} is not an XNYS session") from exc
''',
)


# Complete SEP overlap/reconciliation carries the same observation boundary into
# each protected source traversal.
replace_once(
    "sentinel/feed/sep_reconciliation.py",
    '''def _source_fingerprint(conn, *, fetch, start: str, end: str) -> _PartitionProof:
    """Stable vendor partition -> normalized key/value commitments + update clock."""
    stable = authority.StableSharadarFetch(fetch, after_session=end)
''',
    '''def _source_fingerprint(conn, *, fetch, start: str, end: str,
                        observation_through: str | dt.date | None = None
                        ) -> _PartitionProof:
    """Stable vendor partition -> normalized key/value commitments + update clock."""
    stable = authority.StableSharadarFetch(
        fetch, after_session=end, observation_through=observation_through)
''',
)
replace_once(
    "sentinel/feed/sep_reconciliation.py",
    '''def reconcile_year(conn, *, fetch=sharadar.fetch_table,
                   year: int, start: str, end: str) -> ReconciliationResult:
''',
    '''def reconcile_year(conn, *, fetch=sharadar.fetch_table,
                   year: int, start: str, end: str,
                   observation_through: str | dt.date | None = None
                   ) -> ReconciliationResult:
''',
)
replace_once(
    "sentinel/feed/sep_reconciliation.py",
    '''    source = _source_fingerprint(conn, fetch=fetch, start=start, end=end)
''',
    '''    source = _source_fingerprint(
        conn, fetch=fetch, start=start, end=end,
        observation_through=observation_through)
''',
)
replace_once(
    "sentinel/feed/sep_reconciliation.py",
    '''        result = reconcile_year(
            conn, fetch=fetch, year=year,
            start=start.isoformat(), end=end.isoformat())
''',
    '''        result = reconcile_year(
            conn, fetch=fetch, year=year,
            start=start.isoformat(), end=end.isoformat(),
            observation_through=checked_on)
''',
)
# reconcile_next has the same call once more.
replace_once(
    "sentinel/feed/sep_reconciliation.py",
    '''        result = reconcile_year(
            conn, fetch=fetch, year=year,
            start=start.isoformat(), end=end.isoformat())
''',
    '''        result = reconcile_year(
            conn, fetch=fetch, year=year,
            start=start.isoformat(), end=end.isoformat(),
            observation_through=checked_on)
''',
)


# ---------------------------------------------------------------------------
# Regression additions.
# ---------------------------------------------------------------------------
path = Path("tests/sentinel/test_issue_250_source_authority.py")
text = path.read_text()
text += textwrap.dedent(r'''


def test_late_conflicting_duplicate_refuses_before_first_replay_row():
    params = {"date.gte": "2026-08-24", "date.lte": "2026-08-24"}
    replay = source_validation.validated_market_rows(
        "SEP", [_bar(), _bar(close=99)], params)
    with pytest.raises(source_validation.ConflictingSourceDuplicate):
        next(replay)


def test_seed_evidence_accounts_exact_absent_ineligible_set():
    expected = (
        coherence.SeedExpectedListing("AAA", "2026-08-24", "2026-08-24", True),
        coherence.SeedExpectedListing("UNIT", "2026-08-24", "2026-08-24", False),
    )
    evidence = coherence.assert_seed_listing_coverage(
        {"2026-08-24": {"AAA"}}, expected,
        date_from="2026-08-24", date_to="2026-08-24")
    assert evidence == [{
        "session": "2026-08-24",
        "expected_listing_count": 2,
        "expected_eligible_count": 1,
        "expected_ineligible_count": 1,
        "observed_total_count": 1,
        "observed_expected_count": 1,
        "observed_ineligible_count": 0,
        "missing_eligible": [],
        "missing_eligible_count": 0,
        "extra": [],
        "extra_count": 0,
        "absent_ineligible": ["UNIT"],
        "absent_ineligible_count": 1,
    }]
''')
path.write_text(text)

Path("tests/sentinel/test_issue_250_seed_evidence.py").write_text(
    textwrap.dedent(r'''
    """Durable seed coverage and staging uniqueness regressions for #250."""
    from __future__ import annotations

    import uuid

    import pytest

    from sentinel.feed import store


    def _run(conn):
        run_id = str(uuid.uuid4())
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO feed_ingest_runs"
                " (run_id,kind,status,source_git_commit,runtime_image_digest)"
                " VALUES (%s,'seed','running',%s,%s)",
                (run_id, "a" * 40, "sha256:" + "b" * 64))
        conn.commit()
        return run_id


    def _evidence():
        return [{
            "session": "2026-08-24",
            "expected_listing_count": 2,
            "expected_eligible_count": 1,
            "expected_ineligible_count": 1,
            "observed_total_count": 1,
            "observed_expected_count": 1,
            "observed_ineligible_count": 0,
            "missing_eligible": [], "missing_eligible_count": 0,
            "extra": [], "extra_count": 0,
            "absent_ineligible": ["UNIT"], "absent_ineligible_count": 1,
        }]


    def test_seed_coverage_is_exact_durable_run_evidence(conn):
        run_id = _run(conn)
        with store.corpus_write_lock(conn):
            assert store.write_seed_coverage_evidence(
                conn, run_id=run_id, chunk="2026", evidence=_evidence()) == 1
            assert store.write_seed_coverage_evidence(
                conn, run_id=run_id, chunk="2026", evidence=_evidence()) == 1
        with conn.cursor() as cur:
            cur.execute(
                "SELECT missing_eligible,extra,absent_ineligible,"
                " expected_eligible_count,expected_ineligible_count"
                " FROM sentinel_seed_coverage_evidence WHERE run_id=%s",
                (run_id,))
            row = cur.fetchone()
        assert row == ([], [], ["UNIT"], 1, 1)


    def test_seed_coverage_conflicting_retry_refuses(conn):
        run_id = _run(conn)
        with store.corpus_write_lock(conn):
            store.write_seed_coverage_evidence(
                conn, run_id=run_id, chunk="2026", evidence=_evidence())
            changed = _evidence()
            changed[0]["absent_ineligible"] = ["OTHER"]
            with pytest.raises(ValueError, match="conflicts"):
                store.write_seed_coverage_evidence(
                    conn, run_id=run_id, chunk="2026", evidence=changed)


    def test_staging_source_key_is_unique(conn):
        run_id = str(uuid.uuid4())
        row = (run_id, "2026", "2026-08-24", "AAA", 1, 1, 1, 1, 1)
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO sentinel_sep_staging"
                " (run_id,chunk,session,ticker,open,close,closeunadj,closeadj,volume)"
                " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)", row)
        conn.commit()
        with pytest.raises(Exception):
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO sentinel_sep_staging"
                    " (run_id,chunk,session,ticker,open,close,closeunadj,closeadj,volume)"
                    " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)", row)
        conn.rollback()
    ''').lstrip())
