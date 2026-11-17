"""Offline comparison of causal three/five-level overlays and their paired controls."""
import argparse
import json
from pathlib import Path

from . import inputs
from .report import table

NAMES=dict(baseline='Current Sentinel',selected_three='Selected three-level',selected_five='Selected five-level',
    paired_three='Three levels / selected five-level settings',paired_five='Five levels / selected three-level settings',
    fixed_three='Fixed staged three-level',fixed_five='Fixed staged five-level',spy='SPY')
MAIN=('baseline','selected_three','selected_five','spy')


def metrics_table(paths, order):
    return table(['Policy','CAGR','Multiple','MaxDD','Switches','Allocation turnover','Cost drag'],[
        [NAMES[n],f"{paths[n]['cagr']:.2%}",f"{float(paths[n]['multiple']):.3f}×",f"{paths[n]['maxdd']:.2%}",
         paths[n].get('switches','—'),f"{paths[n]['allocation_turnover']:.2f}" if 'allocation_turnover' in paths[n] else '—',
         f"{paths[n]['overlay_cost_drag']:.2%}" if 'overlay_cost_drag' in paths[n] else '—'] for n in order])


def monthly_table(months):
    return table(['Close',*[f'{NAMES[n]} {m}' for n in MAIN for m in ('CAGR','multiple','MaxDD')]],[
        [month['session'],*[v for n in MAIN for v in (f"{month['series'][n]['cagr']:.2%}",
            f"{float(month['series'][n]['multiple']):.3f}×",f"{month['series'][n]['maxdd']:.2%}")]] for month in months])


def write_report(snapshot: Path, root: Path):
    summary=json.loads((root/'summary.json').read_text())
    fit=json.loads((root/'selection.json').read_text())
    full=json.loads((root/'paths.json').read_text())
    holdout=json.loads((root/'holdout-paths.json').read_text())
    pairs=json.loads((root/'pairs.json').read_text())
    months=json.loads((root/'monthly.json').read_text())
    test_months=json.loads((root/'holdout-monthly.json').read_text())
    years=json.loads((root/'yearly.json').read_text())
    _,rows=inputs.load(snapshot)
    dates=[r['session'] for r in rows]
    split=dates.index(summary['holdout_baseline'])
    chosen=table(['Available levels','Selected configuration','Training CAGR','Training MaxDD'],[
        ['0 / 55 / 100' if count=='3' else '0 / 25 / 55 / 75 / 100',record['id'],
         f"{record['metrics']['cagr']:.2%}",f"{record['metrics']['maxdd']:.2%}"]
        for count,record in fit['selected'].items()])
    paired=table(['Paired comparison','Three-level test CAGR','Five-level test CAGR','Gross log gain','Cost log gain'],[
        [name.replace('_',' '),f"{holdout[p['three']]['cagr']:.2%}",f"{holdout[p['five']]['cagr']:.2%}",
         f"{sum(x['gross_log_gap'] for x in p['holdout']):+.5f}",
         f"{sum(x['cost_log_gap'] for x in p['holdout']):+.5f}"] for name,p in pairs.items()])
    occupancy=table(['Policy','Days at 0%','25%','55%','75%','100%'],[
        [NAMES[n],*[holdout[n]['exposure'].count(a) for a in (0.,.25,.55,.75,1.)]]
        for n in ('baseline','selected_three','selected_five','fixed_three','fixed_five')])
    year_table=table(['Year',*[NAMES[n] for n in MAIN]],[[y['year'],*[f"{y['returns'][n]:.2%}" for n in MAIN]] for y in years])
    training=table(['Configuration','Levels','Training CAGR','Training MaxDD','Turnover'],[
        [r['id'],r['levels'] or 'original',f"{r['metrics']['cagr']:.2%}",f"{r['metrics']['maxdd']:.2%}",
         f"{r['metrics']['allocation_turnover']:.2f}"] for r in fit['candidates']])
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    fig=make_subplots(rows=3,cols=1,shared_xaxes=True,vertical_spacing=.07,
        subplot_titles=('Holdout wealth multiple — log scale','Holdout drawdown','Exposure applied at the next open'))
    colors=dict(baseline='#2458b0',selected_three='#bb7822',selected_five='#087b64',spy='#6a7380')
    for name in MAIN:
        p=holdout[name]
        for panel,values in ((1,[float(x) for x in p['nav']]),(2,[-100*x for x in p['drawdown']])):
            fig.add_trace(go.Scatter(x=dates[split:],y=values,name=NAMES[name],legendgroup=name,showlegend=panel==1,
                line=dict(color=colors[name],width=2)),row=panel,col=1)
        if name!='spy':
            fig.add_trace(go.Scatter(x=dates[split+1:],y=[100*x for x in p['exposure']],name=NAMES[name],
                legendgroup=name,showlegend=False,line=dict(color=colors[name],width=1.4,shape='hv')),row=3,col=1)
    fig.update_layout(template='plotly_white',height=1000,hovermode='x unified',legend=dict(orientation='h'))
    fig.update_yaxes(type='log',row=1,col=1)
    fig.update_yaxes(ticksuffix='%',row=2,col=1)
    fig.update_yaxes(ticksuffix='%',tickvals=[0,25,55,75,100],row=3,col=1)
    fig.write_json(root/'figure.json')
    text=f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sentinel: three versus five exposure levels</title><style>body{{font:16px system-ui;max-width:1320px;margin:30px auto;padding:0 24px;color:#182330;background:#fbfcfe}}p{{line-height:1.65}}h2{{margin-top:36px}}table{{border-collapse:collapse;width:100%;font-size:14px}}th,td{{padding:10px;border-bottom:1px solid #dce3ec;text-align:right;white-space:nowrap}}th:first-child,td:first-child{{text-align:left}}th{{background:#edf2f8}}.scroll{{overflow:auto}}.note{{background:#edf3fc;border-left:4px solid #2458b0;padding:16px}}summary{{cursor:pointer;padding:12px;background:#edf2f8}}code{{overflow-wrap:anywhere}}</style></head><body>
<h1>Three versus five exposure levels</h1>
<p class="note">Every candidate uses the same retained fractional Wealth Core history. No Core book was formed or advanced. Fitting ends at {summary['train_end']}; the later period is excluded from selection. Its history was inspected in prior research, so it is a fitting holdout, not an untouched research sample.</p>
<h2>Frozen selection</h2><p>Fourteen staged settings per grid plus the unchanged baseline fallback. Select highest after-cost training CAGR subject to training MaxDD no worse than current Sentinel; ties use turnover, switches and stable ID. Both settings are saved before evaluating later returns.</p>
<div class="scroll">{chosen}</div>
<h2>Later-period results</h2><p>Baseline close {summary['holdout_baseline']}; first return {summary['holdout_first_return']}; end {summary['end']}. Each policy carries its own state and overnight holding across the split. “Selected” includes the option to retain the original controller.</p>
<div class="scroll">{metrics_table(holdout,MAIN)}</div>
{fig.to_html(full_html=False,include_plotlyjs=True)}
<h2>Separate exposure levels from changed settings</h2><p>Within each pair, the underlying stages and intervention dates are identical. Only early-warning exposure (55% versus 75%) and recovery-probe exposure (55% versus 25%) differ. Fixed settings use warning entry 1, healthy release 3 and recovery confirmation 3. Positive log gains favor five levels.</p>
<div class="scroll">{paired}</div>
<details><summary>All later-period controls and their drawdowns</summary><div class="scroll">{metrics_table(holdout,NAMES)}</div></details>
<h2>Which exposure levels were used?</h2><div class="scroll">{occupancy}</div>
<p>Early warning requires the existing impaired predicate. Confirmed owned/divergence protection retains 55%; native severe protection stays zero immediately. A recovery probe requires confirmed healthy closes after native protection has cleared, while the original recovery gate still withholds full exposure. Neutral closes can maintain the probe; renewed impairment removes it.</p>
<h2>Full retained-history diagnostics</h2><p>{summary['start']} through {summary['end']}. These include fitting years and must not be presented as held-out performance.</p>
<div class="scroll">{metrics_table(full,MAIN)}</div><div class="scroll">{year_table}</div>
<h2>Monthly cumulative metrics</h2><p>Every table includes CAGR, wealth multiple and MaxDD for current Sentinel, both selected overlays and SPY. The final month is partial; short initial annualized returns can be unstable.</p>
<details><summary>Later-period monthly metrics — {len(test_months)} rows from {summary['holdout_baseline']}</summary><div class="scroll">{monthly_table(test_months)}</div></details>
<details><summary>Full-history monthly metrics — {len(months)} rows from {summary['start']}</summary><div class="scroll">{monthly_table(months)}</div></details>
<details><summary>All training candidates — {len(fit['candidates'])} rows</summary><div class="scroll">{training}</div></details>
<h2>Fixed history, independent overlays</h2><p>Canonical Core holdings, cash, entries, exits, corporate actions and price history never change between candidates. Candidate decisions act at the following open; the previous exposure owns the overnight. Cost is 10 basis points per unit of allocation turnover. These are scalar allocation simulations, not broker-fill or liquidity replays.</p>
<p>The saved path ends {summary['end']}. New authenticated sessions can extend the common lineage once when the separate Core replay resumes; controllers do not generate their own Core histories. Current study source: <code>{summary['source_binding']}</code>.</p>
<p><a href="audit.json">Independent audit</a> · <a href="selection.json">Frozen training selection</a> · <a href="pairs.json">Timing and cost attribution</a> · <a href="monthly.json">Full monthly data</a> · <a href="holdout-monthly.json">Holdout monthly data</a> · <a href="summary.json">Run identity</a></p></body></html>'''
    (root/'report.html').write_text(text,encoding='utf8')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--snapshot',type=Path,required=True)
    p.add_argument('--result',type=Path,required=True)
    args=p.parse_args()
    write_report(args.snapshot,args.result)
