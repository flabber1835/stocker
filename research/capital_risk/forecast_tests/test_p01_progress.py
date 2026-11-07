import importlib.util
from pathlib import Path
from types import SimpleNamespace
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location('progress', ROOT / 'p01_iac_namespace_continue.py')
progress = importlib.util.module_from_spec(spec); spec.loader.exec_module(progress)


def episode(q='86', **kw):
    return dict(security_id=progress.SID, current_shares=q, initial_shares=q, exit_pending=False, **kw)


def prior(episodes=None, pending=None):
    return SimpleNamespace(wealth_core={'episodes': {'0': episode()} if episodes is None else episodes},
                           pending=[] if pending is None else pending, median5={'selected': [progress.SID]})


def test_holder_cent_floor_and_rate_are_not_claimed_market_vwap():
    result = progress.settlement([episode()])
    assert result['whole'] == 47 and result['fraction'] == '3/10'
    assert result['modeled_cash'] == '2197/100'
    assert result['observed_contract_vwap'] is None
    assert result['allocation_rate'] * .3 == 21.97


def test_holder_aggregation_precedes_rounding():
    assert progress.settlement([episode('43'), episode('43')]) == progress.settlement([episode('86')])


@pytest.mark.parametrize('quantity', ['0', '-1', '0.1'])
def test_invalid_or_zero_whole_deliveries_refuse(quantity):
    with pytest.raises(ValueError): progress.settlement([episode(quantity)])


def test_integral_entitlement_does_not_fabricate_cash():
    value = progress.settlement([episode('20')])
    assert value['whole'] == 11 and value['fraction'] == '0' and value['modeled_cash'] == '0'
    assert value['allocation_rate'] is None


def codec():
    return progress.EstimateCodec({'run': {'state': {'wealth_core': {'episodes': {'0': episode()}}}}})


def action(): return {'source_security_id': progress.SID}


def test_actual_scope_accepts_only_unchanged_source_holdings():
    assert codec().scope(prior(), action())['episodes']['0'] == episode()


@pytest.mark.parametrize('changed', ['pending', 'exit', 'quantity', 'reference'])
def test_scope_falsifiers(changed):
    value = prior()
    if changed == 'pending': value.pending.append({'security_id': progress.SID})
    elif changed == 'exit': value.wealth_core['episodes']['0']['exit_pending'] = True
    elif changed == 'quantity': value.wealth_core['episodes']['0']['current_shares'] = '87'
    else: value.wealth_core['episodes']['0']['initial_shares'] = '87'
    with pytest.raises(ValueError, match='EXACT_QUALIFIED_HOLDINGS'): codec().scope(value, action())


def test_guard_removal_falsifier():
    # A removed pending guard makes the same hostile input pass, proving the
    # targeted falsifier discriminates the behavior it is intended to protect.
    value = prior(pending=[{'security_id': progress.SID}])
    with pytest.raises(ValueError): codec().scope(value, action())
    source = Path(progress.__file__).read_text()
    broken = source.replace(" and not any(p['security_id'] == SID for p in value['pending'])", '')
    assert source != broken
    namespace = dict(progress.__dict__)
    exec(compile(broken, '<pending-guard-removed>', 'exec'), namespace)
    weakened = namespace['EstimateCodec']({'run': {'state': {'wealth_core': {'episodes': {'0': episode()}}}}})
    assert weakened.scope(value, action())


def test_model_rejects_invented_observed_price_or_changed_identity():
    value = dict(schema=progress.SCHEMA, earliest_affected_session=progress.EVENT,
                 predecessor_checkpoint_sha256='a'*64, root_admission_sha256=progress.ROOT_ADMISSION,
                 source_security_id=progress.SID, delivered_security_id=progress.TARGET,
                 exchange_ratio='11/20', estimated_delivered_share_basis='73.2545',
                 basis='SEC_RSU_CASH_40_29_DIVIDED_BY_0_55_ESTIMATE_NOT_OBSERVED_VWAP',
                 fractional_cash_rounding='HOLDER_FLOOR_TO_CENTS',
                 reference_policy='EXISTING_CANONICAL_INITIAL_REFERENCE_ROUNDING_QUALIFIED_AT_EVENT', sources=[])
    assert progress.EstimatedInput.model_validate(value)
    for field, changed in [('basis', 'OBSERVED_VWAP'), ('estimated_delivered_share_basis', 73.2545),
                           ('delivered_security_id', 'wrong'), ('exchange_ratio', '1')]:
        with pytest.raises(ValueError): progress.EstimatedInput.model_validate({**value, field: changed})


def test_unrelated_action_still_uses_existing_strict_scope(monkeypatch):
    import p01_factual_batch_guard
    sentinel = object(); seen = []
    def original(state, record): seen.append((state, record)); return sentinel
    monkeypatch.setattr(p01_factual_batch_guard, 'require_scope', original)
    state = prior(); record = {'source_security_id': 'another'}
    assert codec().scope(state, record) is sentinel and seen == [(state, record)]
