"""Explicit previously acknowledged baseline for presentation-only fixtures."""
from dataclasses import replace
from sentinel.panel.model import Panel
from sentinel.panel.review_model import OperatorReview


def reviewed_panel(*args, **kwargs):
    panel=Panel(*args, **kwargs)
    return replace(panel,operator_review=OperatorReview(scope='a'*64,head=1,reviewed_head=1,
        status='CLEAN',observed_at=panel.now,reviewed_at=panel.now))
