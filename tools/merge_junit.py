#!/usr/bin/env python3
"""Merge disjoint JUnit files and refuse missing or duplicate test evidence."""
from __future__ import annotations

import argparse
from pathlib import Path
import xml.etree.ElementTree as ET


def _suites(root: ET.Element) -> list[ET.Element]:
    if root.tag == "testsuite":
        return [root]
    if root.tag == "testsuites":
        return list(root.findall("testsuite"))
    raise ValueError(f"unsupported JUnit root: {root.tag}")


def merge(inputs: list[Path], output: Path) -> int:
    if len(inputs) < 2:
        raise ValueError("at least two JUnit inputs are required")

    merged = ET.Element("testsuites")
    identities: set[tuple[str, str]] = set()
    total = 0
    for path in inputs:
        if not path.is_file():
            raise FileNotFoundError(path)
        root = ET.parse(path).getroot()
        suites = _suites(root)
        if not suites:
            raise ValueError(f"empty JUnit suite set: {path}")
        input_cases = 0
        for suite in suites:
            cases = list(suite.iter("testcase"))
            input_cases += len(cases)
            for case in cases:
                identity = (case.get("classname", ""), case.get("name", ""))
                if not all(identity):
                    raise ValueError(f"JUnit testcase lacks identity in {path}: {identity}")
                if identity in identities:
                    raise ValueError(f"duplicate JUnit testcase evidence: {identity}")
                identities.add(identity)
            merged.append(suite)
        if input_cases == 0:
            raise ValueError(f"JUnit input contains no testcases: {path}")
        total += input_cases

    output.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(merged).write(output, encoding="utf-8", xml_declaration=True)
    return total


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("inputs", nargs="+", type=Path)
    args = parser.parse_args()
    total = merge(args.inputs, args.output)
    print(f"MERGED_JUNIT_TESTS={total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
