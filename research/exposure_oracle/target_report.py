"""Standalone target-CAGR evidence, including all cumulative monthly metrics."""
import argparse
from html import escape
import json
from pathlib import Path

from . import inputs
from .report import table


def write_report(snapshot: Path, root: Path):
    summary=json.loads((root/'summary.json').read_text())
    paths=json.loads((root/'paths.json').read_text())
    findings=json.loads((root/'signal-analysis.json').read_text())
    months=json.loads((root/'monthly.json').read_text())
    bounds=json.loads((root/'budget-bounds.json').read_text())
    _,rows=inputs.load(snapshot,summary['start'],summary['end'])
    opt=summary['optimization']
    proved=all(opt[k] for k in ('minimum_changed_days_proven','secondary_deviation_proven',
                               'tertiary_switches_proven'))
    names=dict(actual='Current Sentinel',target='Closest hindsight target' if proved else
               'Best-found hindsight candidate',spy='SPY')
    metrics=table(['Policy','CAGR','Multiple','MaxDD','Switches'],[
        [names[n],f"{p['cagr']:.2%}",f"{float(p['multiple']):.3f}×",f"{p['maxdd']:.2%}",p.get('switches','—')]
        for n,p in paths.items()])
    monthly=table(['Close',*[f'{names[n]} {m}' for n in names for m in ('CAGR','multiple','MaxDD')]],[
        [m['session'],*[v for n in names for v in (f"{m['series'][n]['cagr']:.2%}",
            f"{float(m['series'][n]['multiple']):.3f}×",f"{m['series'][n]['maxdd']:.2%}")]] for m in months])
    changed=table(['Decision close','Applied open','Actual → target','Healthy','Impaired',
                   'Ordinary stress','Sessions to nearest actual switch','Same-state changed / all'],[
        [x['decision_session'],x['session'],f"{x['actual_exposure']:.0%} → {x['oracle_exposure']:.0%}",
         x['signals']['healthy'],x['signals']['impaired'],x['signals']['ordinary'],
         x['nearest_actual_switch_sessions'],
         f"{x['same_boolean_state_changed_days']} / {x['same_boolean_state_days']}"]
        for x in findings['changed_decisions']])
    rules=table(['Rule','Changed days','Oracle days hit','Label false positives','CAGR','MaxDD'],[
        [x['name'].replace('_',' '),x['modified_days'],x['oracle_changed_days_hit'],x['label_false_positives'],
         f"{x['metrics']['cagr']:.2%}",f"{x['metrics']['maxdd']:.2%}"] for x in findings['rule_diagnostics']])
    periods=table(['Period','Sentinel CAGR','Target CAGR','SPY CAGR','Changed decisions'],[
        [f"{p['start']} → {p['end']}",f"{p['cagr']:.2%}",
         f"{findings['periods']['target'][i]['cagr']:.2%}",f"{findings['periods']['spy'][i]['cagr']:.2%}",
         sum(p['start']<x['session']<=p['end'] for x in findings['changed_decisions'])]
        for i,p in enumerate(findings['periods']['actual'])])
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    dates=[r['session'] for r in rows]
    fig=make_subplots(rows=3,cols=1,shared_xaxes=True,vertical_spacing=.08,
        subplot_titles=('Wealth multiple — log scale','Daily close drawdown','Exposure at the following open'))
    colors=dict(actual='#2559aa',target='#a83c60',spy='#687581')
    for name in names:
        p=paths[name]
        for panel,values in ((1,[float(x) for x in p['nav']]),(2,[-100*x for x in p['drawdown']])):
            fig.add_trace(go.Scatter(x=dates,y=values,name=names[name],legendgroup=name,showlegend=panel==1,
                line=dict(color=colors[name],width=2)),row=panel,col=1)
        if name!='spy':
            fig.add_trace(go.Scatter(x=dates[1:],y=[100*x for x in p['exposure']],name=names[name],
                legendgroup=name,showlegend=False,line=dict(color=colors[name],width=1.3,shape='hv')),row=3,col=1)
    fig.update_layout(template='plotly_white',height=1000,hovermode='x unified',legend=dict(orientation='h'))
    fig.update_yaxes(type='log',row=1,col=1)
    fig.update_yaxes(ticksuffix='%',row=2,col=1)
    fig.update_yaxes(ticksuffix='%',tickvals=[0,55,100],row=3,col=1)
    fig.write_json(root/'figure.json')
    budget=summary['target_metrics']['changed_days']
    lower_budget=opt['minimum_changed_days_lower_bound']
    bound_text=(f"Even ignoring drawdown, {lower_budget-1} changes can achieve at most "
                f"{bounds[lower_budget-1]['maximum_cagr']:.2%} CAGR." if lower_budget else
                'The growth-budget lower bound is zero changed decisions.')
    proof_text='; '.join(f"{label}: {'proved' if opt[key] else 'not proved'}" for label,key in (
        ('minimum changed days','minimum_changed_days_proven'),
        ('minimum deviation','secondary_deviation_proven'),('minimum switches','tertiary_switches_proven')))
    frag=findings['fragmentation']; changed_rows=findings['changed_decisions']
    exits=[x for x in changed_rows if x['actual_exposure']==1 and x['oracle_exposure']<1]
    good=sum(x['signals']['healthy'] for x in exits)
    warning=sum(x['signals']['impaired'] for x in exits)
    changed_55=sum(.55 in (x['actual_exposure'],x['oracle_exposure']) for x in changed_rows)
    source=escape(summary['source_binding'])
    text=f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sentinel: 25–30% CAGR target experiment</title><style>body{{font:16px system-ui;max-width:1250px;margin:30px auto;padding:0 24px;color:#172332;background:#fbfcfe}}p{{line-height:1.65}}h2{{margin-top:36px}}table{{border-collapse:collapse;width:100%;font-size:14px}}th,td{{padding:10px;border-bottom:1px solid #dce3ec;text-align:right;white-space:nowrap}}th:first-child,td:first-child{{text-align:left}}th{{background:#edf2f8}}.scroll{{overflow:auto}}.note{{background:#edf3fc;border-left:4px solid #2559aa;padding:16px}}code{{overflow-wrap:anywhere}}summary{{cursor:pointer;padding:14px;background:#edf2f8}}</style></head><body>
<h1>What would 25–30% CAGR have required?</h1>
<p>{summary['start']} through {summary['end']} · {summary['sessions']:,} completed closes · fractional Wealth Core tape.</p>
<p class="note">The target is hindsight-feasible with {budget} changed daily decisions. The complete target band and current Sentinel drawdown limit are enforced after modeled costs. This is evidence about required timing, not a forecast or a newly qualified strategy. The stopped main backtest remains untouched.</p>
<div class="scroll">{metrics}</div>
<h2>Closeness and proof status</h2><p>Closeness means the fewest different daily exposure decisions, then the smallest total exposure deviation, then the fewest switches. {bound_text} The selected path uses {budget} changes, {summary['target_metrics']['deviation_points']} summed percentage points of deviation and {summary['target_metrics']['switches']} switches. Search status — {proof_text}. Independent audit results are linked below; a resource limit is not a proof.</p>
<p>The path has {frag['episodes']} changed episodes: {escape(str(frag['episode_lengths']))} (length in trading sessions → count). Only {frag['changed_within_5_sessions_of_actual_switch']} changed days are within five sessions of an actual Sentinel switch. Changes involving a 55% action: {changed_55}.</p>
{fig.to_html(full_html=False,include_plotlyjs=True)}
<h2>What the existing signals explain</h2><p>Of {len(exits)} hindsight exits from full exposure, {good} were classified healthy at the preceding close and only {warning} met the existing owned-impaired predicate. Matching boolean states recur on many unchanged dates. The final warning flags do not distinguish these rare future losses. This does not prove that their underlying continuous inputs contain no useful information.</p>
<p>Native fast/slow signals, owned healthy/impaired flags, ordinary/base-fast state and recovery reasons are observed before the applied open. The daily export does not retain every raw breadth, acceleration and recent-leadership input. Those continuous series must be recovered in a separate research replay before fitting thresholds or claiming new signals are necessary.</p>
<div class="scroll">{changed}</div>
<h2>Can simple existing-signal rules reproduce the improvement?</h2><p>Each fixed rule acts on every eligible prior-close signal, using the same next-open timing and costs. These are same-sample causal diagnostics, not out-of-sample tests. Label false positives disagree with this sparse hindsight path; they are not automatically money-losing trades. Partial 55% overrides count as hits when they change an oracle-changed day even though the oracle chose an extreme.</p>
<div class="scroll">{rules}</div>
<h2>Where the benefit occurs</h2><p>These blocks summarize a full-period hindsight solution; no block is an untouched holdout.</p><div class="scroll">{periods}</div>
<h2>Monthly cumulative metrics</h2><p>All CAGR, wealth multiples and maximum drawdowns accumulate from {summary['start']}. Short initial annualized figures can be unstable; the final {summary['end']} row is a partial month. Return accounting includes the prior holding overnight, a switch at the open, and 10 basis points per unit of allocation turnover.</p>
<details><summary>Show all {len(months)} monthly rows for Sentinel, target and SPY</summary><div class="scroll">{monthly}</div></details>
<h2>Audit and reproducibility</h2><p>Source binding: <code>{source}</code>. See <a href="audit.json">independent audit</a>, <a href="solver.json">solver bounds</a>, <a href="signal-analysis.json">complete signal and episode evidence</a>, <a href="monthly.json">monthly data</a>, and <a href="summary.json">run identity</a>. The accountant is checked against the recorded canonical implementation. The model uses scalar allocation costs; it does not replay broker fills, liquidity or slippage.</p></body></html>'''
    (root/'report.html').write_text(text,encoding='utf8')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot',type=Path,required=True)
    parser.add_argument('--result',type=Path,required=True)
    args=parser.parse_args()
    write_report(args.snapshot,args.result)
