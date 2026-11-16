from decimal import Decimal as D
import gzip
from itertools import product
import json
import math
from pathlib import Path

import numpy as np
import pytest

from research.exposure_oracle import accounting as A, analysis, inputs, search
from research.exposure_oracle.run import Settings, run
from sentinel.feed.rolling_contract import digest

GRID = (D(0), D('.55'), D(1))


def toy_days(seed=7, count=5):
    rng = np.random.default_rng(seed)
    result = []
    for i in range(count):
        cg, cd, bg, bd = [D(str(round(x,5))) for x in
                          (1+rng.normal(0,.04),1+rng.normal(.005,.06),1+rng.normal(0,.001),1+rng.normal(0,.001))]
        result.append(A.Day(f'2021-01-{i+5:02}',cg,cd,cg*cd,bg,bd,bg*bd))
    return result


def enumerate_paths(matrices, initial):
    result = []
    for path in product(range(len(GRID)),repeat=len(matrices)):
        old, wealth, peak, dd = initial,0.,0.,0.
        for day,action in enumerate(path):
            wealth += matrices[day,old,action]
            peak = max(peak,wealth)
            dd = max(dd,peak-wealth)
            old = action
        if math.isfinite(wealth):
            result.append((wealth,-math.expm1(-dd),path))
    return result


@pytest.mark.parametrize('seed',range(12))
def test_search_matches_exhaustive_paths(seed):
    matrices = np.stack([d.matrix(GRID) for d in toy_days(seed)])
    brute = enumerate_paths(matrices,1)
    solution = search.unconstrained(matrices,1,3)
    assert solution.log_wealth == pytest.approx(max(r[0] for r in brute),abs=1e-12)
    for cap in (0.,.01,.03,.08,.2):
        expected = [r for r in brute if r[1] <= cap+1e-13]
        assert search.feasible(matrices,1,cap) == bool(expected)
        actual = search.constrained(matrices,1,cap)
        if not expected:
            assert actual is None
        else:
            assert actual.log_wealth == pytest.approx(max(r[0] for r in expected),abs=1e-12)
            resolved = next(r for r in brute if list(r[2]) == actual.path)
            assert resolved[1] <= cap+1e-12


def test_minimum_drawdown_brackets_exhaustive_minimum():
    matrices = np.stack([d.matrix(GRID) for d in toy_days(19,4)])
    brute = enumerate_paths(matrices,2)
    expected = min(x[1] for x in brute)
    lo,hi = search.minimum_cap(matrices,2,.5)
    assert lo <= expected+1e-12 and hi >= expected-1e-12
    assert hi-lo < 2e-10


def test_unchanged_exposure_preserves_full_session_branch():
    day = A.Day('2021-01-05',D('1.2'),D('.9'),D('1.08'),D('.9'),D('1.2'),D('1.08'))
    net,gross,cost,turn = day.factors(D('.55'),D('.55'))
    assert gross == net == D('1.08') and cost == 1 and turn == 0
    assert gross != (D('.55')*day.core_gap+D('.45')*day.bil_gap)*(D('.55')*day.core_day+D('.45')*day.bil_day)
    assert math.exp(day.matrix(GRID)[1,1]) == pytest.approx(1.08)


def test_switching_at_open_cannot_avoid_prior_overnight_loss():
    day = A.Day('2021-01-05',D('.8'),D('1.1'),D('.88'),D(1),D(1),D(1))
    assert day.factors(D(1),D(0)) == (D('.7992'),D('.8'),D('.999'),D(1))
    assert day.factors(D(0),D(1))[0] == D('1.0989')


def test_initial_funded_deployment_is_fixed():
    day = A.Day('2021-01-05',*[D(1)]*6,fixed=D(0),fixed_net=D('.999'),fixed_cost=D('.999'))
    matrix = day.matrix(GRID)
    assert np.isneginf(matrix[:,1:]).all()
    assert search.unconstrained([matrix],0,3).path == [0]
    with pytest.raises(ValueError,match='deployment is fixed'):
        day.factors(D(0),D('.55'))


@pytest.mark.parametrize('value',['-.01','1.01','NaN','Infinity'])
def test_unlevered_envelope_refuses_invalid_allocations(value):
    with pytest.raises(ValueError):
        A.allocation(value)


def test_only_three_owner_selected_exposures():
    assert A.make_grid(D(0),[D('.55'),D(1)]) == GRID
    with pytest.raises(ValueError,match='only 0%, 55%, and 100%'):
        A.make_grid(D(0),[D('.5')])


def test_drawdown_cap_guard_and_independent_replay():
    matrices = np.array([[[-.2]]])
    assert search.constrained(matrices,0,.1) is None
    assert not search.feasible(matrices,0,.1)
    day = A.Day('2021-01-05',D(1),D('.8'),D('.8'),D(1),D(1),D(1))
    with pytest.raises(ValueError,match='exceeds requested drawdown'):
        A.replay([day],D(1),[D(1)],'2021-01-04',cap=.1)


def test_drawdown_is_from_peak_not_starting_wealth():
    matrices = np.log(np.array([[[2.]],[[.75]]]))
    assert search.constrained(matrices,0,.2) is None
    assert search.constrained(matrices,0,.25).log_wealth == pytest.approx(math.log(1.5))


def test_pareto_dominance_retains_wealth_drawdown_tradeoff():
    wealth = np.array([1.,1.,.8,1.2,1.1])
    depth = np.array([.1,.2,.05,.3,.3])
    keep = search.nondominated(wealth,depth)
    assert set(keep) == {0,2,3}


def test_resource_limit_never_silently_becomes_beam_search():
    matrices = np.stack([d.matrix(GRID) for d in toy_days()])
    with pytest.raises(search.SearchLimit):
        search.constrained(matrices,0,.5,max_labels=1)


def fixture_rows():
    core,nav = D(100),D(50000)
    actions = [D(1),D('.55'),D(0),D(1)]
    dates = ['2021-01-04','2021-01-05','2021-01-06','2021-01-07','2021-01-08']
    days = toy_days(2,4)
    rows = [dict(session=dates[0],strategy=dict(nav=str(nav)),core=dict(nav=str(core)),
        economics=dict(held_allocation='.55',pending_allocation=str(actions[0]),
                       parent_core_close_equity=str(core),strategy_nav=str(nav),last_session=dates[0]),
        decision=dict(target_core_exposure=float(actions[0]),reason='TEST'))]
    for i,(day,action) in enumerate(zip(days,actions)):
        old = D(rows[-1]['economics']['held_allocation'])
        op = core*day.core_gap
        core = op*day.core_day
        # Match the source's canonical float representation at the valuation boundary.
        op,core = D(str(float(op))),D(str(float(core)))
        previous_core = D(rows[-1]['core']['nav'])
        exact_day = A.Day(dates[i+1],op/previous_core,core/op,core/previous_core,
                         day.bil_gap,day.bil_day,day.bil_full)
        net,gross,cost,turn = exact_day.factors(old,action)
        before,nav = nav,nav*net
        pending = actions[i+1] if i+1 < len(actions) else D(1)
        prices = dict(bil_open_adjusted=str(day.bil_gap),bil_close_adjusted=str(day.bil_full),
            bil_open_signal=str(day.bil_gap),bil_close_signal=str(day.bil_full),
            bil_close_unadjusted=str(day.bil_full),bil_previous_close_adjusted='1',bil_previous_session=dates[i])
        economics = dict(held_allocation=str(action),pending_allocation=str(pending),
            parent_core_open_equity=str(op),parent_core_close_equity=str(core),
            bil_open_adjusted=str(day.bil_gap),bil_close_adjusted=str(day.bil_full),
            bil_previous_close_adjusted_current_publication='1',bil_previous_session=dates[i],
            last_session=dates[i+1],initial_deployment=False,strategy_nav=str(nav),
            previous_strategy_nav=str(before),net_factor=str(net),gross_factor=str(gross),
            transaction_cost_factor=str(cost),turnover=str(turn),strategy_prices=prices)
        rows.append(dict(session=dates[i+1],strategy=dict(nav=str(nav)),core=dict(nav=str(core)),
            economics=economics,decision=dict(target_core_exposure=float(pending),reason='TEST'),
            valuation=dict(session=dates[i+1],blocked=False,open_unresolved_security_ids=[],
                resolved_equity=float(core),estimated_equity=float(core),resolved_open_equity=float(op))))
    return rows


def source_fixture(tmp_path):
    source = tmp_path/'source'
    source.mkdir()
    rows = fixture_rows()
    daily = ('\n'.join(json.dumps(r,sort_keys=True) for r in rows)+'\n').encode()
    root = Path(__file__).resolve().parents[2]
    binding = dict(measurement_start=rows[0]['session'],production=dict(files={
        name:inputs.sha((root/name).read_bytes()) for name in ('sentinel/shadow_observation.py','sentinel/formed_economics.py')}))
    identity = json.dumps(dict(binding=binding)).encode()
    payload = dict(binding=digest(binding),cursor=rows[-1]['session'],measured=len(rows),
        outputs={'daily.jsonl':dict(bytes=len(daily),sha256=inputs.sha(daily))})
    checkpoint = gzip.compress(json.dumps(payload).encode(),mtime=0)
    sha = inputs.sha(checkpoint)
    pointer = dict(file=f'checkpoint-{sha}.json.gz',sha256=sha,session=payload['cursor'])
    (source/'identity.json').write_bytes(identity)
    (source/pointer['file']).write_bytes(checkpoint)
    (source/'daily.jsonl').write_bytes(daily+b'UNCOMMITTED WRITER TAIL')
    inputs.write_json(source/'latest-checkpoint.json',pointer)
    return source,daily,rows


def test_actual_matches_canonical_accountant_and_attribution():
    rows = fixture_rows()
    days,initial,actual = A.tape(rows)
    path = A.replay(days,initial,actual,rows[0]['session'])
    expected = D(rows[-1]['strategy']['nav'])/D(rows[0]['strategy']['nav'])
    assert abs(D(path['multiple'])-expected) < D('1e-24')
    oracle = A.replay(days,initial,[D(0)]*len(days),rows[0]['session'])
    result = analysis.attribution(rows,path,oracle)
    assert result['net_log_gap'] == pytest.approx(math.log(float(D(oracle['multiple'])/expected)))
    assert result['daily'][0]['decision_session'] == '2021-01-04'
    assert result['daily'][0]['session'] == '2021-01-05'


def test_wrong_decision_date_refuses():
    rows = fixture_rows()
    rows[0]['economics']['pending_allocation'] = '0'
    with pytest.raises(ValueError,match='decision-to-open'):
        A.tape(rows)


def test_native_full_is_not_mislabeled_as_final_full_during_recovery_wait():
    decision = dict(target_core_exposure=0,native_target_core_exposure=1,
                    ldrc=dict(desired_allocation=0,reason='FULL_RISK_HELD'))
    assert analysis.limiting_mechanism(decision,0) == 'recovery_wait'
    decision['native_target_core_exposure'] = 0
    assert analysis.limiting_mechanism(decision,0) == 'native_severe'


def test_distinct_55_percent_ceiling_mechanisms():
    decision = dict(target_core_exposure=.55,native_target_core_exposure=1,
                    ldrc=dict(desired_allocation=1),owned_impairment=dict(active=True))
    assert analysis.limiting_mechanism(decision,.55) == 'owned_impairment_55'
    decision['ldrc']['desired_allocation'] = .55
    assert analysis.limiting_mechanism(decision,.55) == 'owned_and_divergence_55'
    decision['owned_impairment']['active'] = False
    assert analysis.limiting_mechanism(decision,.55) == 'divergence_55'


def test_snapshot_copies_only_committed_prefix_and_never_changes_writer(tmp_path):
    source,daily,rows = source_fixture(tmp_path)
    before = {p.name:p.read_bytes() for p in source.iterdir()}
    snapshot = tmp_path/'snapshot'
    inputs.capture(source,snapshot)
    assert (snapshot/'daily.jsonl').read_bytes() == daily
    assert {p.name:p.read_bytes() for p in source.iterdir()} == before
    _,selected = inputs.load(snapshot,'2021-01-05','2021-01-07')
    assert [r['session'] for r in selected] == ['2021-01-05','2021-01-06','2021-01-07']
    with pytest.raises(ValueError,match='completed session'):
        inputs.load(snapshot,end='2021-01-11')


def test_snapshot_daily_hash_guard(tmp_path):
    source,daily,_ = source_fixture(tmp_path)
    (source/'daily.jsonl').write_bytes(daily.replace(b'50000',b'60000',1))
    with pytest.raises(ValueError,match='daily prefix changed'):
        inputs.capture(source,tmp_path/'snapshot')


def test_snapshot_binding_guard(tmp_path):
    source,_,_ = source_fixture(tmp_path)
    identity = json.loads((source/'identity.json').read_text())
    identity['binding']['measurement_start'] = '2021-01-03'
    inputs.write_json(source/'identity.json',identity)
    with pytest.raises(ValueError,match='binding or cursor changed'):
        inputs.capture(source,tmp_path/'snapshot')


def test_source_and_output_overlap_refuses(tmp_path):
    source,_,_ = source_fixture(tmp_path)
    with pytest.raises(ValueError,match='separate'):
        inputs.capture(source,source/'new')
    with pytest.raises(ValueError,match='separate'):
        run(source,None,source/'output',Settings())


def test_full_period_runner_and_report(tmp_path):
    source,_,_ = source_fixture(tmp_path)
    output = tmp_path/'experiment'
    summary = run(source,None,output,Settings(cap_samples=3))
    assert summary['actions'] == ['0','0.55','1']
    assert summary['metrics']['oracle']['cagr'] >= summary['metrics']['actual']['cagr']-1e-10
    assert summary['metrics']['oracle']['maxdd'] <= summary['actual_drawdown_cap']+1e-10
    assert json.loads((output/'status.json').read_text())['status'] == 'COMPLETE'
    document = (output/'report.html').read_text()
    assert '0%, 55%, 100%' in document and 'plotly.js' in document
    from html.parser import HTMLParser
    class Scripts(HTMLParser):
        external = []
        def handle_starttag(self,tag,attrs):
            if tag == 'script' and dict(attrs).get('src'):
                self.external.append(dict(attrs)['src'])
    parser = Scripts()
    parser.feed(document)
    assert not parser.external
