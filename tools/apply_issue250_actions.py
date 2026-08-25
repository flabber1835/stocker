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
# External-spill snapshot correctness and CSV membrane.
# ---------------------------------------------------------------------------
path = Path("sentinel/feed/action_snapshot.py")
text = path.read_text()
text = text.replace("import csv\n", "import csv\nfrom contextlib import closing\n", 1)
count = text.count("with self._connect() as conn:")
if count < 8:
    raise RuntimeError(f"action_snapshot: expected >=8 connection contexts, found {count}")
text = text.replace("with self._connect() as conn:",
                    "with closing(self._connect()) as conn:")
old_reader = '''                    reader = csv.DictReader(text)
                    fields = set(reader.fieldnames or ())
                    missing = sorted(set(required_columns) - fields)
                    if missing:
                        raise ActionSnapshotError(
                            "complete ACTIONS export lacks required column(s): "
                            + ", ".join(missing))

                    def rows() -> Iterator[dict]:
                        for row in reader:
                            yield {
                                key: (None if value == "" else value)
                                for key, value in row.items()
                            }
'''
new_reader = '''                    reader = csv.DictReader(text)
                    fields = list(reader.fieldnames or ())
                    if (len(fields) != len(set(fields))
                            or any(not str(field).strip() for field in fields)):
                        raise ActionSnapshotError(
                            "complete ACTIONS export has invalid/duplicate columns")
                    missing = sorted(set(required_columns) - set(fields))
                    if missing:
                        raise ActionSnapshotError(
                            "complete ACTIONS export lacks required column(s): "
                            + ", ".join(missing))

                    def rows() -> Iterator[dict]:
                        for row in reader:
                            if None in row:
                                raise ActionSnapshotError(
                                    "complete ACTIONS export row is wider than its header")
                            yield {
                                key: (None if value == "" else value)
                                for key, value in row.items()
                            }
'''
if text.count(old_reader) != 2:
    raise RuntimeError(
        f"action_snapshot: expected two CSV reader blocks, found {text.count(old_reader)}")
text = text.replace(old_reader, new_reader)
path.write_text(text)


# ---------------------------------------------------------------------------
# Complete exporter returns ACTIONS as a disk-backed generation, not list[dict].
# ---------------------------------------------------------------------------
replace_once(
    "sentinel/feed/snapshot_export.py",
    "from sentinel.feed import sharadar\n",
    "from sentinel.feed import action_snapshot, sharadar\n",
)
replace_once(
    "sentinel/feed/snapshot_export.py",
    "        max_polls: int | None = None) -> tuple[list[dict], dict]:\n",
    "        max_polls: int | None = None) -> tuple[object, dict]:\n",
)
replace_once(
    "sentinel/feed/snapshot_export.py",
    '''                blob = _safe_download(
                    client, link, http=http, sleep=sleep, now=now)
                rows = _csv_rows(blob, required=required)
                return rows, {
                    "authority": "nasdaq-data-link-table-export/v1",
                    "table": table,
                    "file_status": status,
                    "data_snapshot_time": snapshot.isoformat(),
                    "last_refreshed_time": refreshed.isoformat(),
                    "source_rows": len(rows),
                }
''',
    '''                blob = _safe_download(
                    client, link, http=http, sleep=sleep, now=now)
                evidence = {
                    "authority": "nasdaq-data-link-table-export/v1",
                    "table": table,
                    "file_status": status,
                    "data_snapshot_time": snapshot.isoformat(),
                    "last_refreshed_time": refreshed.isoformat(),
                }
                if table == sharadar.ACTIONS:
                    try:
                        rows = action_snapshot.ActionSnapshot.from_zip_bytes(
                            blob, required_columns=required)
                    except action_snapshot.ActionSnapshotError as exc:
                        raise SharadarSnapshotExportError(str(exc)) from exc
                    evidence.update({
                        "source_rows": rows.source_rows,
                        "distinct_source_rows": len(rows),
                        "exact_repeat_rows": rows.exact_repeat_rows,
                    })
                    return rows, evidence
                rows = _csv_rows(blob, required=required)
                evidence["source_rows"] = len(rows)
                return rows, evidence
''',
)
replace_once(
    "sentinel/feed/snapshot_export.py",
    "def fetch_complete_actions(*, through: str, **kwargs) -> tuple[list[dict], dict]:\n",
    "def fetch_complete_actions(\n        *, through: str, **kwargs\n        ) -> tuple[action_snapshot.ActionSnapshot, dict]:\n",
)


# ---------------------------------------------------------------------------
# Ordinary seed ACTIONS stability uses two external-spill observations.
# ---------------------------------------------------------------------------
replace_once(
    "sentinel/feed/authority.py",
    "from sentinel.feed import action_source, source_validation\n",
    "from sentinel.feed import action_snapshot, action_source, source_validation\n",
)
replace_once(
    "sentinel/feed/authority.py",
    "        self._actions_first: SourceObservation | None = None\n"
    "        self._actions_params: dict | None = None\n",
    "        self._actions_first: SourceObservation | None = None\n"
    "        self._actions_snapshot: action_snapshot.ActionSnapshot | None = None\n"
    "        self._actions_params: dict | None = None\n",
)
replace_once(
    "sentinel/feed/authority.py",
    '''            rows = list(self._fetch(table, params, **kwargs))
            self._actions_first = observe_actions(rows)
            self._actions_params = dict(params or {})
            self._actions_kwargs = dict(kwargs)
            return rows
''',
    '''            rows = action_snapshot.ActionSnapshot.from_rows(
                self._fetch(table, params, **kwargs))
            self._actions_first = observe_actions(rows)
            self._actions_snapshot = rows
            self._actions_params = dict(params or {})
            self._actions_kwargs = dict(kwargs)
            return rows
''',
)
replace_once(
    "sentinel/feed/authority.py",
    '''        rows = list(self._fetch(
            sharadar.ACTIONS,
            dict(self._actions_params or {}),
            **dict(self._actions_kwargs or {})))
        second = observe_actions(rows)
        require_stable(sharadar.ACTIONS, self._actions_first, second)
        self._actions_first = None
        self._actions_params = None
        self._actions_kwargs = None
''',
    '''        first_snapshot = self._actions_snapshot
        try:
            with action_snapshot.ActionSnapshot.from_rows(self._fetch(
                    sharadar.ACTIONS,
                    dict(self._actions_params or {}),
                    **dict(self._actions_kwargs or {}))) as rows:
                second = observe_actions(rows)
                require_stable(sharadar.ACTIONS, self._actions_first, second)
        finally:
            if first_snapshot is not None:
                first_snapshot.close()
            self._actions_first = None
            self._actions_snapshot = None
            self._actions_params = None
            self._actions_kwargs = None
''',
)


# ---------------------------------------------------------------------------
# PostgreSQL ACTIONS publication is a SQL set operation over a bounded batch.
# ---------------------------------------------------------------------------
replace_once(
    "sentinel/feed/store.py",
    "import json\nimport math\n",
    "import datetime as dt\nimport json\nimport math\n",
)
new_write_actions = r'''
def write_actions(conn, rows: Iterable[Any], *, run_id=None,
                  window_start: str | None = None,
                  window_end: str | None = None,
                  batch_size: int = 5_000) -> int:
    """Persist one COMPLETE corporate-action source snapshot.

    Production writes never construct a whole-export identity map, published
    baseline, or observation list in Python. Canonical rows enter a temporary
    PostgreSQL candidate relation in bounded batches. SQL set operations then
    emit PRESENT rows and published-baseline negative space as REMOVED rows.
    Exact seven-column repeats collapse; legitimate siblings remain distinct.
    """
    if batch_size < 1:
        raise ValueError("ACTIONS write batch_size must be positive")
    if run_id is None:
        payload: list[tuple] = []
        written = 0

        def flush_legacy() -> None:
            nonlocal written
            if not payload:
                return
            with conn.cursor() as cur:
                cur.executemany(_ACTION_UPSERT, payload)
            conn.commit()
            written += len(payload)
            payload.clear()

        for row in rows:
            payload.append((
                row["ticker"], row["date"], row["action"], row.get("value"),
                row.get("contraticker"), None))
            if len(payload) >= batch_size:
                flush_legacy()
        flush_legacy()
        return written

    _assert_corpus_locked(conn)
    if window_start is None or window_end is None:
        raise ValueError(
            "a run-stamped ACTIONS write must name the complete fetched window")
    try:
        lo_date = dt.date.fromisoformat(str(window_start))
        hi_date = dt.date.fromisoformat(str(window_end))
    except ValueError as exc:
        raise ValueError("ACTIONS window bounds must be ISO dates") from exc
    lo, hi = lo_date.isoformat(), hi_date.isoformat()
    if lo_date > hi_date:
        raise ValueError(f"reversed ACTIONS window: {lo} > {hi}")
    writer = str(run_id)

    from sentinel.feed import action_source

    candidate = "feed_action_candidate"
    create_candidate = f"""
        CREATE TEMP TABLE IF NOT EXISTS {candidate} (
          source_row_id TEXT NOT NULL,
          source_payload TEXT NOT NULL,
          ticker TEXT NOT NULL,
          session DATE NOT NULL,
          action TEXT NOT NULL,
          name TEXT,
          value TEXT,
          contraticker TEXT,
          contraname TEXT,
          PRIMARY KEY (source_row_id,source_payload)
        ) ON COMMIT PRESERVE ROWS
    """
    insert_candidate = f"""
        INSERT INTO {candidate}
          (source_row_id,source_payload,ticker,session,action,name,value,
           contraticker,contraname)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (source_row_id,source_payload) DO NOTHING
    """
    with conn.cursor() as cur:
        cur.execute(create_candidate)
        cur.execute(f"TRUNCATE TABLE {candidate}")
    conn.commit()

    pending: list[tuple] = []

    def flush_candidate() -> None:
        if not pending:
            return
        with conn.cursor() as cur:
            cur.executemany(insert_candidate, pending)
        conn.commit()
        pending.clear()

    try:
        for raw in rows:
            row = dict(raw)
            payload = action_source.canonical_payload(row)
            identity = action_source.source_row_id(payload)
            ticker = str(payload.get("ticker") or "").strip()
            session = str(payload.get("date") or "").strip()
            action = str(payload.get("action") or "").strip()
            if not ticker or not session or not action:
                raise ValueError("ACTIONS row lacks ticker, date, or action")
            try:
                observed = dt.date.fromisoformat(session)
            except ValueError as exc:
                raise ValueError(
                    f"ACTIONS row {ticker}/{session}/{action} has invalid date") from exc
            if observed.isoformat() != session:
                raise ValueError(
                    f"ACTIONS row {ticker}/{session}/{action} has non-canonical date")
            if not lo_date <= observed <= hi_date:
                raise ValueError(
                    f"ACTIONS row {ticker}/{session}/{action} lies outside the "
                    f"declared complete window [{lo}, {hi}]")
            pending.append((
                identity, action_source.payload_bytes(payload).decode("utf-8"),
                ticker, session, action, payload.get("name"),
                payload.get("value"), payload.get("contraticker"),
                payload.get("contraname")))
            if len(pending) >= batch_size:
                flush_candidate()
        flush_candidate()

        with conn.cursor() as cur:
            cur.execute(
                f"SELECT source_row_id,COUNT(*) FROM {candidate}"
                " GROUP BY source_row_id HAVING COUNT(*)>1 LIMIT 1")
            collision = cur.fetchone()
            if collision is not None:
                raise ValueError(
                    "ACTIONS source-row identity collision for "
                    f"{collision[0]}")
            cur.execute(f"SELECT COUNT(*) FROM {candidate}")
            source_rows = int(cur.fetchone()[0])

            cur.execute(
                "INSERT INTO sentinel_action_generations"
                " (last_written_run_id,window_start,window_end,source_rows)"
                " VALUES (%s,%s,%s,%s)"
                " ON CONFLICT (last_written_run_id) DO NOTHING",
                (writer, lo, hi, source_rows))
            cur.execute(
                "SELECT window_start,window_end,source_rows"
                " FROM sentinel_action_generations"
                " WHERE last_written_run_id=%s", (writer,))
            recorded = cur.fetchone()
            if recorded is None or (
                    str(recorded[0]), str(recorded[1]), int(recorded[2])) != (
                        lo, hi, source_rows):
                raise ValueError(
                    f"ACTIONS generation {writer} was already recorded with a "
                    "different complete-window contract")

            cur.execute(f"""
                INSERT INTO sentinel_action_observations
                  (source_row_id,source_payload,ticker,session,action,name,value,
                   contraticker,contraname,disposition,last_written_run_id)
                SELECT c.source_row_id,c.source_payload::jsonb,c.ticker,c.session,
                       c.action,c.name,c.value,c.contraticker,c.contraname,
                       'PRESENT',%s
                FROM {candidate} c
                ON CONFLICT (last_written_run_id,source_row_id) DO NOTHING
            """, (writer,))
            cur.execute(f"""
                INSERT INTO sentinel_action_observations
                  (source_row_id,source_payload,ticker,session,action,name,value,
                   contraticker,contraname,disposition,last_written_run_id)
                SELECT a.source_row_id,a.source_payload,a.ticker,a.session,a.action,
                       a.name,a.value,a.contraticker,a.contraname,'REMOVED',%s
                FROM sentinel_active_actions a
                LEFT JOIN {candidate} c
                  ON c.source_row_id=a.source_row_id
                WHERE a.session BETWEEN %s AND %s
                  AND c.source_row_id IS NULL
                ON CONFLICT (last_written_run_id,source_row_id) DO NOTHING
            """, (writer, lo, hi))

        from sentinel.feed import actions as action_store
        action_store.record_pending(conn, run_id=writer)
        with conn.cursor() as cur:
            cur.execute(f"DROP TABLE {candidate}")
        conn.commit()
        return source_rows
    except BaseException:
        conn.rollback()
        try:
            with conn.cursor() as cur:
                cur.execute(f"DROP TABLE IF EXISTS {candidate}")
            conn.commit()
        except Exception:
            conn.rollback()
        raise
'''
replace_between(
    "sentinel/feed/store.py",
    "def write_actions(",
    "def write_rejections(",
    new_write_actions,
)


# ---------------------------------------------------------------------------
# Complete reconciliation compares current/prior generations in external spill.
# ---------------------------------------------------------------------------
replace_once(
    "sentinel/feed/maintenance.py",
    "import os\n",
    "import os\nimport uuid\n",
)
replace_once(
    "sentinel/feed/maintenance.py",
    "    action_source, anomalies, authority, calendar, publication, recovery,\n",
    "    action_snapshot, action_source, anomalies, authority, calendar, publication, recovery,\n",
)
stream_helper = r'''
def _iter_active_action_rows(conn) -> Iterable[dict]:
    """Stream the published ACTIONS generation without a client-side result set."""
    name = f"sentinel_actions_{uuid.uuid4().hex}"
    try:
        cursor = conn.cursor(name=name)
    except TypeError:  # deterministic lightweight test doubles
        cursor = conn.cursor()
    with cursor as cur:
        if hasattr(cur, "itersize"):
            cur.itersize = 5_000
        cur.execute(
            "SELECT source_row_id,source_payload,ticker,session,action,name,value,"
            " contraticker,contraname FROM sentinel_active_actions"
            " ORDER BY source_row_id")
        while True:
            batch = cur.fetchmany(2_000)
            if not batch:
                return
            for (identity, payload, ticker, session, action, name, value,
                 contraticker, contraname) in batch:
                yield {
                    "source_row_id": str(identity),
                    "source_payload": payload,
                    "ticker": str(ticker),
                    "date": str(session),
                    "action": str(action),
                    "name": name,
                    "value": value,
                    "contraticker": contraticker,
                    "contraname": contraname,
                }
'''
replace_once(
    "sentinel/feed/maintenance.py",
    "\ndef _bar_affecting_action(row: Mapping) -> bool:\n",
    "\n" + stream_helper + "\n\ndef _bar_affecting_action(row: Mapping) -> bool:\n",
)
new_reconcile = r'''
def reconcile_actions_if_due(conn, *, fetch=sharadar.fetch_table,
                             through: str, force: bool = False
                             ) -> Optional[SourceCursor]:
    """Reconcile complete ACTIONS with bounded memory and exact negative space."""
    store._assert_corpus_locked(conn)
    if ACTIONS_RECONCILE_DAYS < 1:
        raise ValueError("SHARADAR_ACTIONS_RECONCILE_DAYS must be >= 1")
    hi = dt.date.fromisoformat(str(through))
    prior_cursor = load_actions_cursor(conn)
    if (not force and prior_cursor is not None
            and (hi - prior_cursor.processed_through).days < ACTIONS_RECONCILE_DAYS):
        return prior_cursor

    params = sharadar.date_params(ACTIONS_FULL_WINDOW_START, hi.isoformat())
    if fetch is sharadar.fetch_table:
        snapshot, source_evidence = snapshot_export.fetch_complete_actions(
            through=hi.isoformat())
    else:
        stable = _stable_rows(fetch, sharadar.ACTIONS, params)
        snapshot = action_snapshot.ActionSnapshot.from_rows(stable)
        del stable
        source_evidence = {
            "authority": "injected-double-observation/v1",
            "source_rows": snapshot.source_rows,
            "distinct_source_rows": len(snapshot),
            "exact_repeat_rows": snapshot.exact_repeat_rows,
        }

    with snapshot:
        _validate_action_snapshot_window(snapshot, hi=hi)
        if not snapshot:
            raise SharadarMutationRefused(
                "complete Sharadar ACTIONS reconciliation returned zero rows; "
                "refusing to turn a suspicious empty source into mass removals")

        prior_count = snapshot.load_prior_rows(_iter_active_action_rows(conn))
        if prior_count and len(snapshot) < int(prior_count * 0.90):
            raise SharadarMutationRefused(
                f"complete ACTIONS source shrank from {prior_count:,} active "
                f"rows to {len(snapshot):,}; refusing mass-removal authority "
                "without inspection")
        bar_actions = set(SHARE_SPLIT_ACTIONS) | set(DIVIDEND_ACTIONS)
        changed_dates = snapshot.changed_dates(bar_actions)
        changed_source_rows = snapshot.identity_delta_count()
        market_start, market_end = _retained_market_bounds(conn)
        recovery_dates, has_outside_failed_bars = (
            _failed_action_reconcile_bar_footprint(
                conn, market_start=market_start, market_end=market_end))
        semantic_dates = (_semantic_upgrade_replay_dates(
            conn, market_start=market_start, market_end=market_end,
            current_action_rows=snapshot,
            prior_action_rows=snapshot.iter_prior())
            if prior_cursor is None else [])
        replay_dates = sorted(
            set(changed_dates) | set(recovery_dates) | set(semantic_dates))

        if (changed_source_rows == 0
                and not recovery_dates and not semantic_dates
                and not has_outside_failed_bars):
            current = publication.require_current(conn)
            return _write_cursor(
                conn, name=ACTIONS_CURSOR_NAME, kind=ACTIONS_CURSOR_KIND,
                through=hi, publication_version=current.version)

        windows = renormalize.correction_windows(
            replay_dates, market_start=market_start, market_end=market_end)
        run = store.IngestRun(
            conn, "actions_reconcile",
            date_from=ACTIONS_FULL_WINDOW_START, date_to=hi.isoformat(),
            chunks_total=2 + len(windows))
        with run.chunk("actions_full"):
            run.progress.rows_written += store.write_actions(
                conn, snapshot, run_id=run.progress.run_id,
                window_start=ACTIONS_FULL_WINDOW_START,
                window_end=hi.isoformat())
        if windows:
            renormalize.renormalize(
                conn, fetch=fetch, run=run, dates=replay_dates,
                include_action_run_id=run.progress.run_id,
                chunk_prefix="actions", market_start=market_start,
                market_end=market_end)
        with run.chunk("publication_recovery"):
            recovery.record_action_reconcile_retirement_plan(
                conn, run_id=run.progress.run_id,
                plan=recovery.ActionReconcileRetirementPlan(
                    market_start=market_start, market_end=market_end,
                    replay_windows=tuple(windows)))
        run.finish("success")
        published = publication.publish(
            conn, run_id=run.progress.run_id,
            window_start=ACTIONS_FULL_WINDOW_START,
            window_end=hi.isoformat(),
            evidence={
                "kind": "actions_reconcile",
                "source_authority": source_evidence,
                "source_rows": snapshot.source_rows,
                "distinct_source_rows": len(snapshot),
                "exact_repeat_rows": snapshot.exact_repeat_rows,
                "changed_source_rows": changed_source_rows,
                "changed_action_dates": len(set(changed_dates)),
                "recovery_bar_dates": len(set(recovery_dates)),
                "semantic_upgrade_dates": len(set(semantic_dates)),
                "affected_bar_dates": len(set(replay_dates)),
                "retained_market_window": [market_start, market_end],
                "replay_windows": [list(w) for w in windows],
            })
        return _write_cursor(
            conn, name=ACTIONS_CURSOR_NAME, kind=ACTIONS_CURSOR_KIND,
            through=hi, publication_version=published.version)
'''
replace_between(
    "sentinel/feed/maintenance.py",
    "def reconcile_actions_if_due(",
    "__all__ = [",
    new_reconcile,
)


# ---------------------------------------------------------------------------
# Seed writer consumes/relinquishes replayable snapshot deterministically.
# ---------------------------------------------------------------------------
replace_once(
    "sentinel/feed/ingest_impl.py",
    '''        action_source_rows = list(fetch(
            sharadar.ACTIONS, sharadar.date_params(action_start, date_to)))
        run.progress.rows_written += feed_store.write_actions(
            conn, action_source_rows, run_id=run.progress.run_id,
            window_start=action_start, window_end=date_to)
''',
    '''        action_source_rows = fetch(
            sharadar.ACTIONS, sharadar.date_params(action_start, date_to))
        try:
            run.progress.rows_written += feed_store.write_actions(
                conn, action_source_rows, run_id=run.progress.run_id,
                window_start=action_start, window_end=date_to)
        finally:
            close = getattr(action_source_rows, "close", None)
            if close is not None:
                close()
''',
)


# ---------------------------------------------------------------------------
# Bounded-memory and exact-source-grain regressions.
# ---------------------------------------------------------------------------
Path("tests/sentinel/test_issue_235_actions_memory.py").write_text(
    textwrap.dedent(r'''
    """Issue #235/#250 complete ACTIONS bounded-memory regressions."""
    from __future__ import annotations

    import gc
    import inspect
    import io
    import json
    import weakref
    import zipfile

    import pytest

    from sentinel.feed import action_snapshot, action_source, maintenance, store


    def _row(**overrides):
        row = {
            "ticker": "AAA", "date": "2026-08-24", "action": "split",
            "name": "2 for 1", "value": "2", "contraticker": None,
            "contraname": None,
        }
        row.update(overrides)
        return row


    def _zip_csv(text: str) -> bytes:
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("SHARADAR_ACTIONS.csv", text)
        return out.getvalue()


    def _prior(row):
        payload = action_source.canonical_payload(row)
        return {
            **row,
            "source_row_id": action_source.source_row_id(payload),
            "source_payload": json.loads(
                action_source.payload_bytes(payload).decode("utf-8")),
        }


    def test_external_snapshot_collapses_only_exact_source_repeat():
        sibling = _row(name="ADR ratio", value="0.5")
        with action_snapshot.ActionSnapshot.from_rows(
                [_row(), _row(), sibling]) as snapshot:
            assert snapshot.source_rows == 3
            assert len(snapshot) == 2
            assert snapshot.exact_repeat_rows == 1
            assert sorted(item["value"] for item in snapshot) == ["0.5", "2"]
            assert snapshot[0]["ticker"] == "AAA"


    @pytest.mark.parametrize("csv_text,match", [
        ("ticker,date,action,name,value,contraticker,contraname,action\n"
         "AAA,2026-08-24,split,x,2,,,split\n", "duplicate"),
        ("ticker,date,action,name,value,contraticker,contraname\n"
         "AAA,2026-08-24,split,x,2,,,,EXTRA\n", "wider"),
    ])
    def test_external_snapshot_refuses_invalid_csv_shape(csv_text, match):
        with pytest.raises(action_snapshot.ActionSnapshotError, match=match):
            action_snapshot.ActionSnapshot.from_zip_bytes(_zip_csv(csv_text))


    def test_external_snapshot_does_not_retain_whole_input_graph():
        refs = []

        class Tracked(dict):
            pass

        def rows():
            for index in range(20_000):
                row = Tracked(_row(
                    ticker=f"T{index:05d}",
                    date=f"2026-08-{18 + (index % 5):02d}"))
                refs.append(weakref.ref(row))
                yield row

        with action_snapshot.ActionSnapshot.from_rows(rows()) as snapshot:
            gc.collect()
            assert len(snapshot) == 20_000
            assert sum(ref() is not None for ref in refs) <= 1


    def test_external_snapshot_derives_delta_and_bar_dates_in_sqlite():
        unchanged = _row(ticker="BBB", action="dividend", value="1")
        old_split = _row(value="2")
        new_split = _row(value="3")
        with action_snapshot.ActionSnapshot.from_rows(
                [unchanged, new_split]) as snapshot:
            assert snapshot.load_prior_rows(
                [_prior(unchanged), _prior(old_split)]) == 2
            assert snapshot.identity_delta_count() == 2
            assert snapshot.changed_dates({"split", "dividend"}) == ["2026-08-24"]


    def test_production_paths_contain_no_whole_export_object_graphs():
        writer = inspect.getsource(store.write_actions)
        reconcile = inspect.getsource(maintenance.reconcile_actions_if_due)
        assert "distinct_rows(rows)" not in writer
        assert "list(cur.fetchall())" not in writer
        assert "observations = list" not in writer
        assert "_active_action_rows(conn)" not in reconcile
        assert "current_ids = {" not in reconcile
        assert "ActionSnapshot" in reconcile
    ''').lstrip())
