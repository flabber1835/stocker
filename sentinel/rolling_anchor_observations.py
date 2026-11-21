"""Bridge a verified historical price correction into the retained signal units."""
from dataclasses import replace
from decimal import Decimal, localcontext

from sentinel.core.history import WINDOW_SCHEMA
from sentinel.core.rolling_continuity import RollingContinuityRefused
from sentinel.feed import rolling_store
from sentinel.feed.normalized_layout import candidate_query
from sentinel.feed.rolling_contract import CanonicalBar
from sentinel.rolling_reconstruction_evidence import InputsUnavailable


def _observations(conn, binding, changed):
    columns = rolling_store.BAR_COLUMNS
    sql = candidate_query(conn, f"SELECT {','.join('b.' + name for name in columns)} "
        "FROM unnest(%s::text[],%s::date[]) AS wanted(security_id,session) "
        "JOIN sentinel_snapshot_bars b USING (security_id,session) "
        "WHERE b.candidate_id=%s AND b.session=ANY(%s::date[])")
    days = [anchor.session for anchor in changed.values()]
    rows = conn.execute(sql, (list(changed), days, binding['candidate_id'], sorted(set(days)))).fetchall()
    return {row[0]: CanonicalBar.model_validate(dict(zip(columns, row))) for row in rows}


def _same_scale(old, new):
    # Canonical observations are finite binary64 values with at most 17 decimal
    # significant digits in their round-trip strings.
    with localcontext() as ctx:
        ctx.prec = 40
        return (Decimal(str(old.close_signal)) * Decimal(str(new.close_unadjusted))
                == Decimal(str(new.close_signal)) * Decimal(str(old.close_unadjusted)))


def bridge(conn, *, prior, previous, current, anchors, proof):
    """Read the pinned pair before canonical append. Mark and feature rows stay current."""
    if proof.get('schema') != WINDOW_SCHEMA:
        return anchors, proof
    if proof['snapshot_sha256'] != current['snapshot_id']:
        raise RollingContinuityRefused('SIGNAL_OBSERVATION_SNAPSHOT_CHANGED')
    series = prior.feed['series']
    changed = {sid: anchor for sid, anchor in sorted(anchors.items())
               if anchor.raw_close != float(series[sid]['signal_basis_anchor'][1])}
    if not changed:
        return anchors, proof
    for binding in (previous, current):
        manifest = rolling_store.manifest(conn, binding['candidate_id'])
        if manifest.snapshot_id != binding['snapshot_id']:
            raise RollingContinuityRefused('SIGNAL_OBSERVATION_SNAPSHOT_CHANGED')
        if manifest.provider != 'ALPACA_OPENFIGI':
            return anchors, proof

    old_rows, new_rows = (_observations(conn, binding, changed) for binding in (previous, current))
    bridged = dict(anchors)
    revisions = []
    for sid, anchor in changed.items():
        saved = series[sid]
        _, raw, owned = saved['signal_basis_anchor']
        multiplier = saved.get('signal_basis_multiplier', 1.0)
        old, new = old_rows.get(sid), new_rows.get(sid)
        if (old is None or old.close_signal is None or old.close_unadjusted != float(raw)
                or old.close_signal * multiplier != float(owned)):
            raise RollingContinuityRefused('RETAINED_SIGNAL_OBSERVATION_CHANGED: ' + sid)
        if (new is None or new.close_signal is None
                or (new.ticker, new.close_unadjusted, new.close_signal)
                != (anchor.ticker, anchor.raw_close, anchor.signal_close)):
            raise RollingContinuityRefused('CURRENT_SIGNAL_OBSERVATION_CHANGED: ' + sid)
        if (old.split_ratio, old.dividend_per_share) != (new.split_ratio, new.dividend_per_share):
            raise RollingContinuityRefused('SIGNAL_OBSERVATION_ECONOMICS_CHANGED: ' + sid)
        if not _same_scale(old, new):
            raise InputsUnavailable('HELD_SIGNAL_OBSERVATION_BASIS_PENDING: ' + sid)
        # This field carries the observation that establishes the retained unit
        # conversion. The current publication still supplies the feature history.
        bridged[sid] = replace(anchor, raw_close=old.close_unadjusted, signal_close=old.close_signal)
        revisions.append([old.model_dump(mode='json'), new.model_dump(mode='json')])

    witness = {'schema': 'sentinel.protected-price-observations/1',
        'prior_state_sha256': proof['prior_state_sha256'],
        'previous_snapshot_sha256': previous['snapshot_id'], 'snapshot_sha256': current['snapshot_id'],
        'protected_economics_sha256': proof['protected_economics_sha256'], 'revisions': revisions}
    evidence = rolling_store.put_evidence(conn, witness)
    return bridged, {**proof, 'protected_economics_sha256': evidence}
