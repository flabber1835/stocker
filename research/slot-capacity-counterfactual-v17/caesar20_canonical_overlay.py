#!/usr/bin/env python3
"""Canonical Caesar 20 definition for slot-capacity counterfactual diagnostics."""
from __future__ import annotations
import ast

ARMS=("CAESAR20_CANONICAL",)

def _rep(text,old,new,label):
    n=text.count(old)
    if n!=1: raise RuntimeError(f"{label}: expected 1 occurrence, got {n}")
    return text.replace(old,new,1)

def apply_arm(text:str,arm:str)->str:
    if arm!="CAESAR20_CANONICAL": raise ValueError(arm)
    out=_rep(text,"N_SLOTS = 25","N_SLOTS = 20","Caesar 20 slots")
    out=_rep(out,"ENTRY_W = 0.04","ENTRY_W = 0.05","Caesar 20 entry weight")
    ast.parse(out)
    for invariant in (
        "COOLDOWN = 21","REVIEW_AGE = 119","STOP_RET = 0.70",
        "budget=len(ready) if not book.initialized else 1","COST = 0.001",
        "MIN_ADV20 = 20_000_000.0","MIN_DAY_DV = 5_000_000.0",
        "book.receivables.append((gday+1,q*rawdiv))",
    ):
        if invariant not in out: raise RuntimeError(f"missing invariant: {invariant}")
    return out

def arm_dimensions(arm:str)->list[str]:
    if arm!="CAESAR20_CANONICAL": raise ValueError(arm)
    return ["caesar20","canonical","slot_capacity_counterfactual_base"]
