"""Fresh execution presentation over an authenticated, still-valid shadow proof."""
from dataclasses import replace
from datetime import timedelta

from sentinel.panel import model


def project(conn, rows, *, observed_at, valid_until, now):
    from sentinel.panel import sources
    selected = {row.key: row for row in rows}
    shadow = selected['shadow_verification']
    if shadow.status != model.OK:
        return rows  # Preserve negative/source-wait evidence and its original clocks.
    book = selected['book']
    basis = book.shadow_projection
    if (basis is None or book.shadow_book is None
            or basis.session != book.shadow_book.session
            or basis.nav != book.shadow_book.nav
            or basis.slots_total != len(book.shadow_book.slots)
            or not observed_at-timedelta(seconds=600) <= basis.observed_at <= observed_at
            or not observed_at <= now <= valid_until):
        raise ValueError('authenticated shadow display basis unavailable or expired')
    plan, rollout = sources._current_plan(conn), sources._rollout_state(conn)
    if plan is not None and plan['decision_session'] != basis.session:
        plan = None
    view = dict(session=basis.session, updated_at=basis.observed_at,
        decision=dict(session=basis.session, target_core_exposure=str(basis.target_core_exposure)))
    exposure = sources._exposure_row(view, plan, rollout,
        state_error=None, plan_error=None, rollout_error=None, valid_until=valid_until)
    selected['exposure'] = replace(exposure, as_of=now, required_current=True,
        valid_until=valid_until)
    current = model.book_row(available=True, slots_used=basis.slots_used,
        slots_total=basis.slots_total, nav=float(basis.nav), cash=float(basis.cash),
        blocked=basis.blocked, unresolved_terminals=basis.unresolved,
        pending_actions=basis.pending,
        unpriced_securities=len(plan['unpriced_securities']) if plan else None,
        as_of=book.as_of)
    selected['book'] = replace(book, value=current.value, status=current.status,
        detail=current.detail, operational_fact=current.operational_fact)
    return [selected[row.key] for row in rows]
