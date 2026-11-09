"""Scope-aware current styling, separate from native facts and transport age."""
from dataclasses import replace

from sentinel.panel import model

_FINANCIAL_SHADOW = model.SHADOW_ROW_KEYS | {'exposure', 'book', 'terminals'}
_SHADOW = _FINANCIAL_SHADOW | {'feed', 'ingest', 'shadow_segment',
    'paper_plan', 'trading_run', 'completed_trading_run', 'authority', 'automation_cycle'}
_PAPER = frozenset({'paper_reconciliation', 'paper_plan', 'trading_run',
    'completed_trading_run', 'alpaca_account', 'actual_account', 'broker',
    'ownership', 'automation', 'automation_leader', 'automation_cycle',
    'authority', 'runtime_identity', 'issuer_reference', *model.TRIAL_ROW_KEYS})
_INDEPENDENT = frozenset({'backup_restore', 'shadow_worker', 'automation_alerts',
    'alert_dispatcher', 'trading_environment'})
_KNOWN = _SHADOW | _PAPER | _INDEPENDENT


def row_current(panel, row):
    if panel.observation_current:
        return True
    changed = set(panel.observation_changed_scopes)
    if (not changed and not panel.observation_retained) or changed - {'SHADOW', 'PAPER'}:
        return False
    negative = row.status in {model.FAIL, model.UNKNOWN}
    if row.key not in _KNOWN and not row.key.startswith('automation_step_') and not (
            panel.observation_retained and negative):
        return False
    revalidated = row.key in panel.observation_revalidated_keys and (
            'SHADOW' in changed and row.key in _FINANCIAL_SHADOW
            or 'PAPER' in changed and row.key == 'paper_reconciliation')
    current = revalidated or not (('SHADOW' in changed and (row.key in _SHADOW or row.key.startswith('automation_step_')))
                or ('PAPER' in changed and (row.key in _PAPER
                    or row.key.startswith('automation_step_'))))
    if not current or not panel.observation_retained:
        return current
    if negative:
        return True
    if row.is_future(panel.now):
        return False
    from sentinel.panel.presentation import _row_boundary
    boundary = _row_boundary(row)
    if row.paper_plan is not None:
        boundary = min(boundary, row.paper_plan.execute_at) if boundary else row.paper_plan.execute_at
    return boundary is not None and panel.now < boundary


def row_status(panel, row):
    native = row.effective_status(panel.now)
    return native if row_current(panel, row) else model.PENDING


def row_color(panel, row):
    from sentinel.operational_status import color
    native = row.effective_status(panel.now)
    return color(native) if row_current(panel, row) else 'neutral'


def payload_panel(panel):
    """A detached presentation view cannot expose stale payloads as current."""
    return replace(panel, rows=[row if row_current(panel, row) else replace(row,
        shadow_book=None, paper_plan=None, paper_account=None, trading_run=None,
        preparation=None, order_outcomes=[]) for row in panel.rows])
