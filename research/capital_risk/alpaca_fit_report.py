"""Report only actual independently reviewed training and locked diagnostics."""
import argparse
from fractions import Fraction as Q
import hashlib
import html
import json
from pathlib import Path


def load(path):return json.loads(Path(path).read_bytes())
def pct(value):return f'{float(Q(str(value)))*100:.2f}%'
def growth(m):return f"{float(Q(m['multiple'])):.4f}×"


def report(training,diagnostic,output):
    training=Path(training);diagnostic=Path(diagnostic);output=Path(output)
    t=load(training/'stopped-independent-review/review/independent-review.json')
    d=load(diagnostic/'stopped-independent-review/review/independent-review.json')
    selection=load(training/'stopped-independent-review/review/locked-selection.json')
    rows=load(training/'stopped-independent-review/review/all-108-training.json')
    locked=load(diagnostic/'book/locked-selection-reference.json')
    assert t['stage']=='TRAINING' and d['stage']=='DIAGNOSTIC' and t['status']==d['status']=='COMPLETE_REVIEWED'
    assert t['financial_model_sha256']==d['financial_model_sha256'] and selection==locked
    assert selection['finite_class_exhaustive'] and len(rows)==108 and selection['validation_used_for_selection'] is False
    baseline=selection['baseline'];tr={r['profile_id']:r for r in t['profiles']};dr={r['profile_id']:r for r in d['profiles']}
    assert set(dr)==set([baseline]+selection['selected'])
    def diagnostic_metrics(r):
        # Whole continuation metrics include 2025. The diagnostic block must be
        # reconstructed from its actual stopped daily values with a Dec31 anchor.
        from selective_screen import metrics
        import gzip
        with gzip.open(diagnostic/'book/books'/r['profile_id']/'daily.jsonl.gz','rb') as f:daily=[json.loads(v) for v in f]
        train=[v for v in daily if v['session']<='2025-12-31'];valid=[v for v in daily if v['session']>='2026-01-02']
        assert train and valid and len(daily)==r['records']
        return metrics([(v['session'],v['nav']) for v in valid],anchor=('2025-12-31',Q(train[-1]['nav'])))
    diag={k:diagnostic_metrics(r) for k,r in dr.items()}
    base=diag[baseline];winners=[k for k,m in diag.items() if k!=baseline and m['cagr']>base['cagr']+1e-10
        and Q(m['maximum_drawdown_magnitude'])<Q(base['maximum_drawdown_magnitude'])-Q('1e-10')]
    verdict='Selected settings improved both metrics in the 2026 diagnostic.' if winners else 'No selected setting improved both metrics in the 2026 diagnostic.'
    if all(r['additional_funded_transitions']==0 for r in rows if r['profile_id']!=baseline):
        verdict='No setting produced an additional positive funded fill. This search provides no efficacy evidence.'
    def table(records,lookup):
        lines=[]
        for key in records:
            m=lookup[key];lines.append('<tr><td>'+html.escape(key)+('</td><td>'+'Baseline' if key==baseline else '</td><td>Candidate')+
                f"</td><td>{pct(m['total_return'])}</td><td>{pct(m['cagr'])}</td><td>{pct(m['maximum_drawdown_magnitude'])}</td><td>{growth(m)}</td></tr>")
        return '<table><thead><tr><th>Setting</th><th>Role</th><th>Return</th><th>CAGR</th><th>Max drawdown</th><th>Multiple</th></tr></thead><tbody>'+''.join(lines)+'</tbody></table>'
    training_lookup={r['profile_id']:r['metrics'] for r in rows}
    body=f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Owned55 finite fit — reviewed results</title><style>body{{font:16px/1.5 system-ui;max-width:1180px;margin:40px auto;padding:0 22px;color:#182536;background:#f7f9fc}}h1{{font-size:32px}}table{{border-collapse:collapse;width:100%;background:white;margin:20px 0}}th,td{{padding:10px;border-bottom:1px solid #d9e0e8;text-align:right}}th:first-child,td:first-child{{text-align:left}}.verdict{{background:#e3ebf4;padding:20px;border-radius:8px}}small{{color:#485970}}a{{color:#1854a1}}</style>
<h1>Owned55: exhaustive fit of 108 existing parameter settings</h1><p class="verdict">{html.escape(verdict)}</p>
<p>Every setting was ranked using complete net 2025 accounts. Selection was locked before the selected settings and baseline continued into 2026. PAPER remained untouched.</p>
<h2>2026 diagnostic: locked shortlist and matched baseline</h2><p>January 2 to October 27, using each account’s actual December 31 value. CAGR is annualized over this shorter period.</p>{table(list(dr),diag)}
<h2>2025 training: all 108 settings</h2><p>These are fitted results. The finite search is exhaustive; its gap is zero only within the declared 108-setting family. The best attainable performance over other architectures remains unknown.</p>{table([r['profile_id'] for r in rows],training_lookup)}
<h2>What the comparison establishes</h2><p>The comparison uses persistent stock quantities, actual whole-share buys and cash clipping, 10-basis-point stock costs, raw-price marking, recorded claims and a BIL adjusted-return cash proxy. The independent review checked event equations, funded timing, every daily factor, typed checkpoints and journal commitments. A changed exposure signal is insufficient treatment without a differing positive fill.</p>
<p>SPY is a gross adjusted-price benchmark starting at the same first funded open. It excludes modeled stock transaction fees; the strategy accounts include them.</p>
<h2>Limits and production decision</h2><p>This is known history, with a current-cohort survivor-conditioned roster, revised provider history and current classifications. The 2026 diagnostic was not used for selection, but is not unseen out-of-sample evidence. Historical source admission includes explicit name, split-boundary and merger-recipient corrections; provider evidence is not equivalent to issuer verification for every record. Unsupported economic conversions remain refusals.</p>
<p>The research fill model is idealized next raw open, not PAPER’s protected LIMIT/DAY execution. No result certifies the installed system or authorizes promotion. PAPER, broker state and database state were not changed.</p>
<h2>Retained evidence</h2><ul><li><a href="training-selection.json">Locked selection</a></li><li><a href="all-108-training.json">All training scores</a></li><li><a href="diagnostic-metrics.json">Diagnostic metrics</a></li><li><a href="evidence-manifest.json">Evidence hashes and paths</a></li></ul>
<small>Financial model SHA256: {t['financial_model_sha256']}</small></html>'''
    output.mkdir(parents=True,exist_ok=False)
    (output/'REPORT.html').write_text(body,encoding='utf-8')
    for name,value in [('training-selection',selection),('all-108-training',rows),('diagnostic-metrics',diag)]:
        (output/(name+'.json')).write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')
    evidence={}
    for name,root in [('training',training),('diagnostic',diagnostic)]:
        path=root/'stopped-independent-review/review/independent-review.json'
        evidence[name]={'review_path':str(path),'review_sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    (output/'evidence-manifest.json').write_text(json.dumps(evidence,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'verdict':verdict,'report':str(output/'REPORT.html'),'diagnostic_joint_winners':winners}))


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ('training','diagnostic','output'):p.add_argument('--'+name,required=True)
    a=p.parse_args();report(a.training,a.diagnostic,a.output)
