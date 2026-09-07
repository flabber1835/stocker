#!/usr/bin/env python3
"""Exact-source economic alignment for the final Production-equivalent replay."""
from __future__ import annotations
import ast

FINAL_CLASSIFIER_IMPORT = "from backtester import champion_final_security_truth as _bestclass"
DIVIDEND_LAG_SESSIONS = 1


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _replace_classifier(text: str) -> str:
    candidates = (
        "from backtester import research_champion_corrected_classification as _bestclass",
        "from backtester import champion_security_truth_overlay_v2 as _bestclass",
    )
    hits = [old for old in candidates if old in text]
    if len(hits) != 1 or text.count(hits[0]) != 1:
        raise RuntimeError(f"final truth classifier seam is not unique: {hits}")
    return text.replace(hits[0], FINAL_CLASSIFIER_IMPORT, 1)


def _dividend_due_lag(text: str) -> int:
    """Return the exact integer K from the unique book.receivables.append((gday+K,...))."""
    hits = []
    for node in ast.walk(ast.parse(text)):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        owner = node.func.value
        if not (node.func.attr == "append" and isinstance(owner, ast.Attribute)
                and owner.attr == "receivables" and isinstance(owner.value, ast.Name)
                and owner.value.id == "book"):
            continue
        if len(node.args) != 1 or not isinstance(node.args[0], ast.Tuple) or not node.args[0].elts:
            raise RuntimeError("unexpected dividend receivable representation")
        due = node.args[0].elts[0]
        if not (isinstance(due, ast.BinOp) and isinstance(due.op, ast.Add)
                and isinstance(due.left, ast.Name) and due.left.id == "gday"
                and isinstance(due.right, ast.Constant) and type(due.right.value) is int):
            raise RuntimeError("dividend due session must be exactly gday + integer")
        hits.append(int(due.right.value))
    if len(hits) != 1:
        raise RuntimeError(f"dividend receivable append is not unique: {hits}")
    return hits[0]



def assert_one_session_dividend_lag(text: str) -> int:
    """Validate the executable due expression and return its observed lag."""
    lag = _dividend_due_lag(text)
    if lag != DIVIDEND_LAG_SESSIONS:
        raise RuntimeError(f"dividend lag must be exactly {DIVIDEND_LAG_SESSIONS} session; observed {lag}")
    return lag


def _summary_lag_node(text: str) -> ast.Constant:
    values = []
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if isinstance(key, ast.Constant) and key.value == "financial_grade_dividend_lag_sessions":
                    values.append(value)
    if len(values) != 1:
        raise RuntimeError(f"dividend summary field is not unique: {len(values)}")
    value = values[0]
    if not isinstance(value, ast.Constant) or type(value.value) is not int:
        raise RuntimeError("dividend summary lag must be an integer literal")
    return value


def _align_dividend_summary(text: str) -> str:
    """Keep the generated engine's summary consistent with its exact due expression."""
    lag = assert_one_session_dividend_lag(text)
    node = _summary_lag_node(text)
    if node.value not in (1, 15):
        raise RuntimeError(f"unrecognized inherited dividend summary lag: {node.value}")
    if node.value == lag:
        return text
    # AST columns are UTF-8 byte offsets. Change only the value of this key.
    lines = text.encode("utf-8").splitlines(keepends=True)
    start = sum(map(len, lines[:node.lineno - 1])) + node.col_offset
    end = sum(map(len, lines[:node.end_lineno - 1])) + node.end_col_offset
    raw = text.encode("utf-8")
    result = (raw[:start] + str(lag).encode("ascii") + raw[end:]).decode("utf-8")
    if _summary_lag_node(result).value != lag:
        raise RuntimeError("dividend summary alignment failed")
    return result


def _force_one_session_dividend_lag(text: str) -> str:
    """Convert the inherited historical lag to the authoritative one-session contract."""
    inherited_lag = _dividend_due_lag(text)
    if inherited_lag not in (1, 15):
        raise RuntimeError(f"unrecognized inherited dividend lag: {inherited_lag}")
    tree = ast.parse(text)
    target = None
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        owner = node.func.value
        if (node.func.attr == "append" and isinstance(owner, ast.Attribute)
                and owner.attr == "receivables" and isinstance(owner.value, ast.Name)
                and owner.value.id == "book"):
            if target is not None:
                raise RuntimeError("multiple dividend receivable appends")
            target = node
    if target is None:
        raise RuntimeError("dividend receivable append missing")
    due = target.args[0].elts[0]
    if not (isinstance(due, ast.BinOp) and isinstance(due.op, ast.Add)
            and isinstance(due.left, ast.Name) and due.left.id == "gday"
            and isinstance(due.right, ast.Constant) and type(due.right.value) is int):
        raise RuntimeError("unexpected dividend due-session expression")
    old = int(due.right.value)
    if old == DIVIDEND_LAG_SESSIONS:
        return text
    # Exact textual replacement is anchored to the AST-proven expression.
    segment = ast.get_source_segment(text, due)
    if segment is None or text.count(segment) != 1:
        raise RuntimeError("cannot uniquely rewrite dividend due-session expression")
    out = text.replace(segment, f"gday+{DIVIDEND_LAG_SESSIONS}", 1)
    if _dividend_due_lag(out) != DIVIDEND_LAG_SESSIONS:
        raise RuntimeError("one-session dividend rewrite failed")
    return out


def _move_dividend_accrual_before_open_equity(text: str) -> str:
    lines = text.splitlines(keepends=True)
    open_hits = [i for i, line in enumerate(lines) if "open_eq,_=book.equity(opraw)" in line]
    append_hits = [i for i, line in enumerate(lines) if "receivables.append" in line]
    if len(open_hits) != 1 or len(append_hits) != 1:
        raise RuntimeError(f"dividend/open-equity seam not unique: open={open_hits} append={append_hits}")
    oi, ai = open_hits[0], append_hits[0]
    if ai < oi:
        if _dividend_due_lag(text) != DIVIDEND_LAG_SESSIONS:
            raise RuntimeError("pre-open dividend accrual is not exactly one session")
        return text
    start = None
    for i in range(ai, max(-1, ai - 12), -1):
        stripped = lines[i].lstrip()
        if stripped.startswith("for ") and stripped.rstrip().endswith(":"):
            start = i; break
    if start is None:
        raise RuntimeError("could not find dividend accrual loop start")
    base_indent = _indent(lines[start]); end = start + 1
    while end < len(lines):
        if lines[end].strip() and _indent(lines[end]) <= base_indent: break
        end += 1
    block = lines[start:end]
    if "receivables.append" not in "".join(block):
        raise RuntimeError("identified block is not dividend accrual")
    del lines[start:end]
    oi = next(i for i, line in enumerate(lines) if "open_eq,_=book.equity(opraw)" in line)
    lines[oi:oi] = ["            # Production-equivalent ex-date entitlement is part of overnight open equity.\n"] + block
    out = "".join(lines)
    if out.index("receivables.append") > out.index("open_eq,_=book.equity(opraw)"):
        raise RuntimeError("dividend accrual still follows open-equity witness")
    return out


def _remove_cumulative_terminal_retirement(text: str) -> str:
    if "_retired_tids" not in text: return text
    lines=text.splitlines(keepends=True); out=[]; skip=None; removed=0
    for line in lines:
        stripped=line.strip(); indent=_indent(line)
        if skip is not None:
            if stripped and indent <= skip: skip=None
            else: removed += 1; continue
        if "_retired_tids" not in line: out.append(line); continue
        if stripped.startswith("if ") and stripped.endswith(":"): skip=indent
        removed += 1
    result="".join(out)
    if removed == 0 or "_retired_tids" in result: raise RuntimeError("cumulative terminal retirement remains")
    return result


def _remove_missing_mark_hard_abort(text: str) -> str:
    lines=text.splitlines(keepends=True)
    hits=[i for i,line in enumerate(lines) if line.strip()=="eq,unresolved=book.equity(clraw)"]
    if len(hits)!=1: raise RuntimeError(f"close-equity seam not unique: {hits}")
    i=hits[0]+1
    if i<len(lines) and lines[i].lstrip().startswith("if unresolved and date>=START:"):
        base=_indent(lines[i]); j=i+1
        while j<len(lines):
            if lines[j].strip() and _indent(lines[j])<=base: break
            j+=1
        block="".join(lines[i:j])
        if "raise RuntimeError" not in block or "financial-grade NAV unresolved" not in block:
            raise RuntimeError("unexpected unresolved NAV gate")
        del lines[i:j]
    result="".join(lines)
    if "financial-grade NAV unresolved" in result: raise RuntimeError("hard-abort NAV gate remains")
    return result


def install(text: str) -> str:
    out=_replace_classifier(text)
    out=_force_one_session_dividend_lag(out)
    out=_align_dividend_summary(out)
    out=_move_dividend_accrual_before_open_equity(out)
    out=_remove_cumulative_terminal_retirement(out)
    out=_remove_missing_mark_hard_abort(out)
    ast.parse(out); assert_contract(out); return out


def assert_contract(text: str) -> None:
    lag = assert_one_session_dividend_lag(text)
    if _summary_lag_node(text).value != lag:
        raise RuntimeError("generated dividend summary disagrees with executable lag")
    required=(FINAL_CLASSIFIER_IMPORT,"open_eq,_=book.equity(opraw)","receivables.append","term_tids","_leadership_terminal_tids","eq,unresolved=book.equity(clraw)")
    missing=[x for x in required if x not in text]
    if missing: raise RuntimeError(f"production-equivalent economic source missing probes: {missing}")
    forbidden=("_research_capacity_guard(","MAX_TRAILING_VOLUME_PARTICIPATION","_retired_tids","financial-grade NAV unresolved")
    present=[x for x in forbidden if x in text]
    if present: raise RuntimeError(f"production-equivalent economic source retains forbidden seams: {present}")
    if text.index("receivables.append") > text.index("open_eq,_=book.equity(opraw)"):
        raise RuntimeError("dividend receivable does not precede open-equity witness")
    if "elig=elig&~np.isin" in text and "terminal" in text[text.find("elig=elig&~np.isin")-100:text.find("elig=elig&~np.isin")+200].lower():
        raise RuntimeError("terminal IDs still alter pre-ranking eligibility")
