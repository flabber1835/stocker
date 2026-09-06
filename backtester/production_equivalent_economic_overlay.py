#!/usr/bin/env python3
"""Exact-source economic alignment for the final Production-equivalent replay.

This transform is intentionally narrow and fail-closed.  It operates on the
already capacity-corrected generated Champion program and changes only the
remaining known semantic seams documented by
PRODUCTION_EQUIVALENT_ECONOMIC_CONTRACT.md.
"""
from __future__ import annotations

import ast


FINAL_CLASSIFIER_IMPORT = "from backtester import champion_final_security_truth as _bestclass"


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


def _move_dividend_accrual_before_open_equity(text: str) -> str:
    """Move the unique ex-date receivable block ahead of open-equity capture.

    The block is identified structurally: it is the unique indented ``for``
    block before/around open execution containing ``receivables.append`` and a
    due expression using ``gday+1``.  No arithmetic inside the block changes.
    """
    lines = text.splitlines(keepends=True)
    open_hits = [i for i, line in enumerate(lines) if "open_eq,_=book.equity(opraw)" in line]
    append_hits = [i for i, line in enumerate(lines) if "receivables.append" in line]
    if len(open_hits) != 1 or len(append_hits) != 1:
        raise RuntimeError(
            f"dividend/open-equity seam not unique: open={open_hits} append={append_hits}"
        )
    oi, ai = open_hits[0], append_hits[0]
    if ai < oi:
        # Already aligned; still prove one-session lag.
        if "gday+1" not in "".join(lines[max(0, ai - 8): ai + 3]).replace(" ", ""):
            raise RuntimeError("pre-open dividend accrual does not prove gday+1 lag")
        return text

    start = None
    for i in range(ai, max(-1, ai - 12), -1):
        stripped = lines[i].lstrip()
        if stripped.startswith("for ") and stripped.rstrip().endswith(":"):
            start = i
            break
    if start is None:
        raise RuntimeError("could not find dividend accrual loop start")
    base_indent = _indent(lines[start])
    end = start + 1
    while end < len(lines):
        stripped = lines[end].strip()
        if stripped and _indent(lines[end]) <= base_indent:
            break
        end += 1
    block = lines[start:end]
    joined = "".join(block)
    compact = joined.replace(" ", "")
    if "receivables.append" not in joined or "gday+1" not in compact:
        raise RuntimeError("identified receivable block is not the one-session ex-date accrual")
    if any("open_eq" in line for line in block):
        raise RuntimeError("dividend block unexpectedly contains open-equity calculation")

    # Remove the later block, then insert it immediately before open_eq.  The
    # prior-close quantity was already captured after same-session split logic
    # by the terminal/financial overlay.
    del lines[start:end]
    oi = next(i for i, line in enumerate(lines) if "open_eq,_=book.equity(opraw)" in line)
    marker = "            # Production-equivalent ex-date entitlement is part of overnight open equity.\n"
    lines[oi:oi] = [marker] + block
    out = "".join(lines)
    new_open = out.index("open_eq,_=book.equity(opraw)")
    new_append = out.index("receivables.append")
    if new_append > new_open:
        raise RuntimeError("dividend accrual still follows open-equity witness")
    return out


def _remove_cumulative_terminal_retirement(text: str) -> str:
    """Remove research-only lifetime retirement while preserving event vetoes."""
    if "_retired_tids" not in text:
        return text
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    skip_block_indent: int | None = None
    removed = 0
    for line in lines:
        stripped = line.strip()
        indent = _indent(line)
        if skip_block_indent is not None:
            if stripped and indent <= skip_block_indent:
                skip_block_indent = None
            else:
                removed += 1
                continue
        if "_retired_tids" not in line:
            out.append(line)
            continue

        # Known lifetime-state operations are forbidden.  If one starts a
        # conditional whose sole purpose is retirement cancellation, drop its
        # indented body as well.  Current-session ``term_tids`` cancellation is
        # installed independently and remains intact.
        if stripped.startswith("if ") and stripped.endswith(":"):
            skip_block_indent = indent
        removed += 1

    result = "".join(out)
    if removed == 0 or "_retired_tids" in result:
        raise RuntimeError("cumulative terminal retirement was not completely removed")
    return result


def _remove_missing_mark_hard_abort(text: str) -> str:
    """Keep Production carry/unresolved flag but remove replay-only NAV abort."""
    lines = text.splitlines(keepends=True)
    eq_hits = [i for i, line in enumerate(lines) if line.strip() == "eq,unresolved=book.equity(clraw)"]
    if len(eq_hits) != 1:
        raise RuntimeError(f"close-equity seam not unique: {eq_hits}")
    i = eq_hits[0] + 1
    # The strict-v2 path has an immediately following unresolved hard-abort
    # block.  Remove exactly that block if present.
    if i < len(lines) and lines[i].lstrip().startswith("if unresolved and date>=START:"):
        base = _indent(lines[i])
        j = i + 1
        while j < len(lines):
            if lines[j].strip() and _indent(lines[j]) <= base:
                break
            j += 1
        block = "".join(lines[i:j])
        if "raise RuntimeError" not in block or "financial-grade NAV unresolved" not in block:
            raise RuntimeError("unexpected unresolved NAV gate; refusing broad deletion")
        del lines[i:j]
    result = "".join(lines)
    if "financial-grade NAV unresolved" in result:
        raise RuntimeError("hard-abort NAV gate remains")
    return result


def install(text: str) -> str:
    out = _replace_classifier(text)
    out = _move_dividend_accrual_before_open_equity(out)
    out = _remove_cumulative_terminal_retirement(out)
    out = _remove_missing_mark_hard_abort(out)
    ast.parse(out)
    assert_contract(out)
    return out


def assert_contract(text: str) -> None:
    compact = text.replace(" ", "")
    required = (
        FINAL_CLASSIFIER_IMPORT,
        "open_eq,_=book.equity(opraw)",
        "receivables.append",
        "gday+1",
        "term_tids",
        "_leadership_terminal_tids",
        "eq,unresolved=book.equity(clraw)",
    )
    missing = [needle for needle in required if needle not in text and needle not in compact]
    if missing:
        raise RuntimeError(f"production-equivalent economic source missing probes: {missing}")
    forbidden = (
        "_research_capacity_guard(",
        "MAX_TRAILING_VOLUME_PARTICIPATION",
        "_retired_tids",
        "financial-grade NAV unresolved",
    )
    present = [needle for needle in forbidden if needle in text]
    if present:
        raise RuntimeError(f"production-equivalent economic source retains forbidden seams: {present}")
    if text.index("receivables.append") > text.index("open_eq,_=book.equity(opraw)"):
        raise RuntimeError("dividend receivable does not precede open-equity witness")
    # Leadership filter must be a next-witness filter, not a pre-ranking elig
    # mutation.  The only allowed terminal-specific ranking expression is the
    # filtered ``prior_recent_sel`` constructed after ``recsel`` exists.
    if "elig=elig&~np.isin" in text and "terminal" in text[text.find("elig=elig&~np.isin")-100:text.find("elig=elig&~np.isin")+200].lower():
        raise RuntimeError("terminal IDs still alter pre-ranking eligibility")
