"""Bind a separate reviewed semantic proof without relabelling physical books."""
import gzip,hashlib,json
from pathlib import Path
from full_system_benchmark import need
from system_campaign_basis import basis

PROOF_SOURCE=Path('/driver/system_campaign_equivalence_run.py')
sha=lambda raw:hashlib.sha256(raw).hexdigest()


def admitted_basis(core,complete,proof=None):
    if proof is None:
        common_sha,common=basis(core,complete)
        return common_sha,common,{'mode':'PHYSICAL_COMMON_FACTUAL_BASIS'}
    certificate=json.loads((proof/'independent-review-stop/basis-equivalence-review.json').read_bytes())
    worker=json.loads((proof/'basis-equivalence-worker.json').read_bytes())
    spec=json.loads((proof/'spec.json').read_bytes())
    cp=json.loads(gzip.decompress((proof/'book/checkpoint.json.gz').read_bytes()))
    review=json.loads((proof/'independent-review-stop/core-review.json').read_bytes())
    need(spec['arm']=='P00' and spec['complete_outer_sha256']==complete['sha256']
         and complete['completed']==2156 and complete['source_cursor']=='2026-07-31',
         'SEMANTIC_PROOF_EXACT_COMPLETE_DEFAULT_PREDECESSOR')
    need(certificate['schema']=='research.system-campaign-basis-equivalence/1'
         and certificate['independent_review_passed'] is True
         and certificate['independent_review_required'] is False
         and worker['independent_review_required'] is True
         and {k:v for k,v in certificate.items() if k not in
              ('independent_review_passed','independent_review_required','source_file_sha256')}
             =={k:v for k,v in worker.items() if k!='independent_review_required'},
         'SEMANTIC_PROOF_ACTUAL_INDEPENDENT_CERTIFICATE')
    need(certificate['source_file_sha256']==sha(PROOF_SOURCE.read_bytes())
         and (core/'source-bindings.json').read_bytes()==(proof/'source-bindings.json').read_bytes()
         and cp['base']==complete['base'],'SEMANTIC_PROOF_IDENTICAL_FULL_FINANCIAL_SOURCE')
    need(certificate['old_complete_checkpoint_sha256']==complete['sha256']
         and certificate['new_cutoff_checkpoint_sha256']==cp['sha256']
         and certificate['canonical_state_sha256']==cp['run']['state_sha256']
         and certificate['cutoff']==cp['source_cursor']=='2019-04-30'
         and certificate['complete_recurrence_state_exact'] is True
         and certificate['all_remaining_inputs_unchanged_by_finite_date_support'] is True
         and certificate['old_physical_lineage_relabelled'] is False
         and certificate['old_complete_physical_lineage_unchanged'] is True,
         'SEMANTIC_PROOF_ACTUAL_FULL_RECURRENCE_BINDINGS')
    need(review['checkpoint_sha256']==cp['sha256'] and review['all_prefixes_verified'] is True
         and review['all_daily_factors_and_chains_verified'] is True,
         'SEMANTIC_PROOF_ACTUAL_CANONICAL_PREFIX_REVIEW')
    common_sha,common=basis(proof,cp)
    need(common_sha==certificate['common_factual_basis_sha256']
         and json.loads((proof/'common-factual-basis.json').read_bytes())==common,
         'SEMANTIC_PROOF_ACTUAL_COMPLETE_COMMON_BASIS')
    return common_sha,common,{'mode':'INDEPENDENTLY_REVIEWED_BOUNDED_EQUIVALENCE',
        'certificate_sha256':sha((proof/'independent-review-stop/basis-equivalence-review.json').read_bytes()),
        'original_complete_checkpoint_sha256':complete['sha256'],
        'actual_corrected_cutoff_checkpoint_sha256':cp['sha256'],
        'original_physical_book_unchanged':True,'full_corrected_physical_rerun_claimed':False}
