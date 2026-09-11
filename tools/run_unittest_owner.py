#!/usr/bin/env python3
"""Discover and execute every unittest module assigned to one manifest owner."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import unittest

from test_responsibility_lib import load_authority, module_dotted, owned_test_modules, relative_posix


def _iter_tests(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            for test in _iter_tests(item):
                yield test
        else:
            yield item


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    authority = load_authority()
    modules = owned_test_modules(authority, args.owner)
    if not modules:
        raise AssertionError("%s: owner has no test modules" % args.owner)

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    collected = {}
    for module in modules:
        dotted = module_dotted(module)
        module_suite = loader.loadTestsFromName(dotted)
        ids = [test.id() for test in _iter_tests(module_suite)]
        if not ids:
            raise AssertionError("%s: no unittest cases collected" % relative_posix(module))
        collected[relative_posix(module)] = ids
        suite.addTests(module_suite)

    result = unittest.TextTestRunner(verbosity=2).run(suite)
    payload = {
        "schema": "stocker.unittest-owner-execution/1",
        "verdict": "PASS" if result.wasSuccessful() else "FAIL",
        "owner": args.owner,
        "python": sys.version,
        "modules": collected,
        "testsRun": result.testsRun,
        "failures": len(result.failures),
        "errors": len(result.errors),
        "skipped": len(getattr(result, "skipped", [])),
    }
    text = json.dumps(payload, sort_keys=True, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text)
    print(text, end="")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
