#!/usr/bin/env python3
from pathlib import Path

p = Path('audit-src/research/champion-alpha-five-run-validation-v2/experiment_runner.py')
s = p.read_text()
needle = '    (out / "experiment-generated.py").write_text(variant)\n'
marker = "    (OUT/'summary.json').write_text(json.dumps(summary,indent=2))"
witness = """    _end_eq,_end_unresolved=book.equity(raw)
    _end_cash=float(book.cash+sum(x[1] for x in book.receivables))
    _end_alloc=float(eff['A'])
    _end_positions=[]
    for _slot in book.slots:
        if not _slot.held(): continue
        _tid=int(_slot.tid); _px=float(raw[_tid])
        if not (finite(_px) and _px>0): _px=float(book.last_raw.get(_tid,float('nan')))
        if not (finite(_px) and _px>0): raise RuntimeError(f'end-book unresolved price tid={_tid}')
        _mv=float(_slot.qty*_px); _wcw=float(_mv/_end_eq); _effw=float(_end_alloc*_wcw)
        _end_positions.append({'ticker':str(tick[_tid]),'security_id':str(sid[_tid]),'shares':float(_slot.qty),'price':_px,'market_value':_mv,'wealth_core_weight':_wcw,'effective_portfolio_weight':_effw})
    _end_positions.sort(key=lambda z:(-z['effective_portfolio_weight'],z['ticker'],z['security_id']))
    _wc_cash_weight=float(_end_cash/_end_eq)
    _defensive_cash_weight=float(1.0-_end_alloc)
    _effective_wc_cash_weight=float(_end_alloc*_wc_cash_weight)
    _combined_cash_weight=float(_defensive_cash_weight+_effective_wc_cash_weight)
    _endbook={'date':str(date.date()),'full_pit':bool(PIT_MODE),'replay_mode':str(MODE),'book_equity':float(_end_eq),'book_cash_and_receivables':_end_cash,'book_unresolved':bool(_end_unresolved),'overlay_allocation':_end_alloc,'wealth_core_cash_weight':_wc_cash_weight,'effective_wealth_core_cash_weight':_effective_wc_cash_weight,'defensive_cash_weight':_defensive_cash_weight,'combined_cash_weight':_combined_cash_weight,'positions':_end_positions,'position_weight_sum':float(sum(z['effective_portfolio_weight'] for z in _end_positions)),'total_weight_sum':float(sum(z['effective_portfolio_weight'] for z in _end_positions)+_combined_cash_weight)}
    (OUT/'endbook.json').write_text(json.dumps(_endbook,indent=2,sort_keys=True))
"""
replacement = (
    '    marker = ' + repr(marker) + '\n'
    '    witness = ' + repr(witness) + '\n'
    "    if marker not in variant: raise RuntimeError('end-book injection marker missing')\n"
    '    variant = variant.replace(marker, witness + marker, 1)\n'
    '    (out / "experiment-generated.py").write_text(variant)\n'
)
if needle not in s:
    raise RuntimeError('runner injection point missing')
p.write_text(s.replace(needle, replacement, 1))
print('instrumented experiment_runner.py')
