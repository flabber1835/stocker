"""No local historical controller/account computation in numerical helpers."""
import pytest
from pathlib import Path
from system_campaign_numeric import run,controller_paths,value_paths
from system_campaign_numeric_review import review


@pytest.mark.parametrize('entry',('run','controllers','values','review'))
def test_historical_entries_refuse_before_financial_import_or_output(monkeypatch,tmp_path,entry):
    monkeypatch.delenv('FULL_SYSTEM_HOSTED',raising=False)
    destination=tmp_path/'must-not-exist'
    with pytest.raises(ValueError,match='HOSTED_JOINT_NUMERICAL_ONLY'):
        if entry=='run':run(Path('/missing-evidence'),destination)
        elif entry=='controllers':controller_paths([],None,None,{},destination,{})
        elif entry=='values':value_paths(Path('/missing-evidence'),{},[],None,{},destination)
        else:review(Path('/missing-core'),Path('/missing-numeric'),destination)
    assert not destination.exists()
