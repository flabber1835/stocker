"""Self-contained research report with monthly comparison and trial provenance."""
import json
from pathlib import Path

from research.exposure_oracle import inputs
from research.exposure_oracle.report import table

NAMES = dict(baseline='Current Sentinel',selected='Chronological overall selector',
    state='State rules selector',trend='Trend / volatility selector',
    predictive='Predictive models selector',combination='Combined rules selector',
    always_core='Always Core',simple_trend='Fixed simple trend',spy='SPY')


def write(snapshot: Path, output: Path):
    summary=json.loads((output/'summary.json').read_text())
    paths=json.loads((output/'paths.json').read_text())
    months=json.loads((output/'monthly.json').read_text())
    selections=json.loads((output/'selections.json').read_text())
    mechanics=json.loads((output/'mechanics.json').read_text())
    stress=json.loads((output/'stress.json').read_text())
    audit=json.loads((output/'audit.json').read_text())
    _,rows=inputs.load(snapshot)
    dates=[r['session'] for r in rows if r['session']>=summary['baseline']]
    order=['baseline','selected','state','trend','predictive','combination','always_core','simple_trend','spy']
    metrics=table(['Policy','CAGR','Multiple','MaxDD','Switches','Mean exposure'],[
        [NAMES[n],f"{m['cagr']:.2%}",f"{float(m['multiple']):.3f}×",f"{m['maxdd']:.2%}",
         m.get('switches','—'),f"{m['mean_exposure']:.1%}" if 'mean_exposure' in m else '—']
        for n in order for m in [summary['metrics'][n]]])
    chosen=table(['Outer block','Selector','Frozen candidate','Validation CAGR','Validation MaxDD','Outer CAGR'],[
        [s['fold']['id'],NAMES[n],c['id'],f"{c['metrics']['cagr']:.2%}",f"{c['metrics']['maxdd']:.2%}",
         f"{s['outer_metrics'][n]['cagr']:.2%}"] for s in selections for n,c in s['choices'].items()])
    gates=table(['Selector','Passed screening','Positive blocks','Gain excluding best episode¹','Bootstrap adjusted p²','Placebo percentile³'],[
        [NAMES[n],'Yes' if g['passes'] else 'No',str(mechanics[n]['positive_blocks'])+'/5',
         f"{mechanics[n]['log_gain_without_best']:+.4f}",f"{g['adjusted_bootstrap_p']:.3f}",
         f"{g['placebo_cagr_percentile']:.1%}"] for n,g in summary['gates'].items()])
    stresses=table(['Scenario','Policy','CAGR','MaxDD'],[
        [scenario,NAMES[n],f"{m['cagr']:.2%}",f"{m['maxdd']:.2%}"]
        for scenario,series in stress.items() for n,m in series.items() if n in ('baseline','selected',*summary['gates'])])
    attribution=table(['Selector','Gross timing log gain','Cost log gain','Changed opens','Episodes'],[
        [NAMES[n],f"{d['gross_log_gain']:+.5f}",f"{d['cost_log_gain']:+.5f}",d['changed_opens'],len(d['episodes'])]
        for n,d in mechanics.items()])
    from plotly.subplots import make_subplots
    import plotly.graph_objects as go
    fig=make_subplots(rows=2,cols=1,shared_xaxes=True,vertical_spacing=.1,
                     subplot_titles=('Chronological evaluation wealth','Drawdown'))
    for n in order:
        p=paths[n]
        visible=True if n in ('baseline','selected','spy') else 'legendonly'
        fig.add_trace(go.Scatter(x=dates,y=[float(v) for v in p['nav']],name=NAMES[n],
            legendgroup=n,visible=visible),row=1,col=1)
        fig.add_trace(go.Scatter(x=dates,y=[-100*v for v in p['drawdown']],name=NAMES[n],
            legendgroup=n,showlegend=False,visible=visible),row=2,col=1)
    fig.update_layout(template='plotly_white',height=720,hovermode='x unified')
    fig.update_yaxes(type='log',row=1,col=1); fig.update_yaxes(ticksuffix='%',row=2,col=1)
    fig.write_json(output/'figure.json')
    def monthly_table(name):
        names=['baseline',name,'spy']
        return table(['Close',*[NAMES[n]+' '+m for n in names for m in ('CAGR','Multiple','MaxDD')]],[
            [m['session'],*[v for n in names for v in (f"{m['series'][n]['cagr']:.2%}",
                f"{float(m['series'][n]['multiple']):.3f}×",f"{m['series'][n]['maxdd']:.2%}")]] for m in months])
    tables={n:monthly_table(n) for n in ('selected','state','trend','predictive','combination','always_core','simple_trend')}
    options=''.join(f'<option value="{n}">{NAMES[n]}</option>' for n in tables)
    html=f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sentinel structured research</title><style>body{{font:16px system-ui;max-width:1380px;margin:32px auto;padding:0 20px;color:#17283c;background:#fbfcfe}}p{{line-height:1.6}}table{{border-collapse:collapse;width:100%;font-size:13px}}th,td{{padding:9px;border-bottom:1px solid #dde4ed;text-align:right;white-space:nowrap}}th:first-child,td:first-child{{text-align:left}}th{{background:#edf2f8}}.scroll{{overflow:auto;margin-bottom:30px}}.note{{background:#edf4ff;border-left:4px solid #295eac;padding:16px}}h2{{margin-top:36px}}select{{padding:10px;margin-bottom:16px}}summary{{cursor:pointer;padding:12px;background:#edf2f8}}code{{overflow-wrap:anywhere}}</style></head><body>
<h1>Structured Sentinel research</h1><p class="note">576 declared candidates across four controller families; five chronological outer blocks. Every candidate shares the retained fractional Wealth Core path. Model fitting, inner selection and outer evaluation are separated. The history was inspected in earlier research, so these are model holdouts, not untouched research holdouts.</p>
<h2>Chronological evaluation</h2><p>Baseline {summary['baseline']}; first return {summary['first_return']}; final close {summary['source_end']}. CAGR, wealth multiple and maximum drawdown include modeled next-open timing and allocation costs. The overall selector was chosen from earlier data at each block; no winner was selected using the combined outer results.</p><div class="scroll">{metrics}</div>
{fig.to_html(full_html=False,include_plotlyjs=True)}
<h2>Screening and uncertainty</h2><div class="scroll">{gates}</div><p>¹ Incremental log wealth after subtracting the best changed-exposure episode, including its rejoin overnight. This is an attribution sensitivity, not a newly executable path. ² Exploratory maximum-statistic block-bootstrap correction across this batch; it cannot account for unrecorded earlier research or guarantee stationarity. ³ Position among 500 timing shifts with identical exposure occupancy; seam turnover is recalculated. None of these establishes production qualification.</p>
<h2>Mechanics</h2><div class="scroll">{attribution}</div><p>Gross timing and modeled cost contributions reconcile exactly to incremental log wealth. Complete changed episodes and incumbent-state attribution are retained in mechanics.json. Warning duration, return participation and switching are measured on the common Core history.</p>
<h2>Monthly results</h2><p>Cumulative CAGR, multiple and maximum drawdown from the common evaluation baseline through each month end. The final August 2022 row is partial. Early cumulative CAGR is annualized from a short period.</p><label for="policy">Compare with Sentinel and SPY: </label><select id="policy">{options}</select><div id="monthly" class="scroll">{tables['selected']}</div>
<details><summary>Frozen selections and outer blocks</summary><div class="scroll">{chosen}</div></details>
<details><summary>Cost and delay stress tests</summary><div class="scroll">{stresses}</div></details>
<h2>Reproducibility</h2><p>Source history ends {summary['source_end']}; no later returns were fabricated. Raw breadth/leadership series missing from the retained daily export were not invented. Core was not advanced. This is a scalar exposure study, not a broker fill replay. Independent ledger audit: {audit['status']}; {audit['training_candidates']:,} validation trials, {audit['independent_outer_daily_returns']:,} outer daily returns, {audit['monthly_series']:,} monthly series entries.</p><p>Protocol SHA256: <code>{summary['protocol_sha256']}</code>. Full candidate menu, fitted models, trial actions, selection hashes, diagnostics and monthly values accompany this report.</p>
<script>const monthlyTables={json.dumps(tables)};document.getElementById('policy').addEventListener('change',e=>{{document.getElementById('monthly').innerHTML=monthlyTables[e.target.value];}});</script></body></html>'''
    (output/'report.html').write_text(html,encoding='utf8')
    qa=dict(monthly_rows=len(months),monthly_policy_choices=len(tables),series=len(paths),
            chart_traces=len(fig.data),html_bytes=len(html.encode()),status='STRUCTURAL_PASS')
    if len(dates)!=len(paths['baseline']['nav']) or len(months)<100 or len(fig.data)!=18:
        raise ValueError('report completeness differs from declared evaluation')
    inputs.write_json(output/'report-qa.json',qa)
    return qa
