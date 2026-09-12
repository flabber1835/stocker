#!/usr/bin/env python3
"""Discover and execute every unittest module assigned to one manifest owner."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import platform
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

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
    parser.add_argument("--require-python")
    args = parser.parse_args()

    python_version = platform.python_version()
    if args.require_python and python_version != args.require_python:
        raise RuntimeError(
            "runtime Python differs from required authority: expected=%s actual=%s" %
            (args.require_python, python_version))

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
        failed_imports = [test.id() for test in _iter_tests(module_suite)
                          if test.id().startswith("unittest.loader._FailedTest")]
        if failed_imports:
            raise AssertionError(
                "%s: unittest module failed to import: %s" %
                (relative_posix(module), failed_imports))
        collected[relative_posix(module)] = ids
        suite.addTests(module_suite)

    result = unittest.TextTestRunner(verbosity=2).run(suite)
    skipped = list(getattr(result, "skipped", []))
    expected_failures = list(getattr(result, "expectedFailures", []))
    unexpected_successes = list(getattr(result, "unexpectedSuccesses", []))
    passed = (
        result.wasSuccessful()
        and not skipped
        and not expected_failures
        and not unexpected_successes
    )
    payload = {
        "schema": "stocker.unittest-owner-execution/3",
        "verdict": "PASS" if passed else "FAIL",
        "owner": args.owner,
        "python": sys.version,
        "python_version": python_version,
        "required_python": args.require_python,
        "modules": collected,
        "testsRun": result.testsRun,
        "failures": len(result.failures),
        "errors": len(result.errors),
        "skipped": len(skipped),
        "expectedFailures": len(expected_failures),
        "unexpectedSuccesses": len(unexpected_successes),
    }
    text = json.dumps(payload, sort_keys=True, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text)
    print(text, end="")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
