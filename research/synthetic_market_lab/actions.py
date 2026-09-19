from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ActionEvent:
    company_index: int
    action_type: str
    announced_session: int
    effective_session: int
    ratio: float | None = None
    cash_amount: float | None = None
    new_ticker: str | None = None
    new_security_id: str | None = None
    reason: str = ""
    announced_ticker: str | None = None
    announced_security_id: str | None = None
    diagnostics: dict[str, float] = field(default_factory=dict)


def ticker_for(company_index: int, version: int) -> str:
    suffix = "" if version == 0 else chr(ord("A") + ((version - 1) % 26)) + (str((version - 1) // 26) if version > 26 else "")
    return f"X{company_index + 1:04d}{suffix}"


def security_id_for(company_index: int, version: int) -> str:
    return f"S{company_index + 1:06d}-{version + 1:02d}"
