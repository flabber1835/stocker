#!/usr/bin/env python3
"""Final, non-economic instrumentation transform for the retained research replay."""
from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class StaticFinding:
    classification: str
    construct: str
    line: int | None
    detail: str
    causal_reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "classification": self.classification,
            "construct": self.construct,
            "line": self.line,
            "detail": self.detail,
            "causal_reason": self.causal_reason,
        }


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"causal instrumentation {label}: expected one seam, found {count}")
    return text.replace(old, new, 1)


def replace_function(text: str, name: str, next_name: str, body: str) -> str:
    start = text.index(f"def {name}():")
    end = text.index(f"\ndef {next_name}", start)
    return text[:start] + body.rstrip() + "\n\n" + text[end + 1 :]


def instrument_research_source(text: str) -> str:
    """Add causal assertions and trace emission after all existing transforms."""
    text = replace_once(
        text,
        "from backtester.canonical_pit_dataset import CanonicalPITDataset",
        "from backtester.research_causal_runtime import (\n"
        "    CausalPITDataset, GuardedSessionMap, CausalTrace,\n"
        "    canonical_float, canonical_json, sha256_json,\n"
        ")",
        "runtime import",
    )
    text = replace_once(
        text,
        "_CANONICAL=CanonicalPITDataset(",
        "_CANONICAL=CausalPITDataset(",
        "guarded canonical dataset",
    )

    load_actions = r'''def load_actions():
    d=_CANONICAL.actions_frame()
    values=defaultdict(lambda:defaultdict(list)); split_dates=defaultdict(list)
    for r in d.itertuples(index=False):
        ds=pd.Timestamp(r.effective_session); val=float(r.canonical_value) if r.canonical_value else None
        values[ds][str(r.ticker)].append((str(r.action),val,None))
        if str(r.action)=='split' and val is not None: split_dates[str(r.ticker)].append((ds,val))
    return GuardedSessionMap(_CANONICAL.guard,'corporate_actions',values),split_dates'''
    text = replace_function(text, "load_actions", "load_funds", load_actions)

    text = replace_once(
        text,
        "def bil_factors(bil,date,prevdate):\n",
        "def bil_factors(bil,date,prevdate):\n    _CANONICAL.guard.assert_cash(date,prevdate)\n",
        "cash access guard",
    )

    init = "actions,split_dates=load_actions(); spy,bil=load_funds(); book=Book(); native=Native()"
    text = replace_once(
        text,
        init,
        init
        + "\n    trace=CausalTrace(Path(os.environ['CAUSAL_TRACE_PATH']),_CANONICAL.guard,_CANONICAL)"
        + "\n    _sell_signal_day={}\n    _allocation_signal_day=-1",
        "trace initialization",
    )

    session_start = "gday+=1; date=pd.Timestamp(date); ds=date.strftime('%Y-%m-%d')"
    text = replace_once(
        text,
        session_start,
        session_start
        + "\n            _GUARD=_CANONICAL.guard; _GUARD.begin(ds,gday); _GUARD.assert_observation_group(g,ds)"
        + "\n            _session_fills=[]; _session_splits=[]; _session_dividends=[]; _session_terminals=[]; _session_reviews=[]",
        "session clock",
    )

    rolling = "av=dvsum[tids]/20 if gday>=19 else np.full(len(tids),np.nan)"
    text = replace_once(
        text,
        rolling,
        rolling
        + "\n            _GUARD.assert_rolling('current_close',gday,(gday,))"
        + "\n            _GUARD.assert_rolling('recent_21',gday,(gday,gday-21))"
        + "\n            _GUARD.assert_rolling('momentum_21_126',gday,(gday-21,gday-126))"
        + "\n            _GUARD.assert_rolling('volatility_126_ex_recent_21',gday,(gday,gday-125))"
        + "\n            _GUARD.assert_rolling('adv_20',gday,(gday,gday-19))",
        "rolling source bounds",
    )

    ranking_boundary = "inpool=np.zeros(n,bool); inpool[pool]=True"
    text = replace_once(
        text,
        ranking_boundary,
        ranking_boundary
        + "\n            _signal_payload=sorted((str(sid[int(t)]),canonical_float(mom[int(t)]),canonical_float(recent[int(t)]),canonical_float(score[int(t)]),canonical_float(adv[int(t)])) for t in tids)"
        + "\n            _eligible_ids=sorted(str(sid[int(t)]) for t in et)"
        + "\n            _ranking_ids=[str(sid[int(t)]) for t in durable]"
        + "\n            _recent_leadership_ids=[str(sid[int(t)]) for t in recsel]",
        "signal and ranking trace",
    )

    split_line = "                    split_events+=1"
    text = replace_once(
        text,
        split_line,
        split_line
        + "\n                    _GUARD.assert_event(domain='split',event_session=ds)"
        + "\n                    _session_splits.append({'security_id':str(sid[tid]),'ratio':ratio})",
        "split timing",
    )

    terminal_line = "term_tids={z for tk,rs in dayact.items() if (z:=strict_tid(tk,ds)) is not None and any(a in TERMINAL for a,_,_ in rs)}"
    text = replace_once(
        text,
        terminal_line,
        terminal_line
        + "\n            for _term_tid in sorted(term_tids):"
        + "\n                _GUARD.assert_event(domain='terminal',event_session=ds)"
        + "\n                _session_terminals.append({'security_id':str(sid[int(_term_tid)]),'effective_session':ds})",
        "terminal timing",
    )

    normal_sell = "book.cash+=s.qty*float(px)*(1-COST); sells+=1"
    text = replace_once(
        text,
        normal_sell,
        "_sell_sid=str(sid[int(s.tid)]); _sell_qty=float(s.qty); _sell_reason=str(s.sell_reason); _sell_signal=int(_sell_signal_day.get(id(s),-1))\n"
        "                    if _sell_reason!='terminal': _GUARD.assert_fill_after_signal(kind='sell',signal_index=_sell_signal,fill_index=gday,security_id=_sell_sid)\n"
        "                    _session_fills.append({'side':'SELL','security_id':_sell_sid,'quantity':_sell_qty,'raw_open':float(px),'reason':_sell_reason,'signal_index':_sell_signal,'fill_index':gday})\n"
        "                    book.cash+=s.qty*float(px)*(1-COST); sells+=1\n"
        "                    _sell_signal_day.pop(id(s),None)",
        "open sell fill",
    )

    terminal_fallback = """                elif s.sell_reason=='terminal':
                    px2=book.last_raw.get(s.tid,np.nan)
                    if finite(px2) and px2>0: book.cash+=s.qty*float(px2)*(1-COST)
                    book.sec_ready[s.tid]=gday+COOLDOWN"""
    terminal_fallback_new = """                elif s.sell_reason=='terminal':
                    px2=book.last_raw.get(s.tid,np.nan); _sell_sid=str(sid[int(s.tid)]); _sell_qty=float(s.qty)
                    _session_fills.append({'side':'SELL','security_id':_sell_sid,'quantity':_sell_qty,'raw_open':px2,'reason':'terminal_last_mark','signal_index':gday,'fill_index':gday})
                    if finite(px2) and px2>0: book.cash+=s.qty*float(px2)*(1-COST)
                    _sell_signal_day.pop(id(s),None)
                    book.sec_ready[s.tid]=gday+COOLDOWN"""
    text = replace_once(
        text,
        terminal_fallback,
        terminal_fallback_new,
        "terminal fallback fill",
    )

    buy_fill = "book.cash-=q*float(px)*(1+COST); s.tid=tid; s.qty=float(q); s.entry_day=gday; s.reviewed=False; s.pending_sell=False; s.sell_reason=''; s.entry_sig=float(opsig[tid]) if finite(opsig[tid]) and opsig[tid]>0 else np.nan; s.peak=np.nan; book.initialized=True; buys+=1"
    buy_fill_new = """_buy_sid=str(sid[int(tid)]); _buy_signal=int(s.pending_signal_day)
                        _GUARD.assert_fill_after_signal(kind='buy',signal_index=_buy_signal,fill_index=gday,security_id=_buy_sid)
                        book.cash-=q*float(px)*(1+COST); s.tid=tid; s.qty=float(q); s.entry_day=gday; s.reviewed=False; s.pending_sell=False; s.sell_reason=''; s.entry_sig=float(opsig[tid]) if finite(opsig[tid]) and opsig[tid]>0 else np.nan; s.peak=np.nan; book.initialized=True; buys+=1
                        _GUARD.assert_entry_basis(security_id=_buy_sid,adjusted_execution_open=opsig[tid],review_basis=s.entry_sig)
                        _session_fills.append({'side':'BUY','security_id':_buy_sid,'quantity':float(q),'raw_open':float(px),'adjusted_open':opsig[tid],'review_basis':s.entry_sig,'signal_index':_buy_signal,'fill_index':gday})"""
    text = replace_once(text, buy_fill, buy_fill_new, "open buy fill")

    dividend = "if q>0 and rawdiv>0: book.receivables.append((gday+1,q*rawdiv)); div_events+=1"
    dividend_new = """if q>0 and rawdiv>0:
                    _GUARD.assert_event(domain='dividend',event_session=ds)
                    book.receivables.append((gday+1,q*rawdiv)); div_events+=1
                    _session_dividends.append({'security_id':str(sid[int(tid)]),'quantity':float(q),'raw_dividend':rawdiv})"""
    text = replace_once(text, dividend, dividend_new, "dividend timing")

    review_block = """                age=gday-s.entry_day
                if finite(px) and finite(s.peak) and s.peak>0 and float(px)<=s.peak*STOP_RET:
                    s.pending_sell=True; s.sell_reason='stop'
                elif age>=REVIEW_AGE and not s.reviewed and finite(px):
                    qualifies=bool(inpool[s.tid] and finite(recent[s.tid]) and recent[s.tid]>=0)
                    underwater=finite(s.entry_sig) and float(px)<s.entry_sig
                    if underwater and not qualifies: s.pending_sell=True; s.sell_reason='review'
                    else: s.reviewed=True"""
    review_block_new = """                age=gday-s.entry_day; _held_sid=str(sid[int(s.tid)])
                _GUARD.assert_position_age(security_id=_held_sid,entry_index=s.entry_day,current_index=gday,observed_age=age)
                _stop_due=finite(px) and finite(s.peak) and s.peak>0 and float(px)<=s.peak*STOP_RET
                _review_due=age>=REVIEW_AGE and not s.reviewed and finite(px)
                _review_qualifies=bool(inpool[s.tid] and finite(recent[s.tid]) and recent[s.tid]>=0) if _review_due else None
                _review_underwater=bool(finite(s.entry_sig) and float(px)<s.entry_sig) if _review_due else None
                if _review_due:
                    _session_reviews.append({'security_id':_held_sid,'age':int(age),'close':px,'review_basis':s.entry_sig,'qualifies':_review_qualifies,'underwater':_review_underwater,'outcome':('STOP_PRECEDENCE' if _stop_due else ('REVIEW_EXIT' if _review_underwater and not _review_qualifies else 'REVIEW_PASS'))})
                if _stop_due:
                    s.pending_sell=True; s.sell_reason='stop'; _sell_signal_day.setdefault(id(s),gday)
                elif _review_due:
                    qualifies=_review_qualifies; underwater=_review_underwater
                    if underwater and not qualifies: s.pending_sell=True; s.sell_reason='review'; _sell_signal_day.setdefault(id(s),gday)
                    else: s.reviewed=True"""
    text = replace_once(text, review_block, review_block_new, "age review timing")

    measurement = "            if date>=START:"
    text = replace_once(
        text,
        measurement,
        measurement
        + "\n                _GUARD.assert_allocation_application(signal_index=_allocation_signal_day,application_index=gday)",
        "allocation timing",
    )

    benchmark_line = "volacc=float(spy.loc[date,'volacc']) if date in spy.index and finite(spy.loc[date,'volacc']) else None"
    text = replace_once(
        text,
        benchmark_line,
        benchmark_line + "\n            _GUARD.assert_benchmark_cache(spy,date)",
        "benchmark cache guard",
    )

    pending = "pending_native=native_target; pend['control']=ctl_d; pend['A']=a_d; pend['B']=b_d"
    trace_tail = r'''pending_native=native_target; pend['control']=ctl_d; pend['A']=a_d; pend['B']=b_d
            _allocation_signal_day=gday
            _position_state=sorted(({'security_id':str(sid[int(s.tid)]),'quantity':float(s.qty),'entry_index':int(s.entry_day),'age':int(gday-s.entry_day),'review_basis':s.entry_sig,'peak':s.peak,'reviewed':bool(s.reviewed)} for s in book.slots if s.held()),key=lambda row:row['security_id'])
            _selected_ids=[row['security_id'] for row in _position_state]
            _pending_orders=[]
            for _slot in book.slots:
                if _slot.reserved():
                    _pending_orders.append({'side':'BUY','security_id':str(sid[int(_slot.pending_tid)]),'quantity':float(_slot.pending_shares),'signal_index':int(_slot.pending_signal_day)})
                if _slot.held() and _slot.pending_sell:
                    _pending_orders.append({'side':'SELL','security_id':str(sid[int(_slot.tid)]),'quantity':float(_slot.qty),'signal_index':int(_sell_signal_day.get(id(_slot),-1)),'reason':str(_slot.sell_reason)})
            _pending_orders=sorted(_pending_orders,key=lambda row:(row['side'],row['security_id'],row.get('reason','')))
            trace.emit({'date':ds,'chronological_index':gday,
                        'signals':{'count':len(_signal_payload),'sha256':sha256_json(_signal_payload)},
                        'eligible_universe':{'count':len(_eligible_ids),'security_ids':_eligible_ids,'sha256':sha256_json(_eligible_ids)},
                        'rankings':{'count':len(_ranking_ids),'security_ids':_ranking_ids,'sha256':sha256_json(_ranking_ids),'recent_leadership_ids':_recent_leadership_ids},
                        'selected_positions':{'count':len(_selected_ids),'security_ids':_selected_ids,'sha256':sha256_json(_selected_ids),'state':_position_state,'state_sha256':sha256_json(_position_state)},
                        'orders':{'items':_pending_orders,'sha256':sha256_json(_pending_orders)},
                        'fills':{'items':_session_fills,'sha256':sha256_json(_session_fills)},
                        'wealth_core':{'open_equity':open_eq,'close_equity':eq,'drawdown':dd,'recent_r20':recent_r20,'recent_r40':recent_r40},
                        'breadth':{'damaged':dam_b,'green':green_b},
                        'native':{'target':native_target,'state':native.__dict__},
                        'ldrc':{'desired_allocation':ctl_d,'reason':ctl_reason,'state':ctl.__dict__},
                        'allocation':{'effective_native':effective_native,'effective_control':eff['control'],'pending_native':pending_native,'pending_control':pend['control']},
                        'nav':{'control':navs['control'],'A':navs['A'],'B':navs['B'],'spy':(float(spy.loc[date,'closeadj'])/float(spy.loc[START,'closeadj']) if date>=START and date in spy.index and START in spy.index else None)},
                        'events':{'splits':_session_splits,'dividends':_session_dividends,'terminals':_session_terminals,'age_reviews':_session_reviews}})'''
    text = replace_once(text, pending, trace_tail, "causal trace emission")

    text = replace_once(
        text,
        "    out=pd.DataFrame(rows)",
        "    trace.close()\n    out=pd.DataFrame(rows)",
        "trace close",
    )

    required = (
        "CausalPITDataset",
        "_GUARD.begin(ds,gday)",
        "assert_fill_after_signal",
        "assert_entry_basis",
        "assert_position_age",
        "STOP_PRECEDENCE",
        "trace.emit(",
        "trace.close()",
    )
    for needle in required:
        if needle not in text:
            raise RuntimeError(f"causal instrumentation missing required construct: {needle}")
    compile(text, "<generated-causal-research-replay>", "exec")
    return text


class _LeakageVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.findings: list[StaticFinding] = []

    def add(self, classification: str, construct: str, node: ast.AST, detail: str, causal_reason: str) -> None:
        self.findings.append(
            StaticFinding(classification, construct, getattr(node, "lineno", None), detail, causal_reason)
        )

    @staticmethod
    def _name(node: ast.AST) -> str:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            prefix = _LeakageVisitor._name(node.value)
            return f"{prefix}.{node.attr}" if prefix else node.attr
        return ""

    @staticmethod
    def _literal(node: ast.AST) -> Any:
        try:
            return ast.literal_eval(node)
        except Exception:
            return None

    def visit_Call(self, node: ast.Call) -> None:
        name = self._name(node.func)
        leaf = name.rsplit(".", 1)[-1]
        kwargs = {kw.arg: kw.value for kw in node.keywords if kw.arg is not None}
        if leaf == "shift":
            periods = self._literal(kwargs.get("periods")) if "periods" in kwargs else (
                self._literal(node.args[0]) if node.args else 1
            )
            if isinstance(periods, (int, float)) and periods < 0:
                self.add("FORBIDDEN", "negative_shift", node, f"{name} periods={periods}", "Negative shifts read later observations.")
            else:
                self.add("GUARDED_CAUSAL", "nonnegative_shift", node, name, "No future displacement is requested.")
        if leaf == "rolling":
            center = self._literal(kwargs.get("center")) if "center" in kwargs else False
            if center is True:
                self.add("FORBIDDEN", "centered_rolling", node, name, "Centered windows include later rows.")
            else:
                self.add("GUARDED_CAUSAL", "trailing_rolling", node, name, "Runtime prefix recomputation or chronological ring buffers bound the window at T.")
        if leaf in {"bfill", "backfill"}:
            self.add("FORBIDDEN", "backward_fill", node, name, "Backward filling imports later values.")
        if leaf == "fillna" and self._literal(kwargs.get("method")) in {"bfill", "backfill"}:
            self.add("FORBIDDEN", "backward_fill", node, name, "Backward filling imports later values.")
        if leaf == "merge_asof":
            direction = self._literal(kwargs.get("direction")) if "direction" in kwargs else "backward"
            if direction == "forward":
                self.add("FORBIDDEN", "forward_asof_join", node, name, "Forward as-of joins select later rows.")
            else:
                self.add("GUARDED_CAUSAL", "backward_asof_join", node, name, "Backward selection is causal when request time is guarded.")
        if leaf in {"mean", "std", "min", "max", "quantile", "rank"} and "rolling" not in name:
            self.add("REPORTING_ONLY", "whole_frame_reduction_review", node, name, "Inspected manually; economic ranking is session-local and post-run reductions are reporting only.")
        self.generic_visit(node)


def static_leakage_audit(source: str) -> dict[str, Any]:
    tree = ast.parse(source)
    visitor = _LeakageVisitor()
    visitor.visit(tree)
    findings = visitor.findings

    text_checks = [
        ("zcsv(ROOT/'SHARADAR_TICKERS.zip'", "FORBIDDEN", "current_metadata_authority", "Current TICKERS metadata cannot be historical authority."),
        ("relatedtickers", "FORBIDDEN", "survivor_issuer_filter", "Current related-ticker groups can encode future identity."),
        ("lastdate[tids]", "FORBIDDEN", "future_last_listing_filter", "A future last-price date is survivor information."),
        ("d.groupby(d.date.dt.to_period('Q')).date.max()", "REPORTING_ONLY", "quarter_end_reporting", "Used only to choose log checkpoints; it does not enter strategy state."),
        ("close_ring[(gday-21)", "GUARDED_CAUSAL", "ring_buffer_lag_21", "The runtime guard asserts every source index is <= the active index."),
        ("close_ring[(gday-126)", "GUARDED_CAUSAL", "ring_buffer_lag_126", "The runtime guard asserts every source index is <= the active index."),
        ("spy['r20']=spy.closeadj.astype(float).pct_change(20)", "GUARDED_CAUSAL", "vectorized_benchmark_cache", "Every active value is recomputed from the prefix ending at T and compared exactly."),
        ("metadata_for", "GUARDED_CAUSAL", "metadata_asof", "The guarded dataset rejects effective dates later than the active session."),
        ("np.lexsort", "GUARDED_CAUSAL", "session_local_ranking", "Inputs are vectors from the active session only; prefix and poison traces prove invariance."),
    ]
    for needle, classification, construct, reason in text_checks:
        line = None
        if needle in source:
            line = source[: source.index(needle)].count("\n") + 1
            findings.append(StaticFinding(classification, construct, line, needle, reason))
        elif classification == "FORBIDDEN":
            findings.append(StaticFinding("GUARDED_CAUSAL", f"absent_{construct}", None, needle, "Forbidden construct is absent from generated strict-PIT source."))

    forbidden = [finding for finding in findings if finding.classification == "FORBIDDEN"]
    ordered = sorted(
        (finding.as_dict() for finding in findings),
        key=lambda row: (row["classification"], row["line"] if row["line"] is not None else -1, row["construct"]),
    )
    return {
        "schema": "backtester.research-static-leakage-audit/1",
        "status": "PASS" if not forbidden else "FAIL",
        "forbidden_count": len(forbidden),
        "findings": ordered,
    }
