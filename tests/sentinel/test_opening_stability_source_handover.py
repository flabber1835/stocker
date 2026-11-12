"""Verify the exact deployed predecessor and sealed opening stability delta."""
import hashlib
import json

from sentinel import runtime_admission as admission, url_selected_source_basis as basis
from tests.support.source_history import pre_market_history


def test_opening_stability_preserves_installed_source_and_earlier_history():
    profile = basis._profile()
    revision = '75b7c14f32f2e710561ef86a2d3d0782a019b355'
    assert basis.OPENING_STABILITY_PREDECESSOR_REVISION == revision
    before = profile['retained_predecessors'][revision]['files']
    assert admission.source_closure(before) == '81e23cc8b17e0ad3b754e1b972b2bbe3f3927419fc19115ec0e6dfd15ad1f0e5'
    current = admission._source_files(basis.PROFILE.parent)
    actual = profile['retained_predecessors'][basis.MARKET_BUY_PREDECESSOR_REVISION]['files']
    assert basis.predecessor_view(current, previous=actual) == actual
    assert set(actual) == set(before)
    assert {name for name in actual if actual[name] != before[name]} == set(['execution/account_status.py', 'execution_collector.py', 'panel/authority_reader.py', 'panel/delivery.py', 'panel/presentation.py', 'panel/render.py', 'panel/sources.py', 'panel/styles.py', 'panel/verification_service.py', 'url_selected_source_basis.py'])
    assert basis.predecessor_view(current, previous=before) == before
    earlier = {key: value for key, value in pre_market_history(profile).items() if key not in {revision}}
    raw = json.dumps(earlier, sort_keys=True, separators=(',', ':')).encode()
    assert hashlib.sha256(raw).hexdigest() == '366078d68b4b986b87d4d1444a8c9cc076c3c1c9f289f2594a25c7c5602e2665'
    current['panel/verification_service.py'] = '0' * 64
    assert basis.predecessor_view(current, previous=before) is current
