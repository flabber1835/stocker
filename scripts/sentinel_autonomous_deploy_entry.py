#!/usr/bin/env python3
"""Production deployment entry: safe env persistence and broker-free SHADOW."""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path
import sys
from typing import Mapping, Optional, Sequence

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import sentinel_autonomous_deploy as core
import sentinel_autonomous_deploy_bootstrap as bootstrap
from sentinel_env_writer import EnvWriteRefused, safe_update_dotenv


def _deploy_writer(path: Path, updates: Mapping[str, str]) -> None:
    try:
        safe_update_dotenv(path, updates)
    except EnvWriteRefused as exc:
        raise core.DeployRefused(str(exc)) from None


def _requested_mode(argv: Optional[Sequence[str]]) -> Optional[str]:
    args = list(sys.argv[1:] if argv is None else argv)
    mode = None
    index = 0
    while index < len(args):
        value = args[index]
        if value == "--mode":
            if index + 1 >= len(args):
                return None
            mode = args[index + 1]
            index += 2
            continue
        if value.startswith("--mode="):
            mode = value.split("=", 1)[1]
        index += 1
    return mode


def _install_shadow_overlay() -> None:
    """Install after the existing reviewed-mode overlay has selected its classes."""
    BaseConfig = bootstrap.hardened.Config
    BaseDeploy = bootstrap.BootstrapDeploy
    original_verify_account = core.verify_reviewed_account_binding

    class ShadowConfig(BaseConfig):
        """Deployment mechanics required by SHADOW, with no broker authority."""

        def __init__(self, env: Mapping[str, str]) -> None:
            # Keep the reviewed software/backup/deployment mechanics. Broker
            # identity, credentials and signing authority are not SHADOW inputs.
            self.env = dict(env)
            self.deployment_id = str(
                env.get("SENTINEL_DEPLOYMENT_ID", "")).strip()
            self.account_id = str(
                env.get("SENTINEL_PAPER_ACCOUNT_ID", "")).strip()
            self.runtime_repository = core._require(
                env, "SENTINEL_RUNTIME_IMAGE_REPOSITORY")
            self.test_repository = core._require(
                env, "SENTINEL_TEST_IMAGE_REPOSITORY")
            self.authority_dir = core._resolve_repo_path(
                str(env.get(
                    "SENTINEL_AUTHORITY_ARTIFACTS_DIR",
                    "artifacts/sentinel/authority")).strip()
                or "artifacts/sentinel/authority")
            self.actor = str(env.get(
                "SENTINEL_DEPLOY_ACTOR",
                "sentinel-autonomous-deploy")).strip()
            self.reviewer = str(env.get(
                "SENTINEL_DEPLOY_REVIEWER", self.actor)).strip()
            self.ticket_prefix = str(env.get(
                "SENTINEL_DEPLOY_TICKET_PREFIX",
                "autonomous-deploy")).strip()
            self.max_exposure = str(env.get(
                "SENTINEL_DEPLOY_MAXIMUM_EXPOSURE", "1")).strip()
            self.not_before_margin = core._int(
                env.get("SENTINEL_DEPLOY_NOT_BEFORE_MARGIN_SECONDS", "120"),
                name="SENTINEL_DEPLOY_NOT_BEFORE_MARGIN_SECONDS",
                minimum=0, maximum=1800)
            self.health_timeout = core._int(
                env.get("SENTINEL_DEPLOY_HEALTH_TIMEOUT_SECONDS", "300"),
                name="SENTINEL_DEPLOY_HEALTH_TIMEOUT_SECONDS",
                minimum=30, maximum=1800)
            self.allow_empty_bind = core._as_bool(
                env.get("SENTINEL_DEPLOY_ALLOW_EMPTY_BIND", "0"),
                name="SENTINEL_DEPLOY_ALLOW_EMPTY_BIND")
            self.heartbeat_seconds = core._int(
                env.get("SENTINEL_AUTOMATION_HEARTBEAT_SECONDS", "10"),
                name="SENTINEL_AUTOMATION_HEARTBEAT_SECONDS",
                minimum=1, maximum=300)
            self.revoke_previous_signing_key = core._as_bool(
                env.get("SENTINEL_DEPLOY_REVOKE_PREVIOUS_SIGNING_KEY", "0"),
                name="SENTINEL_DEPLOY_REVOKE_PREVIOUS_SIGNING_KEY")
            self.data_retry_seconds = core._int(
                env.get("SENTINEL_DEPLOY_DATA_RETRY_SECONDS", "300"),
                name="SENTINEL_DEPLOY_DATA_RETRY_SECONDS",
                minimum=30, maximum=3600)
            self.data_wait_timeout_seconds = max(
                core._int(
                    env.get(
                        "SENTINEL_DEPLOY_DATA_WAIT_TIMEOUT_SECONDS", "43200"),
                    name="SENTINEL_DEPLOY_DATA_WAIT_TIMEOUT_SECONDS",
                    minimum=300, maximum=86400),
                24 * 3600)
            # These attributes exist for the common deployment object but are
            # never consumed by reviewed SHADOW paths.
            self.signing_key_id = ""
            self.signing_key = Path("/dev/null")
            if not self.actor or not self.reviewer or not self.ticket_prefix:
                raise core.DeployRefused(
                    "deploy actor, reviewer, and ticket prefix must be non-empty")
            if ("@" in self.runtime_repository
                    or "@" in self.test_repository):
                raise core.DeployRefused(
                    "image repositories must be mutable repository names, not digests")
            try:
                exposure = Decimal(self.max_exposure)
            except Exception as exc:
                raise core.DeployRefused(
                    "SENTINEL_DEPLOY_MAXIMUM_EXPOSURE is not a decimal") from exc
            if (not exposure.is_finite()
                    or exposure < 0 or exposure > 1):
                raise core.DeployRefused(
                    "SENTINEL_DEPLOY_MAXIMUM_EXPOSURE must be finite in [0,1]")
            self.authority_dir.mkdir(parents=True, exist_ok=True)

    class ShadowDeploy(BaseDeploy):
        def check_paper_account_deployment_integrity(self) -> str:
            if (self.reviewed_validation is not None
                    and self.reviewed_validation.mode == "shadow"):
                self.phase(
                    "preflight: broker identity integrity not applicable to SHADOW")
                self.broker_readiness = "BROKER_NOT_APPLICABLE"
                return self.broker_readiness
            return super().check_paper_account_deployment_integrity()

        def check_durable_deployment_integrity(self) -> Mapping:
            if (self.reviewed_validation is None
                    or self.reviewed_validation.mode != "shadow"):
                return super().check_durable_deployment_integrity()
            self.phase(
                "integrity: durable execution state remains structurally fenced")
            status = self._status()
            state = status.get("ownership")
            if state == "UNKNOWN":
                raise core.DeployRefused(
                    "canonical account ownership is UNKNOWN")
            if state == "OWNED":
                if (status.get("broker") != "alpaca"
                        or not str(status.get("broker_account_id") or "").strip()
                        or not str(status.get("deployment_id") or "").strip()
                        or not isinstance(status.get("takeover_epoch"), int)
                        or int(status["takeover_epoch"]) < 1):
                    raise core.DeployRefused(
                        "durable OWNED binding is structurally malformed")
                # Retain durable identity for audit receipts without making it
                # a SHADOW prerequisite.
                if not self.cfg.account_id:
                    self.cfg.account_id = str(status["broker_account_id"])
                if not self.cfg.deployment_id:
                    self.cfg.deployment_id = str(status["deployment_id"])
            elif state != "NOT_OWNED":
                raise core.DeployRefused(
                    "canonical ownership state is malformed: %r" % (state,))
            for field in (
                    "paper_execution_authority",
                    "administrative_authority"):
                value = status.get(field)
                if not isinstance(value, dict):
                    raise core.DeployRefused(
                        "%s status is malformed" % field)
                if value.get("error"):
                    raise core.DeployRefused(
                        "%s durable state is unreadable: %s"
                        % (field, value["error"]))
            self.ownership_state = str(state)
            return status

    def verify_account(reviewed, account_id: str) -> None:
        if reviewed.mode == "shadow":
            return
        original_verify_account(reviewed, account_id)

    core.verify_reviewed_account_binding = verify_account
    bootstrap._signing_key_path = lambda _env: None
    bootstrap.hardened.Config = ShadowConfig
    bootstrap.BootstrapDeploy = ShadowDeploy


def install_runtime_guards(requested_mode: Optional[str]) -> None:
    core.update_dotenv = _deploy_writer
    bootstrap._safe_update_dotenv = _deploy_writer

    original_overlay = bootstrap._install_wallclock_independent_dual_overlay

    def overlay() -> None:
        original_overlay()
        # The overlay can rebind BootstrapDeploy, so install the writer again
        # after it runs and then remove broker authority from reviewed SHADOW.
        bootstrap._safe_update_dotenv = _deploy_writer
        core.update_dotenv = _deploy_writer
        if requested_mode == "shadow":
            _install_shadow_overlay()

    bootstrap._install_wallclock_independent_dual_overlay = overlay


def main(argv: Optional[Sequence[str]] = None) -> int:
    requested_mode = _requested_mode(argv)
    install_runtime_guards(requested_mode)
    return bootstrap.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
