"""Actual frozen packets and unheld canonical operation; hosted qualification only."""
import system_campaign_close_gate as original
from system_campaign_pxd_facts import contract,PRIVATE
from system_campaign_pxd_reuse import rewritten


def qualification_body():
    return rewritten(original.qualify,bindings=dict(contract=contract,PRIVATE=PRIVATE),
        fraction_terms=True,preopen=True,replacements={
            'close-canonical-qualification.json':'pxd-canonical-qualification.json',
            'ACTUAL_PACKETS_AND_UNHELD_CLOSE_SCOPE_QUALIFIED':'ACTUAL_PACKETS_AND_UNHELD_PXD_SCOPE_QUALIFIED'})


def qualify(out,cp,loaded,old_objects,request):
    return qualification_body()(out,cp,loaded,old_objects,request)
