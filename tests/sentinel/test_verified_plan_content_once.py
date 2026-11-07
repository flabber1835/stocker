"""The combined plan read earns one shadow proof, without cross-command reuse."""
import inspect
from types import SimpleNamespace

from sentinel import dual_reconciliation as dual
from sentinel.paper import preparation
from tests.sentinel.test_dual_reconciliation import _plan, _result


def test_combined_reader_returns_same_verified_intent_and_sizing_once(monkeypatch):
    calls=[]
    intent=_result()
    def verify(*a,**k):calls.append('shadow');return intent
    def sizing(*a,**k):
        assert k['expected_shadow_result'] is intent
        calls.append('sizing')
        return dict(authority_sha256='d'*64,plan_fingerprint='e'*64)
    monkeypatch.setattr(dual.shadow_runtime,'verified_shadow_status',verify)
    monkeypatch.setattr(dual.shadow_segments,'active_segment',lambda *a:SimpleNamespace(index=0,marker_sha256=None))
    monkeypatch.setattr(dual.dual_plan_authority,'rederive_plan',sizing)
    actual, report=dual.verified_plan_intent(None,plan=_plan(),observation_id='primary',
        starting_cash='50000',binding=object(),rollout_state=object())
    assert actual is intent and report['verdict']=='MATCH'
    assert calls==['shadow','sizing']
    dual.require_plan_matches_verified_shadow(None,plan=_plan(),observation_id='primary',
        starting_cash='50000',binding=object(),rollout_state=object())
    assert calls==['shadow','sizing','shadow','sizing']


def test_current_paper_reader_uses_combined_operation_without_second_shadow_read():
    source=inspect.getsource(preparation.current_paper_plan)
    assert 'result, dual_match = dual_reconciliation.verified_plan_intent(' in source
    assert 'dual_reconciliation.verified_shadow_intent(' not in source
