"""Existing economic segment caveats shared by the operational producer."""
from dataclasses import replace
import os

from sentinel import shadow_segments
from sentinel.panel import model


def disclose(panel: model.Panel, database_url: str) -> model.Panel:
    """Preserve every panel/row fact while adding the retained segment caveat."""
    if not database_url or str(os.environ.get(
            'SENTINEL_REVIEWED_DEPLOYMENT_MODE', '')).strip().lower() != 'dual':
        return panel
    from sentinel.feed import store as feed_store
    from sentinel.panel.sources import STATEMENT_TIMEOUT_MS, _bounded_dsn, _set_statement_timeout

    observation_id = str(os.environ.get('SENTINEL_SHADOW_OBSERVATION_ID', 'primary')).strip()
    if not observation_id:
        return panel
    conn = None
    try:
        conn = feed_store.connect(_bounded_dsn(database_url))
        _set_statement_timeout(conn, STATEMENT_TIMEOUT_MS)
        segment = shadow_segments.active_segment(conn, observation_id)
    except Exception as exc:
        return replace(panel, source_errors=[*panel.source_errors,
            f'shadow segment disclosure: {type(exc).__name__}: {exc}'])
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
    if segment.index == 0:
        return panel
    marker = str(segment.marker_sha256 or '')
    detail = (
        f'causal outage broke performance and strategy-state continuity; '
        f'segment {segment.index} starts {segment.first_session} after '
        f'{segment.reason}; predecessor {segment.predecessor_session}; '
        'this is NOT trial-to-date return. Exact marker approval is necessary '
        'but NOT sufficient for broker transport: '
        'SENTINEL_SHADOW_REGENESIS_APPROVAL_SHA256 must equal the marker '
        f'{marker}, and PAPER must also prove a fresh COMPLETE/RUNNING flat '
        'broker reconciliation with no working orders or durable in-flight '
        'commands before the one-time segment handover can be recorded')
    warning = model.Row(key='shadow_segment', label='Shadow economic performance segment',
        value=f'SEGMENT {segment.index} · START {segment.first_session}', status=model.WARN,
        detail=detail)
    rows = []
    inserted = False
    for row in panel.rows:
        if row.key == 'shadow_verification' and not inserted:
            rows.extend((row, warning))
            inserted = True
        elif row.key == 'shadow_return':
            rows.append(replace(row, label='Certified segment return', detail=detail))
        elif row.key == 'shadow_nav':
            rows.append(replace(row, detail='current segment NAV · '+detail))
        else:
            rows.append(row)
    if not inserted:
        rows.append(warning)
    return replace(panel, rows=rows)
