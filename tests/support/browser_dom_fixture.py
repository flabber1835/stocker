"""Export synthetic renderer inputs for the isolated browser contract test.

Run through stdin in the same runtime image that serves the browser fixture.
No database, credentials, filesystem state or broker observations are consumed.
"""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json

from sentinel.panel import model, review_controls
from sentinel.panel.render import STYLE_ASSET, render
from sentinel.panel.presentation import dashboard_health
from sentinel.panel.review_model import OperatorReview
from sentinel.paper_plan_preview import PlanPreview


now = datetime(2026, 11, 8, 20, tzinfo=timezone.utc)
opening = now + timedelta(days=1, hours=22, minutes=4)
plan = PlanPreview(cycle_id='browser-only-cycle', plan_id='browser-only-plan',
    decision_session=now.date(), effective_session=opening.date(),
    execute_at=opening+timedelta(minutes=1), execution_open_at=opening,
    created_at=now, observation_at=now, legs=[])
book = model.ShadowBook(session=now.date().isoformat(), cash=Decimal(100),
    receivables=Decimal(0), nav=Decimal(100), pending_operations=0, holdings=[],
    slots=[model.ShadowSlot(slot_id=index, state='COOLING', cooldown_total=21,
        cooldown_elapsed=9, cooldown_remaining=12) for index in range(20)])
rows = [
    model.Row('paper_plan', 'Browser plan fixture', 'ready', model.OK,
        as_of=now, valid_until=opening, paper_plan=plan),
    model.Row('book', 'Browser book fixture', '0/20', model.OK,
        as_of=now, valid_until=opening, shadow_book=book),
]
page = model.Panel(now=now, rows=rows,
    operator_review=OperatorReview(scope='a'*64, head=1, reviewed_head=1,
        status='CLEAN', observed_at=now, reviewed_at=now))
negative = replace(page, rows=[*rows, model.Row('broker', 'Browser negative fixture',
    'UNAVAILABLE', model.FAIL, as_of=now, required_current=True)])
partial = replace(page, observation_current=False,
    observation_changed_scopes=('PAPER',))
assert dashboard_health(page)['color'] == 'green' and dashboard_health(negative)['color'] == 'red'
assert dashboard_health(partial)['color'] == 'blue'


def publication(subject, at, end):
    return render(replace(subject, now=at, observation_generated_at=at,
        observation_valid_until=end), refresh_seconds=5)


arrival = now + timedelta(milliseconds=3405)
short_receipts = {}
for residual_ms in (3360, 1550, 670):
    expiry = arrival + timedelta(milliseconds=residual_ms)
    early = arrival + timedelta(milliseconds=residual_ms // 2)
    received = (early + timedelta(milliseconds=3405) if residual_ms == 3360
                else expiry + timedelta(milliseconds=400) if residual_ms == 1550 else early)

    short_receipts[residual_ms] = dict(
        arrival=arrival.isoformat(), received=received.isoformat(),
        initial=publication(page, now, expiry), same=publication(page, early, expiry),
        next=publication(negative if residual_ms == 1550 else page,
            received, received + timedelta(seconds=20)))
partial_expiry = arrival + timedelta(milliseconds=670)
partial_early = arrival + timedelta(milliseconds=335)
partial_received = partial_expiry + timedelta(milliseconds=20)
short_partial = dict(
    arrival=arrival.isoformat(), received=partial_received.isoformat(),
    initial=publication(partial, now, partial_expiry),
    same=publication(partial, partial_early, partial_expiry),
    next=publication(partial, partial_received, partial_received + timedelta(seconds=20)))
review_event = dict(at=now.isoformat(), kind='REVIEW',
    details={'alert_ids':['synthetic-historical-alert']})
review_page = replace(page, rows=[*rows, model.automation_alerts_row(
    installed=True, pending=0, dead_letter=0, unacknowledged=1, as_of=now,
    incidents=['Recorded historical alert; current worker is healthy.'])])
review_initial = replace(review_page, operator_review=OperatorReview(
    scope='a'*64, head=2, reviewed_head=1, status='REVIEW',
    observed_at=now, reviewed_at=now, events=[review_event]))
review_ready_at = now + timedelta(seconds=5)
review_ready = replace(review_page, operator_review=OperatorReview(
    scope='a'*64, head=2, reviewed_head=1, status='REVIEW',
    observed_at=review_ready_at, reviewed_at=now,
    events=[review_event], token='browser-qualified-review-view'))
review_done_at = review_ready_at
review_done = replace(review_page, rows=[*rows, model.automation_alerts_row(
    installed=True, pending=0, dead_letter=0, unacknowledged=0, as_of=review_done_at)],
    operator_review=OperatorReview(scope='a'*64, head=3, reviewed_head=3,
        status='CLEAN', observed_at=review_done_at, reviewed_at=review_done_at,
        events=[dict(at=review_done_at.isoformat(), kind='ACKNOWLEDGED',
                     details={'alert_ids':['synthetic-historical-alert']})]))
assert dashboard_health(review_initial)['color'] == 'amber'
assert dashboard_health(review_done)['color'] == 'green'
review_documents = dict(initial=publication(review_initial, now, now+timedelta(seconds=20)),
    ready=publication(review_ready, review_ready_at, review_ready_at+timedelta(seconds=20)),
    done=publication(review_done, review_done_at, review_done_at+timedelta(seconds=20)))
events = [dict(at=now.isoformat(), kind='FAILED',
               details={'reason': 'Opening verifier failure' if sequence == 2 else f'Event {sequence}'})
          for sequence in range(22, 1, -1)]
history_args = dict(scope='a'*64, head=22, reviewed_head=1)
paged_review = OperatorReview(**history_args, status='REVIEW', observed_at=now, reviewed_at=now,
                              events=events[:20], token='unconsumed-history-view')
history_documents = dict(dashboard=publication(replace(review_page, operator_review=paged_review),
                                               now, now+timedelta(seconds=20)),
                         first=review_controls.history_page(events[:20], **history_args,
                                                            first=22, stylesheet=STYLE_ASSET),
                         last=review_controls.history_page(events[20:], **history_args,
                                                           first=2, stylesheet=STYLE_ASSET))
def delivery_event(sequence, offset, kind, status, *, phase=None):
    key = 'alert_dispatcher'
    at = now - timedelta(minutes=offset)
    evidence = {key: dict(code='ROW_CONDITION', effective_status=status, recovery_phase=phase)}
    details = dict(conditions=[] if kind == 'RECOVERED' else [key],
                   previous=[key] if kind == 'RECOVERED' else [], evidence=evidence)
    return dict(sequence=sequence, kind=kind, at=at.isoformat(), details=details)


delivery_history = [
    delivery_event(6, 3, 'RECOVERED', 'ok'),
    delivery_event(5, 4, 'FAILED', 'fail'),
    delivery_event(4, 15, 'RECOVERED', 'ok'),
    delivery_event(3, 16, 'RECOVERED', 'warn', phase='ALERT_TRANSPORT'),
    delivery_event(2, 17, 'FAILED', 'fail'),
]
mobile_history = publication(replace(review_page, operator_review=OperatorReview(
    scope='a'*64, head=6, reviewed_head=1, status='REVIEW', observed_at=now,
    reviewed_at=now-timedelta(hours=1), events=delivery_history,
    token='mobile-qualified-review-view')), now, now+timedelta(seconds=20))
close_at = datetime(2026, 11, 20, 21, 15, tzinfo=timezone.utc)
close_until = close_at + timedelta(seconds=20)
close_feed = model.feed_row(frontier='2026-11-20', sessions_behind=0, ready=None,
    checks_passed=0, checks_total=0, as_of=close_at, publication_version=26)
close_feed = replace(close_feed, valid_until=close_until, recovery=model.RecoveryEvidence(
    phase='SHADOW_ATTESTATION', automatic=True, deadline=close_until))
close_page = model.Panel(now=close_at, local_paper_mode=True, rows=[close_feed,
    model.Row('shadow_worker', 'Strategy worker', 'Running', model.OK, as_of=close_at,
        required_current=True, valid_until=close_until),
    model.Row('broker', 'Broker', 'Independent broker observation', model.OK, as_of=close_at,
        required_current=True, valid_until=close_until),
    model.Row('paper_plan', 'Next plan', 'Not prepared', model.PENDING)],
    operator_review=OperatorReview(scope='a'*64, head=1, reviewed_head=1, status='CLEAN',
        observed_at=close_at, reviewed_at=close_at))
close_partial = replace(close_page, observation_current=False,
    observation_changed_scopes=('PAPER',), observation_display_keys=('broker',))
close_documents = dict(now=close_at.isoformat(),
    partial=publication(close_partial, close_at, close_until),
    verifying=publication(close_page, close_at+timedelta(seconds=5), close_until))
print(json.dumps(dict(now=now.isoformat(),
    green=render(page, refresh_seconds=5), red=render(negative, refresh_seconds=5),
    green_compact=render(page, refresh_seconds=5, compact=True),
    red_compact=render(negative, refresh_seconds=5, compact=True),
    short_receipts=short_receipts, short_partial=short_partial,
    review_documents=review_documents, history_documents=history_documents,
    mobile_history=mobile_history, close_documents=close_documents)))
