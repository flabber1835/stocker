"""Standalone report for the four predeclared causal controller cases."""
from .report import table


def write_report(root,summary,rows,paths,episodes,years):
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    names = {'baseline':'Current Sentinel','earlier_exit':'Earlier partial exit',
             'recovery_bridge':'55% recovery bridge','combined':'Both changes'}
    colors = {'baseline':'#2458b0','earlier_exit':'#b47715','recovery_bridge':'#11845e','combined':'#854fb4'}
    metrics = table(['Case','CAGR','Multiple','MaxDD','Exposure changes','Longest underwater','Overlay cost drag'],[
        [names[name],f"{p['cagr']:.2%}",f"{float(p['multiple']):.3f}×",f"{p['maxdd']:.2%}",
         p['switches'],str(p['longest_underwater_sessions'])+' sessions',f"{p['overlay_cost_drag']:.2%}"] for name,p in paths.items()])
    fig = make_subplots(rows=3,cols=1,shared_xaxes=True,vertical_spacing=.07,
        subplot_titles=('Wealth multiple','Exposure applied at the open','Drawdown from running close peak'))
    dates = [r['session'] for r in rows]
    for name,p in paths.items():
        for panel,axis,values in ((1,dates,[float(x) for x in p['nav']]),
            (2,dates[1:],[x*100 for x in p['exposure']]),(3,dates,[-x*100 for x in p['drawdown']])):
            fig.add_trace(go.Scatter(x=axis,y=values,name=names[name],legendgroup=name,showlegend=panel == 1,
                line=dict(color=colors[name],width=2,shape='hv' if panel == 2 else 'linear')),row=panel,col=1)
    fig.update_layout(template='plotly_white',height=1000,hovermode='x unified',legend=dict(orientation='h'))
    fig.update_yaxes(tickvals=[0,55,100],ticksuffix='%',row=2,col=1)
    fig.update_yaxes(ticksuffix='%',row=3,col=1)
    fig.update_xaxes(rangeselector=dict(buttons=[dict(count=1,label='1y',step='year',stepmode='backward'),
        dict(count=3,label='3y',step='year',stepmode='backward'),dict(step='all',label='All')]),row=1,col=1)
    year_table = table(['Year',*[names[name] for name in paths]],[
        [r['year'],*[f"{r['returns'][name]:.2%}" for name in paths]] for r in years])
    episode_table = table(['Actual defensive episode','Sessions',*[names[name] for name in paths]],[
        [e['start']+' to '+e['end'],e['days'],*[f"{e['returns'][name]:.2%}" for name in paths]] for e in episodes])
    text = f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sentinel exit and recovery — four fixed tests</title><style>body{{font:16px system-ui;max-width:1250px;margin:30px auto;padding:0 24px;color:#18212f;background:#fbfcfe}}p{{line-height:1.6}}h2{{margin-top:36px}}table{{border-collapse:collapse;width:100%;font-size:14px}}td,th{{padding:10px;border-bottom:1px solid #dbe3ed;text-align:right}}td:first-child,th:first-child{{text-align:left}}th{{background:#edf2f9}}.scroll{{overflow:auto}}.note{{background:#edf3fc;padding:16px;border-left:4px solid #2458b0}}</style>
<h1>Sentinel exit and recovery: four fixed tests</h1><p>{summary['start']} close to {summary['end']} close · only 0%, 55%, 100%</p>
<p class="note">These cases use signals available at each decision close and trade at the following open. They do not use the hindsight oracle. The inspected history is a diagnostic sample; later-period and forward validation are still required.</p>
<p>Earlier partial exit changes the existing owned-impairment entry confirmation from five closes to one. The recovery bridge permits 55% while native exposure has returned to 100% but the existing recovery gate still holds zero. Full-risk release and severe exits retain their existing criteria. Both changes combines the two.</p>
<div class="scroll">{metrics}</div>{fig.to_html(full_html=False,include_plotlyjs=True)}
<h2>Calendar-year returns</h2><div class="scroll">{year_table}</div>
<h2>Returns during each recorded defensive episode</h2><p>All cases use the same episode boundaries, from the preceding close through the last defensive session. Earlier changes can also affect periods outside these windows.</p><div class="scroll">{episode_table}</div>
<h2>Preserved experiment</h2><p>The fractional Core return path and original costs remain fixed. Baseline state and decisions reproduce the recorded controller. Candidate state is replayed from {summary['seed_session']} before any selected window is rebased. The first funded deployment remains fixed when included. Longest underwater duration counts consecutive sessions below a prior closing peak, including unfinished recovery at the window end. Overlay cost drag is the product of the modeled scalar cost factors; Core's internal costs already belong to the shared return tape.</p></html>'''
    (root/'report.html').write_text(text,encoding='utf8')
    fig.write_json(root/'figure.json')
