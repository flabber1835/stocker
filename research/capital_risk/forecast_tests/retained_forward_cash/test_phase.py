"""New source authority and immutable adopted input scope, DATA only."""
import ast,json
from pathlib import Path
import system_campaign_financial_future as future
import system_campaign_financial_partial as partial
import system_campaign_retained_forward_cash as retained

def test_new_may_phase_uses_separate_MSP_primary_and_no_new_supplemental_adoption():
    codec,name,terms=future.selected('P05',cursor='2022-05-31')
    assert name=='system-campaign-p05-own1111-msp-explicit-cash-input-v3.json'
    assert [t['ticker'] for t in terms]==['MSP']
    term,=terms
    assert term['recognition_rule']=='CONFIRMED_PREOPEN_COMPLETION'
    assert (term['native_session'],term['last_trading_session'],term['added']['session'])==('2022-06-22','2022-06-22','2022-06-23')
    assert term['added']['cash_per_share']==35.5
    assert term['primary_extraction']['no_stock_or_contingent_rights_in_common_consideration'] is True
    assert future.supplemental_selection('P05','2022-05-31')==([],[])
    assert codec.catalog['parent_root_admission_sha256']==partial.root_spec('P05','402b9ce10942fca4dcaac829303c6426a83a6a894ecf35d9cf472c4d84a8bb8d')['root_admission_sha256']

def test_observer_plan_selects_only_exact_existing_adopted_descriptor_and_preserves_all14():
    spec=partial.root_spec('P05','402b9ce10942fca4dcaac829303c6426a83a6a894ecf35d9cf472c4d84a8bb8d');cp=dict(repairs=spec['repairs'])
    plan,=retained.selected(cp,spec)
    assert len(cp['repairs'])==14 and cp['repairs'][-1]==plan['descriptor']
    assert plan['terms_count']==26 and len(plan['original_observer_ast'])==10
    assert retained.selected(cp,dict(spec,arm='P03'))==[]
    assert retained.selected(dict(repairs=cp['repairs'][:-1]),spec)==[]

def test_single_observer_preserves_entire_original_advance_and_terminal_AST():
    plan,=retained.plans();Original=retained.observer_class(plan)
    for name in ('advance','terminal','__enter__','__exit__'):
        assert getattr(Original,name) is getattr(future.ActualEvents,name)
    tree=ast.parse(Path(partial.__file__).read_bytes())
    fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='financial_inputs')
    assert 'with retained_cash_context(root, parent, output, spec)' in ast.unparse(fn)
