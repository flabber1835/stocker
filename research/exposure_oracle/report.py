"""Standalone offline charts; Plotly is used only for this report."""
import html
from pathlib import Path

def table(headers, rows):
    head = ''.join(f'<th>{html.escape(str(x))}</th>' for x in headers)
    body = ''.join('<tr>'+''.join(f'<td>{html.escape(str(x))}</td>' for x in row)+'</tr>' for row in rows)
    return '<table><thead><tr>'+head+'</tr></thead><tbody>'+body+'</tbody></table>'


def write_report(root: Path, summary: dict, rows: list[dict], paths: dict[str,dict],
                 frontier: list[dict], attribution: dict, months: list[dict]):
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    labels = {'actual':'Actual Sentinel','oracle':'Hindsight timing oracle',
              'core':'100% Core policy','bil':'0% Core / BIL policy'}
    colors = {'actual':'#2055b1','oracle':'#138262','core':'#a96e12','bil':'#7d8590'}
    comparison = table(['Path','CAGR','Multiple','MaxDD','Switches','Days at 55%'], [
        [labels[name],f"{p['cagr']:.2%}",f"{float(p['multiple']):,.3f}×",f"{p['maxdd']:.2%}",
         p['switches'],p['exposure'].count(.55)] for name,p in paths.items()])
    curve = go.Figure()
    available = [p for p in frontier if p['status'] == 'OPTIMAL']
    available.sort(key=lambda p:p['metrics']['maxdd'])
    curve.add_trace(go.Scatter(x=[p['metrics']['maxdd']*100 for p in available],
        y=[p['metrics']['cagr']*100 for p in available], mode='lines+markers',
        name='Optimal hindsight frontier', marker_color=colors['oracle'],
        customdata=[[p['cap']*100,p['metrics']['multiple']] for p in available],
        hovertemplate='MaxDD %{x:.3f}%<br>CAGR %{y:.3f}%<br>Cap %{customdata[0]:.3f}%<br>Multiple %{customdata[1]}<extra></extra>'))
    for name in ('actual','oracle'):
        p = paths[name]
        curve.add_trace(go.Scatter(x=[p['maxdd']*100],y=[p['cagr']*100],mode='markers',
            name=labels[name],marker=dict(size=14,symbol='star' if name == 'actual' else 'diamond',color=colors[name])))
    curve.add_vline(x=summary['actual_drawdown_cap']*100,line_dash='dash',line_color=colors['actual'])
    curve.update_layout(template='plotly_white',height=450,xaxis_title='Maximum daily-close drawdown (%)',
                        yaxis_title='CAGR (%)',margin=dict(l=65,r=25,t=35,b=60),legend=dict(orientation='h'))
    dates = [r['session'] for r in rows]
    history = make_subplots(rows=3,cols=1,shared_xaxes=True,vertical_spacing=.07,
        subplot_titles=('Wealth multiple (log scale)','Exposure applied at the open','Drawdown from the running close peak'))
    for name,p in paths.items():
        for panel,values in ((1,[float(x) for x in p['nav']]),(3,[-x*100 for x in p['drawdown']])):
            history.add_trace(go.Scatter(x=dates,y=values,name=labels[name],legendgroup=name,
                showlegend=panel == 1,line=dict(color=colors[name],width=2)),row=panel,col=1)
        if name in ('actual','oracle'):
            history.add_trace(go.Scatter(x=dates[1:],y=[100*x for x in p['exposure']],name=labels[name],
                legendgroup=name,showlegend=False,line=dict(color=colors[name],width=1.4,shape='hv')),row=2,col=1)
    history.update_yaxes(type='log',row=1,col=1)
    history.update_yaxes(tickvals=[0,55,100],ticksuffix='%',row=2,col=1)
    history.update_yaxes(ticksuffix='%',row=3,col=1)
    history.update_layout(template='plotly_white',height=1000,hovermode='x unified',
        margin=dict(l=65,r=25,t=60,b=55),legend=dict(orientation='h'))
    history.update_xaxes(rangeselector=dict(buttons=[dict(count=1,label='1y',step='year',stepmode='backward'),
        dict(count=3,label='3y',step='year',stepmode='backward'),dict(step='all',label='All')]),row=1,col=1)
    episode_table = table(['Defensive episode','Sessions','Actual avg exposure','Oracle avg exposure',
                           'Core return','Actual return','Oracle return'],[
        [e['start']+' to '+e['end'],e['days'],f"{e['actual_mean_exposure']:.1%}",
         f"{e['oracle_mean_exposure']:.1%}",f"{e['core_return']:.1%}",
         f"{e['actual_return']:.1%}",f"{e['oracle_return']:.1%}"]
        for e in sorted(attribution['defensive_episodes'],key=lambda e:e['net_log_gap'],reverse=True)[:12]])
    mechanism_table = table(['Actual controlling state','Sessions','Gross log-wealth gap','Overlay-cost log gap','Net log-wealth gap'],[
        [g['label'].replace('_',' '),g['days'],f"{g['gross_log_gap']:.4f}",
         f"{g['cost_log_gap']:.4f}",f"{g['net_log_gap']:.4f}"] for g in attribution['groups']['mechanism']])
    monthly_table = table(['Month / period end','Actual CAGR','Actual multiple','Actual MaxDD',
                           'Oracle CAGR','Oracle multiple','Oracle MaxDD'],[
        [r['session'],f"{r['series']['actual']['cagr']:.2%}",f"{float(r['series']['actual']['multiple']):.3f}×",
         f"{r['series']['actual']['maxdd']:.2%}",f"{r['series']['oracle']['cagr']:.2%}",
         f"{float(r['series']['oracle']['multiple']):.3f}×",f"{r['series']['oracle']['maxdd']:.2%}"] for r in months])
    text = f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Fractional Core — hindsight exposure timing</title><style>
body{{font-family:system-ui,sans-serif;max-width:1250px;margin:32px auto;padding:0 24px;color:#18212f;background:#fbfcfe}}
h1{{font-size:30px}}h2{{margin-top:38px}}p{{line-height:1.6;max-width:1050px}}.note{{background:#edf3fc;border-left:4px solid #2055b1;padding:14px 20px}}
table{{border-collapse:collapse;width:100%;font-size:14px;margin:18px 0}}td,th{{padding:10px 12px;border-bottom:1px solid #d9e1ec;text-align:right}}td:first-child,th:first-child{{text-align:left}}th{{background:#eaf0f7}}.scroll{{overflow:auto}}summary{{cursor:pointer;font-weight:600}}code{{font-size:12px;overflow-wrap:anywhere}}
</style><h1>Fractional Core — hindsight exposure timing</h1>
<p>{dates[0]} close to {dates[-1]} close · {len(dates)-1:,} return sessions · only <b>0%, 55%, 100%</b></p>
<p class="note">The oracle knows future returns and optimizes when to switch. It uses the same fixed Core/BIL path, next-open timing and modeled costs as Sentinel. It is an upper hindsight benchmark, not a forecast or a tradable strategy. The first funded deployment is preserved when present.</p>
{comparison}<h2>CAGR versus drawdown</h2><p>The dashed line is Sentinel’s actual maximum drawdown. The selected oracle maximizes CAGR within that limit. A lower drawdown is preferable; there is no requirement to use the entire limit.</p>
{curve.to_html(full_html=False,include_plotlyjs=True)}
<h2>What the timing changes</h2><p>Exposure differs on {attribution['differing_days']:,} of {len(dates)-1:,} sessions. Actual Sentinel switches {paths['actual']['switches']:,} times; the oracle switches {paths['oracle']['switches']:,} times. Drag on log wealth from overlay costs is {sum(paths['actual']['cost_log']):.4f} for Sentinel and {sum(paths['oracle']['cost_log']):.4f} for the oracle. Internal Core costs are already in the shared return path.</p>
{history.to_html(full_html=False,include_plotlyjs=False)}
<h2>Where the timing gap arises</h2><p>These contributions add to the log of the oracle/actual final wealth ratio. A native-full signal can still be held at zero by the recovery gate. Equal new opening exposures can also have different overnight returns because yesterday's holdings differ.</p><div class="scroll">{mechanism_table}</div>
<h2>Longer defensive episodes</h2><p>Ranked by the oracle’s log-wealth advantage during the episode. The Core return describes the unchanged underlying book. Oracle daily switching may include protection and re-entry within the same episode; an episode difference is not itself a causal, deployable rule.</p>
<div class="scroll">{episode_table}</div><details><summary>Monthly cumulative results</summary><div class="scroll">{monthly_table}</div></details>
<h2>Evidence and boundaries</h2><p>Checkpoint: <code>{html.escape(summary['checkpoint']['file'])}</code><br>Source binding: <code>{html.escape(summary['source_binding'])}</code><br>Exact dynamic programming over three exposure states; no drawdown quantization or beam pruning. Independent Decimal replay validates the selected cap. The main backtest is a separate running process. This snapshot ends at {dates[-1]} and does not contain its unfinished future.</p>
</html>'''
    (root/'report.html').write_text(text,encoding='utf8')
    curve.write_json(root/'frontier-figure.json')
    history.write_json(root/'history-figure.json')
