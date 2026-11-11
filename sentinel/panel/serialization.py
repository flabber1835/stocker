"""Pure public JSON projection and same-image server rendering preflight."""
import json

from sentinel.operational_status import color
from sentinel.panel import model, delivery
from sentinel.panel.presentation import dashboard_health


def public_payload(panel):
    """Use exactly the same evidence eligibility and clocks on every surface."""
    health = dashboard_health(panel)
    display_current = delivery.display_current(panel)
    return {
        'overall': panel.overall,
        'operational': panel.operational if panel.observation_current else model.UNKNOWN,
        'color': color(panel.operational) if panel.observation_current else health['color'],
        'dashboard_health': health,
        'observation': {'current': display_current,
            'strict_current': panel.observation_current,
            'display_current': display_current,
            'display_keys': list(panel.observation_display_keys),
            'retained': panel.observation_retained,
            'generated_at': panel.observation_generated_at.isoformat() if panel.observation_generated_at else None,
            'changed_scopes': list(panel.observation_changed_scopes),
            'revalidated_keys': list(panel.observation_revalidated_keys),
            'valid_until': panel.observation_valid_until.isoformat() if panel.observation_valid_until else None},
        'operator_review': panel.operator_review.model_dump(mode='json') if panel.operator_review and panel.observation_current else None,
        'verification_attempts': panel.trial_details.get('verification_attempts', {}),
        'as_of': panel.now.isoformat(),
        'source_errors': panel.source_errors,
        'rows': [
            {'key': row.key, 'label': row.label, 'value': row.value,
             'status': delivery.row_status(panel, row), 'detail': row.detail,
             'current': delivery.row_current(panel, row),
             'original_status': row.effective_status(panel.now),
             'operational_fact': row.operational_fact.model_dump(mode='json') if delivery.row_current(panel,row) and row.operational_fact is not None else None,
             'as_of': row.as_of.isoformat() if row.as_of else None,
             'stale': row.is_stale(panel.now), 'future': row.is_future(panel.now),
             'required_current': row.required_current,
             'shadow_book': row.shadow_book.model_dump(mode='json') if delivery.row_current(panel,row) and row.can_show_shadow_book(panel.now) else None,
             'paper_plan': row.paper_plan.model_dump(mode='json') if delivery.row_current(panel,row) and row.can_show_paper_plan(panel.now) else None,
             'paper_account': row.paper_account.model_dump(mode='json') if delivery.row_current(panel,row) and row.can_show_paper_account(panel.now) else None,
             'order_outcomes': [item.model_dump(mode='json') for item in row.visible_order_outcomes(panel.now)] if delivery.row_current(panel,row) else [],
             'trading_run': row.trading_run.model_dump(mode='json') if delivery.row_current(panel,row) and row.can_show_trading_run(panel.now) else None,
             'preparation': row.preparation.model_dump(mode='json') if delivery.row_current(panel,row) and row.can_show_preparation(panel.now) else None,
             'source_publication_version': row.source_publication_version,
             'source_session': row.source_session,
             'feed_readiness': row.feed_readiness, 'paper_alignment': row.paper_alignment,
             'valid_until': row.valid_until.isoformat() if row.valid_until else None,
             'recovery': row.recovery.to_dict(panel.now) if row.recovery else None,
             'color': delivery.row_color(panel, row)}
            for row in panel.rows],
        'trial_details': panel.trial_details,
        'trial_history': panel.trial_history,
    }


def preflight(panel):
    """Discard output after exercising HTTP's actual pure server projections."""
    from sentinel.panel.render import render
    json.dumps(public_payload(panel), ensure_ascii=False, allow_nan=False)
    render(panel)
