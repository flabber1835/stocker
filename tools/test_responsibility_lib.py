#!/usr/bin/env python3
"""Shared fail-closed helpers for test ownership and execution evidence.

This module intentionally uses only Python 3.8-compatible standard-library
features because the minimum-host CI job imports it under Python 3.8.15.
"""
from __future__ import annotations

import fnmatch
import json
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
AUTHORITY = ROOT / "tests" / "test-responsibility.json"
SCHEMA = "stocker.test-responsibility/2"


def load_authority(path: Optional[Path] = None) -> dict:
    authority_path = AUTHORITY if path is None else path
    authority = json.loads(authority_path.read_text())
    if authority.get("schema") != SCHEMA:
        raise AssertionError("invalid responsibility schema")
    return authority


def resolve_pattern(pattern: str, root: Path = ROOT) -> List[Path]:
    if any(ch in pattern for ch in "*?["):
        return sorted(root.glob(pattern))
    path = root / pattern
    return [path] if path.exists() else []


def contains(owner_path: Path, test_path: Path) -> bool:
    if owner_path.is_file():
        return owner_path == test_path
    try:
        test_path.relative_to(owner_path)
        return True
    except ValueError:
        return False


def owner_paths(authority: Mapping[str, object], owner_name: str,
                root: Path = ROOT) -> List[Path]:
    owners = authority.get("owners")
    if not isinstance(owners, dict) or owner_name not in owners:
        raise AssertionError("unknown test owner: %s" % owner_name)
    owner = owners[owner_name]
    if not isinstance(owner, dict):
        raise AssertionError("invalid test owner: %s" % owner_name)
    patterns = owner.get("paths")
    if not isinstance(patterns, list) or not patterns:
        raise AssertionError("%s: empty owner path list" % owner_name)
    resolved = []
    for pattern in patterns:
        if not isinstance(pattern, str) or not pattern:
            raise AssertionError("%s: invalid owner path" % owner_name)
        matches = resolve_pattern(pattern, root=root)
        if not matches:
            raise AssertionError(
                "%s: owner path resolves to nothing: %s" % (owner_name, pattern))
        resolved.extend(matches)
    return sorted(set(resolved))


def owned_test_modules(authority: Mapping[str, object], owner_name: str,
                       root: Path = ROOT) -> List[Path]:
    modules = set()
    for path in owner_paths(authority, owner_name, root=root):
        if path.is_file():
            if path.name.startswith("test_") and path.suffix == ".py":
                modules.add(path)
            continue
        for candidate in path.rglob("test_*.py"):
            if candidate.is_file():
                modules.add(candidate)
    return sorted(modules)


def relative_posix(path: Path, root: Path = ROOT) -> str:
    return path.relative_to(root).as_posix()


def module_dotted(path: Path, root: Path = ROOT) -> str:
    relative = relative_posix(path, root=root)
    if not relative.endswith(".py"):
        raise AssertionError("test module must be a .py file: %s" % relative)
    return relative[:-3].replace("/", ".")


def canonical_nodeid(nodeid: str) -> str:
    """Collapse pytest parameter instances to one exact logical test node."""
    value = nodeid.strip()
    if "::" not in value:
        return value
    head, leaf = value.rsplit("::", 1)
    if "[" in leaf and leaf.endswith("]"):
        leaf = leaf.split("[", 1)[0]
    return head + "::" + leaf


def validate_contract_selectors(required: object) -> Dict[str, str]:
    if not isinstance(required, dict) or not required:
        raise AssertionError("missing Alpaca contract authority")
    normalized = {}
    for contract_id, selector in required.items():
        if not isinstance(contract_id, str) or not contract_id:
            raise AssertionError("invalid Alpaca contract id")
        if not isinstance(selector, str) or not selector:
            raise AssertionError("invalid Alpaca contract selector")
        if not selector.startswith("tests/sentinel/test_") or ".py::" not in selector:
            raise AssertionError(
                "%s: Alpaca selector must be an exact logical pytest node id" % contract_id)
        if "[" in selector or "*" in selector or "?" in selector:
            raise AssertionError(
                "%s: Alpaca selector must not contain parameters or wildcards" % contract_id)
        if canonical_nodeid(selector) != selector:
            raise AssertionError("%s: Alpaca selector is not canonical" % contract_id)
        normalized[contract_id] = selector
    selectors = list(normalized.values())
    if len(selectors) != len(set(selectors)):
        raise AssertionError("duplicate Alpaca contract selector")
    return normalized


def resolve_contracts(required: Mapping[str, str],
                      collected_nodeids: Iterable[str]) -> Dict[str, List[str]]:
    """Resolve each exact logical selector to its physical pytest instances."""
    selectors = validate_contract_selectors(dict(required))
    physical_by_logical = {}  # type: Dict[str, List[str]]
    for nodeid in collected_nodeids:
        physical = nodeid.strip()
        if not physical:
            continue
        logical = canonical_nodeid(physical)
        physical_by_logical.setdefault(logical, []).append(physical)

    resolved = {}
    used_logical = set()
    for contract_id, selector in selectors.items():
        physical = sorted(set(physical_by_logical.get(selector, [])))
        if not physical:
            raise AssertionError(
                "%s: required Alpaca contract did not collect exactly: %s" %
                (contract_id, selector))
        if selector in used_logical:
            raise AssertionError(
                "%s: collected node is already owned by another Alpaca contract" % contract_id)
        used_logical.add(selector)
        resolved[contract_id] = physical
    return resolved


def _junit_testcases(paths: Sequence[Path]) -> Iterable[ET.Element]:
    for path in paths:
        tree = ET.parse(str(path))
        for testcase in tree.getroot().iter("testcase"):
            yield testcase


def junit_execution(paths: Sequence[Path], expected_modules: Sequence[Path],
                    root: Path = ROOT) -> Tuple[Set[str], Set[str]]:
    """Return executed module paths and exact logical pytest node ids from JUnit."""
    module_info = []
    for module in expected_modules:
        module_info.append((relative_posix(module, root=root),
                            module_dotted(module, root=root)))
    module_info.sort(key=lambda item: len(item[1]), reverse=True)

    executed_modules = set()  # type: Set[str]
    logical_nodeids = set()  # type: Set[str]
    for testcase in _junit_testcases(paths):
        classname = testcase.attrib.get("classname", "")
        name = testcase.attrib.get("name", "")
        file_attr = testcase.attrib.get("file", "")
        matched = None
        if file_attr:
            normalized = file_attr.replace("\\", "/").lstrip("./")
            for module_path, dotted in module_info:
                if normalized == module_path:
                    matched = (module_path, dotted, "")
                    break
        if matched is None and classname:
            for module_path, dotted in module_info:
                if classname == dotted:
                    matched = (module_path, dotted, "")
                    break
                if classname.startswith(dotted + "."):
                    matched = (module_path, dotted, classname[len(dotted) + 1:])
                    break
        if matched is None:
            continue
        module_path, _dotted, class_suffix = matched
        executed_modules.add(module_path)
        if name:
            nodeid = module_path
            if class_suffix:
                nodeid += "::" + class_suffix.replace(".", "::")
            nodeid += "::" + name
            logical_nodeids.add(canonical_nodeid(nodeid))
    return executed_modules, logical_nodeids


def incident_named(path: str) -> bool:
    name = Path(path).name
    return any(fnmatch.fnmatch(name, pattern)
               for pattern in ("test_pr*.py", "test_issue*.py", "test_review*.py"))
