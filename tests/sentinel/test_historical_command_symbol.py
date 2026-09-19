"""Historical labels are provenance; live obligations retain identity checks."""
from types import SimpleNamespace
import pytest
from sentinel.paper.targets import _informational_active_symbols
from sentinel.paper.model import PaperActivationRefused
from sentinel.execution.states import CommandState


@pytest.mark.parametrize('state', [CommandState.FILLED, CommandState.CANCELLED, CommandState.ACKNOWLEDGED])
def test_current_symbol_survives_settled_old_label_only(state):
    old = SimpleNamespace(security_id='permanent', instrument=SimpleNamespace(symbol='OLD'), state=state)
    observation = SimpleNamespace(positions=[SimpleNamespace(
        instrument=SimpleNamespace(security_id='permanent', symbol='NEW'))], orders=[])
    args = dict(active_security_ids={'permanent'}, commands=[old], observation=observation,
                sizing_proof={'canonical_symbols':{'permanent':'NEW'}})
    if state is CommandState.ACKNOWLEDGED:
        with pytest.raises(PaperActivationRefused, match='conflicting canonical symbols'):
            _informational_active_symbols(**args)
    else:
        assert _informational_active_symbols(**args) == {'permanent':'NEW'}
    assert old.instrument.symbol == 'OLD'
