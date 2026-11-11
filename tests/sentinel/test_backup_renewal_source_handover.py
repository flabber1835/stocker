"""Only backup presentation changes; all predecessor and economic pins remain."""
import hashlib,json
from sentinel import runtime_admission as admission,url_selected_source_basis as basis

def test_exact_installed_backup_projection_predecessor_is_preserved():
    profile=basis._profile();revision=basis.BACKUP_RENEWAL_PREDECESSOR_REVISION
    assert revision=='5ea4452570ebf526714fe64320001fb275418f1a'
    before=profile['retained_predecessors'][revision]['files']
    actual=profile['retained_predecessors'][basis.OPENING_OBSERVATION_PREDECESSOR_REVISION]['files']
    assert len(before)==len(actual)==464
    assert admission.source_closure(before)=='b8dc59db31e58612c7d3f633657f6a6558b5fde01af5881c28eae293f1f6c26f'
    assert {n for n in actual if actual[n]!=before[n]}=={
        'panel/model.py','panel/presentation.py','panel/sources.py','url_selected_source_basis.py'}
    assert basis.predecessor_view(admission._source_files(basis.PROFILE.parent),previous=before)==before
    assert len(profile['retained_predecessors'])==42 and profile['authority_effect']=='NONE'
