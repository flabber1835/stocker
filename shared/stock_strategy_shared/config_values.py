"""Parsing + dotted-path application for single-field strategy-config edits.

Shared by the evaluator's experiment queue (auto-queue recommendations as
wind-tunnel experiments) and the api service's one-click apply (evaluator
Phase 3) — one parser, so "what value does this recommendation mean" cannot
diverge between testing it and applying it.

Values arrive as STRINGS (the evaluator report schema's suggested_value).
Only literals are accepted; prose ("reduce by half", "~0.2") is rejected,
never guessed at.
"""
from __future__ import annotations

import json
from typing import Any

_NULL_TOKENS = {"none", "null", "off", "disabled", "disable"}


def parse_suggested_value(raw: Any) -> tuple[Any, bool]:
    """LLM suggested_value → JSON literal. Returns (value, ok)."""
    if isinstance(raw, (int, float, bool)) or raw is None:
        return raw, True
    s = str(raw).strip()
    if not s:
        return None, False
    try:
        return json.loads(s), True
    except ValueError:
        pass
    low = s.lower()
    if low in _NULL_TOKENS:
        return None, True
    if low == "true":
        return True, True
    if low == "false":
        return False, True
    return None, False


def get_dotted(cfg: dict, path: str) -> Any:
    """Value at a dotted path, or None when absent / non-object traversal."""
    node: Any = cfg
    for part in [p for p in str(path).split(".") if p]:
        if not isinstance(node, dict):
            return None
        node = node.get(part)
    return node


def set_dotted(cfg: dict, path: str, value: Any) -> str | None:
    """Set a dotted path IN PLACE. Returns an error message or None."""
    parts = [p for p in str(path).split(".") if p]
    if not parts:
        return f"invalid config path: {path!r}"
    node = cfg
    for p in parts[:-1]:
        if not isinstance(node, dict):
            return f"config path {path!r} traverses a non-object at {p!r}"
        node = node.setdefault(p, {})
    if not isinstance(node, dict):
        return f"config path {path!r} traverses a non-object"
    node[parts[-1]] = value
    return None
