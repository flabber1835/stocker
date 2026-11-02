"""PXD stopped-window absence and exact ordinary-share notional observation."""
import system_campaign_close_review as original
from system_campaign_pxd_scope import SCHEMA,WATCH,active,require_absent,require_intents,review_guards
from system_campaign_pxd_facts import contract,PRIVATE
from system_campaign_pxd_basis import validate
from system_campaign_pxd_reuse import rewritten


def require_closing_notional(certificate,row,sid,anchor,delivered_close,day,native):
    fn=rewritten(original.require_closing_notional,bindings={},fraction_terms=True)
    return fn(certificate,row,sid,anchor,delivered_close,day,native)


def review_body():
    return rewritten(original.review,bindings=dict(SCHEMA=SCHEMA,active=active,
        require_absent=require_absent,require_intents=require_intents,review_guards=review_guards,
        contract=contract,PRIVATE=PRIVATE,validate=validate,require_closing_notional=require_closing_notional),
        preopen=True,replacements={
            'research.guarded-close-conversion-watch/1':WATCH,
            'ACTUAL_GUARDED_CLOSE_WINDOW_REVIEWED':'ACTUAL_UNOWNED_PXD_PREOPEN_WINDOW_REVIEWED'})


def review(root,cp,output):
    return review_body()(root,cp,output)
