"""Compose the existing eight input codecs; no new facts or proof certificate."""
from contextlib import ExitStack, contextmanager
from pathlib import Path

from full_system_core import hosted
from system_campaign_discovery_context import need


@contextmanager
def retained_inputs(root, checkpoint, output):
    hosted()
    import system_campaign_p02_q4_cash_run as q4
    import system_campaign_p02_unconsumed_cash_run as retained
    from system_campaign_winter2025_cash_context import CashRegistry
    from system_campaign_chinook_facts import hydrate as hydrate_chinook
    from system_campaign_outcome_facts import retained as outcome, evidence as outcome_evidence
    from system_campaign_outcome_input import InputCodec as OutcomeCodec
    root,output=Path(root),Path(output)
    (output/'book/predecessor-checkpoints').mkdir(parents=True,exist_ok=True)
    prior=q4.prior
    with CashRegistry(), retained.retained_scopes(root,checkpoint,output), ExitStack() as stack:
        v1,spin,alder,_=prior.retained(checkpoint,root,output)
        native_z=prior.retained_zogenix(root,output)
        completion=prior.retained_completion(root,checkpoint,output)
        native_a,_=prior.retained_abiomed(root,checkpoint,output)
        amendment=prior.retained_amendment(root,output)
        native_c=hydrate_chinook(root,output)
        model,boundary=outcome(root,checkpoint,output)
        need(model is not None,'DISCOVERY_RETAINED_OUTCOME_INPUT_REQUIRED')
        codecs=(v1,spin,alder,prior.idempotent_dispatch(alder),
            prior.ZogenixCodec(prior.zogenix_evidence(root),native_z),
            prior.InputCodec(prior.evidence(root)),amendment,completion,
            prior.AbiomedCodec(prior.abiomed_evidence(root),native_a),
            prior.ChinookCodec(prior.chinook_evidence(root),native_c),
            OutcomeCodec(outcome_evidence(),boundary))
        for codec in codecs:
            stack.enter_context(codec)
        # No SensorCertificate: the altered path cannot inherit a strict proof.
        yield
