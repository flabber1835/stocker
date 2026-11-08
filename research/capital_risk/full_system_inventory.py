"""Read-only source map for economic controls; never imports strategy code."""
import argparse
import ast
import hashlib
import json
from pathlib import Path

CORE = 'shared/stock_strategy_shared/wealth_core/'


def inventory(root):
    root = Path(root)
    files = {}
    def source(name):
        raw = (root/name).read_bytes(); tree = ast.parse(raw, name)
        files[name] = {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
        return tree, raw.decode()
    def literal(name, variable):
        tree, _ = source(name)
        matches = [node.value for node in tree.body if isinstance(node, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id == variable for t in node.targets)]
        if len(matches) != 1: raise ValueError('REFUSED_INVENTORY_ASSIGNMENT_'+name+':'+variable)
        return ast.literal_eval(matches[0])
    rows = []
    def add(component, key, baseline, alternatives, path, site, coupling):
        tree, text = source(path)
        if site not in text: raise ValueError('REFUSED_INVENTORY_SITE_'+key)
        rows.append({'component': component, 'parameter': key, 'baseline': baseline,
            'bounded_alternatives': alternatives, 'source': path, 'source_site': site,
            'source_line': text[:text.index(site)].count('\n')+1, 'coupling': coupling,
            'coverage_status': 'MAPPED_NOT_YET_SEARCHED'})
    m = CORE+'median5.py'; e = CORE+'engine.py'; s = CORE+'state.py'; v = CORE+'v5.py'; sig = CORE+'signals.py'
    add('CORE_SELECTION','momentum_lookback',literal(sig,'LONG_LOOKBACK_SESSIONS'),[84,126,189,252],sig,'LONG_LOOKBACK_SESSIONS = 126',
        'Active current-window feature route: window_signals.feature -> signals. Couple Buffer retained slices, contiguous requirement, WindowFeatures material limits and input/cache identity. Feed.advance bypasses median5.advance_signals when snapshot_security_bars exists.')
    add('CORE_SELECTION','recent_skip',literal(sig,'SKIP_RECENT_SESSIONS'),[10,21,42],sig,'SKIP_RECENT_SESSIONS = 21',
        'Active snapshot route momentum numerator, recent return and volatility formation slice; do not patch unused rolling-sum route alone.')
    add('CORE_SELECTION','leadership_fraction',.10,[.05,.10,.20],e,'k = leadership_count(',
        'Research config identity and frozen config validator; not current generic v1 defaults.')
    add('CORE_SELECTION','minimum_leaders',25,[15,25,40],e,'cfg.minimum_leadership_population',
        'Leadership membership and admission population minimum; configuration identity.')
    add('CORE_SELECTION','rank_memory_sessions',5,[1,3,5,10],m,'history = (state["rank_history"] + [order])[-5:]',
        'Rank state schema validation/history cap and median ordering.')
    add('CORE_SELECTION','median_rank_front',3,[1,3,5],m,'durable[:3]',
        'Front and remainder slicing must remain a permutation without duplicates.')
    add('CORE_SELECTION','freshness_minimum',0.,[-.02,0.,.02],m,'s.recent >= 0',
        'Freshness applies after leadership and median history; preserve ordering stage.')
    add('CORE_CAPITAL','slots',20,[10,15,20,30],v,'WealthCoreConfig(n_slots=20, entry_weight=0.05',
        'Slot creation, validator, default config, exact NAV/slots admission and restore identity. Never change only nominal entry_weight.')
    add('CORE_CAPITAL','admissions_per_close',1,[1,2,4],e,'max_admissions_per_session: int = 1',
        'Fresh origin/config; issuer/reservation/cash guards stay enforced.')
    add('CORE_EXIT','trailing_retention',.70,[.60,.70,.80,.85],s,'Fraction("0.70")',
        'Actual comparison contains a literal; changing only STOP_RETENTION does not change this call.')
    add('CORE_EXIT','review_age',literal(s,'REVIEW_AGE_SESSIONS'),[63,119,189],s,'self.market_sessions_held >= REVIEW_AGE_SESSIONS',
        'Exactly once with deferred review; preserve flag and split-adjusted price domain.')
    add('CORE_EXIT','slot_cooldown',21,[0,10,21,42],s,'self.cooldown_sessions_elapsed < COOLDOWN_SESSIONS',
        'Separate slot/security policy and validation; no state reset.')
    add('CORE_EXIT','security_cooldown',21,[10,21,42,63],s,'COOLDOWN_SESSIONS = 21',
        'Separate from slot cooldown, exact permanent SID, restore bounds and expiry.')
    f = 'sentinel/controller/champion_frozen.py'
    fast, slow = literal(f,'FAST'), literal(f,'SLOW')
    add('PARENT_NATIVE','ordinary_drawdown',literal(f,'ORD_DD'),[-.10,-.155,-.20],f,'ORD_DD =',
        'Native.step reads this constant; changing only ControllerConfig is insufficient.')
    bounds = {'dd':[-.075,-.10,-.15], 'dam':[.63,.75,.88], 'green':[.10,.20,.30],
              'r5':[-.03,-.05,-.075], 'r10':[-.05,-.08,-.12], 'ddam5':[.15,.30,.45],
              'volacc':[0.,.04,.10], 'spy20':[-.03,-.01,.01], 'r10confirm':[-.075,-.10,-.15]}
    for key, base in fast.items():
        add('PARENT_NATIVE','fast_'+key,base,bounds[key],f,"FAST['"+key+"']",'Canonical Native transition and bound profile identity.')
    bounds = {'dur':[15,30,45], 'ret':[-.01,-.02,-.04], 'r40':[-.01,-.03,-.06],
              'dam':[.60,.75,.88], 'green':[.10,.25,.40]}
    for key, base in slow.items():
        add('PARENT_NATIVE','slow_'+key,base,bounds[key],f,"SLOW['"+key+"']",'Duration saturation and snapshot caps must track any changed horizon.')
    for key, base, vals, site in (
        ('healthy_r20',0.,[-.01,0.,.02],'(r20 > 0)'),
        ('healthy_damaged',.63,[.50,.63,.75],'(dam <= 0.63)'),
        ('healthy_green',.20,[.10,.20,.30],'(green >= 0.2)'),
        ('fast_min_age',10,[5,10,15],'self.fast_age + 1 >= 10'),
        ('fast_healthy_sessions',3,[1,3,5],'self.fast_h >= 3'),
        ('slow_min_age',20,[10,20,30],'self.slow_age + 1 >= 20'),
        ('slow_healthy_sessions',6,[3,6,10],'self.slow_h >= 6'),
        ('fast_rearm_drawdown',-.06,[-.03,-.06,-.10],'dd > -0.06')):
        add('PARENT_NATIVE',key,base,vals,f,site,'Patch corresponding state saturation and snapshot bounds; keep inclusive/strict comparisons.')
    for key, variable, vals in (
        ('recovery_sessions','LDRC_REC',[3,5,8,13]),
        ('divergence_drawdown','LDRC_DD',[-.075,-.10,-.15]),
        ('divergence_r20','LDRC_R20',[-.05,-.085,-.12]),
        ('divergence_ceiling','LDRC_CEIL',[.25,.55,.75])):
        add('PARENT_RECOVERY',key,literal(f,variable),vals,f,variable+' =',
            'CandidateA snapshot caps and champion validation/identity; counter bounds cannot stay at eight after horizon changes.')
    add('PARENT_RECOVERY','full_health_r40',-.04,[-.08,-.04,0.],f,'(recent_r40 > -0.04)',
        'Actual CandidateA literal, not unused metadata constant; no rebound route reintroduced.')
    b = 'sentinel/controller/median5_breadth.py'
    for key, base, vals, site in (
        ('residual_lookback',252,[126,189,252],'index-252'),
        ('minimum_pair_observations',120,[63,90,120],'len(common) < 120'),
        ('minimum_residual_correlation',.145,[0.,.145,.30,.50],'c >= 0.145'),
        ('neighbor_count',3,[1,3,5],'scores[:3]'),
        ('peer_stress_fraction',.50,[.33,.50,.67],'stress >= 0.5'),
        ('individual_damage_drawdown',-.10,[-.075,-.10,-.15],'h.own_dd <= -0.10'),
        ('individual_damage_r21',-.03,[-.01,-.03,-.06],'h.r21 <= -0.03')):
        add('CORRELATION_BREADTH',key,base,vals,b,site,
            'Holding-dependent and lagged; rebuild for each Core path. No retired sector grouping.')
    own = 'sentinel/controller/owned_impairment.py'; tree, text = source(own)
    call, = [n.value for n in tree.body if isinstance(n, ast.Assign)
             and any(isinstance(t, ast.Name) and t.id == 'RULE' for t in n.targets)]
    rule = {k.arg: ast.literal_eval(k.value) for k in call.keywords}
    alternatives = {'entry_drawdown':[-.075,-.10,-.15], 'entry_damage':[.50,.63,.75,.88],
        'entry_green':[.10,.20,.30], 'entry_sessions':[1,3,5], 'recovery_damage':[.50,.63,.75],
        'recovery_green':[.10,.20,.30], 'recovery_sessions':[3,5,8],
        'recovery_core_r20_above':[-.02,0.,.02], 'active_ceiling':[.25,.55,.75]}
    for key, vals in alternatives.items():
        add('OWNED_OVERLAY',key,rule[key],vals,own,"RULE['"+key+"']",'Own latch/counter validation, source and serialized identity; capped by parent.')
    return {'schema': 'research.full-system-controls/1', 'source_files': files,
        'parameters': rows, 'mapped_parameters': len(rows), 'performance_scored': False,
        'architecture_families_separate': ['periodic_rebalancing','volatility_risk_per_holding','per_holding_protection'],
        'fixed_model_assumptions': ['fees','price_domains','corporate_action_facts','dividend_settlement_convention','long_only_unlevered'],
        'active_signal_route': ['research/pooled_input_support/adapter.py:Buffer.prepare',
            'shared/stock_strategy_shared/wealth_core/window_signals.py:feature',
            'shared/stock_strategy_shared/wealth_core/signals.py',
            'sentinel/core/window_material.py:install',
            'shared/stock_strategy_shared/wealth_core/feed.py:snapshot_security_bars',
            'shared/stock_strategy_shared/wealth_core/median5.py:rank'],
        'coverage_warning': 'A source map is not implementation or evidence that any control has been swept.'}


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--source', type=Path, required=True); p.add_argument('--output', type=Path, required=True)
    args = p.parse_args(); value = inventory(args.source)
    with args.output.open('x', encoding='utf8') as f: f.write(json.dumps(value, sort_keys=True, indent=2)+'\n')
    print(json.dumps({'mapped_parameters': value['mapped_parameters'], 'performance_scored': False}))
