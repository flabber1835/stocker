"""Offline research evidence, with local event scores kept distinct from CAGR."""
from html import escape
import json

import plotly.graph_objects as go
from plotly.subplots import make_subplots


def write(output, summary, anatomy):
    fig = make_subplots(rows=2, cols=1, subplot_titles=('What the target oracle captured (log wealth)',
        'Out-of-block precision versus event base rate; fixed logistic probes'))
    for key, title in (('intraday_log','Intraday'),('overnight_log','Overnight'),
                       ('allocation_residual_log','Allocation convention'),('cost_log','Costs')):
        fig.add_trace(go.Bar(name=title, x=[e['decision'] for e in anatomy['episodes']],
                            y=[e[key] for e in anatomy['episodes']]), row=1, col=1)
    records = [r for r in summary['probes'] if r['view']=='augmented' and r['model']=='logistic']
    for task in ('exit','entry'):
        select = [r for r in records if r['task']==task and r['aggregate']['precision'] is not None]
        fig.add_trace(go.Scatter(name=task+' precision lift', mode='markers',
            x=[f"{r['tier']} / {r['horizon']}d" for r in select],
            y=[r['aggregate']['precision']-r['aggregate']['base_rate'] for r in select],
            text=[f"n={r['aggregate']['n']}; flagged={r['aggregate']['flagged']}" for r in select]), row=2,col=1)
    fig.update_layout(height=950, barmode='relative', template='plotly_white', title='From ideal hindsight actions to observable signals')
    headers = ('tier','view','task','horizon','model','n','base rate','AUC','precision','flags','false alarms','mean event gain')
    table = []
    def fmt(v): return 'unavailable' if v is None else f'{v:.3f}'
    for r in summary['probes']:
        m = r['aggregate']
        cells = [r['tier'],r['view'],r['task'],r['horizon'],r['model'],m['n'],fmt(m['base_rate']),
                 fmt(m['auc']),fmt(m['precision']),m['flagged'],m['false_alarms'],fmt(m['mean_flagged_gain'])]
        table.append('<tr>'+''.join('<td>'+escape(str(v))+'</td>' for v in cells)+'</tr>')
    html = '<!doctype html><meta charset="utf-8"><title>Sentinel signal study</title><style>body{font:16px system-ui;margin:36px;max-width:1600px}td,th{padding:7px;border-bottom:1px solid #ddd;text-align:right}th{position:sticky;top:0;background:white}p{max-width:1000px}</style>'
    html += '<h1>Sentinel signal study</h1><p>'+escape(summary['caveat'])+'</p>'
    html += '<p>The anchor changes 22 decisions to reach 25% CAGR. These sparse, full-history choices are described, never used as model training labels. Independent local outcomes ask whether a temporary full exit or entry would add at least 1% relative wealth after costs. Rejoin overnight is included; the first next-open gap is already owned.</p>'
    html += '<p>All models use earlier completed outcomes. Augmented tiers have date-matched existing-feature controls. Overlapping events are not independent samples or additive portfolio returns. Tree threshold ties can flag more than 10%; thresholds are frozen from training.</p>'
    html += fig.to_html(full_html=False, include_plotlyjs=True)
    html += '<h2>Coverage</h2><pre>'+escape(json.dumps(summary['complete_feature_dates'], indent=2))+'</pre>'
    html += '<h2>Chronological probe diagnostics</h2><table><thead><tr>'+''.join('<th>'+escape(h)+'</th>' for h in headers)+'</tr></thead><tbody>'+''.join(table)+'</tbody></table>'
    html += '<p>See summary.json for per-block scores, oracle-profiles.json for exact decision-close values and retrospective percentiles, models.json for frozen coefficients/trees, and audit.json for independent reconstruction.</p>'
    (output/'report.html').write_text(html, encoding='utf8')
