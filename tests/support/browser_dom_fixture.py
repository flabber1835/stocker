"""Export synthetic renderer inputs for the isolated browser contract test.

Run through stdin in the same runtime image that serves the browser fixture.
No database, credentials, filesystem state or broker observations are consumed.
"""
import base64
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path

from sentinel.panel import model
from sentinel.panel.render import render
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
assert dashboard_health(page)['color'] == 'green' and dashboard_health(negative)['color'] == 'red'
print(json.dumps(dict(now=now.isoformat(),
    png=base64.b64encode(Path('sentinel/panel/static/caesars-palace-512.png').read_bytes()).decode(),
    green=render(page, refresh_seconds=5), red=render(negative, refresh_seconds=5))))
