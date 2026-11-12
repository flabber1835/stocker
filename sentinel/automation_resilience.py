"""Unattended policy for the shared durable automation scheduler."""

from sentinel.automation.service import AutomationService


class RecoveryAutomationService(AutomationService):
    """Keep retrying infrastructure outages while each callback stays bounded."""

    _unattended_recovery = True


__all__ = ["RecoveryAutomationService"]
