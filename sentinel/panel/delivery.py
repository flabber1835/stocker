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
    if not changed or changed - {'SHADOW', 'PAPER'}:
        return False
    if row.key not in _KNOWN and not row.key.startswith('automation_step_'):
        return False
    if row.key in panel.observation_revalidated_keys and (
            'SHADOW' in changed and row.key in _FINANCIAL_SHADOW
            or 'PAPER' in changed and row.key == 'paper_reconciliation'):
        return True
    return not (('SHADOW' in changed and (row.key in _SHADOW or row.key.startswith('automation_step_')))
                or ('PAPER' in changed and (row.key in _PAPER
                    or row.key.startswith('automation_step_'))))


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
