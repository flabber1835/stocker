"""Explicit owner-authorized local PAPER iteration, never live authority."""
from __future__ import annotations

import os
import re
from typing import Mapping, TYPE_CHECKING

if TYPE_CHECKING:
    from sentinel.binding import AccountBinding

MODE_ENV = "SENTINEL_LOCAL_PAPER_MODE"
MODE = "OWNER_AUTHORIZED_FUNCTION_FIRST_V1"
ACCOUNT_ENV = "SENTINEL_LOCAL_PAPER_ACCOUNT_ID"


def enabled(values: Mapping[str, str] | None = None) -> bool:
    values = os.environ if values is None else values
    selected = values.get(MODE_ENV, "").strip()
    if not selected:
        return False
    if selected != MODE:
        raise RuntimeError("unsupported local PAPER operating mode")
    from sentinel.config import assert_paper_url, DEFAULT_BASE_URL
    assert_paper_url(values.get("ALPACA_BASE_URL", DEFAULT_BASE_URL))
    if not re.fullmatch(r"PA[A-Za-z0-9]+", values.get(ACCOUNT_ENV, "")):
        raise RuntimeError("local PAPER mode requires the owner's exact paper account")
    return True


def bound_account(conn) -> AccountBinding | None:
    """Read and verify this invocation's local binding, without caching it."""
    if not enabled():
        return None
    from sentinel import binding
    bound = binding.require(conn)
    if (bound.broker != "alpaca"
            or bound.broker_account_id != os.environ[ACCOUNT_ENV]):
        raise RuntimeError("local PAPER account does not match the durable binding")
    return bound


def require_bound_account(conn) -> bool:
    """Retain the Boolean API used by independent operational boundaries."""
    return bound_account(conn) is not None


def require_runtime(conn, runtime_identity: Mapping) -> None:
    if bound_account(conn) is None:
        raise RuntimeError("local PAPER operation was not authorized")
    validate_runtime_identity(runtime_identity)


def validate_runtime_identity(runtime_identity: Mapping) -> None:
    """Pure identity comparison; this does not verify an account or issue a grant."""
    from sentinel.authority import runtime_artifact_identity
    artifacts = runtime_artifact_identity(runtime_identity)
    commit = os.environ.get("SENTINEL_GIT_COMMIT", "")
    digest = os.environ.get("SENTINEL_RUNTIME_IMAGE_DIGEST", "")
    if (not re.fullmatch(r"[0-9a-f]{40}", commit)
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest)
            or os.environ.get("SENTINEL_IMAGE_SOURCE_REVISION") != commit
            or artifacts.get("git_commit") != commit
            or artifacts.get("runtime_image_digest") != digest
            or artifacts.get("test_image_digest") != digest):
        raise RuntimeError("local PAPER runtime must identify its actual local commit and image")


def require_execution_config(conn, configuration_sha256: str) -> None:
    if bound_account(conn) is None:
        raise RuntimeError('local PAPER operation was not authorized')
    validate_execution_policy(configuration_sha256)


def validate_execution_policy(configuration_sha256: str) -> None:
    """Pure policy comparison; this does not verify an account or issue a grant."""
    from sentinel.authority import canonical_sha256, execution_config_identity
    from sentinel.config import DEFAULT_BASE_URL
    from sentinel.execution.protected_limits import ProtectedLimitPolicy
    policy = ProtectedLimitPolicy.from_env()
    if policy is None or policy.cap_bps != 100:
        raise RuntimeError('local PAPER iteration requires the selected 100-basis-point protected DAY policy')
    actual = execution_config_identity(paper_base_url=DEFAULT_BASE_URL)
    if canonical_sha256(actual) != configuration_sha256:
        raise RuntimeError('local PAPER execution configuration differs from actual policy')


def runtime_and_execution_config(conn, *, runtime_identity: Mapping,
                                 configuration_sha256: str) -> AccountBinding | None:
    """Verify one local operation against its own fresh durable binding.

    Only checked account facts leave this function. They are not a grant or a
    reusable validation context; each later authority boundary reads afresh.
    """
    bound = bound_account(conn)
    if bound is not None:
        validate_runtime_identity(runtime_identity)
        validate_execution_policy(configuration_sha256)
    return bound
