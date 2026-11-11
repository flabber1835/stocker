"""Remove an unused read while retaining the actual stage's fresh input."""
import pytest

from tests.scripts.test_sentinel_local_delivery_coordinator import model,operation  # noqa: F401


def test_each_stage_keeps_its_used_fresh_environment_read_without_the_discarded_copy(operation):
    host,journal,delivery=operation
    reads=[];original=host.load_values
    def load():
        reads.append(journal.read()['stage'])
        return original()
    host.load_values=load
    assert delivery.step()['stage']=='PREFLIGHT_PASS'
    assert reads==['NEW']
    reads.clear()
    assert delivery.step()['stage']=='DRAIN_REQUESTED'
    assert reads==['PREFLIGHT_PASS']
    reads.clear()
    host.values['SECRET']='new configuration'
    with pytest.raises(model.DeliveryRefused,match='NON_RUNTIME_CONFIGURATION_CHANGED'):
        delivery.step()
    assert reads==['DRAIN_REQUESTED']
    assert journal.read()['stage']=='DRAIN_REQUESTED'
    assert not any(isinstance(call,tuple) and call[0]=='stop' for call in host.calls)
