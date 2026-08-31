"""Semantic compatibility preflight for Sentinel's NAS host utilities.

The application containers remain Python 3.12.  This module covers only the
host orchestration process and intentionally exercises the immutable image
identity code that failed on Synology rather than checking a version string
alone.
"""
from __future__ import annotations

import importlib
import sys


MINIMUM_HOST_PYTHON = (3, 8, 15)
HOST_MODULES = (
    "sentinel_certification_state",
    "sentinel_forward_run",
    "sentinel_host_capabilities",
    "sentinel_strip_cpu_limits",
    "sentinel_test_run",
)


class HostPythonRefused(RuntimeError):
    """The host cannot safely run the certification orchestration."""


def _load(name: str):
    try:
        return importlib.import_module("scripts." + name)
    except ModuleNotFoundError as exc:
        # ``python scripts/sentinel_host_python.py`` puts ``scripts/`` rather
        # than the repository root first on sys.path.
        if exc.name not in {"scripts", "scripts." + name}:
            raise
        return importlib.import_module(name)


def check() -> None:
    if sys.version_info < MINIMUM_HOST_PYTHON:
        actual = ".".join(str(part) for part in sys.version_info[:3])
        required = ".".join(str(part) for part in MINIMUM_HOST_PYTHON)
        raise HostPythonRefused(
            "host Python " + actual + " is unsupported; minimum is " + required
        )

    loaded = {name: _load(name) for name in HOST_MODULES}
    digest = "sha256:" + "a" * 64
    image = {"repo_digests": ["registry.example/image@" + digest]}
    test_digest, test_ref = loaded["sentinel_test_run"]._unique_repo_identity(
        image, field="preflight.test_image"
    )
    forward_digest, forward_ref = loaded[
        "sentinel_forward_run"
    ]._unique_repo_identity(image, label="preflight.forward_image")
    if (test_digest, test_ref) != (digest, image["repo_digests"][0]):
        raise HostPythonRefused("test-run immutable RepoDigest semantics drifted")
    if (forward_digest, forward_ref) != (digest, image["repo_digests"][0]):
        raise HostPythonRefused("forward-run immutable RepoDigest semantics drifted")

    value = {"z": "\u00e9", "a": 1}
    expected = b'{"a":1,"z":"\xc3\xa9"}'
    if loaded["sentinel_test_run"]._canonical(value) != expected:
        raise HostPythonRefused("test-run canonical JSON bytes drifted")
    if loaded["sentinel_forward_run"].canonical_bytes(value) != expected:
        raise HostPythonRefused("forward-run canonical JSON bytes drifted")


def main() -> int:
    try:
        check()
    except (HostPythonRefused, ImportError, OSError) as exc:
        print("HOST PYTHON REFUSED: " + str(exc), file=sys.stderr)
        return 1
    version = ".".join(str(part) for part in sys.version_info[:3])
    print("host_python_compatible:" + version)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
