from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from urllib.parse import urlsplit


class TradingEnvironment(str, Enum):
    PAPER = "ALPACA_PAPER"
    LIVE = "ALPACA_LIVE"


class TradingEndpointRefused(ValueError):
    pass


_ORIGINS = {
    "paper-api.alpaca.markets": TradingEnvironment.PAPER,
    "api.alpaca.markets": TradingEnvironment.LIVE,
}


@dataclass(frozen=True)
class TradingEndpoint:
    environment: TradingEnvironment
    base_url: str

    def __post_init__(self) -> None:
        expected = {"https://" + host: environment
                    for host, environment in _ORIGINS.items()}
        if (not isinstance(self.environment, TradingEnvironment)
                or expected.get(self.base_url) is not self.environment):
            raise TradingEndpointRefused("trading origin and environment differ")

    @classmethod
    def parse(cls, value: str) -> "TradingEndpoint":
        if not isinstance(value, str) or not value or value != value.strip():
            raise TradingEndpointRefused("an exact Alpaca HTTPS origin is required")
        try:
            parsed = urlsplit(value)
            host = (parsed.hostname or "").lower()
            valid_port = parsed.port in (None, 443)
        except ValueError as exc:
            raise TradingEndpointRefused("malformed Alpaca trading origin") from exc
        if (parsed.scheme.lower() != "https" or host not in _ORIGINS
                or parsed.username is not None or parsed.password is not None
                or not valid_port or parsed.path not in ("", "/")
                or "?" in value or "#" in value
                or "\\" in value or any(ord(char) < 33 for char in value)):
            raise TradingEndpointRefused("unsupported Alpaca trading origin")
        return cls(environment=_ORIGINS[host], base_url="https://" + host)

    @property
    def assets_url(self) -> str:
        return self.base_url + "/v2/assets"

    def subject(self, *, account_id: str, takeover_epoch: int) -> dict:
        if (not isinstance(account_id, str) or not account_id.strip()
                or account_id != account_id.strip()
                or type(takeover_epoch) is not int or takeover_epoch < 1):
            raise TradingEndpointRefused("exact account and positive takeover epoch required")
        return {"broker": "alpaca", "broker_account_id": account_id,
                "environment": self.environment.value, "base_url": self.base_url,
                "takeover_epoch": takeover_epoch}
