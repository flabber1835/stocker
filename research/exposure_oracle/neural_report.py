"""Offline learning and held-out economic report; never mixes refit with test."""
from .report import table


def write_report(root,summary,rows,paths,months,history):
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    names = dict(neural='Neural network',sentinel='Current Sentinel',core='Always Core',
                 bil='BIL',majority='Training majority',oracle='Hindsight ideal',spy='SPY')
    order = ('neural','sentinel','core','spy','bil','oracle')
    metrics = table(['Policy','CAGR','Multiple','MaxDD','Exposure changes','Turnover'],[
        [names[n],f"{paths[n]['cagr']:.2%}",f"{float(paths[n]['multiple']):.3f}×",f"{paths[n]['maxdd']:.2%}",
         paths[n].get('switches','—'),f"{paths[n]['turnover']:.2f}" if 'turnover' in paths[n] else '—'] for n in order])
    fits = table(['Partition','Examples','Teacher 0 / 55 / 100','Accuracy','Cross-entropy'],[
        [name,p['samples'],' / '.join(str(v) for v in p['teacher_classes'].values()),
         f"{summary['classification'][name]['accuracy']:.2%}",f"{summary['classification'][name]['cross_entropy']:.4f}"]
        for name,p in summary['partitions'].items()])
    fig = make_subplots(rows=3,cols=1,shared_xaxes=True,vertical_spacing=.07,
        subplot_titles=('Wealth multiple (log scale)','Exposure applied at next open','Drawdown from closing peak'))
    dates = [r['session'] for r in rows]
    colors = dict(neural='#8b3a9c',sentinel='#2458b0',core='#ab7720',spy='#636b75',bil='#418a67',oracle='#cc5840')
    for name in order:
        p = paths[name]
        for panel,axis,values in ((1,dates,[float(x) for x in p['nav']]),
                                (3,dates,[-x*100 for x in p['drawdown']])):
            fig.add_trace(go.Scatter(x=axis,y=values,name=names[name],legendgroup=name,showlegend=panel==1,
                line=dict(color=colors[name],width=2)),row=panel,col=1)
        if name in ('neural','sentinel','oracle'):
            fig.add_trace(go.Scatter(x=dates[1:],y=[100*x for x in p['exposure']],name=names[name],
                legendgroup=name,showlegend=False,line=dict(color=colors[name],width=1.5,shape='hv')),row=2,col=1)
    fig.update_layout(template='plotly_white',height=1000,hovermode='x unified',legend=dict(orientation='h'))
    fig.update_yaxes(type='log',row=1,col=1)
    fig.update_yaxes(tickvals=[0,55,100],ticksuffix='%',row=2,col=1)
    fig.update_yaxes(ticksuffix='%',row=3,col=1)
    learning = go.Figure()
    for name,title in (('train_cross_entropy','Training'),('validation_cross_entropy','Validation')):
        learning.add_scatter(x=[r['epoch'] for r in history],y=[r[name] for r in history],name=title)
    learning.add_vline(x=summary['selected_epoch'],line_dash='dash')
    learning.update_layout(template='plotly_white',height=350,xaxis_title='Epoch',yaxis_title='Cross-entropy')
    monthly = table(['Close','NN CAGR','NN multiple','NN MaxDD','Sentinel CAGR','Sentinel MaxDD','SPY CAGR','SPY MaxDD'],[
        [m['session'],f"{m['series']['neural']['cagr']:.2%}",f"{float(m['series']['neural']['multiple']):.3f}×",
         f"{m['series']['neural']['maxdd']:.2%}",f"{m['series']['sentinel']['cagr']:.2%}",
         f"{m['series']['sentinel']['maxdd']:.2%}",f"{m['series']['spy']['cagr']:.2%}",
         f"{m['series']['spy']['maxdd']:.2%}"] for m in months])
    test = summary['classification']['test']
    matrix = table(['Teacher / predicted','0%','55%','100%'],[[a,*r] for a,r in zip(('0%','55%','100%'),test['confusion'])])
    text = f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Neural imitation of ideal Sentinel</title><style>body{{font:16px system-ui;max-width:1250px;margin:30px auto;padding:0 24px;color:#18212f;background:#fbfcfe}}p{{line-height:1.6}}h2{{margin-top:36px}}table{{border-collapse:collapse;width:100%;font-size:14px}}td,th{{padding:10px;border-bottom:1px solid #dbe3ed;text-align:right}}td:first-child,th:first-child{{text-align:left}}th{{background:#edf2f9}}.scroll{{overflow:auto}}.note{{background:#edf3fc;padding:16px;border-left:4px solid #2458b0}}</style>
<h1>Neural imitation of ideal Sentinel</h1><p>Model-held-out period: {summary['test_start']} close to {summary['test_end']} close.</p>
<p class="note">Training ends in 2012; 2013–2015 selects the checkpoint; 2016 onward is excluded from fitting and checkpoint selection. Each period has independently bounded hindsight labels. These dates were inspected in earlier research, so this is model holdout, not an untouched research holdout. No production change.</p>
<h2>Held-out economics</h2><div class="scroll">{metrics}</div>
<p>All controller policies share the starting holding, fixed Core/BIL path and next-open accounting. SPY is the retained passive benchmark. Turnover includes modeled changes in the Core/T-bill allocation. Hindsight uses future returns; the neural network uses only completed-close features.</p>
{fig.to_html(full_html=False,include_plotlyjs=True)}
<h2>Did it learn the ideal actions?</h2><div class="scroll">{fits}</div>
<p>Held-out accuracy of always predicting the training-majority action: {test['training_majority_accuracy']:.2%}; current Sentinel: {test['sentinel_accuracy']:.2%}. Classes lacking teacher examples have no positive training support.</p>
<div class="scroll">{matrix}</div>
<h2>Training checkpoint</h2><p>{summary['architecture']['parameters']} fitted weights/biases; selected epoch {summary['selected_epoch']} of {summary['epochs_run']} run. Selection uses validation cross-entropy, not test CAGR.</p>
{learning.to_html(full_html=False,include_plotlyjs=False)}
<h2>Monthly cumulative metrics</h2><p>All figures accumulate from the test baseline; annualized CAGR for a short initial period can be unstable. The last row may be an incomplete month.</p><div class="scroll">{monthly}</div>
<h2>Saved models</h2><p><code>evaluation-model.json</code> produced the held-out results above. <code>all-history-model.json</code> was separately fitted to all historical ideal labels for the already selected epoch count; it has no held-out result on these dates. Both store feature order, scaling and finite weights as JSON, without executable pickle. Later-data and forward qualification remain pending.</p></html>'''
    (root/'report.html').write_text(text,encoding='utf8')
    fig.write_json(root/'figure.json')
    learning.write_json(root/'learning-figure.json')
