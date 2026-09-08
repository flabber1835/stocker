#!/usr/bin/env python3
"""Inject one counterfactual economic dimension into the frozen experiment runner.

Counterfactual: at the decision close, a new slot may be reserved only if cash
can fund the full whole-share ENTRY_W target. The ordinary next-open affordability
clipping remains unchanged, isolating the decision-time `min(target,cash)` rule.
"""
from pathlib import Path

p=Path('audit-src/research/champion-alpha-five-run-validation-v2/experiment_runner.py')
s=p.read_text()
helper=r'''
def _apply_full_target_cash_counterfactual(text: str) -> str:
    old = """                        target=min(eq*ENTRY_W,book.cash); q=int(target//(float(px)*(1+COST)))
                        if q<1: continue
"""
    new = """                        target=eq*ENTRY_W; q=int(target//(float(px)*(1+COST)))
                        if q<1: continue
                        _full_target_cost=float(q)*float(px)*(1+COST)
                        if book.cash+1e-9<_full_target_cost: continue
"""
    n=text.count(old)
    if n!=1:
        raise RuntimeError(f'full-target-cash counterfactual anchor count={n}')
    out=text.replace(old,new,1)
    compile(out,'<full-target-cash-counterfactual>','exec')
    return out
'''
anchor='\ndef main() -> int:\n'
if s.count(anchor)!=1: raise RuntimeError('runner main anchor mismatch')
s=s.replace(anchor,'\n'+helper+anchor,1)
old='    variant = apply_arm(certified_base, args.arm)\n'
new=old+'    variant = _apply_full_target_cash_counterfactual(variant)\n'
if s.count(old)!=1: raise RuntimeError('runner variant anchor mismatch')
s=s.replace(old,new,1)
p.write_text(s)
print('installed full-target-cash counterfactual')
