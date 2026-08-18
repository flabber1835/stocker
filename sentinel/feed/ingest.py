"""Seed and daily ingest — fetch, normalise, write, publish progress.

```text
SHARADAR  ->  domains.normalise_sep_rows  ->  store.write_bars
                        |                            |
                        +--------- IngestRun.chunk ---+
                                     publishes committed progress per year
```

Two modes, one path:

```text
seed    the full history, one CALENDAR YEAR per chunk. Hours. Watchable.
daily   everything since the newest session already stored, plus a small
        re-fetch window so a vendor restatement of recent bars is picked up
```

**The daily fetch deliberately overlaps.** Resuming strictly after the last
stored session would never revisit a bar, and Sharadar restates: a split or a
correction lands on rows already written. The upserts are idempotent, so
re-fetching a short tail costs one small request and repairs silently. Resuming
without overlap would leave a stale bar in place forever, and the trailing stop
reads exactly those closes.
"""
from __future__ import annotations

import datetime as _dt
import logging
from typing import Callable, Iterable, Optional

from sentinel.feed import domains, sharadar, universe
from sentinel.feed import store as feed_store

log = logging.getLogger(__name__)

#: Sessions re-fetched behind the frontier on a daily run. Ten trading days is
#: comfortably longer than a vendor's correction lag and still one small request.
DAILY_OVERLAP_DAYS = 14

#: Wealth Core needs 126 sessions of history before it can plan, and the
#: deployment doc prefers 252 for margin. The seed default reaches far enough
#: back that neither is ever the constraint.
DEFAULT_SEED_START = "1998-01-01"


def _today() -> str:
    return _dt.date.today().isoformat()


def _report_split_disagreements(report, authoritative, *, ignore_keys=()) -> list:
    """LOUD when the stated and derived split ratios describe different events.

    Equal or reciprocal evidence is oriented deterministically. Anything else
    is not applied: silently preferring either source would turn a data problem
    into a share count nobody questions.
    """
    from sentinel.feed import actions_map

    ignored = set(ignore_keys)
    bad = [d for d in actions_map.split_disagreements(report, authoritative)
           if (d["ticker"], d["session"]) not in ignored]
    for d in bad[:20]:
        log.warning(
            "sentinel: SPLIT DISAGREEMENT %s %s stated=%.6g derived=%.6g — "
            "NOT APPLIED; ACTIONS is neither equal nor reciprocal to the "
            "price-domain ratio", d["ticker"], d["session"], d["stated"],
            d["derived"])
    if len(bad) > 20:
        log.warning("sentinel: +%d further split disagreements", len(bad) - 20)

    # The OTHER half, and the half that is easy to leave silent because the
    # fallback handles it: a split the prices show and ACTIONS never recorded.
    # Summarised rather than listed per row — in thin early history this is a
    # coverage statement about the actions feed, not a per-security fault.
    only = actions_map.splits_only_derived(report, authoritative)
    if only:
        log.warning(
            "sentinel: %d split(s) inferred from prices with NO ACTIONS row "
            "(applied as derived-only non-seam events; e.g. %s) — ACTIONS "
            "does not cover every "
            "split in this window", len(only),
            ", ".join(f"{d['ticker']} {d['session']} x{d['derived']:.6g}"
                      for d in only[:5]))
    return bad


def _action_maps(conn, start: str, end: str, *, include_run_id=None):
    """(authoritative_splits, dividends) for [start, end], from the ACTIONS rows
    ALREADY STORED for this window.

    Read back from `sentinel_actions` rather than from the fetch response, so a
    resumed or re-run chunk uses exactly what the corpus holds — the derived
    ratio would otherwise depend on whether this process happened to be the one
    that downloaded the actions.

    THE SESSION AXIS IS THE EXCHANGE CALENDAR, NOT THE STORED BARS. The ex-date
    is a CALENDAR date and can fall on a weekend or a holiday, so both maps snap
    forward to the first real session; an event dated on a non-session never
    fires and would leave the entitlement outstanding. Snapping against the
    sessions already in `sentinel_bars` looks equivalent and is not: this runs
    BEFORE the chunk's own bars are written, so on a seed the stored set is
    empty and every weekend ex-date silently vanished. The corpus cannot be its
    own witness for a day it does not yet hold — the same argument
    `feed/calendar.py` exists under.
    """
    from sentinel.feed import actions, actions_map, calendar

    lo, _ = calendar.action_date_window(start, end)
    rows = actions.active_rows(
        conn, start=lo, end=end, include_run_id=include_run_id)
    sessions = calendar.sessions_in_range(start, end)
    splits, ambiguous = actions_map.split_rows_from_actions(rows, sessions)
    # A zero stated value makes the normaliser apply 1.0 and records an
    # unresolved disposition.  It also prevents the price-derived fallback
    # from silently deciding which of several vendor rows was intended.
    for item in ambiguous:
        splits[(item["ticker"], item["session"])] = 0.0
    return (splits, actions_map.dividends_from_actions(rows, sessions),
            rows, ambiguous)


def _ordered_sep(conn, rows: Iterable[dict], *, run_id: str, chunk: str):
    """Vendor price rows in (date, ticker) order, WITHOUT holding the chunk.

    `normalise_sep_rows` RAISES on an out-of-order stream rather than silently
    recovering split ratios against the wrong bar, so the ordering has to come
    from somewhere. It cannot come from the vendor: `fetch_table` cursor-pages
    an HTTP API that requests no sort and promises none, so a correct corpus
    rested on an undocumented property of someone else's service.

    THIS USED TO BE `sorted(rows, ...)`, at "the call site that can afford it —
    one chunk is a year, not a corpus". A universe-scale year is precisely what
    could not be afforded: ~10,000 securities x ~252 sessions is ~2.5M vendor
    dicts held alive at once, 1-2 GB against a 2g container ceiling, before a
    single bar is normalised.

    The sort now happens in PostgreSQL, which spills to disk above `work_mem`
    and therefore has the bounded-memory property the interpreter lacks. Both
    halves stream, so no stage of the ingest holds more than a batch. See
    `sentinel/feed/staging.py`.
    """
    from sentinel.feed import staging

    staged = staging.stage(conn, rows, run_id=run_id, chunk=chunk)
    log.info("sentinel: staged %d SEP rows for chunk %s", staged, chunk)
    try:
        yield from staging.staged(conn, run_id=run_id, chunk=chunk)
    finally:
        # ALWAYS, including on the exception path. Scratch that survives a
        # failed chunk is read by the resumed one as if it belonged to it.
        staging.clear(conn, run_id=run_id, chunk=chunk)


def _resolution_tombstones(conn, run, *, lo: str, hi: str, report,
                           emitted: list[dict], current_action_rows) -> list[dict]:
    """Explicitly resolve covered historical events; silence resolves nothing."""
    from sentinel.core.terminal import DIVIDEND_ACTIONS
    from sentinel.feed import (actions_map, anomalies as anomaly_store, calendar,
                               publication)

    kinds = (anomaly_store.SPLIT_DISPOSITION_KINDS
             + anomaly_store.DIVIDEND_DISPOSITION_KINDS)
    targets = anomaly_store.active_rows(conn, start=lo, end=hi, kinds=kinds)
    targets.extend(anomaly_store.pending_rows(conn, start=lo, end=hi))

    emitted_keys = set()
    for item in emitted:
        family = ("split" if item["kind"] in anomaly_store.SPLIT_DISPOSITION_KINDS
                  else "dividend" if item["kind"] in
                  anomaly_store.DIVIDEND_DISPOSITION_KINDS else item["kind"])
        emitted_keys.add((family, str(item["ticker"]).upper(),
                          str(item["session"])))

    raw_lo, _ = calendar.action_date_window(lo, hi)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT EXISTS (SELECT 1 FROM sentinel_action_generations"
            " WHERE last_written_run_id=%s AND window_start<=%s"
            "   AND window_end>=%s)",
            (run.progress.run_id, raw_lo, hi))
        complete_actions = bool(cur.fetchone()[0])
    current_rows = [row for row in current_action_rows
                    if raw_lo <= str(row.get("date") or "") <= hi]
    sessions = calendar.sessions_in_range(lo, hi)
    current_splits = {
        (str(ticker).upper(), str(session))
        for ticker, session in actions_map.split_ratios_from_actions(
            current_rows, sessions)
    }
    valid_dividends = set()
    for row in current_rows:
        if str(row.get("action") or "").lower() not in DIVIDEND_ACTIONS:
            continue
        try:
            usable = row.get("value") is not None and float(row["value"]) > 0
        except (TypeError, ValueError):
            usable = False
        if usable:
            valid_dividends.add((str(row.get("ticker") or "").upper(),
                                 str(row.get("date") or "")))

    out = []
    seen = set()
    for row in targets:
        kind = row["kind"]
        ticker, session = str(row["ticker"]).upper(), str(row["session"])
        if kind in anomaly_store.DIVIDEND_DISPOSITION_KINDS:
            family = "dividend"
        elif kind in anomaly_store.SPLIT_DISPOSITION_KINDS:
            family = "split"
        else:
            continue
        key = (family, ticker, session)
        if key in seen or key in emitted_keys:
            continue
        seen.add(key)
        if family == "dividend":
            if kind == "DIVIDEND_RESOLVED" or (ticker, session) not in valid_dividends:
                continue
            out.append({
                "kind": "DIVIDEND_RESOLVED", "ticker": ticker,
                "session": session,
                "detail": "current authoritative ACTIONS row has a usable "
                          "positive dividend amount; prior unusable evidence "
                          "is retained as history"})
            continue

        if (kind == "SPLIT_RESOLVED_NO_EVENT"
                or (ticker, session) in current_splits
                or not complete_actions):
            continue
        # A 1.0 normaliser result is not itself evidence: it is also the fallback
        # for a missing predecessor.  Require the report's explicit unsnapped
        # comparison against a real predecessor.
        if (ticker, session) not in {
                (str(t).upper(), str(s))
                for t, s in report.split_no_event_evidence}:
            continue
        with conn.cursor() as cur:
            cur.execute(
                "SELECT b.security_id,"
                f" {publication.effective_split_ratio('b')}"
                " FROM sentinel_bars b WHERE b.last_written_run_id=%s"
                "   AND UPPER(b.ticker)=%s AND b.session=%s",
                (run.progress.run_id, ticker, session))
            bar_rows = cur.fetchall()
        if len(bar_rows) != 1:
            continue
        security_id, effective = str(bar_rows[0][0]), float(bar_rows[0][1])
        if abs(effective - 1.0) > 1e-12:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO sentinel_bar_split_repairs"
                    " (security_id,session,split_ratio,prior_split_ratio,"
                    "  last_written_run_id) VALUES (%s,%s,1.0,%s,%s)"
                    " ON CONFLICT (security_id,session,last_written_run_id)"
                    " DO NOTHING",
                    (security_id, session, effective, run.progress.run_id))
                cur.execute(
                    "SELECT split_ratio FROM sentinel_bar_split_repairs"
                    " WHERE security_id=%s AND session=%s"
                    "   AND last_written_run_id=%s",
                    (security_id, session, run.progress.run_id))
                correction = cur.fetchone()
            if correction is None or abs(float(correction[0]) - 1.0) > 1e-12:
                continue
        out.append({
            "kind": "SPLIT_RESOLVED_NO_EVENT", "ticker": ticker,
            "session": session,
            "detail": "current complete ACTIONS window has no split and the "
                      "current SEP predecessor comparison derives no split; "
                      "the effective candidate ratio is exactly 1.0 and prior "
                      "event evidence is retained as history"})
    return out


def _persist_chunk_evidence(conn, run, chunk: str, lo: str, hi: str,
                            report, splits, action_rows,
                            current_action_rows, ambiguous_splits=()) -> None:
    """Everything the chunk learned that is not a bar.

    All of it durable, because a certification runs in a different process
    hours later and cannot consult a log line that scrolled past during a
    six-hour seed.
    """
    from sentinel.feed import actions_map

    # 1. the refused rows themselves — stamped with the candidate generation.
    # A later successful publication may resolve them in the active projection,
    # but the failed history is never deleted or attributed by guess.
    feed_store.write_rejections(
        conn, report.rejections, run_id=run.progress.run_id)

    # 2. THAT SOME REFUSALS WERE NOT KEPT. The report retains at most
    #    `max_rejections` rows and counts the rest, which is right — a broad
    #    identity outage must not sit in memory. What was wrong is that the
    #    count died with the process, so an audit could examine 50,000 of
    #    175,000 refusals and report CLEAR.
    feed_store.write_rejection_truncation(
        conn, run_id=run.progress.run_id, chunk=chunk, window_start=lo, window_end=hi,
        retained=len(report.rejections), truncated=report.rejections_truncated)

    # 3. anomalies that were RESOLVED but not resolved away
    anomalies = []
    ambiguous_keys = {(d["ticker"], d["session"]) for d in ambiguous_splits}
    reported_disagreements = _report_split_disagreements(
        report, splits, ignore_keys=ambiguous_keys)
    for d in reported_disagreements:
        anomalies.append({
            "kind": "SPLIT_DISAGREEMENT", "ticker": d["ticker"],
            "session": d["session"],
            "detail": f"stated={d['stated']:.6g} derived={d['derived']:.6g}"})
    for d in actions_map.splits_only_derived(report, splits):
        anomalies.append({
            "kind": "SPLIT_ONLY_DERIVED", "ticker": d["ticker"],
            "session": d["session"], "detail": f"derived={d['derived']:.6g}"})
    for d in ambiguous_splits:
        anomalies.append({
            "kind": "AMBIGUOUS_SPLIT_MULTIPLICITY", "ticker": d["ticker"],
            "session": d["session"],
            "detail": f"distinct_rows={d['distinct_rows']} "
                      f"distinct_values={d['distinct_values']!r} "
                      f"invalid_value_rows={d['invalid_value_rows']}; "
                      "no ACTIONS multiplier applied"})
    for (tkr, sess), item in sorted(report.split_dispositions.items()):
        if (tkr, sess) in ambiguous_keys:
            continue
        disposition = item["disposition"]
        if disposition in {
                actions_map.SPLIT_CORROBORATED_DIRECT,
                actions_map.SPLIT_CORROBORATED_RECIPROCAL}:
            anomalies.append({
                "kind": "SPLIT_CORROBORATED_DERIVED", "ticker": tkr,
                "session": sess,
                "detail": f"orientation={disposition} "
                          f"stated={item['stated']:.12g} "
                          f"derived={item['derived']:.12g} "
                          f"applied={item['applied_ratio']:.12g}"})
        elif disposition == actions_map.SPLIT_AUTHORITATIVE_APPLIED:
            anomalies.append({
                "kind": "SPLIT_AUTHORITATIVE_APPLIED", "ticker": tkr,
                "session": sess,
                "detail": f"stated={item['stated']:.12g} "
                          f"applied={item['applied_ratio']:.12g}"})
        elif (disposition == actions_map.SPLIT_UNRESOLVED
              and item["derived"] is None):
            # A disagreement with price evidence was already recorded above.
            # This branch covers the equally unsafe action-only denominator,
            # without emitting the same anomaly/log record twice.
            derived = item["derived"]
            detail = (f"stated={item['stated']:.12g} derived="
                      f"{derived if derived is not None else 'unavailable'}; "
                      "NOT applied because orientation is unresolved")
            anomalies.append({
                "kind": "SPLIT_DISAGREEMENT", "ticker": tkr,
                "session": sess, "detail": detail})
            log.warning("sentinel: SPLIT DISAGREEMENT %s %s — %s",
                        tkr, sess, detail)
    for row in actions_map.unusable_dividend_rows_detail(action_rows):
        anomalies.append({
            "kind": "UNUSABLE_DIVIDEND", "ticker": row["ticker"],
            "session": row["date"],
            "detail": f"action={row['action']} value={row['value']!r}"})
    # A split derived at the window's leading edge that ACTIONS did not confirm.
    # NOT applied (see domains.normalise_sep_rows) and therefore NOT visible in
    # the bar it concerns, which is exactly why it has to be durable: the only
    # trace of the question would otherwise be a value that looks ordinary.
    for (tkr, sess), ratio in report.seam_splits_uncorroborated.items():
        log.warning(
            "sentinel: seam artifact suppressed %s %s derived=%.6g — NOT "
            "applied; the seeded predecessor may use an older adjustment vintage",
            tkr, sess, ratio)
        anomalies.append({
            "kind": "SEAM_SPLIT_UNCORROBORATED", "ticker": tkr, "session": sess,
            "detail": f"derived={ratio:.6g} against a SEEDED predecessor with no "
                      f"ACTIONS row; NOT applied. Either the actions feed missed "
                      f"a real split, or the seeded close belongs to an older "
                      f"vendor adjustment vintage."})
    anomalies.extend(_resolution_tombstones(
        conn, run, lo=lo, hi=hi, report=report, emitted=anomalies,
        current_action_rows=current_action_rows))
    if anomalies:
        feed_store.write_anomalies(
            conn, anomalies, run_id=run.progress.run_id, require_lock=True)


def seed(conn, *, date_from: str = DEFAULT_SEED_START, date_to: Optional[str] = None,
         fetch: Callable[..., Iterable[dict]] = sharadar.fetch_table,
         resolve_identity=None) -> feed_store.IngestProgress:
    """Load the full history, one calendar year per chunk.

    Idempotent by construction: every write is an upsert keyed on
    (security_id, session), so an interrupted seed is resumed by running it
    again. That is why the orphan reclaim keeps a dead run's committed rows
    rather than rolling them back.

    HOLDS THE CORPUS WRITE LOCK FOR THE WHOLE RUN, not per chunk. An in-place
    upsert while a session has the corpus pinned changes what that session's
    `data_version` describes — and the version does not move to say so. Taking
    it per chunk would leave a window between chunks in which a reader could pin
    a half-written corpus, which is the same defect one level down.

    Acquired in the public entry point rather than left to the caller, for the
    reason `execute_session` gives about its writer lock: a prerequisite that
    lives in a docstring is one a future call site can simply forget.
    """
    with feed_store.corpus_write_lock(conn):
        return _seed_locked(conn, date_from=date_from, date_to=date_to,
                            fetch=fetch, resolve_identity=resolve_identity)


def _seed_locked(conn, *, date_from: str, date_to: Optional[str],
                 fetch: Callable[..., Iterable[dict]],
                 resolve_identity) -> feed_store.IngestProgress:
    date_to = date_to or _today()
    chunks = sharadar.year_chunks(date_from, date_to)
    run = feed_store.IngestRun(conn, "seed", date_from=date_from,
                               date_to=date_to, chunks_total=len(chunks) + 3)

    # TICKERS FIRST. Identity is not decoration on the price load — a bar keyed
    # on the SYMBOL splices two unrelated companies that reused it, and the
    # momentum computed across that seam is wrong for as long as the corpus
    # lives. Loading prices before identity would mean re-loading them after.
    with run.chunk("tickers"):
        rows = list(fetch(sharadar.TICKERS))
        run.progress.rows_written += universe.write_universe(
            conn, rows, date_to, run_id=run.progress.run_id)

    # ACTIONS first, and as its own chunk. It is small, it is the AUTHORITATIVE
    # corporate-action stream, and having it before the prices means the split
    # ratio derived from the two price domains has something to be cross-checked
    # against from the first year rather than the last.
    with run.chunk("actions"):
        from sentinel.feed import calendar
        action_start, _ = calendar.action_date_window(date_from, date_to)
        action_source_rows = list(fetch(
            sharadar.ACTIONS, sharadar.date_params(action_start, date_to)))
        run.progress.rows_written += feed_store.write_actions(
            conn, action_source_rows, run_id=run.progress.run_id,
            window_start=action_start, window_end=date_to)

    # SPY is a FUND, not an SEP equity. Fetch only this ticker from SFP and keep
    # it in the controller's dedicated total-return table.
    with run.chunk("spy"):
        params = {"ticker": "SPY", **sharadar.date_params(date_from, date_to)}
        rows = fetch(sharadar.SFP, params)
        run.progress.rows_written += feed_store.write_spy_total_return(
            conn, rows, run_id=run.progress.run_id, require_lock=True)

    # Built ONCE from what was just stored, then reused for every year. Rebuilding
    # per chunk would be correct and would re-read the whole universe 29 times.
    resolver = resolve_identity or universe.load_resolver(
        conn, include_run_id=run.progress.run_id).resolve

    for lo, hi in chunks:
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

    run.finish("success")
    _publish_version(conn, run, date_from, date_to)
    return run.progress


def _publish_version(conn, run, window_start: str, window_end: str):
    """Declare a new corpus version — AFTER the run has succeeded.

    Ordering is the whole distinction between a run and a version. A run that
    fails halfway has a `run_id`, and it must never be citable as the corpus a
    decision was made against; a version exists only when a coherent, validated
    state was reached. Calling this before `run.finish("success")` would erase
    that difference while looking identical in a schema dump.

    NON-FATAL. A corpus that loaded correctly but could not be published is
    still a correct corpus, and failing the ingest here would discard hours of
    work over a bookkeeping row. The absence shows up as a chain gap and as a
    stale `data_version`, both of which are visible.
    """
    from sentinel.feed import publication

    try:
        published = publication.publish(
            conn, run_id=run.progress.run_id, window_start=window_start,
            window_end=window_end,
            evidence={"kind": run.progress.kind,
                      "rows_written": run.progress.rows_written,
                      "rows_dropped": run.progress.rows_dropped,
                      "chunks": run.progress.chunks_done})
        log.info("sentinel: published corpus version %d (previous %s)",
                 published.version, published.previous_version)
        return published
    except publication.CorpusBusy:
        log.warning("sentinel: corpus NOT published — a session holds it "
                    "pinned. The rows are written and idempotent; re-run the "
                    "ingest to publish once the session releases.")
    except Exception as exc:                                  # noqa: BLE001
        log.warning("sentinel: corpus NOT published (%s). The data is loaded; "
                    "decisions will keep recording the PREVIOUS data_version "
                    "until a publication succeeds.", exc)
    return None


def daily(conn, *, fetch: Callable[..., Iterable[dict]] = sharadar.fetch_table,
          resolve_identity=None, overlap_days: int = DAILY_OVERLAP_DAYS,
          today: Optional[str] = None) -> feed_store.IngestProgress:
    """Fetch from `overlap_days` behind the stored frontier through today.

    HOLDS THE CORPUS WRITE LOCK, exactly as `seed` does and for the same
    reason. This path is the one that actually races a reader: it runs every
    evening, its 14-day overlap window REWRITES rows a session may be reading,
    and the rewrite is silent — the published version stays where it is while
    the rows it names change underneath.
    """
    with feed_store.corpus_write_lock(conn):
        return _daily_locked(conn, fetch=fetch,
                             resolve_identity=resolve_identity,
                             overlap_days=overlap_days, today=today)


def _daily_locked(conn, *, fetch: Callable[..., Iterable[dict]],
                  resolve_identity, overlap_days: int,
                  today: Optional[str]) -> feed_store.IngestProgress:
    to = today or _today()
    frontier = feed_store.latest_session(conn)
    if frontier is None:
        raise RuntimeError(
            "the corpus is empty, so there is no frontier to resume from. Run "
            "`feed-seed` first — a daily fetch would silently load a two-week "
            "window and leave Wealth Core with far less history than the 126 "
            "sessions it needs, which surfaces as an eligibility failure rather "
            "than as the missing seed it actually is.")
    start = (_dt.date.fromisoformat(frontier)
             - _dt.timedelta(days=overlap_days)).isoformat()
    # Refuse before opening the durable run row.  A future/corrupt frontier must
    # not become a successful empty ingest whose publication advances anyway.
    sharadar.validate_date_range(start, to)

    run = feed_store.IngestRun(conn, "daily", date_from=start, date_to=to,
                               chunks_total=4)
    # Refreshed daily, not just at seed. Listings change: an IPO or a rename
    # arrives with no stored identity, and every one of its bars would be dropped
    # as unresolvable — silently, since dropping is the correct response to an
    # unknown security and looks identical to one.
    with run.chunk("tickers"):
        rows = list(fetch(sharadar.TICKERS))
        run.progress.rows_written += universe.write_universe(
            conn, rows, to, run_id=run.progress.run_id)

    with run.chunk("actions"):
        from sentinel.feed import calendar
        action_start, _ = calendar.action_date_window(start, to)
        action_source_rows = list(
            fetch(sharadar.ACTIONS, sharadar.date_params(action_start, to)))
        run.progress.rows_written += feed_store.write_actions(
            conn, action_source_rows, run_id=run.progress.run_id,
            window_start=action_start, window_end=to)

    # A legacy corpus may be complete while this table is empty. Repair the
    # exact readiness-required 41-session tail, not the 14-calendar-day equity
    # overlap, and request only SPY from the fund table.
    with run.chunk("spy"):
        from sentinel.feed import calendar, readiness
        spy_start = calendar.previous_sessions(
            to, readiness.REQUIRED_SPY_SESSIONS)[0]
        params = {"ticker": "SPY", **sharadar.date_params(spy_start, to)}
        rows = fetch(sharadar.SFP, params)
        run.progress.rows_written += feed_store.write_spy_total_return(
            conn, rows, run_id=run.progress.run_id, require_lock=True)

    with run.chunk("prices"):
        report = domains.NormalisationReport()
        splits, divs, action_rows, ambiguous_splits = _action_maps(
            conn, start, to, include_run_id=run.progress.run_id)
        bars = domains.normalise_sep_rows(
            _ordered_sep(conn,
                         fetch(sharadar.SEP, sharadar.date_params(start, to)),
                         run_id=run.progress.run_id, chunk="prices"),
            resolve_identity=resolve_identity or universe.load_resolver(
                conn, include_run_id=run.progress.run_id).resolve,
            authoritative_splits=splits, dividends=divs,
            # THE DAILY PATH IS WHERE THE DEFECT BIT HARDEST. This window opens
            # 14 days behind the frontier and runs EVERY EVENING, so its leading
            # edge was re-derived as "no split" nightly and written over
            # whatever a better-positioned earlier run had established.
            prior_observations=feed_store.previous_observations(conn, start),
            report=report)
        run.progress.rows_written += feed_store.write_bars(
            conn, bars, run_id=run.progress.run_id, require_lock=True)
        _persist_chunk_evidence(conn, run, "prices", start, to, report, splits,
                                action_rows, action_rows, ambiguous_splits)
        run.progress.rows_dropped += (report.dropped_no_raw_close
                                      + report.dropped_no_identity)
        # Checked on the DAILY path, where a vendor outage looks like a quiet
        # market. A seed spanning decades would be dominated by legitimately
        # sparse early years, so the same threshold there would refuse a healthy
        # load.
        domains.assert_raw_price_domain(report)
        # The frontier was captured BEFORE this ingest wrote anything. Validate
        # every SEP session the vendor actually exposed beyond that frontier —
        # not the requested wall-clock `to`. That distinction is what makes a
        # Saturday catch-up inspect Friday, a holiday stay N/A, and a multi-day
        # catch-up unable to hide a collapsed intermediate session behind a
        # healthy latest session.
        for session in sorted(report.rows_by_session):
            if session > frontier:
                domains.assert_identity_domain(report, session)

    run.finish("success")
    # AFTER both daily-domain validations. A version published before them would
    # be citable by a decision made against a corpus the ingest was about to
    # reject.
    _publish_version(conn, run, start, to)
    return run.progress
