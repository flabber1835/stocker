"""Broker-capable CLI dispatch installed only in the authorized image.

The ordinary runtime still parses these commands so it can issue a precise
refusal, but it does not contain this executable route registry.  Host
administrators able to replace arbitrary application code remain outside the
runtime membrane documented in ``docs/sentinel-deployment.md``.
"""
from __future__ import annotations

from sentinel.cli import _shared, account, authority, automation, paper


ROUTES = {
    "migration-plan": account._migration_plan,
    "inspect-paper-account": paper._inspect_paper_account,
    "inspect-empty-paper-account": paper._inspect_empty_paper_account,
    "bind-empty-paper-account": paper._bind_empty_paper_account,
    "prepare-paper-plan": paper._prepare_paper_plan,
    "execute-paper-plan": paper._execute_paper_plan,
    "install-administrative-certificate": (
        authority._install_administrative_certificate),
    "activate-administrative-certificate": (
        authority._activate_administrative_certificate),
    "install-system-certificate": authority._install_system_certificate,
    "activate-system-certificate": authority._activate_system_certificate,
    "rotate-system-certificate": authority._activate_system_certificate,
    "set-paper-rollout-mode": authority._set_paper_rollout_mode,
    "activate-paper-automation": automation._activate_paper_automation,
    "release-paper-automation-kill-switch": (
        automation._release_paper_automation_kill),
    "automation-run": automation._automation_run,
    "migrate-account": account._migrate_account,
    "adopt-restored-account": account._adopt_restored,
}


if frozenset(ROUTES) != _shared.AUTHORIZED_RUNTIME_COMMANDS:
    raise RuntimeError(
        "authorized CLI route registry differs from the command membrane")


__all__ = ["ROUTES"]
