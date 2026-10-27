"""A live atomic publisher explains unavailability, never financial readiness."""
from datetime import datetime, timezone

from sentinel import source_publication_wait
from sentinel.feed import store
from sentinel.panel import model, observer_codec


# Public compatibility aliases; operational and panel callers share one proof.
PROOF_SQL = source_publication_wait.PROOF_SQL
deadline_from_record = source_publication_wait.deadline_from_record


def observe(database_url, include_paper, expected_key):
    """Called only for a real exhausted CorpusLockUnavailable refusal."""
    from sentinel.panel import read_projection
    if read_projection.subject_for(database_url,include_paper)!=expected_key:
        raise ValueError('publication wait subject changed before observation')
    proof=source_publication_wait.observe(database_url,now=datetime.now(timezone.utc))
    if proof is None:
        return None
    decision,deadline,now=proof.decision_session,proof.deadline,proof.observed_at
    labels=({'paper_reconciliation':'Alpaca PAPER mirror'} if include_paper else {
        'shadow_verification':'Certified shadow strategy','shadow_nav':'Certified shadow NAV',
        'shadow_return':'Certified strategy return','exposure':'Exposure','book':'Book','terminals':'Terminals'})
    rows=[model.Row(key,label,f'WAITING FOR {decision} DATA PUBLICATION',model.WARN,
        'A live atomic source writer owns this preparation; current portfolio verification '
        'and values are unavailable. Original deadline '+deadline.isoformat(),
        as_of=now,required_current=True,valid_until=deadline,
        recovery=model.RecoveryEvidence(phase='SOURCE_PUBLICATION',automatic=True,deadline=deadline))
        for key,label in labels.items()]
    result=observer_codec.pack(rows,[],observed_at=now)
    if read_projection.subject_for(database_url,include_paper)!=expected_key:
        raise ValueError('publication wait subject changed during observation')
    return result
